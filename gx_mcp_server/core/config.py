# gx_mcp_server/core/config.py
"""Configuration for DuckDB integration loaded from environment variables.

Per contracts/duckdb_config.schema.json and spec.md FR-007.
"""

import os
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class DuckDBConfig:
    """Configuration for DuckDB integration.

    Controlled by environment variables:
    - GX_DUCKDB_ENABLED: Whether DuckDB integration is enabled (default: true)
    - GX_DUCKDB_SIZE_THRESHOLD_MB: File size threshold in MB (default: 500)
    - GX_DUCKDB_MEMORY_LIMIT: DuckDB memory limit e.g., '4GB' (default: None)
    - GX_DUCKDB_TEMP_DIR: Directory for temp/spill files (default: None)
    - GX_DUCKDB_SHARED_PATH: Path to shared DuckDB file exported by duckdb-local (default: None)
    """

    enabled: bool = True
    size_threshold_mb: int = 500
    memory_limit: Optional[str] = None
    temp_directory: Optional[str] = None
    shared_db_path: Optional[str] = None

    @property
    def size_threshold_bytes(self) -> int:
        """Return size threshold in bytes."""
        return self.size_threshold_mb * 1024 * 1024


# Memory limit pattern: digits followed by optional K/M/G/T and B
_MEMORY_LIMIT_PATTERN = re.compile(r"^\d+[KMGT]?B$", re.IGNORECASE)


def _parse_bool(value: str) -> bool:
    """Parse a string to boolean."""
    return value.lower() in ("true", "1", "yes", "on")


def _validate_memory_limit(value: str) -> str:
    """Validate memory limit format.

    Args:
        value: Memory limit string (e.g., '4GB', '512MB')

    Returns:
        Validated uppercase memory limit string

    Raises:
        ValueError: If format is invalid
    """
    value = value.strip().upper()
    if not _MEMORY_LIMIT_PATTERN.match(value):
        raise ValueError(
            f"Invalid memory limit format '{value}': expected pattern like '4GB', '512MB', '1024KB'"
        )
    return value


def load_config() -> DuckDBConfig:
    """Load DuckDB configuration from environment variables.

    Returns:
        DuckDBConfig instance with validated settings

    Raises:
        ValueError: If configuration values are invalid

    Examples:
        >>> import os
        >>> os.environ['GX_DUCKDB_ENABLED'] = 'true'
        >>> os.environ['GX_DUCKDB_SIZE_THRESHOLD_MB'] = '100'
        >>> config = load_config()
        >>> config.enabled
        True
        >>> config.size_threshold_mb
        100
    """
    config = DuckDBConfig()

    # GX_DUCKDB_ENABLED
    enabled_str = os.environ.get("GX_DUCKDB_ENABLED")
    if enabled_str is not None:
        config.enabled = _parse_bool(enabled_str)

    # GX_DUCKDB_SIZE_THRESHOLD_MB
    threshold_str = os.environ.get("GX_DUCKDB_SIZE_THRESHOLD_MB")
    if threshold_str is not None:
        try:
            threshold = int(threshold_str)
            if threshold < 1 or threshold > 10000:
                raise ValueError(
                    f"GX_DUCKDB_SIZE_THRESHOLD_MB must be between 1 and 10000, got {threshold}"
                )
            config.size_threshold_mb = threshold
        except ValueError as e:
            if "invalid literal" in str(e):
                raise ValueError(
                    f"GX_DUCKDB_SIZE_THRESHOLD_MB must be an integer, got '{threshold_str}'"
                ) from e
            raise

    # GX_DUCKDB_MEMORY_LIMIT
    memory_limit = os.environ.get("GX_DUCKDB_MEMORY_LIMIT")
    if memory_limit is not None:
        config.memory_limit = _validate_memory_limit(memory_limit)

    # GX_DUCKDB_TEMP_DIR
    temp_dir = os.environ.get("GX_DUCKDB_TEMP_DIR")
    if temp_dir is not None:
        # Don't validate existence - directory may be created later
        config.temp_directory = temp_dir

    # GX_DUCKDB_SHARED_PATH - Path to shared DuckDB file from duckdb-local export
    shared_path = os.environ.get("GX_DUCKDB_SHARED_PATH")
    if shared_path is not None:
        config.shared_db_path = shared_path

    return config


# Global cached configuration (lazy loaded)
_config: Optional[DuckDBConfig] = None


def get_config() -> DuckDBConfig:
    """Get the cached DuckDB configuration.

    Loads configuration from environment on first call and caches it.
    Use reload_config() to force reload.

    Returns:
        Cached DuckDBConfig instance
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> DuckDBConfig:
    """Reload configuration from environment variables.

    Use this after changing environment variables to pick up new values.

    Returns:
        Fresh DuckDBConfig instance
    """
    global _config
    _config = load_config()
    return _config
