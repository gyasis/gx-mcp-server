# Great Expectations Library - Complete Guide

## Overview

Great Expectations (GX) is an open-source Python library for data validation, profiling, and documentation. It brings the discipline of software unit testing to data pipelines, allowing data teams to express what they "expect" from their data using declarative syntax.

## What is Great Expectations?

Great Expectations is a leading open-source Python-based framework designed specifically for data validation, documentation, and profiling. It enables data teams to express what they "expect" from their data using a declarative syntax. These expectations serve as unit tests for data, allowing engineers to catch data quality issues early in the pipeline—before they pollute data warehouses or break downstream analytics and machine learning models.

## Core Purpose

- **Data Validation**: Define and test expectations about data quality
- **Automated Documentation**: Generate HTML reports (Data Docs) from tests
- **Data Profiling**: Automatically generate test suites from existing data
- **Pipeline Integration**: Works with Airflow, Dagster, Prefect, and other orchestration tools

## Key Components

1. **Data Context**: Central configuration and project management
2. **Datasources & Execution Engines**: Connect to Pandas, Spark, or SQL databases
3. **Expectations**: Declarative assertions (e.g., "column should not be null")
4. **Expectation Suites**: Collections of expectations for specific datasets
5. **Checkpoints**: Operational triggers that run validations and actions
6. **Data Docs**: HTML reports generated from validation results

## Main Features

- **300+ Built-in Expectations** covering:
  - Table-level checks (row counts, column matching)
  - Column-level checks (uniqueness, ranges, regex patterns)
  - Statistical checks (means, distributions, data drift)
- **Multi-backend Support**: Write once, run on Pandas, Spark, or SQL
- **Automated Profiling**: Generate initial expectations from data samples
- **Living Documentation**: Data Docs stay current with your tests

## Common Use Cases

1. **Pipeline Data Quality Gates**: Validate data at ingestion, transformation, and production stages
2. **Data Drift Detection**: Monitor ML model input data for distribution changes
3. **Data Migration Validation**: Ensure parity when moving between systems
4. **Data Governance**: Make data quality visible to technical and non-technical stakeholders

## Installation

```bash
pip install great_expectations
```

## Core API Methods & Examples

### 1. Initialization & Data Context

```python
import great_expectations as gx

# Create Data Context (entry point)
context = gx.get_context()
```

### 2. Connecting to Data Sources

#### For Pandas DataFrames:

```python
import pandas as pd

df = pd.DataFrame({
    "passenger_count": [1, 2, 3, 4],
    "total_amount": [10.5, 15.0, 7.25, 22.0]
})

data_source = context.data_sources.add_pandas(name="my_pandas_datasource")
data_asset = data_source.add_dataframe_asset(name="my_taxi_data")
batch_definition = data_asset.add_batch_definition_whole_dataframe("all_rows")
batch = batch_definition.get_batch(batch_parameters={"dataframe": df})
```

#### For PostgreSQL:

```python
connection_string = "postgresql+psycopg2://user:pass@host/db"

data_source = context.data_sources.add_postgres(
    "postgres db", connection_string=connection_string
)
data_asset = data_source.add_table_asset(name="taxi data", table_name="nyc_taxi_data")
batch_definition = data_asset.add_batch_definition_whole_table("batch definition")
batch = batch_definition.get_batch()
```

#### For Filesystem (CSV files):

```python
data_source = context.data_sources.add_pandas_filesystem(
    name="my_data_source", base_directory="./data/folder_with_data"
)
data_asset = data_source.add_csv_asset(name="my_data_asset")
batch_definition = data_asset.add_batch_definition_path(
    name="my_batch_definition", path="yellow_tripdata_sample_2019-01.csv"
)
```

### 3. Creating Expectation Suites

```python
# Create an Expectation Suite
suite = context.suites.add(
    gx.ExpectationSuite(name="my_expectation_suite")
)

# Add Expectations to the suite
suite.add_expectation(
    gx.expectations.ExpectColumnValuesToNotBeNull(column="pickup_datetime")
)
suite.add_expectation(
    gx.expectations.ExpectColumnValuesToNotBeNull(column="passenger_count")
)
suite.add_expectation(
    gx.expectations.ExpectColumnValuesToBeBetween(
        column="passenger_count", min_value=1, max_value=6, severity="warning"
    )
)
suite.add_expectation(
    gx.expectations.ExpectColumnValuesToBeBetween(
        column="fare_amount", min_value=0, severity="critical"
    )
)
```

### 4. Common Expectation Methods

#### Distribution Expectations:
- `ExpectColumnValuesToBeBetween(column, min_value, max_value)` - Values within range
- `ExpectColumnMeanToBeBetween(column, min_value, max_value)` - Mean within range
- `ExpectColumnMedianToBeBetween(column, min_value, max_value)` - Median within range
- `ExpectColumnKLDivergenceToBeLessThan(column, threshold)` - Distribution similarity
- `ExpectColumnValueZScoresToBeLessThan(column, threshold)` - Outlier detection
- `ExpectColumnQuantileValuesToBeBetween(column, quantiles, value_ranges)` - Quantile validation

#### Other Common Expectations:
- `ExpectColumnValuesToNotBeNull(column)` - No null values
- `ExpectColumnValuesToBeUnique(column)` - Unique values
- `ExpectColumnValuesToMatchRegex(column, regex)` - Pattern matching
- `ExpectTableRowCountToBeBetween(min_value, max_value)` - Row count validation

### 5. Creating Validation Definitions

```python
validation_definition = context.validation_definitions.add(
    gx.ValidationDefinition(
        name="my_validation_definition",
        data=batch_definition,  # or batch
        suite=suite,
    )
)
```

### 6. Creating and Running Checkpoints

```python
# Create a Checkpoint
checkpoint = context.checkpoints.add(
    gx.Checkpoint(
        name="my_checkpoint",
        validation_definitions=[validation_definition],
        actions=[
            gx.checkpoint.actions.UpdateDataDocsAction(),
            # Optional: SlackNotificationAction, etc.
        ]
    )
)

# Run the Checkpoint
checkpoint_result = checkpoint.run()
print(checkpoint_result.describe())
```

### 7. Checkpoint with Actions (Advanced)

```python
from great_expectations.checkpoint import (
    SlackNotificationAction,
    UpdateDataDocsAction,
)

# Create actions list
action_list = [
    SlackNotificationAction(
        name="send_slack_notification_on_failed_expectations",
        slack_token="${validation_notification_slack_webhook}",
        slack_channel="${validation_notification_slack_channel}",
        notify_on="failure",
        show_failed_expectations=True,
    ),
    UpdateDataDocsAction(
        name="update_all_data_docs",
    ),
]

# Create checkpoint with actions
checkpoint = gx.Checkpoint(
    name="my_checkpoint",
    validation_definitions=validation_definitions,
    actions=action_list,
    result_format={"result_format": "COMPLETE"},
)

# Save to context
context.checkpoints.add(checkpoint)

# Retrieve later
checkpoint = context.checkpoints.get("my_checkpoint")
```

## Complete End-to-End Example

```python
import great_expectations as gx

# 1. Create Data Context
context = gx.get_context()

# 2. Connect to data
connection_string = "postgresql+psycopg2://try_gx:try_gx@postgres.workshops.greatexpectations.io/gx_example_db"
data_source = context.data_sources.add_postgres("postgres db", connection_string=connection_string)
data_asset = data_source.add_table_asset(name="taxi data", table_name="nyc_taxi_data")
batch_definition = data_asset.add_batch_definition_whole_table("batch definition")
batch = batch_definition.get_batch()

# 3. Create Expectation Suite
suite = context.suites.add(
    gx.core.expectation_suite.ExpectationSuite(name="expectations")
)
suite.add_expectation(
    gx.expectations.ExpectColumnValuesToBeBetween(
        column="passenger_count", min_value=1, max_value=6, severity="warning"
    )
)
suite.add_expectation(
    gx.expectations.ExpectColumnValuesToBeBetween(
        column="fare_amount", min_value=0, severity="critical"
    )
)

# 4. Create Validation Definition
validation_definition = context.validation_definitions.add(
    gx.core.validation_definition.ValidationDefinition(
        name="validation definition",
        data=batch_definition,
        suite=suite,
    )
)

# 5. Create and run Checkpoint
checkpoint = context.checkpoints.add(
    gx.checkpoint.checkpoint.Checkpoint(
        name="checkpoint",
        validation_definitions=[validation_definition]
    )
)

checkpoint_result = checkpoint.run()
print(checkpoint_result.describe())
```

## Key Methods Summary

### Data Context Methods:
- `gx.get_context()` - Initialize context
- `context.data_sources.add_pandas()` - Add Pandas datasource
- `context.data_sources.add_postgres()` - Add PostgreSQL datasource
- `context.suites.add()` - Create expectation suite
- `context.validation_definitions.add()` - Create validation definition
- `context.checkpoints.add()` - Create checkpoint
- `context.checkpoints.get()` - Retrieve checkpoint

### Expectation Suite Methods:
- `suite.add_expectation()` - Add expectation to suite

### Checkpoint Methods:
- `checkpoint.run()` - Execute validation
- `checkpoint_result.describe()` - Get results summary

## Integration Support

GX Core supports Python `3.10` through `3.13`.
Experimental support for Python `3.14` and later can be enabled by setting a `GX_PYTHON_EXPERIMENTAL` environment variable when installing `great_expectations`.

## Considerations

- **Learning Curve**: Multiple concepts and configuration files
- **Performance**: Can be resource-intensive for very large datasets
- **API Evolution**: Has undergone significant changes (V2 to V3)

## Research Sources

- **Gemini Deep Research**: Comprehensive analysis with 32 cited sources
- **Gemini Research**: Current best practices and getting started guide
- **GitMCP**: Code examples from the official repository

## Great Expectations MCP Server

### Overview

Yes, there **IS** a Great Expectations MCP (Model Context Protocol) server! It's a **community-created** implementation called `gx-mcp-server` that allows AI agents (like Claude Desktop or custom LLM applications) to perform data quality checks using the Great Expectations framework.

**Note**: This is **not** an official server maintained by the Great Expectations team, but rather a community-driven project.

### What Does It Do Exactly?

The Great Expectations MCP server acts as a **bridge** between an AI model (the client) and your data quality infrastructure. It enables AI agents to:

1. **Load datasets** from various sources (CSV files, URLs, Snowflake, BigQuery)
2. **Define data quality rules** (Expectations) dynamically
3. **Run validation checks** (Checkpoints) programmatically
4. **Interpret validation results** and explain failures in plain language

### Key Features

- **Flexible Data Sources**: 
  - Load CSV data from files, URLs, or inline content (up to 1 GB)
  - Connect to Snowflake or BigQuery using URI prefixes
  - Support for local files and cloud databases

- **Dynamic Expectation Suites**: 
  - Create and modify Expectation Suites on the fly
  - Define data quality rules based on AI understanding of the data

- **Validation Capabilities**: 
  - Synchronous or asynchronous validation of data
  - Detailed results with failure explanations

- **Security Measures**: 
  - Basic and Bearer-token authentication
  - CORS and rate limiting support

- **Observability**: 
  - Prometheus metrics
  - OpenTelemetry spans for monitoring and tracing

### Available Tools (MCP Functions)

When connected to an MCP client, the server exposes several functions:

1. **`load_dataset`**: Loads data into memory from various sources
2. **`create_suite`**: Creates a new named Expectation Suite
3. **`add_expectation`**: Adds specific rules (e.g., "column 'age' must be between 0 and 120") to a suite
4. **`run_checkpoint`**: Executes the validation and returns a summary
5. **`get_validation_result`**: Retrieves detailed failure logs for a specific run
6. **`list_expectation_suites`**: Lists all the "rulesets" currently defined in the project
7. **`describe_expectation_suite`**: Provides the details of a specific suite
8. **`get_data_docs_url`**: Returns the link to the HTML Data Docs generated by GX

### Installation & Usage

#### Using Docker (Recommended)

```bash
# Run in stdio mode (default for Claude Desktop)
docker run --rm -i davidf9999/gx-mcp-server:latest

# Run in HTTP mode (for remote/containerized deployment)
docker run -d -p 8000:8000 --name gx-mcp-server davidf9999/gx-mcp-server:latest
```

#### Adding to Claude Desktop

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "great-expectations": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "davidf9999/gx-mcp-server:latest"]
    }
  }
}
```

#### Using uv (Python Package Manager)

```bash
# Install via uv
uv pip install gx-mcp-server

# Run the server
gx-mcp-server
```

### Use Cases

The primary use case is **Natural Language Data Observability**. Instead of logging into a dashboard or checking a Slack alert, a data engineer can ask an AI:

- *"Did the warehouse sync pass its quality checks this morning?"*
- *"Why did the 'customer_onboarding' suite fail?"*
- *"Run the data quality checks on the staging environment and tell me if it's safe to promote to production."*
- *"Check if this CSV has valid email addresses"*

### Why This Matters

Before this integration, if you asked an AI to "check if this CSV has valid email addresses," it would try to write a script or manually inspect a few rows. With the **Great Expectations MCP server**, the AI can:

1. **Connect** to your actual production database
2. **Apply** industry-standard data quality tests
3. **Report** exactly which rows failed and why, using a robust, reproducible framework

This is particularly useful for **Agentic Workflows** where an AI is responsible for data engineering, ETL monitoring, or automated reporting.

### Resources

- **GitHub Repository**: https://github.com/davidf9999/gx-mcp-server
- **PyPI Package**: https://pypi.org/project/gx-mcp-server/
- **Smithery Registry**: https://smithery.ai/server/@davidf9999/gx-mcp-server

### Summary

- **Official?** No (community-driven)
- **Main Function:** Allows LLMs to run data quality tests and read the results
- **Key Tools:** Run Checkpoints, List Suites, Read Validation Results, Load Datasets
- **Transport Modes:** Supports both `stdio` (for local use) and `http` (for remote deployment)

## Additional Resources

- **Official Documentation**: https://docs.greatexpectations.io/
- **GitHub Repository**: https://github.com/great-expectations/great_expectations
- **Expectation Gallery**: https://greatexpectations.io/expectations/
- **Community Slack**: https://greatexpectations.io/slack
- **Discourse Forum**: https://discourse.greatexpectations.io/

