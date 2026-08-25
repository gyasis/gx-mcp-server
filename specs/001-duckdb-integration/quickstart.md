# Quickstart: DuckDB Integration

**Feature Branch**: `001-duckdb-integration`
**Target Audience**: Developers implementing this feature
**Prerequisites**: Familiarity with Great Expectations, SQLAlchemy, and the existing gx-mcp-server codebase

---

## Overview

This guide helps developers get started implementing the DuckDB integration for large CSV validation. After reading this, you'll understand:

1. How the feature fits into the existing architecture
2. Key implementation patterns and gotchas
3. How to test your implementation

---

## Architecture Context

### Before (Current State)

```
User Request → load_dataset() → pandas.read_csv() → DataFrame → DatasetHandle
```

**Limitation**: Files >1GB cause memory errors.

### After (With DuckDB Integration)

```
User Request → load_dataset() → RoutingDecision
                                     │
                    ┌────────────────┴────────────────┐
                    │                                 │
              file < 500MB                     file >= 500MB
              OR no duckdb://                  OR duckdb://
                    │                                 │
                    ▼                                 ▼
            pandas.read_csv()              DuckDBConnectionManager
                    │                                 │
                    ▼                                 ▼
              DataFrame                    SqlAlchemy Engine
                    │                                 │
                    └────────────────┬────────────────┘
                                     │
                                     ▼
                              DatasetHandle
                              (with engine metadata)
```

---

## Getting Started

### 1. Install Dependencies

```bash
# Add to pyproject.toml
uv add duckdb duckdb-engine

# Or if using pip
pip install duckdb>=0.9.0 duckdb-engine>=0.9.0
```

### 2. Verify DuckDB Installation

```python
# Quick verification script
import duckdb
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# Test basic DuckDB
conn = duckdb.connect(":memory:")
result = conn.execute("SELECT 42 as answer").fetchone()
assert result[0] == 42
print("DuckDB direct: OK")

# Test SQLAlchemy integration
engine = create_engine("duckdb:///:memory:", poolclass=StaticPool)
with engine.connect() as conn:
    result = conn.execute("SELECT 42 as answer").fetchone()
    assert result[0] == 42
print("SQLAlchemy + DuckDB: OK")

# Test CSV loading
conn = duckdb.connect(":memory:")
conn.execute("""
    CREATE TABLE test AS
    SELECT * FROM read_csv_auto('/path/to/test.csv')
""")
print("CSV loading: OK")
```

---

## Implementation Patterns

### Pattern 1: StaticPool for In-Memory Databases (CRITICAL)

**Problem**: Great Expectations may create multiple connections during validation, causing "Connection Closed" errors.

**Solution**: Always use `StaticPool` for in-memory DuckDB databases.

```python
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool, NullPool

def create_duckdb_engine(db_path: str | None, config: dict) -> Engine:
    """Create SQLAlchemy engine for DuckDB with correct pooling."""
    if db_path is None or db_path == ":memory:":
        # In-memory: StaticPool maintains single connection
        return create_engine(
            "duckdb:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False}
        )
    else:
        # File-based: NullPool is fine since data persists
        return create_engine(
            f"duckdb:///{db_path}",
            poolclass=NullPool
        )
```

### Pattern 2: Zero-Copy CSV Loading

**Problem**: Loading large CSVs into memory defeats the purpose.

**Solution**: Use `read_csv_auto()` to create a view.

```python
def load_csv_as_view(conn: duckdb.DuckDBPyConnection, csv_path: str, view_name: str):
    """Create a DuckDB view from CSV without loading into memory."""
    # read_csv_auto streams the CSV - no full memory load
    conn.execute(f"""
        CREATE VIEW {view_name} AS
        SELECT * FROM read_csv_auto(?)
    """, [csv_path])
```

### Pattern 3: Thread-Safe Cursor Access

**Problem**: DuckDB connections are NOT thread-safe.

**Solution**: Use `cursor()` for thread-local operations.

```python
from contextlib import contextmanager

class DuckDBConnectionManager:
    def __init__(self, db_path: str | None, config: dict):
        self._conn = duckdb.connect(db_path or ":memory:", config=config)

    @contextmanager
    def cursor(self):
        """Thread-safe cursor access."""
        cur = self._conn.cursor()
        try:
            yield cur
        finally:
            cur.close()

    def execute(self, sql: str, params=None):
        """Execute SQL with thread-local cursor."""
        with self.cursor() as cur:
            return cur.execute(sql, params or []).fetchall()
```

### Pattern 4: URI Parsing

**Solution**: Use `urllib.parse` for RFC 3986 compliance.

```python
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class DuckDBURIConfig:
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
        raise ValueError(f"Invalid scheme: {parsed.scheme}")

    # Path handling: urlparse keeps leading slash
    path = parsed.path.lstrip("/") if parsed.path else None
    params = parse_qs(parsed.query)

    # Determine type
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

### Pattern 5: Size-Based Routing

```python
import os
from gx_mcp_server.core.config import DuckDBConfig

def should_use_duckdb(source: str, config: DuckDBConfig) -> RoutingDecision:
    """Determine if DuckDB should be used for this source."""
    # Check if explicitly disabled
    if not config.enabled:
        return RoutingDecision(engine="pandas", reason="DuckDB disabled via config")

    # Check for explicit duckdb:// URI
    if source.startswith("duckdb://"):
        uri_config = parse_duckdb_uri(source)
        return RoutingDecision(
            engine="duckdb",
            reason="Explicit duckdb:// URI scheme",
            uri_config=uri_config
        )

    # Check file size for automatic routing
    if os.path.isfile(source):
        file_size = os.path.getsize(source)
        threshold_bytes = config.size_threshold_mb * 1024 * 1024

        if file_size > threshold_bytes:
            return RoutingDecision(
                engine="duckdb",
                reason=f"File size ({file_size} bytes) exceeds threshold ({threshold_bytes} bytes)",
                file_size_bytes=file_size
            )
        else:
            return RoutingDecision(
                engine="pandas",
                reason=f"File size ({file_size} bytes) below threshold ({threshold_bytes} bytes)",
                file_size_bytes=file_size
            )

    # Default to pandas for URLs and other sources
    return RoutingDecision(engine="pandas", reason="Non-file source defaults to pandas")
```

---

## Common Gotchas

### Gotcha 1: Forgetting StaticPool

```python
# WRONG - will cause "Connection Closed" errors
engine = create_engine("duckdb:///:memory:")

# CORRECT
engine = create_engine("duckdb:///:memory:", poolclass=StaticPool)
```

### Gotcha 2: Memory vs File Database Confusion

```python
# In-memory (data lost when connection closes)
"duckdb:///:memory:"

# File-based (data persists)
"duckdb:///path/to/db.duckdb"

# Note the triple slash for file paths!
```

### Gotcha 3: Thread Safety

```python
# WRONG - sharing connection across threads
class BAD:
    def __init__(self):
        self.conn = duckdb.connect(":memory:")

    def query(self, sql):  # Called from multiple threads
        return self.conn.execute(sql)  # Race condition!

# CORRECT - cursor per operation
class GOOD:
    def __init__(self):
        self.conn = duckdb.connect(":memory:")

    def query(self, sql):
        cur = self.conn.cursor()  # Thread-local
        try:
            return cur.execute(sql).fetchall()
        finally:
            cur.close()
```

### Gotcha 4: CSV Path in Query Parameters

```python
# WRONG - SQL injection risk
conn.execute(f"SELECT * FROM read_csv_auto('{csv_path}')")

# CORRECT - parameterized query
conn.execute("SELECT * FROM read_csv_auto(?)", [csv_path])
```

---

## Testing Your Implementation

### Unit Test: URI Parsing

```python
def test_parse_csv_uri():
    config = parse_duckdb_uri("duckdb:///data/sales.csv")
    assert config.uri_type == "csv"
    assert config.path == "data/sales.csv"

def test_parse_memory_uri():
    config = parse_duckdb_uri("duckdb:///:memory:?memory_limit=2GB")
    assert config.uri_type == "memory"
    assert config.path is None
    assert config.memory_limit == "2GB"

def test_parse_database_uri():
    config = parse_duckdb_uri("duckdb:///warehouse.db?table=users&read_only=true")
    assert config.uri_type == "database"
    assert config.table == "users"
    assert config.read_only is True
```

### Integration Test: Large File Loading

```python
import tempfile
import pytest

@pytest.fixture
def large_csv(tmp_path):
    """Create a 600MB CSV file for testing."""
    csv_path = tmp_path / "large.csv"
    with open(csv_path, "w") as f:
        f.write("id,value\n")
        # Write enough rows to exceed 500MB
        for i in range(10_000_000):
            f.write(f"{i},{i * 1.5}\n")
    return csv_path

def test_large_file_routes_to_duckdb(large_csv):
    result = load_dataset(str(large_csv))
    assert result.engine == "duckdb"
    assert result.row_count == 10_000_000
```

### Integration Test: Validation Result Parity

```python
def test_validation_result_format_parity(sample_csv):
    """Ensure DuckDB and pandas produce identical result formats."""
    # Load same data via both engines
    pandas_handle = load_dataset(str(sample_csv))
    duckdb_handle = load_dataset(f"duckdb:///{sample_csv}")

    # Create same suite
    suite = create_suite("test_suite", pandas_handle.id)
    add_expectation(suite.id, "expect_column_to_exist", {"column": "id"})

    # Run validation on both
    pandas_result = run_checkpoint(pandas_handle.id, suite.id)
    duckdb_result = run_checkpoint(duckdb_handle.id, suite.id)

    # Compare (excluding timing and engine metadata)
    assert pandas_result.success == duckdb_result.success
    assert len(pandas_result.results) == len(duckdb_result.results)
```

---

## File Structure Reference

```
gx_mcp_server/
├── connectors/
│   └── duckdb.py           # NEW: DuckDBConnectionManager, create_duckdb_engine
├── core/
│   ├── config.py           # NEW: DuckDBConfig, load_config()
│   ├── schema.py           # MODIFY: Add DuckDBURIConfig, extend DatasetHandle
│   └── storage.py          # MODIFY: Track engine metadata
├── tools/
│   ├── datasets.py         # MODIFY: Add routing logic, duckdb:// handling
│   └── validation.py       # MODIFY: Route to correct execution engine
└── exceptions.py           # NEW: DuckDBError, DuckDBConnectionError, etc.
```

---

## Next Steps

1. Read the full [research.md](./research.md) for detailed decision rationale
2. Review [data-model.md](./data-model.md) for entity definitions
3. Check JSON schemas in `contracts/` for API contracts
4. Run `/speckit.tasks` to generate implementation tasks

---

## Resources

- [DuckDB Python API Documentation](https://duckdb.org/docs/api/python/overview)
- [duckdb-engine GitHub](https://github.com/Mause/duckdb_engine)
- [Great Expectations SqlAlchemyExecutionEngine](https://docs.greatexpectations.io/docs/)
- [SQLAlchemy Connection Pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html)
