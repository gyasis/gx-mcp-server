# Project Constitution: DuckDB Integration

**Feature Branch**: `001-duckdb-integration`
**Created**: 2026-01-11
**Purpose**: Defines guiding principles for implementation decisions

---

## Core Principles

### Principle 1: Memory Efficiency First

**Description**: The primary goal of this feature is to enable validation of large datasets without exhausting system memory. All design decisions must prioritize memory efficiency over raw speed.

**Implications**:
- Use DuckDB's zero-copy CSV reading via `read_csv_auto()` instead of loading data into memory
- Prefer views over materialized tables when possible
- Set appropriate `memory_limit` constraints on DuckDB connections
- Clean up connections promptly when no longer needed

**Violations**:
- Loading entire CSV into pandas DataFrame before routing decision
- Caching large intermediate results in memory
- Creating unnecessary copies of data

---

### Principle 2: Backwards Compatibility

**Description**: Existing users and integrations must continue working without modification. The DuckDB integration is additive, not disruptive.

**Implications**:
- All existing API signatures remain unchanged
- Validation result format is identical between pandas and DuckDB paths
- Default behavior (no env vars set) works for 99% of use cases
- No breaking changes to `DatasetHandle` interface

**Violations**:
- Changing return type of existing tools
- Requiring new mandatory parameters
- Altering validation result structure

---

### Principle 3: Fail-Safe Defaults

**Description**: The system should work correctly out of the box with sensible defaults. Users should only need configuration for edge cases or optimization.

**Implications**:
- Default threshold (500MB) covers most "large file" scenarios
- DuckDB enabled by default when dependencies are available
- Fallback to pandas when DuckDB unavailable (with warning)
- Clear error messages guide users toward resolution

**Violations**:
- Requiring users to set environment variables for basic functionality
- Silent failures without logging
- Cryptic error messages from underlying libraries

---

### Principle 4: Explicit Over Implicit (URI Scheme)

**Description**: When users explicitly request DuckDB via `duckdb://` URI, that decision is honored regardless of other factors like file size.

**Implications**:
- `duckdb://` URI bypasses size-based routing logic
- User intent is respected even for small files
- Invalid URIs produce clear, actionable errors

**Violations**:
- Ignoring `duckdb://` scheme for small files
- Auto-correcting user-specified URIs
- Silently falling back when explicit DuckDB requested

---

### Principle 5: Thread Safety

**Description**: The system must handle concurrent validation requests safely without data corruption or race conditions.

**Implications**:
- Use `cursor()` context manager for thread-local DuckDB operations
- StaticPool for in-memory databases (maintains single connection)
- NullPool for file-based databases (no connection sharing)
- No shared mutable state between validation requests

**Violations**:
- Sharing DuckDB connections across threads
- Global mutable state for connection management
- Assuming single-threaded execution

---

## Decision Framework

When faced with implementation choices, apply principles in this order:

1. **Memory Efficiency** - Does this choice minimize memory usage?
2. **Backwards Compatibility** - Does this break existing behavior?
3. **Fail-Safe Defaults** - Does this work without configuration?
4. **Explicit Over Implicit** - Does this respect user intent?
5. **Thread Safety** - Is this safe for concurrent use?

---

## Compliance Checklist

Before completing implementation, verify:

- [ ] Large files (>500MB) route to DuckDB automatically
- [ ] Small files (<500MB) use pandas (no regression)
- [ ] Validation results identical between engines
- [ ] `duckdb://` URI forces DuckDB regardless of size
- [ ] Clear error messages for all failure modes
- [ ] No new mandatory configuration required
- [ ] Thread-safe connection management
- [ ] Connection cleanup on handle disposal
