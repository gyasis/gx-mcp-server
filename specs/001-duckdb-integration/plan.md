# Implementation Plan: DuckDB Integration for Large CSV Validation

**Branch**: `001-duckdb-integration` | **Date**: 2026-01-11 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-duckdb-integration/spec.md`

## Summary

This feature integrates DuckDB as an alternative execution engine for Great Expectations within the gx-mcp-server. Large CSV files (>500MB) are automatically routed to DuckDB for out-of-core processing, while smaller files continue using pandas. Users can explicitly request DuckDB via `duckdb://` URI scheme.

Technical approach: Use `SqlAlchemyExecutionEngine` with `duckdb-engine` SQLAlchemy dialect, `StaticPool` for connection management, and `read_csv_auto()` for zero-copy CSV streaming.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: great-expectations>=0.17.0, duckdb>=0.9.0, duckdb-engine>=0.9.0, sqlalchemy>=2.0.0
**Storage**: In-memory (DuckDB `:memory:`) + file-based (`.duckdb` files) + temp directory for spill
**Testing**: pytest with existing test structure in `tests/`
**Target Platform**: Linux server (MCP server deployment), also supports macOS/Windows
**Project Type**: Single project (library + MCP server)
**Performance Goals**: 10GB file validation in <5 minutes, memory <4GB regardless of file size
**Constraints**: Must maintain backward compatibility with existing pandas path, <10% regression for small files
**Scale/Scope**: Files up to 10GB+ in production, concurrent validation requests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Since the constitution is a template, we follow these general principles:

- [x] **Library-First**: DuckDB connector will be a self-contained module in `connectors/`
- [x] **Test-First**: Tests defined in spec.md acceptance scenarios will be written first
- [x] **Simplicity**: Uses existing GE infrastructure (SqlAlchemyExecutionEngine) rather than custom engine
- [x] **Backward Compatibility**: Existing pandas path unchanged, feature is additive

## Project Structure

### Documentation (this feature)

```text
specs/001-duckdb-integration/
├── plan.md              # This file
├── research.md          # Phase 0 output - COMPLETED
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── duckdb_uri.schema.json
│   └── dataset_handle.schema.json
├── checklists/
│   └── requirements.md  # Validation checklist - COMPLETED
└── tasks.md             # Phase 2 output (via /speckit.tasks)
```

### Source Code (repository root)

```text
gx_mcp_server/
├── connectors/
│   ├── __init__.py
│   ├── bigquery.py      # Existing
│   ├── snowflake.py     # Existing
│   └── duckdb.py        # NEW: DuckDB connector + connection manager
├── core/
│   ├── __init__.py
│   ├── context.py       # Existing
│   ├── schema.py        # MODIFY: Add DuckDBURIConfig, extend DatasetHandle
│   ├── storage.py       # MODIFY: Add engine metadata tracking
│   └── config.py        # NEW: Environment variable configuration
├── tools/
│   ├── __init__.py
│   ├── datasets.py      # MODIFY: Add duckdb:// URI routing + size-based routing
│   ├── expectations.py  # Existing (no changes needed)
│   ├── health.py        # Existing (no changes needed)
│   └── validation.py    # MODIFY: Handle DuckDB-backed datasets
├── exceptions.py        # NEW: DuckDB-specific exceptions
├── server.py            # Existing (no changes needed)
└── ...

tests/
├── conftest.py          # MODIFY: Add DuckDB fixtures
├── test_datasets.py     # MODIFY: Add duckdb:// URI tests
├── test_validation.py   # MODIFY: Add DuckDB validation tests
├── test_duckdb/         # NEW: DuckDB-specific tests
│   ├── test_connector.py
│   ├── test_uri_parsing.py
│   ├── test_large_files.py
│   └── test_fallback.py
└── ...
```

**Structure Decision**: Single project structure matches existing codebase. New DuckDB connector follows pattern established by `connectors/snowflake.py` and `connectors/bigquery.py`.

## Complexity Tracking

> No constitution violations requiring justification.

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| Single new module | `connectors/duckdb.py` | Follows existing connector pattern |
| Minimal modifications | 4 existing files modified | Changes are additive, not refactoring |
| No new abstractions | Uses existing GE SqlAlchemyExecutionEngine | Avoids custom engine complexity |

## Phase Outputs

### Phase 0: Research (COMPLETED)
- [x] `research.md` - Consolidated research findings with decisions and rationale

### Phase 1: Design (IN PROGRESS)
- [ ] `data-model.md` - Key entities and relationships
- [ ] `contracts/` - JSON schemas for DuckDBURIConfig, DatasetHandle extensions
- [ ] `quickstart.md` - Developer onboarding guide

### Phase 2: Tasks (PENDING - via /speckit.tasks)
- [ ] `tasks.md` - Dependency-ordered implementation tasks

## Key Design Decisions (from research.md)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| GE Integration | SqlAlchemyExecutionEngine + duckdb-engine | Reuses existing GE infrastructure |
| Connection Pool | StaticPool for memory, NullPool for file | Prevents "Connection Closed" errors |
| URI Scheme | `duckdb:///path.csv`, `duckdb:///:memory:` | RFC 3986 compliant, matches existing patterns |
| Size Threshold | 500MB default | Balances pandas speed vs memory safety |
| CSV Loading | `read_csv_auto()` | Zero-copy streaming, auto schema detection |
| Thread Safety | `connection.cursor()` | Thread-local access per DuckDB docs |

## Dependencies to Add

```toml
# pyproject.toml additions
[project.dependencies]
duckdb = ">=0.9.0"
duckdb-engine = ">=0.9.0"
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GX_DUCKDB_ENABLED` | `true` | Enable/disable DuckDB integration |
| `GX_DUCKDB_SIZE_THRESHOLD_MB` | `500` | Auto-routing threshold in MB |
| `GX_DUCKDB_MEMORY_LIMIT` | `4GB` | DuckDB memory limit |
| `GX_DUCKDB_TEMP_DIR` | System temp | Temp directory for spill |
