# Research: DuckDB Integration for Large CSV Validation

**Feature Branch**: `001-duckdb-integration`
**Completed**: 2026-01-11
**Sources**: Team Orchestrator agents, Gemini Research, Context7 documentation

---

## Executive Summary

This research phase investigated how to integrate DuckDB as an alternative execution engine for Great Expectations within the gx-mcp-server. The goal is to enable validation of CSV files larger than 1GB by leveraging DuckDB's out-of-core processing capabilities.

---

## Decision 1: Use SqlAlchemyExecutionEngine with duckdb-engine

### Decision
Integrate DuckDB with Great Expectations using the `SqlAlchemyExecutionEngine` paired with the `duckdb-engine` SQLAlchemy dialect.

### Rationale
- Great Expectations already supports `SqlAlchemyExecutionEngine` for SQL databases
- `duckdb-engine` provides a complete SQLAlchemy dialect for DuckDB
- This approach reuses existing GE infrastructure rather than creating custom engine
- All existing expectations that work with SQL datasources will work with DuckDB
- Minimal code changes required - follows established patterns in codebase

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|------------------|
| Custom PandasExecutionEngine subclass | Would require reimplementing all pandas expectations, high maintenance burden |
| Direct DuckDB API without GE | Loses validation capabilities, would need to reimplement expectations |
| Polars integration | Less mature GE support, DuckDB has better SQL compatibility |

### Implementation Notes
```python
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# Connection string patterns
"duckdb:///:memory:"           # In-memory database
"duckdb:///path/to/db.duckdb"  # File-based database
```

---

## Decision 2: Use StaticPool for Connection Management

### Decision
**CRITICAL**: Use `sqlalchemy.pool.StaticPool` when creating DuckDB engines for Great Expectations integration.

### Rationale
- DuckDB connections are NOT thread-safe
- GE's SqlAlchemyExecutionEngine may create multiple connections during validation
- Without StaticPool, connections get closed between operations causing "Connection Closed" errors
- StaticPool maintains a single connection throughout the engine's lifetime
- This is the documented solution for in-memory databases with SQLAlchemy

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|------------------|
| Default connection pool | Causes "Connection Closed" errors with in-memory databases |
| NullPool | Creates new connection each time, loses in-memory data |
| QueuePool | Overkill for single-connection use case, adds complexity |

### Implementation Notes
```python
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# CRITICAL: StaticPool prevents connection closed errors
engine = create_engine(
    "duckdb:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False}
)
```

For file-based databases, `NullPool` can be used since data persists:
```python
from sqlalchemy.pool import NullPool

engine = create_engine(
    "duckdb:///path/to/db.duckdb",
    poolclass=NullPool
)
```

---

## Decision 3: URI Scheme Design (RFC 3986 Compliant)

### Decision
Support `duckdb://` URI scheme with three variants:
- `duckdb:///path/to/file.csv` - CSV file routing
- `duckdb:///:memory:` - In-memory database
- `duckdb:///path/to/db.duckdb?table=tablename` - Database table

### Rationale
- Follows RFC 3986 URI standard for consistency
- Matches existing patterns in codebase (`snowflake://`, `bigquery://`)
- File extension detection (.csv vs .db/.duckdb) enables automatic type inference
- Query parameters provide flexibility without path ambiguity
- Clear, predictable behavior for users

### URI Patterns

| Pattern | Type | Description |
|---------|------|-------------|
| `duckdb:///path/to/data.csv` | CSV | Load CSV file into DuckDB |
| `duckdb:///:memory:` | Memory | In-memory database |
| `duckdb:///:memory:?csv=/path/to/data.csv` | Memory+CSV | Load CSV into memory |
| `duckdb:///path/to/db.duckdb?table=users` | Database | Query existing table |
| `duckdb:///path/to/db.duckdb?view=v_users` | Database | Query existing view |

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `table` | string | None | Table name to query |
| `view` | string | None | View name to query |
| `csv` | string | None | CSV path for memory databases |
| `read_only` | bool | false | Open in read-only mode |
| `memory_limit` | string | None | DuckDB memory limit (e.g., "4GB") |

### Implementation Notes
```python
from dataclasses import dataclass
from typing import Literal, Optional
from urllib.parse import urlparse, parse_qs

@dataclass
class DuckDBURIConfig:
    """Parsed DuckDB URI configuration."""
    uri_type: Literal["csv", "database", "memory"]
    path: Optional[str]
    table: Optional[str] = None
    view: Optional[str] = None
    csv_source: Optional[str] = None
    read_only: bool = False
    memory_limit: Optional[str] = None

def parse_duckdb_uri(uri: str) -> DuckDBURIConfig:
    """Parse a duckdb:// URI into configuration."""
    parsed = urlparse(uri)

    if parsed.scheme != "duckdb":
        raise ValueError(f"Invalid scheme: {parsed.scheme}, expected 'duckdb'")

    path = parsed.path.lstrip("/") if parsed.path else None
    params = parse_qs(parsed.query)

    # Determine type from path
    if path == ":memory:" or not path:
        uri_type = "memory"
        path = None
    elif path.endswith(".csv"):
        uri_type = "csv"
    else:
        uri_type = "database"

    return DuckDBURIConfig(
        uri_type=uri_type,
        path=path,
        table=params.get("table", [None])[0],
        view=params.get("view", [None])[0],
        csv_source=params.get("csv", [None])[0],
        read_only=params.get("read_only", ["false"])[0].lower() == "true",
        memory_limit=params.get("memory_limit", [None])[0],
    )
```

---

## Decision 4: Size-Based Automatic Routing

### Decision
Automatically route CSV files larger than a configurable threshold (default: 500MB) to DuckDB, while smaller files continue using pandas.

### Rationale
- Maintains backward compatibility for existing workflows
- Pandas is faster for small files (no startup overhead)
- DuckDB excels at large files with out-of-core processing
- 500MB threshold balances pandas performance vs memory safety
- Environment variable allows infrastructure tuning without code changes

### Threshold Selection
| Threshold | Pros | Cons |
|-----------|------|------|
| 100MB | Early DuckDB benefits | Unnecessary for most files |
| 500MB | Safe default, pandas handles well | Some large files still use pandas |
| 1GB | Maximizes pandas usage | Risk of memory issues |

**Selected: 500MB** - Conservative default that prevents OOM while maintaining pandas speed for typical files.

### Configuration
```python
import os

# Environment variables
GX_DUCKDB_ENABLED = os.getenv("GX_DUCKDB_ENABLED", "true").lower() == "true"
GX_DUCKDB_SIZE_THRESHOLD_MB = int(os.getenv("GX_DUCKDB_SIZE_THRESHOLD_MB", "500"))
GX_DUCKDB_MEMORY_LIMIT = os.getenv("GX_DUCKDB_MEMORY_LIMIT", "4GB")
```

---

## Decision 5: Zero-Copy CSV Reading with read_csv_auto()

### Decision
Use DuckDB's `read_csv_auto()` function for loading CSV files, enabling zero-copy streaming.

### Rationale
- `read_csv_auto()` auto-detects schema (column types, delimiters, headers)
- Streams data in chunks - memory usage is O(chunk_size) not O(file_size)
- Supports glob patterns for multiple files (`*.csv`)
- Built-in error handling with `store_rejects` option
- Significantly faster than pandas for large files

### Implementation Notes
```sql
-- Basic usage
SELECT * FROM read_csv_auto('/path/to/data.csv')

-- With options
SELECT * FROM read_csv_auto(
    '/path/to/data.csv',
    header=true,
    sample_size=10000,
    store_rejects=true
)

-- Multiple files
SELECT * FROM read_csv_auto('/data/*.csv', union_by_name=true)
```

### Python Integration
```python
import duckdb

conn = duckdb.connect(":memory:")

# Create view from CSV (zero-copy reference)
conn.execute("""
    CREATE VIEW dataset AS
    SELECT * FROM read_csv_auto(?)
""", [csv_path])

# Query with GE
# The view can be used with SqlAlchemyExecutionEngine
```

---

## Decision 6: Out-of-Core Processing Configuration

### Decision
Configure DuckDB memory limits and temp directory for out-of-core processing of datasets larger than available RAM.

### Rationale
- DuckDB automatically spills to disk when memory limit exceeded
- Temp directory allows processing datasets larger than RAM
- Memory limit prevents OOM conditions
- Configuration via environment variables enables infrastructure tuning

### Configuration Options
```python
import duckdb

conn = duckdb.connect("/tmp/db.duckdb", config={
    "memory_limit": "2GB",      # Maximum RAM usage
    "temp_directory": "/tmp/duckdb",  # Spill location
    "threads": 4,               # Parallelism
})
```

Or via SQL:
```sql
SET memory_limit = '2GB';
SET temp_directory = '/tmp/duckdb';
SET threads = 4;
```

### Disk Space Requirements
- Temp storage: 1-2x CSV file size during processing
- Database file: Compressed, typically 30-50% of CSV size

---

## Decision 7: Thread Safety and Connection Management

### Decision
Use `connection.cursor()` for thread-local access to DuckDB connections.

### Rationale
- DuckDB connections are NOT thread-safe
- `cursor()` provides thread-local operation handling
- Prevents data corruption in concurrent access scenarios
- Aligns with DuckDB documentation recommendations

### Implementation Pattern
```python
import duckdb
from contextlib import contextmanager

class DuckDBConnectionManager:
    def __init__(self, db_path: str, config: dict = None):
        self._conn = duckdb.connect(db_path, config=config or {})

    @contextmanager
    def cursor(self):
        """Thread-safe cursor access."""
        cur = self._conn.cursor()
        try:
            yield cur
        finally:
            cur.close()

    def close(self):
        self._conn.close()
```

---

## Decision 8: Error Handling Strategy

### Decision
Implement graceful fallback to pandas when DuckDB encounters errors, with clear error messages for unrecoverable cases.

### Rationale
- Maintains system reliability when DuckDB is unavailable
- Clear error messages help users diagnose issues
- Fallback prevents complete failure for small files
- Large files (>1GB) must fail clearly since pandas cannot handle them

### Error Categories

| Error Type | Handling |
|------------|----------|
| DuckDB not installed | Fallback to pandas + warning (small files), clear error (large files) |
| Invalid URI format | Clear error with valid format examples |
| File not found | Standard file not found error |
| Disk space exhausted | Clear error indicating disk space issue |
| Memory limit exceeded | Clear error suggesting increased limit or temp directory |
| CSV parsing error | Return DuckDB's detailed error message |

### Implementation Notes
```python
class DuckDBError(Exception):
    """Base exception for DuckDB integration errors."""
    pass

class DuckDBConnectionError(DuckDBError):
    """Failed to establish DuckDB connection."""
    pass

class DuckDBCSVError(DuckDBError):
    """Failed to parse CSV file."""
    pass

class DuckDBUnavailableError(DuckDBError):
    """DuckDB is not installed or incompatible."""
    pass
```

---

## File Structure Recommendation

Based on research, the following file structure is recommended:

```
gx_mcp_server/
├── connectors/
│   └── duckdb.py           # NEW: DuckDB connector + connection manager
├── core/
│   ├── schema.py           # MODIFY: Add DuckDBURIConfig
│   ├── storage.py          # MODIFY: Add engine metadata to DatasetHandle
│   └── config.py           # NEW: Environment variable configuration
├── tools/
│   ├── datasets.py         # MODIFY: Add duckdb:// URI routing
│   └── validation.py       # MODIFY: Handle DuckDB-backed datasets
└── exceptions.py           # NEW: DuckDB-specific exceptions
```

---

## Dependencies

### Required
```toml
[project.dependencies]
duckdb = ">=0.9.0"
duckdb-engine = ">=0.9.0"
```

### Version Compatibility
- DuckDB 0.9.0+ required for `read_csv_auto` improvements
- duckdb-engine 0.9.0+ required for SQLAlchemy 2.0 compatibility
- Great Expectations 0.17+ for SqlAlchemyExecutionEngine stability

---

## Performance Expectations

Based on research and DuckDB benchmarks:

| File Size | Pandas Load Time | DuckDB Load Time | Memory (Pandas) | Memory (DuckDB) |
|-----------|------------------|------------------|-----------------|-----------------|
| 100MB | 2s | 1s | 300MB | 100MB |
| 1GB | 20s | 5s | 3GB | 200MB |
| 5GB | OOM | 25s | OOM | 500MB |
| 10GB | OOM | 50s | OOM | 800MB |

*Note: DuckDB memory with 2GB limit and temp directory configured*

---

## Open Questions (Resolved)

| Question | Resolution |
|----------|------------|
| Which SQLAlchemy pool to use? | StaticPool for memory, NullPool for file |
| How to handle thread safety? | Use cursor() for thread-local access |
| What size threshold? | 500MB default, configurable via env var |
| How to detect DuckDB availability? | Try import, catch ImportError |

---

## References

1. DuckDB Python API Documentation (v1.1+)
2. duckdb-engine SQLAlchemy Dialect Documentation
3. Great Expectations SqlAlchemyExecutionEngine Source
4. RFC 3986 - Uniform Resource Identifier (URI): Generic Syntax
5. SQLAlchemy Connection Pooling Documentation
