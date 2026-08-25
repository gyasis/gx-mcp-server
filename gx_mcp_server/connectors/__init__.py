"""Database connectors for loading datasets from cloud warehouses.

This module provides connectors for:
- DuckDB: High-performance analytics database for large CSV files (>500MB)
"""

from gx_mcp_server.connectors.duckdb import (
    DuckDBConnectionManager,
    is_duckdb_available,
    parse_duckdb_uri,
)

__all__ = [
    "DuckDBConnectionManager",
    "is_duckdb_available",
    "parse_duckdb_uri",
]
