# gx_mcp_server/tools/sources.py
"""Data source management tools for gx-mcp-server.

Provides tools to:
- List available data sources (files, shared DuckDB tables)
- Attach to exported DuckDB databases from duckdb-local
- Discover sources in directories
"""

import os
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from gx_mcp_server.core.config import get_config
from gx_mcp_server.logging import logger


class DataSource(BaseModel):
    """Represents a data source available for validation."""

    name: str = Field(description="Source identifier")
    type: str = Field(description="Source type: file, table, view, s3, snowflake")
    path: Optional[str] = Field(default=None, description="File path or URI")
    database: Optional[str] = Field(default=None, description="Database name for DB sources")
    schema_name: Optional[str] = Field(default=None, description="Schema name")
    table: Optional[str] = Field(default=None, description="Table or view name")
    row_count: Optional[int] = Field(default=None, description="Estimated row count if known")
    columns: Optional[list[str]] = Field(default=None, description="Column names if known")


class SourceList(BaseModel):
    """List of available data sources."""

    sources: list[DataSource] = Field(default_factory=list)
    shared_db_connected: bool = Field(default=False, description="Whether shared DuckDB is attached")
    shared_db_path: Optional[str] = Field(default=None, description="Path to shared DuckDB")


class AttachResult(BaseModel):
    """Result of attaching to shared DuckDB."""

    success: bool
    message: str
    tables: list[str] = Field(default_factory=list, description="Tables available after attach")
    views: list[str] = Field(default_factory=list, description="Views available after attach")


# Module-level state for shared DB connection
_shared_db_attached: bool = False
_shared_db_conn = None


def register(mcp: FastMCP) -> None:
    """Register data source tools with the MCP server."""

    @mcp.tool()
    def list_sources(
        include_shared_db: bool = True,
        scan_directory: Optional[str] = None,
    ) -> SourceList:
        """List all available data sources that can be validated with Great Expectations.

        WHEN TO USE:
        - As your FIRST step to discover what data is available for validation
        - Before calling load_dataset() to see available tables/files
        - After calling attach_shared_db() to verify tables are accessible
        - To find data files in a directory you want to validate

        WHAT IT RETURNS:
        - List of DataSource objects with name, type, path, row_count, columns
        - Whether shared DuckDB is connected
        - Path to shared DuckDB file (if configured)

        WORKFLOW CONTEXT:
        This tool integrates with duckdb-local MCP server via export workflow:
        1. In duckdb-local: Run `EXPORT DATABASE '/path/to/exported.duckdb'`
        2. In gx-mcp-server: Call `attach_shared_db()` to connect
        3. Call `list_sources()` to see available tables/views
        4. Use table names with `load_dataset()` for validation

        Args:
            include_shared_db: If True, queries the attached shared DuckDB
                for tables/views. Set to False to skip database sources.
                Default: True
            scan_directory: Path to directory to scan for data files
                (.csv, .parquet, .json, .duckdb). Scans one level deep
                into subdirectories. Set to None to skip file scanning.
                Default: None

        Returns:
            SourceList containing:
            - sources: List of DataSource objects with:
                - name: Source identifier (table name or filename)
                - type: "table", "view", or "file"
                - path: File path (for file sources)
                - database: "shared" (for DB sources)
                - table: Table/view name
                - row_count: Number of rows (if known)
                - columns: List of column names (if known)
            - shared_db_connected: True if shared DuckDB is accessible
            - shared_db_path: Path to shared DuckDB file

        Examples:
            # Discover all available sources
            >>> list_sources()
            SourceList(sources=[...], shared_db_connected=True, ...)

            # Only list files in a data directory
            >>> list_sources(include_shared_db=False, scan_directory="/data/exports")

            # Verify shared database is connected and see tables
            >>> result = list_sources()
            >>> if result.shared_db_connected:
            ...     for src in result.sources:
            ...         print(f"{src.name}: {src.row_count} rows")
        """
        global _shared_db_attached, _shared_db_conn

        config = get_config()
        sources: list[DataSource] = []
        shared_connected = False

        # Check shared DuckDB
        if include_shared_db and config.shared_db_path:
            if os.path.exists(config.shared_db_path):
                try:
                    import duckdb

                    if _shared_db_conn is None:
                        _shared_db_conn = duckdb.connect(config.shared_db_path, read_only=True)
                        _shared_db_attached = True

                    # Get tables
                    tables = _shared_db_conn.execute(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                    ).fetchall()

                    for (table_name,) in tables:
                        # Get column info
                        cols = _shared_db_conn.execute(
                            f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}'"
                        ).fetchall()
                        col_names = [c[0] for c in cols]

                        # Get row count estimate
                        try:
                            count = _shared_db_conn.execute(
                                f"SELECT COUNT(*) FROM \"{table_name}\""
                            ).fetchone()[0]
                        except Exception:
                            count = None

                        sources.append(
                            DataSource(
                                name=table_name,
                                type="table",
                                database="shared",
                                table=table_name,
                                row_count=count,
                                columns=col_names,
                            )
                        )

                    shared_connected = True
                    logger.info(f"Listed {len(tables)} tables from shared DuckDB")

                except Exception as e:
                    logger.warning(f"Failed to connect to shared DuckDB: {e}")

        # Scan directory for files
        if scan_directory:
            scan_path = Path(scan_directory)
            if scan_path.exists() and scan_path.is_dir():
                # Look for data files
                patterns = ["*.csv", "*.parquet", "*.json", "*.duckdb"]
                for pattern in patterns:
                    for file_path in scan_path.glob(pattern):
                        file_type = file_path.suffix.lstrip(".")
                        sources.append(
                            DataSource(
                                name=file_path.stem,
                                type="file",
                                path=str(file_path),
                            )
                        )

                # Also check subdirectories one level deep
                for subdir in scan_path.iterdir():
                    if subdir.is_dir():
                        for pattern in patterns:
                            for file_path in subdir.glob(pattern):
                                sources.append(
                                    DataSource(
                                        name=f"{subdir.name}/{file_path.stem}",
                                        type="file",
                                        path=str(file_path),
                                    )
                                )

        return SourceList(
            sources=sources,
            shared_db_connected=shared_connected,
            shared_db_path=config.shared_db_path,
        )

    @mcp.tool()
    def attach_shared_db(db_path: Optional[str] = None) -> AttachResult:
        """Connect to a DuckDB database file to access tables/views for validation.

        WHEN TO USE:
        - After duckdb-local MCP server exports a database file
        - When you want to validate tables created in another DuckDB session
        - To reconnect to a different database file
        - As part of the data sharing workflow between MCP servers

        WORKFLOW WITH duckdb-local:
        1. In duckdb-local: Load data, create views/tables as needed
        2. In duckdb-local: `EXPORT DATABASE '/home/user/.local/share/duckdb/exported.duckdb'`
        3. In gx-mcp-server: `attach_shared_db()` or `attach_shared_db("/path/to/exported.duckdb")`
        4. Call `list_sources()` to see available tables/views
        5. Load and validate: `load_dataset("table_name", "table")`

        WHAT IT DOES:
        - Opens read-only connection to the DuckDB file
        - Closes any existing shared connection first
        - Queries information_schema for available tables and views
        - Makes tables accessible via list_sources() and load_dataset()

        Args:
            db_path: Full path to DuckDB database file to attach.
                - If None: Uses GX_DUCKDB_SHARED_PATH environment variable
                - If env var not set: Returns error asking for path
                Common paths:
                - "/home/user/.local/share/duckdb/exported.duckdb"
                - "/shared/duckdb/exported.duckdb" (Docker)

        Returns:
            AttachResult containing:
            - success: True if connection established
            - message: Description of result or error
            - tables: List of BASE TABLE names found (e.g., ["customers", "orders"])
            - views: List of VIEW names found (e.g., ["sales_summary", "daily_metrics"])

        Error Cases:
            - "No shared DB path provided": Set GX_DUCKDB_SHARED_PATH or pass db_path
            - "Shared DB file not found": File doesn't exist, run EXPORT in duckdb-local first
            - "Failed to attach": Database file corrupted or incompatible version

        Examples:
            # Using environment variable (recommended for Docker)
            >>> attach_shared_db()
            AttachResult(success=True, message="Successfully attached", tables=["orders"], views=["summary"])

            # Explicit path
            >>> attach_shared_db("/home/user/data/analytics.duckdb")

            # Check if specific tables are available
            >>> result = attach_shared_db()
            >>> if "sales_data" in result.tables:
            ...     # Proceed with validation
            ...     pass
        """
        global _shared_db_attached, _shared_db_conn

        config = get_config()
        path = db_path or config.shared_db_path

        if not path:
            return AttachResult(
                success=False,
                message="No shared DB path provided. Set GX_DUCKDB_SHARED_PATH or pass db_path.",
            )

        if not os.path.exists(path):
            return AttachResult(
                success=False,
                message=f"Shared DB file not found: {path}. Run EXPORT DATABASE in duckdb-local first.",
            )

        try:
            import duckdb

            # Close existing connection if any
            if _shared_db_conn is not None:
                _shared_db_conn.close()

            _shared_db_conn = duckdb.connect(path, read_only=True)
            _shared_db_attached = True

            # Get tables and views
            tables = _shared_db_conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
            ).fetchall()
            table_names = [t[0] for t in tables]

            views = _shared_db_conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' AND table_type = 'VIEW'"
            ).fetchall()
            view_names = [v[0] for v in views]

            logger.info(f"Attached to shared DuckDB: {len(table_names)} tables, {len(view_names)} views")

            return AttachResult(
                success=True,
                message=f"Successfully attached to {path}",
                tables=table_names,
                views=view_names,
            )

        except Exception as e:
            logger.error(f"Failed to attach shared DuckDB: {e}")
            return AttachResult(
                success=False,
                message=f"Failed to attach: {str(e)}",
            )

    @mcp.tool()
    def get_shared_table_schema(table_name: str) -> dict:
        """Inspect the schema and sample data of a table in the attached shared DuckDB.

        WHEN TO USE:
        - Before validation to understand column names and data types
        - To determine which expectations to add (e.g., value ranges, types)
        - To preview data before running expensive validations
        - After list_sources() to get details on a specific table

        REQUIRES:
        - attach_shared_db() must be called first to connect to database
        - Table must exist in the attached database

        WHAT IT RETURNS:
        - Column definitions with names, SQL types, and nullability
        - Total row count for the table
        - Sample of first 5 rows to preview data values

        Args:
            table_name: Exact name of table or view to inspect.
                Get valid names from list_sources() or attach_shared_db().
                Case-sensitive in DuckDB.

        Returns:
            Dictionary containing:
            - table_name: The inspected table name
            - row_count: Total number of rows
            - columns: List of column definitions:
                - name: Column name (e.g., "customer_id")
                - type: SQL data type (e.g., "VARCHAR", "INTEGER", "TIMESTAMP")
                - nullable: True if column allows NULL values
            - sample_data: First 5 rows as list of dicts

        Error Cases:
            - {"error": "Shared DB not attached..."}: Call attach_shared_db() first
            - {"error": "Table 'X' not found..."}: Table doesn't exist, check name spelling

        Examples:
            # Inspect table schema before validation
            >>> schema = get_shared_table_schema("customer_orders")
            >>> print(f"Table has {schema['row_count']} rows")
            >>> for col in schema['columns']:
            ...     print(f"  {col['name']}: {col['type']}")

            # Check what columns are available for expectations
            >>> schema = get_shared_table_schema("sales_data")
            >>> column_names = [c['name'] for c in schema['columns']]
            >>> # Now you know which columns to validate

            # Preview sample data to understand value patterns
            >>> schema = get_shared_table_schema("products")
            >>> for row in schema['sample_data']:
            ...     print(row)
        """
        global _shared_db_conn

        if _shared_db_conn is None:
            return {"error": "Shared DB not attached. Call attach_shared_db() first."}

        try:
            # Get column info
            columns = _shared_db_conn.execute(
                f"""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = '{table_name}'
                ORDER BY ordinal_position
                """
            ).fetchall()

            if not columns:
                return {"error": f"Table '{table_name}' not found in shared DB"}

            # Get sample rows
            sample = _shared_db_conn.execute(
                f'SELECT * FROM "{table_name}" LIMIT 5'
            ).fetchdf()

            # Get row count
            count = _shared_db_conn.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]

            return {
                "table_name": table_name,
                "row_count": count,
                "columns": [
                    {"name": c[0], "type": c[1], "nullable": c[2] == "YES"}
                    for c in columns
                ],
                "sample_data": sample.to_dict(orient="records"),
            }

        except Exception as e:
            return {"error": f"Failed to get schema: {str(e)}"}

    @mcp.tool()
    def cleanup_temp_files(
        max_age_hours: int = 24,
        dry_run: bool = True,
    ) -> dict:
        """Remove old temporary files created by DuckDB and gx-mcp-server to free disk space.

        WHEN TO USE:
        - Periodically to reclaim disk space from accumulated temp files
        - When disk space is low and you suspect temp file buildup
        - After processing many large datasets
        - As part of routine maintenance

        WHAT IT CLEANS:
        - *.duckdb files (orphaned DuckDB databases)
        - *.duckdb.wal files (DuckDB write-ahead logs)
        - *.tmp files (temporary processing files)
        - gx_temp_*.csv files (temporary exports)

        DIRECTORIES SCANNED:
        - Configured temp directory (GX_DUCKDB_TEMP_DIR)
        - /tmp/duckdb
        - /tmp/gx_mcp

        SAFETY:
        - Default is dry_run=True (preview only, no deletion)
        - Always run with dry_run=True first to see what would be deleted
        - Only files older than max_age_hours are considered

        Args:
            max_age_hours: Minimum age in hours for files to be considered for cleanup.
                Files modified more recently than this are preserved.
                Default: 24 hours. Recommended minimum: 1 hour.
            dry_run: Safety flag controlling whether files are actually deleted.
                - True (default): Only list files, DO NOT delete anything
                - False: Actually delete matching files
                IMPORTANT: Always run with True first to preview!

        Returns:
            Dictionary containing:
            - dry_run: Whether this was a preview (True) or actual cleanup (False)
            - max_age_hours: The age threshold used
            - files_found: Count of files matching criteria
            - files_deleted: Count of files actually deleted (0 if dry_run=True)
            - bytes_freed_mb: Disk space freed in megabytes (0 if dry_run=True)
            - files: List of file details (paths if dry_run, deleted paths if not)
            - message: Human-readable summary

        Examples:
            # STEP 1: Always preview first (safe)
            >>> cleanup_temp_files(dry_run=True)
            {"dry_run": True, "files_found": 15, "message": "Found 15 files older than 24h"}

            # STEP 2: If preview looks good, actually clean
            >>> cleanup_temp_files(dry_run=False)
            {"dry_run": False, "files_deleted": 15, "bytes_freed_mb": 2.5, ...}

            # Clean files older than 12 hours
            >>> cleanup_temp_files(max_age_hours=12, dry_run=False)

            # Check for very old files (>7 days)
            >>> cleanup_temp_files(max_age_hours=168, dry_run=True)
        """
        import time

        config = get_config()
        now = time.time()
        max_age_seconds = max_age_hours * 3600

        files_found: list[dict] = []
        files_deleted: list[str] = []
        bytes_freed = 0

        # Directories to scan for temp files
        scan_dirs = [
            config.temp_directory,
            "/tmp/duckdb",
            "/tmp/gx_mcp",
        ]

        # Patterns for temp files
        temp_patterns = ["*.duckdb", "*.duckdb.wal", "*.tmp", "gx_temp_*.csv"]

        for scan_dir in scan_dirs:
            if not scan_dir or not os.path.exists(scan_dir):
                continue

            scan_path = Path(scan_dir)
            for pattern in temp_patterns:
                for file_path in scan_path.glob(pattern):
                    try:
                        stat = file_path.stat()
                        age_hours = (now - stat.st_mtime) / 3600

                        file_info = {
                            "path": str(file_path),
                            "size_mb": round(stat.st_size / (1024 * 1024), 2),
                            "age_hours": round(age_hours, 1),
                        }

                        if age_hours > max_age_hours:
                            files_found.append(file_info)

                            if not dry_run:
                                bytes_freed += stat.st_size
                                file_path.unlink()
                                files_deleted.append(str(file_path))
                                logger.info(f"Deleted temp file: {file_path}")

                    except Exception as e:
                        logger.warning(f"Error processing {file_path}: {e}")

        return {
            "dry_run": dry_run,
            "max_age_hours": max_age_hours,
            "files_found": len(files_found),
            "files_deleted": len(files_deleted),
            "bytes_freed_mb": round(bytes_freed / (1024 * 1024), 2),
            "files": files_found if dry_run else files_deleted,
            "message": (
                f"Found {len(files_found)} files older than {max_age_hours}h"
                if dry_run
                else f"Deleted {len(files_deleted)} files, freed {round(bytes_freed / (1024 * 1024), 2)} MB"
            ),
        }

    logger.debug("Registered data source tools: list_sources, attach_shared_db, get_shared_table_schema, cleanup_temp_files")
