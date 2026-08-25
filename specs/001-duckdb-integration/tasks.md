# Tasks: DuckDB Integration for Large CSV Validation

**Feature Branch**: `001-duckdb-integration`
**Input**: Design documents from `/specs/001-duckdb-integration/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Project initialization and dependency configuration

- [ ] T001 [P] Add DuckDB dependencies to `pyproject.toml`: `duckdb>=0.9.0`, `duckdb-engine>=0.9.0`
- [ ] T002 [P] Create project structure: `gx_mcp_server/connectors/` directory with `__init__.py`
- [ ] T003 [P] Create test structure: `tests/test_duckdb/` directory with `__init__.py`
- [ ] T004 Run `uv sync` to install new dependencies and verify DuckDB imports work

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Core Schema & Configuration

- [ ] T005 [P] Create `DuckDBURIConfig` dataclass in `gx_mcp_server/core/schema.py` per `contracts/duckdb_uri_config.schema.json`
- [ ] T006 [P] Create `RoutingDecision` dataclass in `gx_mcp_server/core/schema.py` per `contracts/routing_decision.schema.json`
- [ ] T007 [P] Create `DuckDBConfig` dataclass in `gx_mcp_server/core/config.py` with env vars: `GX_DUCKDB_ENABLED`, `GX_DUCKDB_SIZE_THRESHOLD_MB`, `GX_DUCKDB_MEMORY_LIMIT`, `GX_DUCKDB_TEMP_DIR`
- [ ] T008 [P] Create `load_config()` function in `gx_mcp_server/core/config.py` to parse environment variables

### Exception Hierarchy

- [ ] T009 [P] Create `gx_mcp_server/exceptions.py` with base `DuckDBError` exception
- [ ] T010 [P] Add `DuckDBConnectionError` exception for connection failures in `gx_mcp_server/exceptions.py`
- [ ] T011 [P] Add `DuckDBURIParseError` exception for URI parsing failures in `gx_mcp_server/exceptions.py`

### DuckDB Connection Manager

- [ ] T012 Create `DuckDBConnectionManager` class in `gx_mcp_server/connectors/duckdb.py` (depends on T005, T007)
- [ ] T013 Implement `cursor()` context manager for thread-safe cursor access in `gx_mcp_server/connectors/duckdb.py`
- [ ] T014 Implement `create_duckdb_engine()` with `StaticPool` for memory, `NullPool` for file in `gx_mcp_server/connectors/duckdb.py`
- [ ] T015 Implement `close()` method with proper resource cleanup in `gx_mcp_server/connectors/duckdb.py`

### URI Parsing

- [ ] T016 Implement `parse_duckdb_uri()` function in `gx_mcp_server/connectors/duckdb.py` (depends on T005, T011)

### DatasetHandle Extension

- [ ] T017 Extend `DatasetHandle` in `gx_mcp_server/core/schema.py` with `engine` field per `contracts/dataset_handle.schema.json`
- [ ] T018 Add `EngineMetadata` nested dataclass for DuckDB-specific metadata in `gx_mcp_server/core/schema.py`

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 + 4 - Large CSV Validation + Seamless Results (Priority: P1) 🎯 MVP

**Goal**: Validate CSV files >500MB automatically via DuckDB with identical result format to pandas

**Independent Test**: Load a 2GB CSV, run validation, verify success without memory errors and results match pandas format

### Tests for US1 + US4

- [ ] T019 [P] [US1] Create `tests/test_duckdb/test_large_files.py` with test for 600MB+ CSV loading AND explicit memory assertion (process RSS < 2GB during 2GB file validation per SC-002)
- [ ] T020 [P] [US4] Create `tests/test_duckdb/test_result_parity.py` with test comparing pandas vs DuckDB result format

### Implementation for US1 - Automatic Large File Routing

- [ ] T021 [US1] Implement `should_use_duckdb()` routing function in `gx_mcp_server/tools/datasets.py` (depends on T006, T007)
- [ ] T022 [US1] Implement `load_csv_as_view()` for zero-copy CSV loading in `gx_mcp_server/connectors/duckdb.py`
- [ ] T023 [US1] Modify `load_dataset()` in `gx_mcp_server/tools/datasets.py` to call routing and handle DuckDB path
- [ ] T024 [US1] Update `DataStorage` in `gx_mcp_server/core/storage.py` to track engine metadata

### Implementation for US4 - Result Format Parity

- [ ] T025 [US4] Modify `run_checkpoint()` in `gx_mcp_server/tools/validation.py` to route to correct execution engine based on `DatasetHandle.engine`
- [ ] T026 [US4] Ensure `SqlAlchemyExecutionEngine` produces identical `ValidationResult` structure
- [ ] T027 [US4] Update `ValidationResult` in `gx_mcp_server/core/schema.py` to include `engine` and `run_time_ms` fields

**Checkpoint**: US1 + US4 complete - Large files validate with identical results to pandas

---

## Phase 4: User Story 2 - Explicit DuckDB URI Support (Priority: P2)

**Goal**: Support `duckdb://` URI scheme for explicit DuckDB usage regardless of file size

**Independent Test**: Use `duckdb:///path/to/small.csv` with a 50MB file and verify DuckDB is used

### Tests for US2

- [ ] T028 [P] [US2] Create `tests/test_duckdb/test_uri_parsing.py` with tests for all URI formats
- [ ] T029 [P] [US2] Add test for `duckdb:///path.csv` CSV loading in `tests/test_duckdb/test_uri_parsing.py`
- [ ] T030 [P] [US2] Add test for `duckdb:///db.db?table=name` database loading in `tests/test_duckdb/test_uri_parsing.py`
- [ ] T031 [P] [US2] Add test for `duckdb:///:memory:?csv=/path` memory mode in `tests/test_duckdb/test_uri_parsing.py`

### Implementation for US2

- [ ] T032 [US2] Update `load_dataset()` in `gx_mcp_server/tools/datasets.py` to detect `duckdb://` scheme and parse URI
- [ ] T033 [US2] Implement CSV URI handling (`duckdb:///path.csv`) in `gx_mcp_server/tools/datasets.py`
- [ ] T034 [US2] Implement database URI handling (`duckdb:///db?table=name`) in `gx_mcp_server/tools/datasets.py`
- [ ] T035 [US2] Implement memory URI handling (`duckdb:///:memory:`) in `gx_mcp_server/tools/datasets.py`
- [ ] T036 [US2] Add URI format validation with clear error messages using `DuckDBURIParseError`

**Checkpoint**: US2 complete - All `duckdb://` URI formats work correctly

---

## Phase 5: User Story 3 - Configuration-Based Routing (Priority: P3)

**Goal**: Allow administrators to configure size threshold and enable/disable DuckDB via environment variables

**Independent Test**: Set `GX_DUCKDB_SIZE_THRESHOLD_MB=100`, load 150MB file, verify DuckDB is used

### Tests for US3

- [ ] T037 [P] [US3] Create `tests/test_duckdb/test_config.py` with test for custom threshold
- [ ] T038 [P] [US3] Add test for `GX_DUCKDB_ENABLED=false` disabling in `tests/test_duckdb/test_config.py`
- [ ] T039 [P] [US3] Add test for `GX_DUCKDB_MEMORY_LIMIT` configuration in `tests/test_duckdb/test_config.py`

### Implementation for US3

- [ ] T040 [US3] Ensure `load_config()` in `gx_mcp_server/core/config.py` reads all env vars correctly
- [ ] T041 [US3] Update `should_use_duckdb()` in `gx_mcp_server/tools/datasets.py` to respect `config.enabled`
- [ ] T042 [US3] Update `DuckDBConnectionManager` to apply `config.memory_limit` setting
- [ ] T043 [US3] Update `DuckDBConnectionManager` to use `config.temp_directory` for spill files

**Checkpoint**: US3 complete - All configuration options work correctly

---

## Phase 6: Error Handling & Fallback

**Purpose**: Graceful degradation when DuckDB unavailable (FR-006)

### Tests for Fallback

- [ ] T044 [P] Create `tests/test_duckdb/test_fallback.py` with test for DuckDB unavailable scenario
- [ ] T045 [P] Add test for fallback with file under pandas limit in `tests/test_duckdb/test_fallback.py`
- [ ] T046 [P] Add test for clear error when file too large and DuckDB unavailable

### Implementation

- [ ] T047 Implement DuckDB availability check in `gx_mcp_server/connectors/duckdb.py`
- [ ] T048 Update `should_use_duckdb()` to handle fallback logic with `fallback_from` field
- [ ] T049 Add warning logging when falling back from DuckDB to pandas
- [ ] T050 Add clear error message when file >1GB and DuckDB unavailable

**Checkpoint**: Graceful fallback works for all edge cases

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T051 [P] Add connection cleanup on `DatasetHandle` garbage collection (FR-010)
- [ ] T052 [P] Add logging throughout DuckDB operations for debugging
- [ ] T053 [P] Update `__init__.py` exports in `gx_mcp_server/connectors/`
- [ ] T054 [P] Update `__init__.py` exports in `gx_mcp_server/core/`
- [ ] T055 Run `quickstart.md` validation script from `specs/001-duckdb-integration/quickstart.md`
- [ ] T056 Run full test suite: `uv run pytest`
- [ ] T057 Run type checking: `uv run mypy gx_mcp_server`
- [ ] T058 Run linting: `uv run ruff check . --fix`

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1: Setup ──────────────────────────────────────────────────────────────►
                   │
                   ▼
Phase 2: Foundational ───────────────────────────────────────────────────────►
                   │
         ┌────────┴────────┐
         │                 │
         ▼                 ▼
Phase 3: US1+US4      Phase 4: US2      (can run in parallel after Phase 2)
(P1 - MVP)            (P2)
         │                 │
         └────────┬────────┘
                  │
                  ▼
            Phase 5: US3 (P3)
                  │
                  ▼
            Phase 6: Fallback
                  │
                  ▼
            Phase 7: Polish
```

### Task Dependencies Within Phases

**Phase 2 (Foundational)**:
- T005-T011 (schemas, config, exceptions) can run in parallel [P]
- T012-T015 (ConnectionManager) depends on T005, T007
- T016 (parse_duckdb_uri) depends on T005, T011
- T017-T018 (DatasetHandle extension) depends on T005

**Phase 3 (US1+US4)**:
- T019-T020 (tests) can run in parallel [P]
- T021 depends on T006, T007
- T022 depends on T012
- T023 depends on T021, T022
- T025-T027 depend on T023

### Parallel Opportunities

```bash
# Launch all Phase 2 schema/config tasks together:
T005: "Create DuckDBURIConfig in gx_mcp_server/core/schema.py"
T006: "Create RoutingDecision in gx_mcp_server/core/schema.py"
T007: "Create DuckDBConfig in gx_mcp_server/core/config.py"
T008: "Create load_config() in gx_mcp_server/core/config.py"
T009: "Create DuckDBError in gx_mcp_server/exceptions.py"
T010: "Add DuckDBConnectionError in gx_mcp_server/exceptions.py"
T011: "Add DuckDBURIParseError in gx_mcp_server/exceptions.py"

# Launch US2 tests together:
T028: "Create tests/test_duckdb/test_uri_parsing.py"
T029: "Add test for CSV URI loading"
T030: "Add test for database URI loading"
T031: "Add test for memory URI loading"
```

---

## Implementation Strategy

### MVP First (US1 + US4 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: US1 + US4
4. **STOP and VALIDATE**: Test with 600MB+ CSV file
5. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 + US4 → Large file validation works (MVP!)
3. US2 → Explicit URI support added
4. US3 → Configuration options added
5. Fallback → Error handling complete
6. Polish → Production ready

---

## Task Summary

| Phase | Tasks | Parallel | Story Coverage |
|-------|-------|----------|----------------|
| Setup | T001-T004 | 3 | - |
| Foundational | T005-T018 | 7 | - |
| US1+US4 (P1) | T019-T027 | 2 | US1, US4 |
| US2 (P2) | T028-T036 | 4 | US2 |
| US3 (P3) | T037-T043 | 3 | US3 |
| Fallback | T044-T050 | 3 | Cross-cutting |
| Polish | T051-T058 | 4 | Cross-cutting |

**Total Tasks**: 58
**Parallel Tasks**: 26
**Critical Path**: Setup → Foundational → US1+US4 (MVP)

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Success Criteria SC-001 through SC-008 are verified by Phase 7 tests
