# gx_mcp_server/core/schema.py
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# =============================================================================
# DuckDB Integration Types (T005, T006, T017, T018)
# =============================================================================


class URIType(str, Enum):
    """Type of DuckDB connection determined from URI."""

    CSV = "csv"
    DATABASE = "database"
    MEMORY = "memory"


class ExecutionEngine(str, Enum):
    """Execution engine for dataset processing."""

    PANDAS = "pandas"
    DUCKDB = "duckdb"


class DuckDBURIConfig(BaseModel):
    """Configuration parsed from a duckdb:// URI.

    Per contracts/duckdb_uri_config.schema.json
    """

    uri_type: URIType = Field(
        description="Type of DuckDB connection determined from URI"
    )
    path: Optional[str] = Field(
        default=None,
        description="File system path to CSV or database file. None for in-memory databases.",
    )
    table: Optional[str] = Field(
        default=None, description="Table name to query from database file"
    )
    view: Optional[str] = Field(
        default=None, description="View name to query from database file"
    )
    csv_source: Optional[str] = Field(
        default=None,
        description="CSV file path for memory databases. Only valid when uri_type is 'memory'.",
    )
    read_only: bool = Field(
        default=False, description="Open database in read-only mode"
    )
    memory_limit: Optional[str] = Field(
        default=None, description="DuckDB memory limit (e.g., '4GB', '512MB')"
    )


class RoutingDecision(BaseModel):
    """Decision outcome for pandas vs DuckDB execution engine routing.

    Per contracts/routing_decision.schema.json
    """

    engine: ExecutionEngine = Field(description="Selected execution engine")
    reason: str = Field(
        min_length=1, description="Human-readable explanation for the routing decision"
    )
    file_size_bytes: Optional[int] = Field(
        default=None, ge=0, description="File size in bytes if source is a file"
    )
    uri_config: Optional[DuckDBURIConfig] = Field(
        default=None,
        description="Parsed DuckDB URI configuration if duckdb:// scheme was used",
    )
    fallback_from: Optional[Literal["duckdb"]] = Field(
        default=None,
        description="Original engine if fallback occurred. Only 'duckdb' is valid since pandas never falls back.",
    )


class EngineMetadata(BaseModel):
    """DuckDB-specific metadata for a dataset handle.

    Per contracts/dataset_handle.schema.json engine_metadata
    """

    duckdb_table: Optional[str] = Field(
        default=None, description="Table or view name in DuckDB"
    )
    duckdb_path: Optional[str] = Field(
        default=None, description="Database file path. None for in-memory databases."
    )
    connection_id: Optional[str] = Field(
        default=None, description="Reference to DuckDBConnectionManager"
    )
    memory_limit: Optional[str] = Field(
        default=None, description="Applied memory limit for this connection"
    )


# =============================================================================
# Original Schema Types (unchanged API)
# =============================================================================


class DatasetHandle(BaseModel):
    """Handle representing a loaded dataset."""

    handle: str


class DatasetHandleExtended(BaseModel):
    """Extended handle with execution engine metadata.

    Per contracts/dataset_handle.schema.json
    Used internally for DuckDB routing; DatasetHandle remains for API compatibility.
    """

    id: str = Field(description="Unique identifier for the dataset handle")
    name: str = Field(min_length=1, description="Display name for the dataset")
    source: str = Field(description="Original source path, URL, or URI")
    row_count: int = Field(ge=0, description="Number of rows in the dataset")
    columns: List[str] = Field(
        min_length=1, description="List of column names in the dataset"
    )
    engine: ExecutionEngine = Field(
        description="Execution engine used for this dataset"
    )
    engine_metadata: Optional[EngineMetadata] = Field(
        default=None,
        description="Engine-specific metadata. Only populated for duckdb engine.",
    )


class SuiteHandle(BaseModel):
    suite_name: str


class ToolResponse(BaseModel):
    success: bool
    message: str


class ValidationResult(BaseModel):
    validation_id: str


class ValidationResultDetail(BaseModel):
    statistics: Dict[str, Any]
    results: Any
    success: bool
    error: Optional[str] = None
    engine: Optional[ExecutionEngine] = Field(
        default=None, description="Execution engine used for validation"
    )
    run_time_ms: Optional[int] = Field(
        default=None, ge=0, description="Validation run time in milliseconds"
    )
