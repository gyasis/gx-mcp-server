# GX-MCP-Server Quickstart Guide

> Quick reference for configuring and testing the Great Expectations MCP Server with Claude Desktop and CLI.

## Claude Desktop Configuration

Add to your Claude Desktop config (`~/.claude/settings.json` or similar):

### STDIO Mode (Local Development)

```json
{
  "mcpServers": {
    "gx-mcp-server": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "gx_mcp_server"]
    }
  }
}
```

### HTTP Mode (Docker Compose)

```json
{
  "mcpServers": {
    "gx-mcp-server": {
      "type": "http",
      "url": "http://localhost:8765/mcp/"
    }
  }
}
```

### Docker with Authentication

```json
{
  "mcpServers": {
    "gx-mcp-server": {
      "type": "http",
      "url": "http://localhost:8765/mcp/",
      "headers": {
        "Authorization": "Basic dXNlcjpwYXNz"
      }
    }
  }
}
```

---

## Docker Compose (Local Development with DuckDB)

For local development using your fork with DuckDB support:

```bash
# Start the server (builds from local Dockerfile)
docker-compose up

# Start in background
docker-compose up -d

# Rebuild after code changes
docker-compose up --build

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

**Port**: The server runs on **port 8765** (not 8000) to avoid conflicts.

**Claude Desktop config for Docker Compose**:
```json
{
  "mcpServers": {
    "gx-mcp-server": {
      "type": "http",
      "url": "http://localhost:8765/mcp/"
    }
  }
}
```

**Environment variables** (set in docker-compose.yml):
- `MCP_MODE=http` - HTTP transport mode
- `GX_DUCKDB_ENABLED=true` - DuckDB for large files
- `GX_DUCKDB_SIZE_THRESHOLD_MB=500` - Files >500MB use DuckDB
- `GX_DUCKDB_MEMORY_LIMIT=8GB` - DuckDB RAM allocation

**Auto-restart**: The container is configured with `restart: unless-stopped` for automatic recovery.

---

## Claude CLI Commands

### Add the Server

```bash
# Local dev (STDIO)
claude mcp add gx-mcp-server-local -- uv run python -m gx_mcp_server

# Docker Compose (HTTP) - recommended for local fork with DuckDB
docker-compose up -d
claude mcp add gx-mcp-server --transport http http://localhost:8765/mcp/
```

### Manage Servers

```bash
claude mcp list                        # See configured servers
claude mcp remove gx-mcp-server-local  # Remove a server
```

---

## Test Example

Run this to verify MCP tools are working:

```bash
claude "Load CSV data id,age
1,25
2,19
3,45 and validate ages 21-65, show failed records"
```

---

## Available MCP Tools

When the MCP server is properly connected, you'll see these **11 tools**:

### Core Validation Tools

| Tool | Description |
|------|-------------|
| `load_dataset` | Load CSV from file, URL, or inline string (auto-routes large files to DuckDB) |
| `create_suite` | Create a Great Expectations suite |
| `add_expectation` | Add expectations to a suite |
| `run_checkpoint` | Run validation and get results |
| `get_validation_result` | Get detailed validation results |

### Data Source Management Tools

| Tool | Description |
|------|-------------|
| `list_sources` | List available data sources (files, shared DB tables) |
| `attach_shared_db` | Attach to exported DuckDB from duckdb-local |
| `get_shared_table_schema` | Inspect table schema in shared DB |
| `cleanup_temp_files` | Garbage collect orphan temp files |

### Utility Tools

| Tool | Description |
|------|-------------|
| `get_version` | Get API version |
| `ping` | Health check |

### Example Tool Call Flow

Claude will execute these tools in sequence:

1. **load_dataset**
   ```json
   {
     "source": "id,age\n1,25\n2,19\n3,45",
     "source_type": "inline"
   }
   ```
   → Returns dataset handle

2. **create_suite**
   ```json
   {
     "name": "age_validation"
   }
   ```
   → Returns suite handle

3. **add_expectation**
   ```json
   {
     "suite_id": "<suite_handle>",
     "expectation_type": "expect_column_values_to_be_between",
     "kwargs": {"column": "age", "min_value": 21, "max_value": 65}
   }
   ```

4. **run_checkpoint**
   ```json
   {
     "dataset_id": "<dataset_handle>",
     "suite_id": "<suite_handle>"
   }
   ```
   → Returns validation results

---

## Quick Test Commands

```bash
# From the project directory
cd /path/to/gx-mcp-server

# Run examples script
uv run python scripts/run_examples.py

# Or with justfile
just run-examples

# Run with MCP Inspector (GUI for testing tools)
uv run python -m gx_mcp_server --inspect
```

The **Inspector GUI** (http://127.0.0.1:6274) lets you manually test each tool and see JSON responses.

---

## Server Modes

```bash
# STDIO (for AI clients like Claude Desktop)
uv run python -m gx_mcp_server

# HTTP (for web clients)
uv run python -m gx_mcp_server --http

# Inspector GUI (for testing)
uv run python -m gx_mcp_server --inspect
```

---

## Troubleshooting

### Check Server Health (HTTP mode)

```bash
curl http://localhost:8765/mcp/health
```

### Debug Mode

```bash
claude mcp add gx-debug -- uv run python -m gx_mcp_server --log-level DEBUG
```

### Common Issues

| Issue | Solution |
|-------|----------|
| "Failed to connect" | Ensure server is running and port accessible |
| "Authentication failed" | Verify credentials and auth headers |
| "File not found" | Check paths relative to server working directory |
| Tools not appearing | Run `claude mcp list` to verify server is added |

---

## DuckDB Integration (Large Files)

For CSV files >500MB, DuckDB is automatically used:

```bash
# Enable DuckDB (enabled by default)
export GX_DUCKDB_ENABLED=true

# Configure threshold (default 500MB)
export GX_DUCKDB_SIZE_THRESHOLD_MB=500

# Explicit DuckDB URI
load_dataset("duckdb:///path/to/large_file.csv")
```

---

## Sharing Data with duckdb-local MCP Server

gx-mcp-server can validate tables/views created in the `duckdb-local` MCP server using an export workflow:

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  duckdb-local (in-memory)                                         │
│  1. Load/query data: parquet, CSV, S3, Snowflake                 │
│  2. Create views/tables                                           │
│  3. Export: EXPORT DATABASE '/path/to/exported.duckdb'           │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  gx-mcp-server                                                    │
│  1. attach_shared_db() → connect to exported DB                  │
│  2. list_sources() → see available tables                        │
│  3. Validate with Great Expectations                             │
└──────────────────────────────────────────────────────────────────┘
```

### Workflow

1. **In duckdb-local** - Create and export your data:
   ```sql
   -- Load data, create views, etc.
   CREATE VIEW sales_summary AS SELECT ...;

   -- Export to shared location
   EXPORT DATABASE '/home/user/.local/share/duckdb/exported.duckdb';
   ```

2. **In gx-mcp-server** - Attach and validate:
   ```
   attach_shared_db()           → Connect to exported DB
   list_sources()               → See available tables/views
   get_shared_table_schema("sales_summary")  → Inspect schema
   load_dataset("sales_summary", "table")    → Load for validation
   ```

### Configuration

Set the shared path in docker-compose.yml:
```yaml
environment:
  - GX_DUCKDB_SHARED_PATH=/shared/duckdb/exported.duckdb
volumes:
  - /home/user/.local/share/duckdb:/shared/duckdb
```

---

## More Information

- Full documentation: [README.md](README.md)
- Project roadmap: [ROADMAP-v2.md](ROADMAP-v2.md)
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)
