# Feature Specification: DuckDB Integration for Large CSV Validation

**Feature Branch**: `001-duckdb-integration`
**Created**: 2026-01-11
**Status**: Draft
**Input**: User description: "DuckDB integration for gx-mcp-server to enable handling of large CSV files beyond the current 1GB limit using DuckDB's out-of-core processing capabilities"

## Overview

This feature enables the gx-mcp-server to validate datasets of any size by integrating DuckDB as an alternative execution engine. Large CSV files (>500MB) will be automatically routed to DuckDB for processing, while smaller files continue using the existing pandas path. Users can also explicitly request DuckDB processing via a `duckdb://` URI scheme.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Validate Large CSV File Automatically (Priority: P1)

As a data engineer, I want to validate CSV files larger than 1GB without changing my workflow, so that I can ensure data quality on enterprise-scale datasets.

**Why this priority**: This is the core value proposition - enabling validation of files that currently fail due to memory constraints. Without this, the feature provides no user value.

**Independent Test**: Can be fully tested by loading a 2GB CSV file and running validation. If successful, the system validates the file without memory errors and returns quality results.

**Acceptance Scenarios**:

1. **Given** a CSV file of 2GB exists on disk, **When** I call `load_dataset` with the file path, **Then** the system loads it without memory errors and returns a valid dataset handle
2. **Given** a large CSV file has been loaded via DuckDB, **When** I run validation with an expectation suite, **Then** I receive validation results in the same format as pandas-backed datasets
3. **Given** a CSV file of 100MB exists, **When** I call `load_dataset` with the file path, **Then** the system uses the existing pandas path (no change in behavior)

---

### User Story 2 - Explicit DuckDB URI Support (Priority: P2)

As a power user, I want to explicitly specify DuckDB processing using a `duckdb://` URI, so that I can force DuckDB usage or connect to existing DuckDB databases.

**Why this priority**: Provides flexibility for users who know they want DuckDB regardless of file size, or who have data in existing DuckDB databases.

**Independent Test**: Can be tested by using `duckdb:///path/to/file.csv` and verifying DuckDB is used even for small files.

**Acceptance Scenarios**:

1. **Given** a small CSV file (<500MB), **When** I use `duckdb:///path/to/file.csv` as the source, **Then** the system uses DuckDB to process it
2. **Given** an existing DuckDB database with a users table, **When** I use `duckdb:///path/to/database.db?table=users` as the source, **Then** the system connects and loads that table for validation
3. **Given** an invalid DuckDB URI format, **When** I call `load_dataset`, **Then** the system returns a clear error message explaining the valid format

---

### User Story 3 - Configuration-Based Routing (Priority: P3)

As an administrator, I want to configure the size threshold for automatic DuckDB routing, so that I can tune the behavior for my infrastructure.

**Why this priority**: Enables customization for different deployment environments without requiring code changes.

**Independent Test**: Can be tested by setting environment variable and verifying routing behavior changes accordingly.

**Acceptance Scenarios**:

1. **Given** `GX_DUCKDB_SIZE_THRESHOLD_MB=100` is set, **When** I load a 150MB CSV, **Then** it is processed via DuckDB
2. **Given** `GX_DUCKDB_ENABLED=false` is set, **When** I load any CSV regardless of size, **Then** it is processed via pandas (DuckDB disabled)
3. **Given** default configuration (no environment variables set), **When** I load a 600MB CSV, **Then** it is processed via DuckDB (default threshold: 500MB)

---

### User Story 4 - Seamless Validation Experience (Priority: P1)

As an MCP client user, I want validation results from DuckDB-backed datasets to be indistinguishable from pandas-backed results, so that I don't need to change my downstream workflows.

**Why this priority**: Critical for backward compatibility - existing integrations and automations must continue working without modification.

**Independent Test**: Can be tested by comparing validation result schema and content between pandas and DuckDB paths for the same dataset.

**Acceptance Scenarios**:

1. **Given** a dataset loaded via DuckDB, **When** I call `run_checkpoint`, **Then** the validation result format matches the existing pandas-backed format exactly
2. **Given** a validation fails on a DuckDB-backed dataset, **When** I call `get_validation_result`, **Then** I see the same detailed failure information as with pandas-backed datasets
3. **Given** a suite created on a pandas-backed dataset, **When** I apply it to a DuckDB-backed dataset with the same schema, **Then** all expectations execute correctly

---

### Edge Cases

- What happens when DuckDB installation is missing or incompatible?
  - System falls back to pandas with a warning message for files under the current limit; returns clear error for files over the limit
- What happens when a CSV file is exactly at the threshold size?
  - Files at or below threshold use pandas; files above threshold use DuckDB
- How does the system handle corrupt or malformed CSV files via DuckDB?
  - DuckDB errors are captured and returned as clear error messages to the user
- What happens if DuckDB runs out of disk space during processing?
  - System returns a clear error message indicating disk space issue
- How does the system handle concurrent validation requests?
  - Each validation gets its own DuckDB connection; read-only operations can run concurrently

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST automatically route CSV files larger than a configurable threshold (default: 500MB) to DuckDB for processing
- **FR-002**: System MUST support `duckdb://` URI scheme for explicit DuckDB processing
- **FR-003**: System MUST support connecting to existing DuckDB database files via `duckdb:///path/to/db?table=tablename` syntax
- **FR-004**: System MUST use DuckDB's zero-copy CSV reading for large files
- **FR-005**: System MUST return validation results in the same format regardless of whether pandas or DuckDB execution engine was used
- **FR-006**: System MUST fall back to pandas gracefully when DuckDB is unavailable for files under the current size limit
- **FR-007**: System MUST expose configuration via environment variables: `GX_DUCKDB_ENABLED`, `GX_DUCKDB_SIZE_THRESHOLD_MB`, `GX_DUCKDB_MEMORY_LIMIT`
- **FR-008**: System MUST track which execution engine (pandas or DuckDB) was used for each dataset handle
- **FR-009**: System MUST support in-memory DuckDB databases via `duckdb://:memory:` URI
- **FR-010**: System MUST clean up DuckDB connections when dataset handles are no longer needed

### Error Message Templates

The following error message templates ensure consistent, actionable feedback:

| Error Code | Condition | Message Template |
|------------|-----------|------------------|
| `DUCKDB_URI_INVALID_SCHEME` | URI doesn't start with `duckdb://` | `Invalid URI scheme: expected 'duckdb://', got '{scheme}://'` |
| `DUCKDB_URI_MISSING_PATH` | Database URI missing path | `DuckDB URI requires a path: use 'duckdb:///path/to/file.csv' or 'duckdb:///path/to/db.duckdb?table=name'` |
| `DUCKDB_URI_MISSING_TABLE` | Database file without table param | `DuckDB database URI requires table parameter: 'duckdb:///{path}?table=tablename'` |
| `DUCKDB_URI_INVALID_EXTENSION` | Unrecognized file extension | `Unsupported file type '{ext}': expected .csv or .duckdb/.db` |
| `DUCKDB_FILE_NOT_FOUND` | Path doesn't exist | `File not found: '{path}'` |
| `DUCKDB_CONNECTION_FAILED` | Connection error | `Failed to connect to DuckDB: {error}` |
| `DUCKDB_TABLE_NOT_FOUND` | Table doesn't exist in database | `Table '{table}' not found in database '{path}'` |
| `DUCKDB_UNAVAILABLE` | DuckDB not installed (large file) | `Cannot process file ({size_mb}MB): DuckDB is required for files over {threshold_mb}MB but is not available. Install with: pip install duckdb duckdb-engine` |
| `DUCKDB_FALLBACK` | DuckDB unavailable (small file) | `WARNING: DuckDB unavailable, falling back to pandas for '{path}'` |
| `DUCKDB_DISK_SPACE` | Disk space exhausted | `DuckDB ran out of disk space while processing '{path}'. Free up space in '{temp_dir}' and retry.` |
| `DUCKDB_MEMORY_LIMIT_INVALID` | Invalid memory limit format | `Invalid memory limit format '{value}': expected pattern like '4GB', '512MB', '1024KB'` |

### Key Entities

- **DatasetHandle**: Represents a loaded dataset - extended to include execution engine metadata (pandas vs DuckDB) and connection information
- **DuckDBConnection**: Represents a connection to DuckDB for executing queries - includes connection string, database path, and table reference
- **RoutingDecision**: Represents the logic that determines whether to use pandas or DuckDB based on file size, URI scheme, and configuration

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can successfully load and validate CSV files of 5GB or larger without memory errors
- **SC-002**: Validation of a 10GB file completes in under 5 minutes on standard hardware
- **SC-003**: Memory usage during large file validation stays below 4GB regardless of file size
- **SC-004**: No performance regression for files under 500MB - validation time remains within 10% of current performance
- **SC-005**: 100% of existing API tests pass without modification (backward compatibility)
- **SC-006**: Validation result format is identical between pandas and DuckDB execution paths
- **SC-007**: System gracefully handles DuckDB unavailability with clear error messages
- **SC-008**: Users can configure routing threshold without code changes via environment variables

## Assumptions

- Users have sufficient disk space for DuckDB's temporary storage (approximately 1-2x the CSV file size)
- The target environment supports Python 3.11+ (already a requirement)
- Great Expectations 0.17+ is available (supports SQLAlchemy execution engine)
- DuckDB 0.9.0+ and duckdb-engine 0.9.0+ are available as dependencies

## Out of Scope

- MCP-to-MCP communication with separate DuckDB MCP server (Phase 3 per PRD - future feature)
- Replacing SQLite storage backend with DuckDB (Phase 4 per PRD - future feature)
- Automatic Parquet conversion optimization (Phase 2 per PRD - future feature)
- Streaming validation for datasets larger than available disk space
- Distributed processing across multiple nodes
