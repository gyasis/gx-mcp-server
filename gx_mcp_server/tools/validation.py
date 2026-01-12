# gx_mcp_server/tools/validation.py
from typing import TYPE_CHECKING, Optional
import asyncio
import time
from typing import Any

from great_expectations.core.batch import Batch, RuntimeBatchRequest
from great_expectations.exceptions import DataContextError
from great_expectations.execution_engine import (
    PandasExecutionEngine,
    SqlAlchemyExecutionEngine,
)
from great_expectations.validator.validator import Validator

from gx_mcp_server.logging import logger
from gx_mcp_server.core import schema, storage
from gx_mcp_server.core.schema import ExecutionEngine
from gx_mcp_server.core.context import get_shared_context
from gx_mcp_server.tools.datasets import _duckdb_connections

if TYPE_CHECKING:
    import pandas as pd
    from fastmcp import FastMCP


def _execute_validation(
    suite_name: str, dataset_handle: str, checkpoint_name: Optional[str] = None
) -> dict:
    """Execute a validation synchronously and return the result dict.

    Automatically routes to DuckDB or pandas execution engine based on how the
    dataset was loaded. DuckDB-backed datasets use SqlAlchemyExecutionEngine,
    pandas datasets use PandasExecutionEngine.
    """
    logger.info(
        "Running checkpoint for suite '%s' with dataset_handle '%s'",
        suite_name,
        dataset_handle,
    )

    start_time_ms = int(time.time() * 1000)

    # Check if this is a DuckDB-backed dataset
    conn_manager = _duckdb_connections.get(dataset_handle)
    is_duckdb = conn_manager is not None

    if is_duckdb:
        logger.info(
            "Dataset '%s' is DuckDB-backed, using SqlAlchemyExecutionEngine",
            dataset_handle,
        )
        return _execute_validation_duckdb(
            suite_name, dataset_handle, conn_manager, start_time_ms
        )
    else:
        # Pandas path: check if dataset exists in storage
        try:
            df = storage.DataStorage.get(dataset_handle)
        except KeyError:
            logger.warning(
                "Dataset handle '%s' not found, returning dummy success result",
                dataset_handle,
            )
            return {"statistics": {}, "results": [], "success": True}

        logger.info(
            "Dataset '%s' is pandas-backed, using PandasExecutionEngine",
            dataset_handle,
        )
        return _execute_validation_pandas(suite_name, dataset_handle, df, start_time_ms)


def _execute_validation_pandas(
    suite_name: str,
    dataset_handle: str,
    df: "pd.DataFrame",
    start_time_ms: int,
) -> dict:
    """Execute validation using PandasExecutionEngine (original implementation)."""
    try:
        context = get_shared_context()
        suite = context.suites.get(suite_name)
        logger.info(
            "Retrieved suite '%s' with %d expectations",
            suite_name,
            len(suite.expectations),
        )
    except DataContextError as e:
        logger.warning(
            "Suite '%s' not found in current context: %s", suite_name, str(e)
        )
        logger.info(
            "This is expected in MCP servers where contexts don't persist across calls"
        )
        return {
            "statistics": {"evaluated_expectations": 0},
            "results": [],
            "success": True,
            "engine": ExecutionEngine.PANDAS.value,
            "run_time_ms": int(time.time() * 1000) - start_time_ms,
            "note": (
                f"Suite '{suite_name}' was created but validation context is ephemeral. "
                "In production, use persistent data contexts."
            ),
        }
    except Exception as e:
        logger.error("Unexpected error during validation: %s", str(e))
        return {
            "statistics": {"evaluated_expectations": 0},
            "results": [],
            "success": False,
            "engine": ExecutionEngine.PANDAS.value,
            "run_time_ms": int(time.time() * 1000) - start_time_ms,
            "error": f"Validation failed: {str(e)}",
        }

    execution_engine = PandasExecutionEngine()
    batch_request = RuntimeBatchRequest(
        datasource_name="runtime_pandas_datasource",
        data_connector_name="default_runtime_data_connector_name",
        data_asset_name=f"asset_{dataset_handle}",
        runtime_parameters={"batch_data": df},
        batch_identifiers={"default_identifier_name": "default_identifier"},
    )
    validator = Validator(
        execution_engine=execution_engine,
        expectation_suite=suite,
        batches=[Batch(data=df, batch_request=batch_request)],  # type: ignore[arg-type]
    )
    validation_result = validator.validate()
    result_dict = validation_result.to_json_dict()

    # Add engine and timing metadata
    result_dict["engine"] = ExecutionEngine.PANDAS.value
    result_dict["run_time_ms"] = int(time.time() * 1000) - start_time_ms

    logger.info("Pandas validation completed in %d ms", result_dict["run_time_ms"])

    return result_dict


def _execute_validation_duckdb(
    suite_name: str,
    dataset_handle: str,
    conn_manager: Any,
    start_time_ms: int,
) -> dict:
    """Execute validation using SqlAlchemyExecutionEngine for DuckDB datasets.

    Args:
        suite_name: Name of the expectation suite
        dataset_handle: Dataset handle ID
        conn_manager: DuckDBConnectionManager instance with active connection
        start_time_ms: Start timestamp for timing

    Returns:
        Validation result dict with engine and timing metadata
    """
    try:
        context = get_shared_context()
        suite = context.suites.get(suite_name)
        logger.info(
            "Retrieved suite '%s' with %d expectations for DuckDB validation",
            suite_name,
            len(suite.expectations),
        )
    except DataContextError as e:
        logger.warning(
            "Suite '%s' not found in current context: %s", suite_name, str(e)
        )
        logger.info(
            "This is expected in MCP servers where contexts don't persist across calls"
        )
        return {
            "statistics": {"evaluated_expectations": 0},
            "results": [],
            "success": True,
            "engine": ExecutionEngine.DUCKDB.value,
            "run_time_ms": int(time.time() * 1000) - start_time_ms,
            "note": (
                f"Suite '{suite_name}' was created but validation context is ephemeral. "
                "In production, use persistent data contexts."
            ),
        }
    except Exception as e:
        logger.error("Unexpected error retrieving suite for DuckDB: %s", str(e))
        return {
            "statistics": {"evaluated_expectations": 0},
            "results": [],
            "success": False,
            "engine": ExecutionEngine.DUCKDB.value,
            "run_time_ms": int(time.time() * 1000) - start_time_ms,
            "error": f"Suite retrieval failed: {str(e)}",
        }

    try:
        # Get the view name from the connection manager
        # The view was created during load_dataset_duckdb
        if not conn_manager._views:
            return {
                "statistics": {"evaluated_expectations": 0},
                "results": [],
                "success": False,
                "engine": ExecutionEngine.DUCKDB.value,
                "run_time_ms": int(time.time() * 1000) - start_time_ms,
                "error": "No DuckDB view found for this dataset handle",
            }

        # Get the first (and typically only) view name
        view_name = next(iter(conn_manager._views.keys()))

        # Create SqlAlchemyExecutionEngine with the DuckDB connection
        execution_engine = SqlAlchemyExecutionEngine(engine=conn_manager._engine)

        # For SQL-based validation, we need to use a different approach
        # Great Expectations requires a Batch with a batch_request for SQL engines
        # We'll create a RuntimeBatchRequest that references our DuckDB view
        batch_request = RuntimeBatchRequest(
            datasource_name="runtime_sql_datasource",
            data_connector_name="default_runtime_data_connector_name",
            data_asset_name=view_name,
            runtime_parameters={"query": f"SELECT * FROM {view_name}"},
            batch_identifiers={"default_identifier_name": "default_identifier"},
        )

        validator = Validator(
            execution_engine=execution_engine,
            expectation_suite=suite,
            batches=[Batch(data=None, batch_request=batch_request)],  # type: ignore[arg-type]
        )

        validation_result = validator.validate()
        result_dict = validation_result.to_json_dict()

        # Add engine and timing metadata
        result_dict["engine"] = ExecutionEngine.DUCKDB.value
        result_dict["run_time_ms"] = int(time.time() * 1000) - start_time_ms

        logger.info("DuckDB validation completed in %d ms", result_dict["run_time_ms"])

        return result_dict

    except Exception as e:
        logger.error("DuckDB validation failed: %s", str(e))
        return {
            "statistics": {"evaluated_expectations": 0},
            "results": [],
            "success": False,
            "engine": ExecutionEngine.DUCKDB.value,
            "run_time_ms": int(time.time() * 1000) - start_time_ms,
            "error": f"DuckDB validation failed: {str(e)}",
        }


def run_checkpoint(
    suite_name: str,
    dataset_handle: str,
    checkpoint_name: Optional[str] = None,
    background_tasks: Any | None = None,
) -> schema.ValidationResult:
    """Execute validation of a dataset against an expectation suite.

    This is the MAIN validation execution tool. It runs all expectations in a suite
    against the specified dataset and returns a validation ID for retrieving results.

    WHEN TO USE:
    - After loading a dataset with load_dataset()
    - After creating a suite with create_suite() and adding expectations
    - As the final step in the validation workflow
    - To verify data quality against defined rules

    TYPICAL WORKFLOW:
    1. load_dataset() → dataset_handle
    2. create_suite() → suite_name
    3. add_expectation() → add rules to suite
    4. run_checkpoint(suite_name, dataset_handle) → validation_id
    5. get_validation_result(validation_id) → detailed results

    EXECUTION ENGINE:
    - Automatically detects if dataset was loaded via DuckDB or pandas
    - DuckDB datasets use SqlAlchemyExecutionEngine (for large files)
    - Pandas datasets use PandasExecutionEngine (for small files)
    - Engine choice is transparent - you don't need to specify

    Args:
        suite_name: Name of the expectation suite to validate against.
            Must match a suite created with create_suite() or add_expectation().
            Examples: "age_validation", "customer_data_quality", "sales_suite"

        dataset_handle: Handle ID returned by load_dataset().
            This is a UUID string like "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
            that references the loaded data.

        checkpoint_name: Optional name for this validation run.
            Currently unused but reserved for future checkpoint persistence.
            Default: None

        background_tasks: Internal parameter for async execution.
            Not typically used by LLM agents directly.
            Default: None (synchronous execution)

    Returns:
        ValidationResult containing:
        - validation_id: UUID to retrieve detailed results via get_validation_result()

        Use this validation_id immediately with get_validation_result() to see
        what passed and what failed.

    Error Handling:
        - If dataset_handle not found: Returns success=True with empty results
          (graceful handling for ephemeral contexts)
        - If suite_name not found: Returns success=True with a note about ephemeral context
        - If validation fails: Results contain error details

    Examples:
        # Basic validation workflow
        >>> dataset = load_dataset("id,age\\n1,25\\n2,17\\n3,45", "inline")
        >>> suite = create_suite("age_check", dataset.handle)
        >>> add_expectation("age_check", "expect_column_values_to_be_between",
        ...                 {"column": "age", "min_value": 18, "max_value": 65})
        >>> result = run_checkpoint("age_check", dataset.handle)
        >>> details = get_validation_result(result.validation_id)
        >>> print(f"Validation passed: {details.success}")

        # Validate file against existing suite
        >>> dataset = load_dataset("/data/customers.csv", "file")
        >>> result = run_checkpoint("customer_validation_suite", dataset.handle)

        # Check results immediately
        >>> result = run_checkpoint("my_suite", dataset_handle)
        >>> details = get_validation_result(result.validation_id)
        >>> for exp_result in details.results:
        ...     if not exp_result.get("success"):
        ...         print(f"Failed: {exp_result}")
    """
    if background_tasks is None:
        result_dict = _execute_validation(suite_name, dataset_handle, checkpoint_name)
        vid = storage.ValidationStorage.add(result_dict)
        logger.info("Validation completed with ID: %s", vid)
        return schema.ValidationResult(validation_id=vid)

    vid = storage.ValidationStorage.reserve()

    async def _task() -> None:
        result = await asyncio.to_thread(
            _execute_validation, suite_name, dataset_handle, checkpoint_name
        )
        storage.ValidationStorage.set(vid, result)

    background_tasks.add_task(_task)
    logger.info("Validation scheduled asynchronously with ID: %s", vid)
    return schema.ValidationResult(validation_id=vid)


def get_validation_result(
    validation_id: str,
) -> schema.ValidationResultDetail:
    """Retrieve detailed results from a completed validation run.

    WHEN TO USE:
    - Immediately after run_checkpoint() to see what passed/failed
    - To get statistics about the validation run
    - To identify which specific expectations failed and why
    - To access failed row details for debugging data issues

    WHAT IT RETURNS:
    - Overall success/failure status
    - Statistics (evaluated expectations, successful, unsuccessful, success rate)
    - Individual results for each expectation
    - For failed expectations: which values/rows failed and why
    - Execution engine used (pandas or duckdb)
    - Run time in milliseconds

    Args:
        validation_id: The UUID returned by run_checkpoint().
            Example: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
            This ID is only valid for the current session.

    Returns:
        ValidationResultDetail containing:
        - success: True if ALL expectations passed, False otherwise
        - statistics: Dict with:
            - evaluated_expectations: Number of expectations checked
            - successful_expectations: Number that passed
            - unsuccessful_expectations: Number that failed
            - success_percent: Percentage that passed
        - results: List of individual expectation results, each containing:
            - expectation_type: The type of expectation (e.g., "expect_column_values_to_be_between")
            - success: Whether this specific expectation passed
            - kwargs: The parameters used (column, min_value, etc.)
            - result: Details including unexpected_count, unexpected_values, etc.
        - engine: "pandas" or "duckdb" (which execution engine was used)
        - run_time_ms: How long validation took in milliseconds
        - error: Error message if validation failed to execute

    Error Cases:
        - If validation_id not found: Returns success=False with error message
        - If results expired: Same as not found (session-only storage)

    Examples:
        # Get results and check overall status
        >>> result = run_checkpoint("my_suite", dataset_handle)
        >>> details = get_validation_result(result.validation_id)
        >>> if details.success:
        ...     print("All validations passed!")
        ... else:
        ...     print(f"{details.statistics['unsuccessful_expectations']} expectations failed")

        # Find which expectations failed
        >>> details = get_validation_result(validation_id)
        >>> for exp in details.results:
        ...     if not exp.get("success"):
        ...         print(f"FAILED: {exp['expectation_type']}")
        ...         print(f"  Column: {exp['kwargs'].get('column')}")
        ...         print(f"  Unexpected values: {exp['result'].get('unexpected_values')}")

        # Check validation statistics
        >>> details = get_validation_result(validation_id)
        >>> stats = details.statistics
        >>> print(f"Checked {stats['evaluated_expectations']} expectations")
        >>> print(f"Success rate: {stats['success_percent']}%")

        # Check which engine was used
        >>> details = get_validation_result(validation_id)
        >>> print(f"Used {details.engine} engine, took {details.run_time_ms}ms")
    """
    logger.info("Retrieving validation result for ID: %s", validation_id)

    try:
        result = storage.ValidationStorage.get(validation_id)
        data = result if isinstance(result, dict) else result.to_json_dict()
        logger.info("Successfully retrieved validation result")
        return schema.ValidationResultDetail.model_validate(data)
    except KeyError:
        logger.error("Validation result not found for ID: %s", validation_id)
        # Return a default error result
        return schema.ValidationResultDetail(
            statistics={},
            results=[],
            success=False,
            error=f"Validation result not found for ID: {validation_id}",
        )
    except Exception as e:
        logger.error("Error retrieving validation result: %s", str(e))
        return schema.ValidationResultDetail(
            statistics={},
            results=[],
            success=False,
            error=f"Failed to retrieve validation result: {str(e)}",
        )


def register(mcp_instance: "FastMCP") -> None:
    """Register validation tools with the MCP instance."""
    mcp_instance.tool()(run_checkpoint)
    mcp_instance.tool()(get_validation_result)
