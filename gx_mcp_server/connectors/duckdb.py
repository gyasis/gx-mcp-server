# gx_mcp_server/connectors/duckdb.py
"""DuckDB connector for large CSV file processing.

Per spec.md, research.md, and tasks.md T012-T016.
Provides zero-copy CSV loading and SQLAlchemy integration for Great Expectations.
"""

import logging
import os
import re
import threading
import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Generator, Optional
from urllib.parse import parse_qs, urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool, StaticPool

from gx_mcp_server.core.config import DuckDBConfig, get_config
from gx_mcp_server.core.schema import DuckDBURIConfig, URIType
from gx_mcp_server.exceptions import (
    DuckDBConnectionError,
    DuckDBFileNotFoundError,
    DuckDBURIParseError,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# URI Parsing (T016)
# =============================================================================


def parse_duckdb_uri(uri: str) -> DuckDBURIConfig:
    """Parse a duckdb:// URI into configuration.

    Supports three URI formats:
    1. CSV file: duckdb:///path/to/file.csv
    2. Database with table: duckdb:///path/to/db.duckdb?table=name
    3. In-memory: duckdb:///:memory:?csv=/path/to/file.csv

    Args:
        uri: DuckDB URI string

    Returns:
        DuckDBURIConfig with parsed settings

    Raises:
        DuckDBURIParseError: If URI format is invalid

    Examples:
        >>> config = parse_duckdb_uri("duckdb:///data/sales.csv")
        >>> config.uri_type
        <URIType.CSV: 'csv'>
        >>> config.path
        '/data/sales.csv'
    """
    # Validate scheme
    if not uri.startswith("duckdb://"):
        scheme = uri.split("://")[0] if "://" in uri else "unknown"
        raise DuckDBURIParseError(
            f"Invalid URI scheme: expected 'duckdb://', got '{scheme}://'", uri=uri
        )

    # Parse URI components
    parsed = urlparse(uri)
    path = parsed.path
    query_params = parse_qs(parsed.query)

    # Handle memory mode: duckdb:///:memory:
    if path == "/:memory:" or path == ":memory:":
        csv_source = query_params.get("csv", [None])[0]
        memory_limit = query_params.get("memory_limit", [None])[0]
        return DuckDBURIConfig(
            uri_type=URIType.MEMORY,
            path=None,
            csv_source=csv_source,
            memory_limit=memory_limit,
        )

    # Validate path exists
    if not path or path == "/":
        raise DuckDBURIParseError(
            "DuckDB URI requires a path: use 'duckdb:///path/to/file.csv' "
            "or 'duckdb:///path/to/db.duckdb?table=name'",
            uri=uri,
        )

    # Determine URI type by extension
    ext = os.path.splitext(path)[1].lower()

    if ext == ".csv":
        # CSV file mode
        read_only = query_params.get("read_only", ["false"])[0].lower() == "true"
        memory_limit = query_params.get("memory_limit", [None])[0]
        return DuckDBURIConfig(
            uri_type=URIType.CSV,
            path=path,
            read_only=read_only,
            memory_limit=memory_limit,
        )

    elif ext in (".duckdb", ".db"):
        # Database file mode
        table = query_params.get("table", [None])[0]
        view = query_params.get("view", [None])[0]

        if not table and not view:
            raise DuckDBURIParseError(
                f"DuckDB database URI requires table parameter: 'duckdb://{path}?table=tablename'",
                uri=uri,
            )

        if table and view:
            raise DuckDBURIParseError(
                "Cannot specify both 'table' and 'view' parameters", uri=uri
            )

        read_only = query_params.get("read_only", ["false"])[0].lower() == "true"
        memory_limit = query_params.get("memory_limit", [None])[0]
        return DuckDBURIConfig(
            uri_type=URIType.DATABASE,
            path=path,
            table=table,
            view=view,
            read_only=read_only,
            memory_limit=memory_limit,
        )

    else:
        raise DuckDBURIParseError(
            f"Unsupported file type '{ext}': expected .csv or .duckdb/.db", uri=uri
        )


# =============================================================================
# Connection Manager (T012-T015)
# =============================================================================


class DuckDBConnectionManager:
    """Manages DuckDB connections with proper pooling for Great Expectations.

    Uses StaticPool for in-memory databases (CRITICAL - prevents connection closed errors)
    and NullPool for file-based databases.

    Thread-safe via cursor() context manager.

    Examples:
        >>> manager = DuckDBConnectionManager()
        >>> manager.create_connection()
        >>> with manager.cursor() as cursor:
        ...     cursor.execute("SELECT 42")
        ...     result = cursor.fetchone()
        >>> manager.close()
    """

    def __init__(
        self,
        config: Optional[DuckDBConfig] = None,
        connection_id: Optional[str] = None,
    ):
        """Initialize connection manager.

        Args:
            config: DuckDB configuration. Uses global config if not provided.
            connection_id: Unique ID for this connection. Auto-generated if not provided.
        """
        self._config = config or get_config()
        self._connection_id = connection_id or str(uuid.uuid4())
        self._engine: Optional[Engine] = None
        self._is_memory: bool = False
        self._db_path: Optional[str] = None
        self._lock = threading.Lock()
        self._views: dict[str, str] = {}  # Track created views for cleanup

    @property
    def connection_id(self) -> str:
        """Return unique identifier for this connection."""
        return self._connection_id

    @property
    def is_connected(self) -> bool:
        """Return True if engine is created and connected."""
        return self._engine is not None

    @property
    def db_path(self) -> Optional[str]:
        """Return database path, or None for in-memory."""
        return self._db_path

    def create_connection(
        self,
        path: Optional[str] = None,
        memory: bool = True,
    ) -> Engine:
        """Create SQLAlchemy engine for DuckDB.

        CRITICAL: Uses StaticPool for in-memory databases to prevent
        "Connection Closed" errors with Great Expectations.

        Args:
            path: Database file path. None for in-memory.
            memory: If True and path is None, use in-memory database.

        Returns:
            SQLAlchemy Engine configured for DuckDB

        Raises:
            DuckDBConnectionError: If connection fails
            DuckDBFileNotFoundError: If database file doesn't exist
        """
        with self._lock:
            if self._engine is not None:
                return self._engine

            try:
                self._is_memory = path is None and memory
                self._db_path = path

                if self._is_memory:
                    # In-memory: MUST use StaticPool to maintain single connection
                    # Note: DuckDB doesn't need check_same_thread (that's SQLite-only)
                    connection_string = "duckdb:///:memory:"
                    self._engine = create_engine(
                        connection_string,
                        poolclass=StaticPool,
                    )
                    logger.debug(
                        f"Created in-memory DuckDB connection {self._connection_id}"
                    )
                else:
                    # File-based: use NullPool (data persists in file)
                    if path and not os.path.exists(path):
                        # For new databases, DuckDB will create the file
                        pass
                    connection_string = f"duckdb:///{path}"
                    self._engine = create_engine(
                        connection_string,
                        poolclass=NullPool,
                    )
                    logger.debug(
                        f"Created file-based DuckDB connection {self._connection_id} at {path}"
                    )

                # Apply configuration settings
                self._apply_config()

                return self._engine

            except Exception as e:
                raise DuckDBConnectionError(
                    f"Failed to connect to DuckDB: {e}", path=path
                ) from e

    def create_duckdb_engine(
        self,
        path: Optional[str] = None,
        memory: bool = True,
    ) -> Engine:
        """Alias for create_connection() for API compatibility."""
        return self.create_connection(path=path, memory=memory)

    def _apply_config(self) -> None:
        """Apply DuckDB configuration settings to connection."""
        if self._engine is None:
            return

        settings = []

        # Memory limit
        if self._config.memory_limit:
            settings.append(f"SET memory_limit = '{self._config.memory_limit}'")

        # Temp directory
        if self._config.temp_directory:
            settings.append(f"SET temp_directory = '{self._config.temp_directory}'")

        if settings:
            with self._engine.connect() as conn:
                for setting in settings:
                    conn.execute(text(setting))
                conn.commit()
            logger.debug(f"Applied DuckDB settings: {settings}")

    @contextmanager
    def cursor(self) -> Generator[Any, None, None]:
        """Thread-safe cursor access via context manager.

        Yields:
            SQLAlchemy connection for executing queries

        Raises:
            DuckDBConnectionError: If no connection exists

        Examples:
            >>> with manager.cursor() as cursor:
            ...     cursor.execute(text("SELECT * FROM data"))
            ...     rows = cursor.fetchall()
        """
        if self._engine is None:
            raise DuckDBConnectionError(
                "No connection established. Call create_connection() first."
            )

        with self._lock:
            with self._engine.connect() as conn:
                yield conn

    def load_csv_as_view(
        self,
        csv_path: str,
        view_name: Optional[str] = None,
    ) -> str:
        """Load CSV file as a DuckDB view using zero-copy reading.

        Uses read_csv_auto() for automatic schema detection and lazy loading.
        Does NOT load entire file into memory.

        Args:
            csv_path: Path to CSV file
            view_name: Name for the view. Auto-generated if not provided.

        Returns:
            Name of created view

        Raises:
            DuckDBFileNotFoundError: If CSV file doesn't exist
            DuckDBConnectionError: If no connection exists
        """
        if not os.path.exists(csv_path):
            raise DuckDBFileNotFoundError(csv_path)

        if self._engine is None:
            raise DuckDBConnectionError(
                "No connection established. Call create_connection() first."
            )

        # Generate safe view name from file path
        if view_name is None:
            base_name = os.path.splitext(os.path.basename(csv_path))[0]
            # Sanitize to valid SQL identifier
            safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", base_name)
            view_name = f"csv_{safe_name}_{uuid.uuid4().hex[:8]}"

        # Create view using read_csv_auto (zero-copy, lazy loading)
        # Escape path for SQL
        escaped_path = csv_path.replace("'", "''")

        with self.cursor() as conn:
            conn.execute(
                text(
                    f"CREATE OR REPLACE VIEW {view_name} AS "
                    f"SELECT * FROM read_csv_auto('{escaped_path}')"
                )
            )
            conn.commit()

        self._views[view_name] = csv_path
        logger.info(f"Created view '{view_name}' for CSV: {csv_path}")

        return view_name

    def close(self) -> None:
        """Close connection and clean up resources.

        Drops all views created by this manager and disposes engine.
        """
        with self._lock:
            if self._engine is not None:
                try:
                    # Clean up views
                    with self._engine.connect() as conn:
                        for view_name in self._views:
                            try:
                                conn.execute(text(f"DROP VIEW IF EXISTS {view_name}"))
                            except Exception as e:
                                logger.warning(f"Failed to drop view {view_name}: {e}")
                        conn.commit()
                except Exception as e:
                    logger.warning(f"Error cleaning up views: {e}")

                try:
                    self._engine.dispose()
                except Exception as e:
                    logger.warning(f"Error disposing engine: {e}")

                self._engine = None
                self._views.clear()
                logger.debug(f"Closed DuckDB connection {self._connection_id}")

    def __enter__(self) -> "DuckDBConnectionManager":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - ensures cleanup."""
        self.close()

    def __del__(self) -> None:
        """Destructor - cleanup on garbage collection."""
        try:
            self.close()
        except Exception:
            pass  # Ignore errors during GC


# =============================================================================
# Availability Check
# =============================================================================


def is_duckdb_available() -> bool:
    """Check if DuckDB is available and functional.

    Returns:
        True if DuckDB can be imported and used, False otherwise
    """
    try:
        import duckdb

        # Quick functional test
        conn = duckdb.connect(":memory:")
        result = conn.execute("SELECT 42").fetchone()
        conn.close()
        return result == (42,)
    except Exception as e:
        logger.warning(f"DuckDB availability check failed: {e}")
        return False
