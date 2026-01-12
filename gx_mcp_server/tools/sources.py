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
        """List available data sources for validation.

        Shows:
        - Tables/views from attached shared DuckDB (if configured)
        - Files in scanned directory (if provided)

        Args:
            include_shared_db: Include tables from shared DuckDB export
            scan_directory: Optional directory to scan for data files

        Returns:
            SourceList with available sources

        Examples:
            - List all sources: list_sources()
            - Scan a directory: list_sources(scan_directory="/data/exports")
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
        """Attach to a shared DuckDB file exported by duckdb-local.

        Use this to access tables/views created in duckdb-local after export.

        Args:
            db_path: Path to DuckDB file. If not provided, uses GX_DUCKDB_SHARED_PATH env var.

        Returns:
            AttachResult with success status and available tables/views

        Examples:
            - Use configured path: attach_shared_db()
            - Explicit path: attach_shared_db("/tmp/exported.duckdb")
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
        """Get schema information for a table in the shared DuckDB.

        Args:
            table_name: Name of the table to inspect

        Returns:
            Dictionary with column names, types, and sample data

        Examples:
            - get_shared_table_schema("sales_data")
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
        """Clean up orphan temporary DuckDB files and exports.

        Removes temporary files older than max_age_hours to free disk space.

        Args:
            max_age_hours: Delete files older than this (default: 24 hours)
            dry_run: If True, only list files without deleting (default: True)

        Returns:
            Dictionary with files found and optionally deleted

        Examples:
            - Preview cleanup: cleanup_temp_files(dry_run=True)
            - Actually clean: cleanup_temp_files(max_age_hours=12, dry_run=False)
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
