# gx_mcp_server/tools/datasets.py
"""Dataset loading tools with DuckDB routing for large files.

Per spec.md FR-001 and FR-007: Automatic routing to DuckDB for files >500MB.
"""

import io
import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

import pandas as pd

# ``polars`` is optional and used when streaming large CSVs
try:
    import polars as pl

    HAS_POLARS = True
except Exception:  # pragma: no cover - polars optional
    HAS_POLARS = False

from gx_mcp_server.connectors import bigquery as bigquery_conn
from gx_mcp_server.connectors import snowflake as snowflake_conn
from gx_mcp_server.connectors.duckdb import (
    DuckDBConnectionManager,
    is_duckdb_available,
    parse_duckdb_uri,
)
from gx_mcp_server.core.config import get_config
from gx_mcp_server.core.schema import (
    DatasetHandleExtended,
    DuckDBURIConfig,
    EngineMetadata,
    ExecutionEngine,
    RoutingDecision,
    URIType,
)
from gx_mcp_server.exceptions import DuckDBURIParseError

from gx_mcp_server.logging import logger
from gx_mcp_server.core import schema, storage

# =============================================================================
# Global DuckDB Connection Registry (T023)
# =============================================================================
# Track active DuckDB connections by handle for later use in validation
_duckdb_connections: dict[str, DuckDBConnectionManager] = {}


# =============================================================================
# Connection Management API (T051)
# =============================================================================


def get_duckdb_connection(handle_id: str) -> DuckDBConnectionManager | None:
    """Get the DuckDB connection manager for a dataset handle.

    Args:
        handle_id: The UUID handle returned by load_dataset()

    Returns:
        DuckDBConnectionManager if the handle has a DuckDB connection, None otherwise

    Examples:
        >>> handle = load_dataset("duckdb:///data/large.csv", "file")
        >>> conn = get_duckdb_connection(handle.id)
        >>> if conn:
        ...     with conn.cursor() as cursor:
        ...         cursor.execute(text("SELECT COUNT(*) FROM view"))
    """
    return _duckdb_connections.get(handle_id)


def cleanup_duckdb_connection(handle_id: str) -> bool:
    """Clean up a DuckDB connection for a specific dataset handle.

    Closes the connection and removes it from the global registry.
    Safe to call even if the handle doesn't have a DuckDB connection.

    Args:
        handle_id: The UUID handle to clean up

    Returns:
        True if a connection was cleaned up, False if handle not found

    Examples:
        >>> handle = load_dataset("duckdb:///data/large.csv", "file")
        >>> # ... use the dataset ...
        >>> cleanup_duckdb_connection(handle.id)
        True
    """
    manager = _duckdb_connections.pop(handle_id, None)
    if manager is not None:
        try:
            manager.close()
            logger.debug("Cleaned up DuckDB connection for handle=%s", handle_id)
            return True
        except Exception as e:
            logger.warning(
                "Error cleaning up DuckDB connection for handle=%s: %s", handle_id, e
            )
            return True  # Still removed from registry
    return False


def cleanup_all_duckdb_connections() -> int:
    """Clean up all DuckDB connections in the global registry.

    Useful for shutdown or testing scenarios. Closes all connections
    and clears the registry.

    Returns:
        Number of connections cleaned up

    Examples:
        >>> # During shutdown or after tests
        >>> count = cleanup_all_duckdb_connections()
        >>> print(f"Cleaned up {count} connections")
    """
    count = 0
    handle_ids = list(_duckdb_connections.keys())
    for handle_id in handle_ids:
        if cleanup_duckdb_connection(handle_id):
            count += 1
    logger.info("Cleaned up %d DuckDB connections", count)
    return count


def get_active_duckdb_connection_count() -> int:
    """Get the number of active DuckDB connections.

    Useful for monitoring and debugging.

    Returns:
        Number of active connections in the registry
    """
    return len(_duckdb_connections)


if TYPE_CHECKING:
    from fastmcp import FastMCP


# =============================================================================
# DuckDB Routing (T021 - FR-007)
# =============================================================================


def should_use_duckdb(
    source: str,
    source_type: Literal["file", "url", "inline"],
) -> RoutingDecision:
    """Determine whether to use DuckDB or pandas for dataset processing.

    Per FR-007: Automatic routing based on file size threshold (default 500MB).
    DuckDB is selected when:
    1. Source is a duckdb:// URI (explicit request)
    2. Source is a CSV file larger than threshold AND DuckDB is available
    3. GX_DUCKDB_ENABLED=true (default)

    Args:
        source: Path to file, URL, inline CSV, or duckdb:// URI
        source_type: Type of source - "file", "url", or "inline"

    Returns:
        RoutingDecision with engine selection and reasoning

    Examples:
        >>> decision = should_use_duckdb("duckdb:///data/large.csv", "file")
        >>> decision.engine
        <ExecutionEngine.DUCKDB: 'duckdb'>

        >>> decision = should_use_duckdb("/data/small.csv", "file")  # <500MB
        >>> decision.engine
        <ExecutionEngine.PANDAS: 'pandas'>
    """
    config = get_config()

    # Case 1: DuckDB disabled entirely
    if not config.enabled:
        return RoutingDecision(
            engine=ExecutionEngine.PANDAS,
            reason="DuckDB disabled via GX_DUCKDB_ENABLED=false",
            file_size_bytes=None,
        )

    # Case 2: Explicit duckdb:// URI
    if source.startswith("duckdb://"):
        try:
            uri_config = parse_duckdb_uri(source)
            if not is_duckdb_available():
                return RoutingDecision(
                    engine=ExecutionEngine.PANDAS,
                    reason="DuckDB URI requested but DuckDB not available",
                    file_size_bytes=None,
                    uri_config=uri_config,
                    fallback_from="duckdb",
                )
            return RoutingDecision(
                engine=ExecutionEngine.DUCKDB,
                reason="Explicit duckdb:// URI",
                file_size_bytes=None,
                uri_config=uri_config,
            )
        except DuckDBURIParseError as e:
            logger.warning("Invalid duckdb:// URI: %s", e)
            return RoutingDecision(
                engine=ExecutionEngine.PANDAS,
                reason=f"Invalid duckdb:// URI: {e}",
                file_size_bytes=None,
                fallback_from="duckdb",
            )

    # Case 3: Non-file sources always use pandas
    if source_type != "file":
        return RoutingDecision(
            engine=ExecutionEngine.PANDAS,
            reason=f"Source type '{source_type}' uses pandas (DuckDB only for files)",
            file_size_bytes=None,
        )

    # Case 4: File-based routing by size
    path = Path(source)
    if not path.is_file():
        return RoutingDecision(
            engine=ExecutionEngine.PANDAS,
            reason="File does not exist, will fail during load",
            file_size_bytes=None,
        )

    file_size_bytes = path.stat().st_size
    threshold_bytes = config.size_threshold_bytes

    # Below threshold: use pandas
    if file_size_bytes < threshold_bytes:
        return RoutingDecision(
            engine=ExecutionEngine.PANDAS,
            reason=f"File size ({file_size_bytes / (1024 * 1024):.1f}MB) "
            f"below threshold ({config.size_threshold_mb}MB)",
            file_size_bytes=file_size_bytes,
        )

    # Above threshold: check DuckDB availability
    if not is_duckdb_available():
        return RoutingDecision(
            engine=ExecutionEngine.PANDAS,
            reason=f"File size ({file_size_bytes / (1024 * 1024):.1f}MB) "
            f"exceeds threshold ({config.size_threshold_mb}MB) but DuckDB not available",
            file_size_bytes=file_size_bytes,
            fallback_from="duckdb",
        )

    # Above threshold and DuckDB available: use DuckDB
    return RoutingDecision(
        engine=ExecutionEngine.DUCKDB,
        reason=f"File size ({file_size_bytes / (1024 * 1024):.1f}MB) "
        f"exceeds threshold ({config.size_threshold_mb}MB), routing to DuckDB",
        file_size_bytes=file_size_bytes,
    )


def get_csv_size_limit_bytes() -> int:
    """
    Get CSV size limit in bytes from the environment, defaulting to 50MB.
    Limits to range [1, 1024] MB.
    """
    DEFAULT_MB = 50
    min_mb, max_mb = 1, 1024
    value = os.getenv("MCP_CSV_SIZE_LIMIT_MB")
    try:
        mb = int(value) if value else DEFAULT_MB
        if mb < min_mb or mb > max_mb:
            mb = DEFAULT_MB
    except Exception:
        mb = DEFAULT_MB
    return mb * 1024 * 1024


def load_dataset(
    source: str,
    source_type: Literal["file", "url", "inline"] = "file",
    max_rows: Optional[int] = None,
    use_polars: bool = False,
) -> schema.DatasetHandle | DatasetHandleExtended | dict:
    """Load data into memory for validation with Great Expectations.

    This is the PRIMARY data loading tool. Supports multiple data sources and
    automatically routes large files (>500MB) to DuckDB for efficient processing.

    WHEN TO USE:
    - To load CSV data from files, URLs, or inline strings for validation
    - After discovering sources with list_sources()
    - Before creating expectations and running checkpoints
    - For large files that need DuckDB processing (auto-routed)

    TYPICAL WORKFLOW:
    1. load_dataset() → Get dataset handle
    2. create_suite() → Create expectation suite
    3. add_expectation() → Add validation rules
    4. run_checkpoint() → Execute validation
    5. get_validation_result() → Get detailed results

    SUPPORTED SOURCE TYPES:

    FILE (source_type="file"):
    - Local CSV files: "/path/to/data.csv"
    - Parquet files: "/path/to/data.parquet"
    - Files >500MB auto-route to DuckDB for memory efficiency

    URL (source_type="url"):
    - HTTP/HTTPS URLs to CSV files: "https://example.com/data.csv"
    - Max file size limit applies (default 50MB for URLs)

    INLINE (source_type="inline"):
    - CSV data as a string: "col1,col2\\n1,a\\n2,b"
    - Useful for small test datasets
    - Max size limit applies

    SPECIAL URIs:
    - duckdb:///path/to/file.csv - Force DuckDB processing
    - duckdb:///path/to/db.duckdb?table=my_table - Load from existing DuckDB
    - snowflake://account/database/schema/table - Load from Snowflake
    - bigquery://project/dataset/table - Load from BigQuery

    Args:
        source: The data source location. Format depends on source_type:
            - "file": Local file path (e.g., "/data/sales.csv")
            - "url": HTTP(S) URL (e.g., "https://example.com/data.csv")
            - "inline": Raw CSV string (e.g., "id,name\\n1,Alice\\n2,Bob")
            - Special URIs: "duckdb://...", "snowflake://...", "bigquery://..."

        source_type: How to interpret the source parameter:
            - "file" (default): source is a local file path
            - "url": source is an HTTP/HTTPS URL to fetch
            - "inline": source is the CSV data itself as a string

        max_rows: Limit the number of rows loaded. Useful for:
            - Testing expectations on a sample before full validation
            - Memory-constrained environments
            - Quick previews of large datasets
            Default: None (load all rows)

        use_polars: Use Polars library for CSV reading (if installed).
            - True: Uses polars.scan_csv for lazy loading (more memory efficient)
            - False (default): Uses pandas.read_csv
            Only applies to file source_type.

    Returns:
        On success:
        - DatasetHandle: Contains handle ID for pandas-loaded datasets
        - DatasetHandleExtended: Contains handle ID + engine metadata for DuckDB datasets
          (includes: engine type, row_count, columns, DuckDB table name)

        On failure:
        - dict with "error" key explaining what went wrong

    Error Cases:
        - {"error": "File not found"}: source_type="file" but file doesn't exist
        - {"error": "Local CSV exceeds 50 MB limit"}: File too large for pandas
        - {"error": "Only http(s) URLs are allowed"}: Invalid URL scheme
        - {"error": "Remote CSV exceeds 50 MB limit"}: URL response too large
        - {"error": "DuckDB dataset loading failed: ..."}: DuckDB routing error

    Examples:
        # Load local CSV file
        >>> handle = load_dataset("/data/customer_orders.csv", "file")
        >>> print(handle.handle)  # UUID to use in create_suite, run_checkpoint

        # Load from URL
        >>> handle = load_dataset("https://data.example.com/sales.csv", "url")

        # Load inline test data
        >>> handle = load_dataset(
        ...     "id,age,status\\n1,25,active\\n2,19,pending\\n3,45,active",
        ...     "inline"
        ... )

        # Force DuckDB for memory efficiency
        >>> handle = load_dataset("duckdb:///data/large_file.csv", "file")

        # Load existing DuckDB table
        >>> handle = load_dataset("duckdb:///data/analytics.duckdb?table=sales", "file")

        # Preview first 1000 rows only
        >>> handle = load_dataset("/data/huge_file.csv", "file", max_rows=1000)

        # Load from Snowflake (requires credentials)
        >>> handle = load_dataset("snowflake://account/db/schema/table", "file")
    """
    logger.info(
        "Called load_dataset(source_type=%s, max_rows=%s, use_polars=%s)",
        source_type,
        max_rows,
        use_polars,
    )

    # ==========================================================================
    # T023: DuckDB Routing Decision
    # ==========================================================================
    # Check if DuckDB should be used (explicit URI or large file)
    routing_decision = should_use_duckdb(source, source_type)
    logger.info(
        "Routing decision: engine=%s, reason=%s",
        routing_decision.engine.value,
        routing_decision.reason,
    )

    # ==========================================================================
    # DuckDB Path (FR-007: Large files or explicit duckdb:// URI)
    # ==========================================================================
    if routing_decision.engine == ExecutionEngine.DUCKDB:
        return _load_dataset_duckdb(source, routing_decision)

    # ==========================================================================
    # Pandas Path (small files, URLs, inline)
    # ==========================================================================
    return _load_dataset_pandas(source, source_type, max_rows, use_polars)


def _load_dataset_duckdb(
    source: str,
    routing_decision: RoutingDecision,
) -> DatasetHandleExtended | dict:
    """Load dataset via DuckDB for large files or explicit duckdb:// URIs.

    Creates a DuckDB view over the CSV file without loading into memory.
    Stores connection in global registry for later use in validation.

    Args:
        source: File path or duckdb:// URI
        routing_decision: Routing decision with URI config if applicable

    Returns:
        DatasetHandleExtended with DuckDB engine metadata
        dict with error if loading fails
    """
    from sqlalchemy import text

    try:
        # Determine the actual CSV path
        if routing_decision.uri_config:
            uri_config = routing_decision.uri_config
            if uri_config.uri_type == URIType.CSV:
                csv_path = uri_config.path
            elif uri_config.uri_type == URIType.MEMORY and uri_config.csv_source:
                csv_path = uri_config.csv_source
            elif uri_config.uri_type == URIType.DATABASE:
                # For database URIs, we connect to existing database
                return _load_dataset_duckdb_database(uri_config)
            else:
                return {"error": f"Unsupported DuckDB URI type: {uri_config.uri_type}"}
        else:
            # Size-based routing: source is the file path
            csv_path = source

        # Validate file exists
        if not csv_path or not Path(csv_path).is_file():
            return {"error": f"CSV file not found: {csv_path}"}

        # Create DuckDB connection manager
        manager = DuckDBConnectionManager()
        config = get_config()

        # Create in-memory connection with optional memory limit
        manager.create_connection(memory=True)

        # Apply memory limit from URI or config
        memory_limit = None
        if routing_decision.uri_config and routing_decision.uri_config.memory_limit:
            memory_limit = routing_decision.uri_config.memory_limit

        # Load CSV as view (zero-copy, lazy loading)
        view_name = manager.load_csv_as_view(csv_path)

        # Get metadata from the view
        with manager.cursor() as conn:
            # Get row count
            result = conn.execute(text(f"SELECT COUNT(*) FROM {view_name}"))
            row_count = result.fetchone()[0]

            # Get column names
            result = conn.execute(text(f"SELECT * FROM {view_name} LIMIT 0"))
            columns = list(result.keys())

        # Generate handle ID
        import uuid

        handle_id = str(uuid.uuid4())

        # Store connection in global registry for later use in validation
        _duckdb_connections[handle_id] = manager

        # Create engine metadata
        engine_metadata = EngineMetadata(
            duckdb_table=view_name,
            duckdb_path=None,  # In-memory
            connection_id=manager.connection_id,
            memory_limit=memory_limit or config.memory_limit,
        )

        # Store engine metadata in storage layer for later retrieval
        storage.DataStorage.add_duckdb_handle(handle_id, engine_metadata)

        # Create extended handle
        handle = DatasetHandleExtended(
            id=handle_id,
            name=Path(csv_path).stem,
            source=csv_path,
            row_count=row_count,
            columns=columns,
            engine=ExecutionEngine.DUCKDB,
            engine_metadata=engine_metadata,
        )

        logger.info(
            "Loaded dataset via DuckDB handle=%s (view=%s, rows=%d, columns=%d)",
            handle_id,
            view_name,
            row_count,
            len(columns),
        )

        return handle

    except Exception as e:
        logger.error("Failed to load dataset via DuckDB: %s", str(e))
        return {"error": f"DuckDB dataset loading failed: {str(e)}"}


def _load_dataset_duckdb_database(
    uri_config: DuckDBURIConfig,
) -> DatasetHandleExtended | dict:
    """Load dataset from existing DuckDB database file.

    Args:
        uri_config: Parsed duckdb:// URI with database path and table/view name

    Returns:
        DatasetHandleExtended with DuckDB engine metadata
        dict with error if loading fails
    """
    from sqlalchemy import text

    try:
        db_path = uri_config.path
        table_or_view = uri_config.table or uri_config.view

        if not db_path or not Path(db_path).is_file():
            return {"error": f"DuckDB database file not found: {db_path}"}

        # Validate table/view is specified (should be validated by parse_duckdb_uri)
        if not table_or_view:
            return {"error": "DuckDB database URI requires table or view parameter"}

        # Create connection to existing database
        manager = DuckDBConnectionManager()
        manager.create_connection(path=db_path, memory=False)

        # Get metadata from the table/view
        with manager.cursor() as conn:
            # Get row count
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_or_view}"))
            row_count = result.fetchone()[0]

            # Get column names
            result = conn.execute(text(f"SELECT * FROM {table_or_view} LIMIT 0"))
            columns = list(result.keys())

        # Generate handle ID
        import uuid

        handle_id = str(uuid.uuid4())

        # Store connection in global registry
        _duckdb_connections[handle_id] = manager

        # Create engine metadata
        engine_metadata = EngineMetadata(
            duckdb_table=table_or_view,
            duckdb_path=db_path,
            connection_id=manager.connection_id,
            memory_limit=uri_config.memory_limit,
        )

        # Store engine metadata in storage layer for later retrieval
        storage.DataStorage.add_duckdb_handle(handle_id, engine_metadata)

        # Create extended handle
        handle = DatasetHandleExtended(
            id=handle_id,
            name=table_or_view,
            source=f"duckdb://{db_path}?table={table_or_view}",
            row_count=row_count,
            columns=columns,
            engine=ExecutionEngine.DUCKDB,
            engine_metadata=engine_metadata,
        )

        logger.info(
            "Loaded dataset from DuckDB database handle=%s (table=%s, rows=%d)",
            handle_id,
            table_or_view,
            row_count,
        )

        return handle

    except Exception as e:
        logger.error("Failed to load from DuckDB database: %s", str(e))
        return {"error": f"DuckDB database loading failed: {str(e)}"}


def _load_dataset_pandas(
    source: str,
    source_type: Literal["file", "url", "inline"],
    max_rows: Optional[int],
    use_polars: bool,
) -> schema.DatasetHandle | dict:
    """Load dataset via pandas (original implementation).

    Args:
        source: Path to file, URL, or inline CSV string
        source_type: Type of source
        max_rows: Maximum rows to read
        use_polars: Use polars for reading if available

    Returns:
        DatasetHandle for pandas-loaded datasets
        dict with error if loading fails
    """
    LIMIT_BYTES = get_csv_size_limit_bytes()
    limit_mb = LIMIT_BYTES // (1024 * 1024)

    try:
        # Handle Snowflake and BigQuery connectors
        if source.startswith("snowflake://"):
            df = snowflake_conn.load(source)
            handle = storage.DataStorage.add(df)
            logger.info(
                "Loaded dataset from Snowflake handle=%s (shape=%s)",
                handle,
                df.shape,
            )
            return schema.DatasetHandle(handle=handle)

        if source.startswith("bigquery://"):
            df = bigquery_conn.load(source)
            handle = storage.DataStorage.add(df)
            logger.info(
                "Loaded dataset from BigQuery handle=%s (shape=%s)",
                handle,
                df.shape,
            )
            return schema.DatasetHandle(handle=handle)

        # Reject large inline payloads
        if source_type == "inline" and len(source.encode("utf-8")) > LIMIT_BYTES:
            logger.warning(
                "Inline CSV too large: %d bytes (limit: %d MB)", len(source), limit_mb
            )
            return {"error": f"Inline CSV exceeds {limit_mb} MB limit"}

        if source_type == "file":
            path = Path(source)
            if path.is_file():
                if path.stat().st_size > LIMIT_BYTES:
                    logger.warning(
                        "Local CSV too large: %d bytes (limit: %d MB)",
                        path.stat().st_size,
                        limit_mb,
                    )
                    return {"error": f"Local CSV exceeds {limit_mb} MB limit"}
            if use_polars and HAS_POLARS:
                scan = pl.scan_csv(path)
                if max_rows is not None:
                    pl_df = scan.fetch(max_rows)
                else:
                    pl_df = scan.collect()
                df = pl_df.to_pandas()
            else:
                df = pd.read_csv(path, nrows=max_rows)
        elif source_type == "url":
            import requests  # type: ignore[import]
            from urllib.parse import urlparse

            parsed = urlparse(source)
            if parsed.scheme not in {"http", "https"}:
                return {"error": "Only http(s) URLs are allowed"}

            resp = requests.get(source, timeout=30, stream=True)
            resp.raise_for_status()
            # Enforce Content-Length if provided
            size = int(resp.headers.get("Content-Length", 0))
            if size > LIMIT_BYTES:
                logger.warning(
                    "Remote CSV too large: %d bytes (limit: %d MB)", size, limit_mb
                )
                return {"error": f"Remote CSV exceeds {limit_mb} MB limit"}
            if size == 0:
                # Stream download up to limit
                chunks = []
                total = 0
                for chunk in resp.iter_content(chunk_size=8192, decode_unicode=True):
                    if chunk:
                        total += len(chunk.encode("utf-8"))
                        if total > LIMIT_BYTES:
                            logger.warning(
                                "Remote CSV streamed exceeds %d MB limit", limit_mb
                            )
                            return {"error": f"Remote CSV exceeds {limit_mb} MB limit"}
                        chunks.append(chunk)
                txt = "".join(chunks)
            else:
                txt = resp.text
            df = pd.read_csv(io.StringIO(txt), nrows=max_rows)
        elif source_type == "inline":
            df = pd.read_csv(io.StringIO(source), nrows=max_rows)
        else:
            logger.error("Unknown source_type: %s", source_type)
            return {"error": f"Unknown source_type: {source_type}"}

        handle = storage.DataStorage.add(df)
        logger.info(
            "Loaded dataset handle=%s (shape=%s, columns=%s)",
            handle,
            df.shape,
            df.columns.tolist(),
        )
        return schema.DatasetHandle(handle=handle)

    except Exception as e:
        logger.error("Failed to load dataset: %s", str(e))
        return {"error": f"Dataset loading failed: {str(e)}"}


def register(mcp_instance: "FastMCP") -> None:
    """Register dataset tools with the MCP instance."""
    mcp_instance.tool()(load_dataset)
