# Data Model: DuckDB Integration

**Feature Branch**: `001-duckdb-integration`
**Created**: 2026-01-11
**Source**: [research.md](./research.md), [spec.md](./spec.md)

---

## Entity Overview

This document defines the key entities for the DuckDB integration feature. These entities represent the data structures that flow through the system when processing large CSV files via DuckDB.

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  DuckDBURIConfig │────▶│ RoutingDecision  │────▶│  DatasetHandle  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
         │                       │                        │
         │                       │                        │
         ▼                       ▼                        ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│DuckDBConnection │     │  DuckDBConfig    │     │ValidationResult │
│    Manager      │     │  (Environment)   │     │   (Extended)    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

---

## Entity Definitions

### 1. DuckDBURIConfig

**Purpose**: Represents a parsed `duckdb://` URI with all configuration options extracted.

**Lifecycle**: Created during URI parsing, consumed by connection manager.

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `uri_type` | Literal["csv", "database", "memory"] | Yes | Determines how to connect |
| `path` | Optional[str] | No | File system path (None for memory) |
| `table` | Optional[str] | No | Table name for database connections |
| `view` | Optional[str] | No | View name for database connections |
| `csv_source` | Optional[str] | No | CSV path for memory+CSV pattern |
| `read_only` | bool | No | Open database in read-only mode |
| `memory_limit` | Optional[str] | No | DuckDB memory limit (e.g., "4GB") |

**URI Type Determination**:
- `memory`: Path is `:memory:` or empty
- `csv`: Path ends with `.csv`
- `database`: All other cases (`.db`, `.duckdb`)

**Example Instances**:
```
URI: duckdb:///data/sales.csv
→ DuckDBURIConfig(uri_type="csv", path="data/sales.csv")

URI: duckdb:///:memory:?csv=/tmp/data.csv&memory_limit=2GB
→ DuckDBURIConfig(uri_type="memory", path=None, csv_source="/tmp/data.csv", memory_limit="2GB")

URI: duckdb:///warehouse.db?table=customers&read_only=true
→ DuckDBURIConfig(uri_type="database", path="warehouse.db", table="customers", read_only=True)
```

---

### 2. DuckDBConfig (Environment Configuration)

**Purpose**: Holds environment-based configuration for DuckDB integration.

**Lifecycle**: Created once at server startup, read-only thereafter.

| Attribute | Type | Default | Environment Variable |
|-----------|------|---------|---------------------|
| `enabled` | bool | True | `GX_DUCKDB_ENABLED` |
| `size_threshold_mb` | int | 500 | `GX_DUCKDB_SIZE_THRESHOLD_MB` |
| `memory_limit` | str | "4GB" | `GX_DUCKDB_MEMORY_LIMIT` |
| `temp_directory` | Optional[str] | None | `GX_DUCKDB_TEMP_DIR` |

**Behavior**:
- `enabled=False`: All requests use pandas, even with `duckdb://` URIs
- `size_threshold_mb`: Files larger than this are automatically routed to DuckDB
- `memory_limit`: Applied to all DuckDB connections
- `temp_directory`: Used for out-of-core processing spill files

---

### 3. RoutingDecision

**Purpose**: Represents the outcome of deciding whether to use pandas or DuckDB for a dataset.

**Lifecycle**: Created during `load_dataset()`, influences DatasetHandle creation.

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `engine` | Literal["pandas", "duckdb"] | Yes | Selected execution engine |
| `reason` | str | Yes | Human-readable explanation |
| `file_size_bytes` | Optional[int] | No | File size if applicable |
| `uri_config` | Optional[DuckDBURIConfig] | No | Parsed URI if duckdb:// scheme |
| `fallback_from` | Optional[str] | No | Original engine if fallback occurred |

**Decision Logic**:
1. If URI starts with `duckdb://` → engine="duckdb"
2. Else if file size > threshold → engine="duckdb"
3. Else → engine="pandas"
4. If DuckDB unavailable and file < 1GB → engine="pandas", fallback_from="duckdb"

**Example Instances**:
```
File: 50MB CSV, no URI scheme
→ RoutingDecision(engine="pandas", reason="File size below threshold")

File: 2GB CSV, no URI scheme
→ RoutingDecision(engine="duckdb", reason="File size exceeds 500MB threshold", file_size_bytes=2147483648)

File: 10MB CSV, duckdb:// URI
→ RoutingDecision(engine="duckdb", reason="Explicit duckdb:// URI scheme", uri_config=...)

File: 2GB CSV, DuckDB unavailable
→ Error (cannot fallback - file too large)
```

---

### 4. DatasetHandle (Extended)

**Purpose**: Represents a loaded dataset. Extended to track execution engine metadata.

**Lifecycle**: Created after successful dataset load, referenced by UUID in subsequent operations.

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | str (UUID) | Yes | Unique identifier |
| `name` | str | Yes | Display name |
| `source` | str | Yes | Original source path/URL |
| `row_count` | int | Yes | Number of rows |
| `columns` | List[str] | Yes | Column names |
| `engine` | Literal["pandas", "duckdb"] | Yes | **NEW**: Execution engine used |
| `engine_metadata` | Optional[EngineMetadata] | No | **NEW**: Engine-specific details |

**EngineMetadata** (nested):
| Attribute | Type | Description |
|-----------|------|-------------|
| `duckdb_table` | Optional[str] | Table/view name in DuckDB |
| `duckdb_path` | Optional[str] | Database file path (None for memory) |
| `connection_id` | Optional[str] | Connection manager reference |
| `memory_limit` | Optional[str] | Applied memory limit |

**Behavior**:
- `engine="pandas"`: Standard in-memory DataFrame storage
- `engine="duckdb"`: Data remains in DuckDB, accessed via SQLAlchemy

---

### 5. DuckDBConnectionManager

**Purpose**: Manages DuckDB connections with proper lifecycle and thread safety.

**Lifecycle**: Created per-dataset, cleaned up when DatasetHandle is garbage collected.

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `connection_id` | str (UUID) | Yes | Unique identifier |
| `db_path` | Optional[str] | No | Database file path (None for memory) |
| `sqlalchemy_engine` | Engine | Yes | SQLAlchemy engine instance |
| `is_memory` | bool | Yes | Whether using in-memory database |
| `config` | dict | Yes | DuckDB configuration applied |

**Methods**:
| Method | Returns | Description |
|--------|---------|-------------|
| `cursor()` | ContextManager[Cursor] | Thread-safe cursor access |
| `execute(sql)` | Result | Execute SQL query |
| `close()` | None | Clean up resources |

**Connection Pooling**:
- In-memory databases: `StaticPool` (single persistent connection)
- File-based databases: `NullPool` (connection per operation)

---

### 6. ValidationResult (Extended)

**Purpose**: Validation result with engine provenance information.

**Lifecycle**: Created after checkpoint execution, stored in ValidationStorage.

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | str (UUID) | Yes | Unique identifier |
| `success` | bool | Yes | Overall validation success |
| `results` | List[ExpectationResult] | Yes | Individual expectation results |
| `statistics` | ValidationStatistics | Yes | Summary statistics |
| `engine` | Literal["pandas", "duckdb"] | Yes | **NEW**: Engine that ran validation |
| `run_time_ms` | int | Yes | **NEW**: Execution time |

**Behavior**:
- Result format is identical regardless of engine
- `engine` field enables debugging/audit of execution path

---

## Entity Relationships

### Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         load_dataset() Flow                         │
└─────────────────────────────────────────────────────────────────────┘

     ┌──────────┐
     │  Source  │ (file path, URL, or duckdb:// URI)
     └────┬─────┘
          │
          ▼
     ┌──────────────────┐
     │  Parse URI       │
     │  (if duckdb://)  │
     └────┬─────────────┘
          │
          ▼
     ┌──────────────────┐     ┌─────────────────┐
     │ DuckDBURIConfig  │◀────│  DuckDBConfig   │
     │                  │     │  (env vars)     │
     └────┬─────────────┘     └─────────────────┘
          │
          ▼
     ┌──────────────────┐
     │ RoutingDecision  │ (pandas vs duckdb)
     └────┬─────────────┘
          │
          ├─────────────────────────────────┐
          │ engine="pandas"                 │ engine="duckdb"
          ▼                                 ▼
     ┌──────────────────┐          ┌──────────────────┐
     │  pandas.read_csv │          │ DuckDBConnection │
     │                  │          │     Manager      │
     └────┬─────────────┘          └────┬─────────────┘
          │                              │
          └──────────────┬───────────────┘
                         │
                         ▼
                   ┌──────────────────┐
                   │  DatasetHandle   │
                   │  (with engine    │
                   │   metadata)      │
                   └──────────────────┘
```

### Validation Flow

```
     ┌──────────────────┐
     │  DatasetHandle   │
     └────┬─────────────┘
          │
          ▼
     ┌──────────────────────────────────────────┐
     │  run_checkpoint()                        │
     │  - Check engine in DatasetHandle         │
     │  - Route to appropriate execution engine │
     └────┬─────────────────────────────────────┘
          │
          ├─────────────────────────────────┐
          │ engine="pandas"                 │ engine="duckdb"
          ▼                                 ▼
     ┌──────────────────┐          ┌──────────────────┐
     │ PandasExecution  │          │ SqlAlchemy       │
     │ Engine           │          │ ExecutionEngine  │
     └────┬─────────────┘          └────┬─────────────┘
          │                              │
          └──────────────┬───────────────┘
                         │
                         ▼
                   ┌──────────────────┐
                   │ ValidationResult │
                   │ (identical format│
                   │  for both engines)│
                   └──────────────────┘
```

---

## State Transitions

### DatasetHandle States

```
                    ┌─────────┐
                    │ Loading │
                    └────┬────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │ Loaded  │    │ Loaded  │    │  Error  │
    │ (pandas)│    │ (duckdb)│    │         │
    └────┬────┘    └────┬────┘    └─────────┘
         │               │
         └───────┬───────┘
                 │
                 ▼
           ┌───────────┐
           │ Validated │
           └───────────┘
```

### DuckDBConnectionManager States

```
    ┌──────────────┐
    │   Created    │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │  Connected   │◀──────┐
    └──────┬───────┘       │
           │               │
           ▼               │
    ┌──────────────┐       │
    │  Executing   │───────┘
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │   Closed     │
    └──────────────┘
```

---

## Data Constraints

### DuckDBURIConfig Constraints

| Constraint | Description |
|------------|-------------|
| `uri_type` + `path` | If `uri_type="csv"`, `path` must end with `.csv` |
| `table` + `view` | Mutually exclusive - only one can be set |
| `csv_source` | Only valid when `uri_type="memory"` |
| `memory_limit` | Must match pattern `\d+[KMGT]?B` if set |

### RoutingDecision Constraints

| Constraint | Description |
|------------|-------------|
| `fallback_from` | Only set when fallback actually occurred |
| `uri_config` | Only set when `duckdb://` URI was parsed |
| `file_size_bytes` | Only set for file-based sources |

### DatasetHandle Constraints

| Constraint | Description |
|------------|-------------|
| `engine_metadata` | Only populated when `engine="duckdb"` |
| `row_count` | Must be >= 0 |
| `columns` | Must have at least one column |

---

## Validation Rules

### URI Validation
1. Scheme must be exactly `duckdb`
2. Path must be valid file system path or `:memory:`
3. Query parameters must be from allowed set
4. File extensions determine `uri_type`

### Size Threshold Validation
1. Threshold must be positive integer
2. Files at exactly threshold use pandas (threshold is exclusive)
3. Threshold comparison uses actual file size, not estimated

### Connection Validation
1. File-based databases must exist on disk
2. Tables/views must exist in database
3. CSV files must be readable

---

## Appendix: JSON Schema References

The formal JSON schemas for these entities are defined in:
- `contracts/duckdb_uri_config.schema.json` - DuckDBURIConfig
- `contracts/dataset_handle.schema.json` - Extended DatasetHandle
- `contracts/routing_decision.schema.json` - RoutingDecision
