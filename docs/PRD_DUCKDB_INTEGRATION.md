# Product Requirements Document: DuckDB Integration for gx-mcp-server

## Executive Summary

This PRD outlines the requirements for integrating DuckDB capabilities into the Great Expectations MCP Server (`gx-mcp-server`) to enable handling of large CSV files beyond the current 1GB limit. The integration will allow users to validate datasets of any size using DuckDB's out-of-core processing capabilities while maintaining the existing API and user experience.

**Status**: Draft  
**Version**: 1.0  
**Date**: 2025-01-14  
**Author**: Analysis Team

---

## 1. Problem Statement

### Current Limitations

The `gx-mcp-server` currently has the following constraints:

1. **CSV Size Limit**: Default 50MB, maximum 1GB (configurable via `MCP_CSV_SIZE_LIMIT_MB`)
2. **Memory Constraints**: All CSV files are loaded into pandas DataFrames in memory
3. **Performance**: Large files cause memory issues and slow processing
4. **Scalability**: Cannot handle datasets larger than available RAM

### User Impact

- Users cannot validate large CSV files (>1GB) through the MCP server
- Memory-intensive operations fail on resource-constrained systems
- No efficient way to process very large datasets without cloud warehouses

### Business Value

- Enable validation of enterprise-scale datasets (10GB+)
- Reduce infrastructure requirements (no need for Spark clusters)
- Improve user experience for data quality workflows
- Support for local-first data validation workflows

---

## 2. Solution Overview

### Primary Approach: Direct DuckDB Integration

Integrate DuckDB directly into `gx-mcp-server` as:
1. **Execution Engine**: Use DuckDB via SQLAlchemy for Great Expectations validations
2. **Data Connector**: Add `duckdb://` URI prefix for loading large CSVs
3. **Smart Routing**: Automatically route large files to DuckDB, small files to Pandas

### Secondary Approach: MCP-to-MCP Communication (Optional)

Enable `gx-mcp-server` to communicate with a separate DuckDB MCP server for distributed scenarios.

---

## 3. Technical Architecture

### 3.1 Current Architecture

```
┌─────────────────┐
│  MCP Client     │
│  (Claude/LLM)   │
└────────┬────────┘
         │
         │ MCP Protocol
         │
┌────────▼─────────────────────────┐
│      gx-mcp-server               │
│  ┌──────────────────────────┐   │
│  │  tools/datasets.py       │   │
│  │  - load_dataset()        │   │
│  │  - CSV → pandas DataFrame│   │
│  └──────────────────────────┘   │
│  ┌──────────────────────────┐   │
│  │  tools/validation.py     │   │
│  │  - PandasExecutionEngine │   │
│  └──────────────────────────┘   │
│  ┌──────────────────────────┐   │
│  │  storage/                 │   │
│  │  - In-memory (default)    │   │
│  │  - SQLite (optional)      │   │
│  └──────────────────────────┘   │
└──────────────────────────────────┘
```

### 3.2 Proposed Architecture with DuckDB

```
┌─────────────────┐
│  MCP Client     │
│  (Claude/LLM)   │
└────────┬────────┘
         │
         │ MCP Protocol
         │
┌────────▼──────────────────────────────────────────┐
│      gx-mcp-server                                 │
│  ┌──────────────────────────────────────────────┐ │
│  │  tools/datasets.py                           │ │
│  │  - load_dataset()                            │ │
│  │  - Smart routing:                            │ │
│  │    • < 500MB → pandas DataFrame             │ │
│  │    • > 500MB → DuckDB connector             │ │
│  │  - duckdb:// URI support                    │ │
│  └──────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────┐ │
│  │  connectors/duckdb.py                        │ │
│  │  - load_csv_via_duckdb()                     │ │
│  │  - connect_to_duckdb_db()                    │ │
│  │  - Zero-copy CSV reading                     │ │
│  └──────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────┐ │
│  │  tools/validation.py                         │ │
│  │  - Execution engine selection:               │ │
│  │    • PandasExecutionEngine (small data)      │ │
│  │    • SqlAlchemyExecutionEngine (DuckDB)     │ │
│  └──────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────┐ │
│  │  storage/duckdb_backend.py (optional)        │ │
│  │  - Replace SQLite with DuckDB                │ │
│  │  - Faster analytical queries                 │ │
│  └──────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────┘
         │
         │ (Optional) MCP Protocol
         │
┌────────▼─────────────────────────┐
│  duckdb-mcp-server (optional)    │
│  - For distributed scenarios      │
└───────────────────────────────────┘
```

### 3.3 Key Components

#### 3.3.1 DuckDB Connector (`connectors/duckdb.py`)

**Purpose**: Load large CSVs and connect to DuckDB databases

**Functions**:
- `load_csv_via_duckdb(path: str, max_rows: Optional[int] = None) -> DuckDBConnection`
  - Uses DuckDB's `read_csv_auto()` for zero-copy CSV reading
  - Returns connection string for GX SQLAlchemy engine
  - Handles files of any size (limited by disk, not RAM)

- `load_from_duckdb_uri(uri: str) -> DuckDBConnection`
  - Parse `duckdb:///path/to/db` or `duckdb://:memory:`
  - Connect to existing DuckDB databases
  - Support query parameters for table selection

**Example Usage**:
```python
# Large CSV file
load_dataset("duckdb:///path/to/large_file.csv", source_type="file")

# Existing DuckDB database
load_dataset("duckdb:///data/analytics.db?table=users", source_type="file")

# In-memory DuckDB with CSV
load_dataset("duckdb://:memory:?csv=/path/to/data.csv", source_type="file")
```

#### 3.3.2 Smart Routing Logic

**Location**: `tools/datasets.py`

**Logic**:
```python
def load_dataset(source: str, source_type: str, ...):
    # Check file size
    if source_type == "file":
        file_size = Path(source).stat().st_size
        size_threshold = get_csv_size_limit_bytes()  # Current limit
    
    # Route based on size
    if file_size > size_threshold:
        # Use DuckDB connector
        return duckdb_connector.load_csv_via_duckdb(source)
    else:
        # Use existing pandas path
        return pandas_load(source)
```

#### 3.3.3 Execution Engine Selection

**Location**: `tools/validation.py`

**Changes**:
- Detect if dataset handle is DuckDB-backed
- Select appropriate execution engine:
  - Pandas DataFrame → `PandasExecutionEngine`
  - DuckDB connection → `SqlAlchemyExecutionEngine` with DuckDB dialect

**Code Pattern**:
```python
def _execute_validation(suite_name: str, dataset_handle: str):
    dataset_info = storage.DataStorage.get_info(dataset_handle)
    
    if dataset_info.get("engine") == "duckdb":
        # Use SQLAlchemy execution engine
        connection_string = dataset_info["connection_string"]
        execution_engine = SqlAlchemyExecutionEngine(
            connection_string=connection_string
        )
    else:
        # Use Pandas execution engine (existing)
        df = storage.DataStorage.get(dataset_handle)
        execution_engine = PandasExecutionEngine()
    
    # Continue with validation...
```

---

## 4. Implementation Plan

### Phase 1: Core DuckDB Integration (MVP)

**Goal**: Enable loading and validating large CSVs via DuckDB

**Tasks**:
1. ✅ Add `duckdb` and `duckdb-engine` to `pyproject.toml` dependencies
2. ✅ Create `connectors/duckdb.py` with CSV loading functions
3. ✅ Modify `tools/datasets.py` to detect large files and route to DuckDB
4. ✅ Update `tools/validation.py` to support SQLAlchemy execution engine
5. ✅ Add `duckdb://` URI prefix parsing
6. ✅ Update storage to track execution engine type
7. ✅ Add configuration for size threshold (default: 500MB)

**Dependencies**:
- `duckdb>=0.9.0`
- `duckdb-engine>=0.9.0` (SQLAlchemy dialect)

**Testing**:
- Unit tests for DuckDB connector
- Integration tests with large CSV files (>1GB)
- Performance benchmarks vs pandas
- Memory usage profiling

### Phase 2: Enhanced Features

**Goal**: Improve usability and performance

**Tasks**:
1. Add Parquet conversion for large CSVs (performance optimization)
2. Implement streaming validation for very large datasets
3. Add DuckDB-specific optimizations (columnar projection, predicate pushdown)
4. Support for DuckDB views and CTEs
5. Connection pooling for multiple validations

### Phase 3: MCP-to-MCP Communication (Optional)

**Goal**: Enable distributed scenarios with separate DuckDB MCP server

**Tasks**:
1. Add MCP client capability to `gx-mcp-server`
2. Implement tool discovery for `duckdb-mcp-server`
3. Add `validate_from_duckdb_mcp()` tool
4. Handle connection string passing between servers
5. Error handling and fallback mechanisms

**Considerations**:
- Requires `duckdb-mcp-server` to be running
- Adds network latency
- More complex error handling
- May not be necessary if direct integration works well

### Phase 4: Storage Backend Replacement (Optional)

**Goal**: Replace SQLite with DuckDB for metadata storage

**Tasks**:
1. Create `storage/duckdb_backend.py`
2. Implement `DataStorage` and `ValidationStorage` using DuckDB
3. Add migration path from SQLite to DuckDB
4. Benchmark performance improvements
5. Update configuration options

---

## 5. API Changes

### 5.1 New URI Scheme

**Format**: `duckdb://[path][?query]`

**Examples**:
```
duckdb:///path/to/large_file.csv
duckdb:///data/analytics.db?table=users
duckdb://:memory:?csv=/path/to/data.csv
duckdb:///shared/db.duckdb?view=cleaned_data
```

### 5.2 Enhanced `load_dataset` Tool

**New Parameters** (optional):
- `use_duckdb: bool = False` - Force DuckDB usage
- `duckdb_memory_limit: Optional[str] = None` - Set DuckDB memory limit

**Behavior Changes**:
- Automatically uses DuckDB for files > size threshold
- Returns dataset handle with execution engine metadata
- No breaking changes for existing small-file workflows

### 5.3 New Configuration Options

**Environment Variables**:
- `GX_DUCKDB_ENABLED=true` - Enable DuckDB support (default: true)
- `GX_DUCKDB_SIZE_THRESHOLD_MB=500` - Size threshold for DuckDB routing
- `GX_DUCKDB_MEMORY_LIMIT=4GB` - DuckDB memory limit
- `GX_DUCKDB_MCP_SERVER_URL` - Optional: URL to DuckDB MCP server

---

## 6. Benefits and Trade-offs

### Benefits

1. **No Size Limits**: Handle datasets of any size (limited by disk, not RAM)
2. **Better Performance**: 10-50x faster for analytical queries on large data
3. **Memory Efficiency**: Out-of-core processing prevents OOM errors
4. **Backward Compatible**: Small files still use fast pandas path
5. **Industry Standard**: DuckDB is widely adopted for analytical workloads
6. **Great Expectations Native**: GX already supports SQLAlchemy engines

### Trade-offs

1. **Additional Dependency**: Adds `duckdb` and `duckdb-engine` packages
2. **Complexity**: More execution paths to test and maintain
3. **Learning Curve**: Users need to understand when DuckDB is used
4. **File Format**: Some operations may require Parquet conversion
5. **Concurrency**: DuckDB is single-writer (but supports multiple readers)

### Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Performance regression for small files | Medium | Keep pandas path for files < threshold |
| DuckDB dependency issues | Low | Make DuckDB optional, fallback to pandas |
| Memory leaks in long-running server | Medium | Connection pooling and proper cleanup |
| Breaking changes to API | High | Maintain backward compatibility, version API |

---

## 7. Success Metrics

### Performance Metrics
- ✅ Successfully load and validate CSV files > 1GB
- ✅ Memory usage stays within container limits
- ✅ Validation time for 10GB file < 5 minutes
- ✅ No performance regression for files < 500MB

### User Experience Metrics
- ✅ Zero breaking changes to existing API
- ✅ Automatic routing (no user configuration needed)
- ✅ Clear error messages for edge cases
- ✅ Documentation and examples available

### Technical Metrics
- ✅ Test coverage > 80% for new code
- ✅ All existing tests pass
- ✅ No memory leaks in long-running scenarios
- ✅ Proper error handling and logging

---

## 8. Alternative Approaches Considered

### 8.1 MCP-to-MCP Communication Only

**Approach**: Have `gx-mcp-server` call `duckdb-mcp-server` tools

**Pros**:
- Clean separation of concerns
- Reuses existing DuckDB MCP server
- No new dependencies in gx-mcp-server

**Cons**:
- Requires both servers running
- Network overhead and latency
- More complex error handling
- Dependency on external server availability

**Decision**: Implement as optional Phase 3, not primary approach

### 8.2 Replace Pandas Entirely

**Approach**: Always use DuckDB, even for small files

**Pros**:
- Simpler codebase (one execution path)
- Consistent behavior

**Cons**:
- Slower for small files (DuckDB overhead)
- Breaking change for existing users
- Loss of pandas-specific optimizations

**Decision**: Rejected - maintain pandas path for small files

### 8.3 Spark Integration

**Approach**: Use Spark for large files instead of DuckDB

**Pros**:
- Handles very large distributed datasets
- Industry standard for big data

**Cons**:
- Much heavier dependency
- Requires cluster setup
- Overkill for single-machine scenarios
- GX already supports Spark separately

**Decision**: Rejected - DuckDB is better fit for MCP server use case

---

## 9. Dependencies and Requirements

### New Python Dependencies

```toml
[project]
dependencies = [
    # ... existing dependencies ...
    "duckdb>=0.9.0",
    "duckdb-engine>=0.9.0",  # SQLAlchemy dialect
]

[project.optional-dependencies]
duckdb = [
    "duckdb>=0.9.0",
    "duckdb-engine>=0.9.0",
]
```

### System Requirements

- **Disk Space**: Sufficient for DuckDB database files (typically 1-2x CSV size)
- **Memory**: No additional requirements (DuckDB uses out-of-core processing)
- **Python**: 3.11+ (already required)

### Great Expectations Compatibility

- **Minimum GX Version**: 0.17+ (SQLAlchemy execution engine support)
- **Execution Engine**: Uses `SqlAlchemyExecutionEngine` with DuckDB dialect

---

## 10. Testing Strategy

### Unit Tests

1. **DuckDB Connector Tests**:
   - CSV loading with various sizes
   - URI parsing and validation
   - Connection string generation
   - Error handling

2. **Smart Routing Tests**:
   - Small files route to pandas
   - Large files route to DuckDB
   - Threshold edge cases
   - Configuration overrides

3. **Execution Engine Tests**:
   - SQLAlchemy engine initialization
   - Validation with DuckDB backend
   - Result format consistency

### Integration Tests

1. **End-to-End Workflows**:
   - Load 5GB CSV → Create suite → Validate
   - Compare results between pandas and DuckDB paths
   - Memory usage profiling

2. **Performance Tests**:
   - Benchmark validation time for various file sizes
   - Memory usage comparison
   - Concurrent validation scenarios

### Compatibility Tests

1. **Backward Compatibility**:
   - All existing tests pass
   - Small files work identically
   - API contracts unchanged

---

## 11. Documentation Requirements

### User Documentation

1. **Getting Started Guide**:
   - How DuckDB integration works
   - When DuckDB is used automatically
   - Manual DuckDB usage examples

2. **Configuration Guide**:
   - Environment variables
   - Size thresholds
   - Memory limits

3. **Examples**:
   - Large CSV validation
   - DuckDB database connection
   - Performance optimization tips

### Developer Documentation

1. **Architecture Overview**:
   - Execution engine selection
   - Connector patterns
   - Storage backend options

2. **Extension Guide**:
   - Adding new connectors
   - Custom execution engines
   - Storage backend implementation

---

## 12. Open Questions

1. **Size Threshold**: What should be the default threshold? (Proposed: 500MB)
2. **Parquet Conversion**: Should we automatically convert large CSVs to Parquet?
3. **MCP-to-MCP**: Is Phase 3 (MCP communication) necessary or can we skip it?
4. **Storage Backend**: Should we replace SQLite with DuckDB in Phase 4?
5. **Memory Limits**: Should we expose DuckDB memory configuration to users?

---

## 13. Timeline and Milestones

### Phase 1: Core Integration (4-6 weeks)
- Week 1-2: DuckDB connector implementation
- Week 3-4: Execution engine integration
- Week 5-6: Testing and documentation

### Phase 2: Enhanced Features (2-3 weeks)
- Parquet optimization
- Performance tuning
- Advanced features

### Phase 3: MCP-to-MCP (Optional, 2-3 weeks)
- MCP client implementation
- Integration testing
- Documentation

### Phase 4: Storage Backend (Optional, 1-2 weeks)
- DuckDB backend implementation
- Migration tools
- Performance benchmarking

---

## 14. References

### Related Documentation
- [Great Expectations SQLAlchemy Execution Engine](https://docs.greatexpectations.io/docs/guides/connecting_to_your_data/database/sqlalchemy/)
- [DuckDB Documentation](https://duckdb.org/docs/)
- [DuckDB SQLAlchemy Dialect](https://github.com/Mause/duckdb_engine)
- [gx-mcp-server Architecture](./architecture_mermaid.md)

### Research Sources
- Gemini Deep Research: DuckDB integration patterns
- Gemini Brainstorm: MCP-to-MCP communication architectures
- Great Expectations execution engine analysis

---

## Appendix A: Code Examples

### Example 1: Loading Large CSV

```python
# Automatically uses DuckDB for files > 500MB
result = load_dataset(
    source="/path/to/10gb_file.csv",
    source_type="file"
)
# Returns: DatasetHandle with engine="duckdb"
```

### Example 2: Explicit DuckDB Usage

```python
# Force DuckDB usage
result = load_dataset(
    source="duckdb:///path/to/large_file.csv",
    source_type="file",
    use_duckdb=True
)
```

### Example 3: DuckDB Database Connection

```python
# Connect to existing DuckDB database
result = load_dataset(
    source="duckdb:///data/analytics.db?table=users",
    source_type="file"
)
```

### Example 4: Validation with DuckDB

```python
# Validation automatically uses DuckDB execution engine
validation_result = run_checkpoint(
    suite_name="my_suite",
    dataset_handle=result.handle  # DuckDB-backed handle
)
```

---

## Appendix B: Architecture Diagrams

### Data Flow: Large CSV Validation

```
User Request
    │
    ▼
load_dataset("large.csv")
    │
    ▼
[File Size Check]
    │
    ├─ < 500MB → Pandas Path (existing)
    │
    └─ > 500MB → DuckDB Connector
                  │
                  ▼
            DuckDB.read_csv_auto()
                  │
                  ▼
            SQLAlchemy Connection
                  │
                  ▼
            GX SqlAlchemyExecutionEngine
                  │
                  ▼
            Validation Results
```

---

**End of PRD**

