# gx_mcp_server/exceptions.py
"""Exception hierarchy for DuckDB integration.

Per spec.md Error Message Templates and tasks.md T009-T011.
"""


class DuckDBError(Exception):
    """Base exception for all DuckDB-related errors.

    All DuckDB exceptions inherit from this class, allowing callers to catch
    any DuckDB-related error with a single except clause.
    """

    pass


class DuckDBConnectionError(DuckDBError):
    """Exception raised when DuckDB connection fails.

    Used when:
    - Unable to connect to DuckDB database file
    - Connection pool exhausted
    - Database file is locked or inaccessible

    Error code: DUCKDB_CONNECTION_FAILED
    """

    def __init__(self, message: str, path: str | None = None):
        """Initialize connection error.

        Args:
            message: Error description
            path: Database path that failed to connect (optional)
        """
        self.path = path
        super().__init__(message)


class DuckDBURIParseError(DuckDBError):
    """Exception raised when DuckDB URI parsing fails.

    Used when:
    - URI doesn't start with 'duckdb://'
    - Required parameters are missing
    - Invalid file extension
    - Malformed URI format

    Error codes:
    - DUCKDB_URI_INVALID_SCHEME
    - DUCKDB_URI_MISSING_PATH
    - DUCKDB_URI_MISSING_TABLE
    - DUCKDB_URI_INVALID_EXTENSION
    """

    def __init__(self, message: str, uri: str | None = None):
        """Initialize URI parse error.

        Args:
            message: Error description
            uri: The URI that failed to parse (optional)
        """
        self.uri = uri
        super().__init__(message)


class DuckDBFileNotFoundError(DuckDBError):
    """Exception raised when referenced file does not exist.

    Error code: DUCKDB_FILE_NOT_FOUND
    """

    def __init__(self, path: str):
        """Initialize file not found error.

        Args:
            path: Path to file that was not found
        """
        self.path = path
        super().__init__(f"File not found: '{path}'")


class DuckDBTableNotFoundError(DuckDBError):
    """Exception raised when table does not exist in database.

    Error code: DUCKDB_TABLE_NOT_FOUND
    """

    def __init__(self, table: str, path: str):
        """Initialize table not found error.

        Args:
            table: Table name that was not found
            path: Database path searched
        """
        self.table = table
        self.path = path
        super().__init__(f"Table '{table}' not found in database '{path}'")


class DuckDBUnavailableError(DuckDBError):
    """Exception raised when DuckDB is required but not available.

    Error code: DUCKDB_UNAVAILABLE
    """

    def __init__(self, file_size_mb: float, threshold_mb: int = 500):
        """Initialize unavailable error.

        Args:
            file_size_mb: Size of file in MB
            threshold_mb: Threshold that triggered DuckDB requirement
        """
        self.file_size_mb = file_size_mb
        self.threshold_mb = threshold_mb
        super().__init__(
            f"Cannot process file ({file_size_mb:.1f}MB): DuckDB is required for files "
            f"over {threshold_mb}MB but is not available. "
            "Install with: pip install duckdb duckdb-engine"
        )


class DuckDBDiskSpaceError(DuckDBError):
    """Exception raised when DuckDB runs out of disk space.

    Error code: DUCKDB_DISK_SPACE
    """

    def __init__(self, path: str, temp_dir: str | None = None):
        """Initialize disk space error.

        Args:
            path: File being processed
            temp_dir: Temporary directory that ran out of space
        """
        self.path = path
        self.temp_dir = temp_dir or "system temp directory"
        super().__init__(
            f"DuckDB ran out of disk space while processing '{path}'. "
            f"Free up space in '{self.temp_dir}' and retry."
        )


class DuckDBMemoryLimitError(DuckDBError):
    """Exception raised when memory limit format is invalid.

    Error code: DUCKDB_MEMORY_LIMIT_INVALID
    """

    def __init__(self, value: str):
        """Initialize memory limit error.

        Args:
            value: Invalid memory limit value
        """
        self.value = value
        super().__init__(
            f"Invalid memory limit format '{value}': "
            "expected pattern like '4GB', '512MB', '1024KB'"
        )
