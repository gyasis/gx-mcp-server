# gx_mcp_server/tools/expectations.py
"""
MCP tools for managing Great Expectations suites and expectations.
"""

import threading
from typing import TYPE_CHECKING, Any, Dict

import great_expectations as gx
from great_expectations.core import ExpectationSuite
from great_expectations.exceptions import DataContextError

from gx_mcp_server.logging import logger
from gx_mcp_server.core import schema
from gx_mcp_server.core.context import get_shared_context
from importlib.metadata import version


API_VERSION = version("gx-mcp-server")


def get_version() -> dict:
    """Get the current version of the gx-mcp-server.

    WHEN TO USE:
    - To verify which version of gx-mcp-server is running
    - For debugging or compatibility checks
    - To include version info in logs or reports

    Returns:
        Dictionary containing:
        - version: Semantic version string (e.g., "0.1.0", "1.2.3")

    Examples:
        >>> get_version()
        {"version": "0.1.0"}
    """
    return {"version": API_VERSION}


if TYPE_CHECKING:
    from fastmcp import FastMCP

_lock = threading.Lock()


def create_suite(
    suite_name: str,
    dataset_handle: str,
    profiler: bool = False,
) -> schema.SuiteHandle:
    """Create a new expectation suite to hold validation rules.

    An expectation suite is a named collection of expectations (validation rules)
    that can be run against datasets. Create a suite, add expectations to it,
    then use it with run_checkpoint() to validate data.

    WHEN TO USE:
    - After loading a dataset with load_dataset()
    - Before adding expectations with add_expectation()
    - To organize related validation rules under a meaningful name
    - When starting a new validation workflow

    TYPICAL WORKFLOW:
    1. load_dataset() → dataset_handle
    2. create_suite("my_suite", dataset_handle) → creates empty suite
    3. add_expectation("my_suite", ...) → add validation rules
    4. run_checkpoint("my_suite", dataset_handle) → execute validation
    5. get_validation_result() → see results

    SUITE NAMING:
    - Use descriptive names that indicate what's being validated
    - Examples: "customer_data_quality", "age_validation", "sales_completeness"
    - Names must be unique within a session

    Args:
        suite_name: Unique name for the expectation suite.
            - Use lowercase with underscores (e.g., "customer_validation")
            - Should describe what the suite validates
            - Must be unique (creating with same name overwrites)
            Examples: "age_check", "product_catalog_quality", "financial_compliance"

        dataset_handle: Handle ID returned by load_dataset().
            Currently used for reference/context. In future versions,
            may be used for profiler-based expectation generation.
            Example: "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        profiler: DEPRECATED - Do not use.
            Auto-generation of expectations via profiling is deprecated
            in Great Expectations 1.5+. Always use add_expectation() instead.
            Default: False

    Returns:
        SuiteHandle containing:
        - suite_name: The name of the created suite (use this with add_expectation
          and run_checkpoint)

    Note:
        The suite is stored in-memory and only persists for the current session.
        In production deployments, configure a persistent Data Context.

    Examples:
        # Create a suite for age validation
        >>> dataset = load_dataset("id,age\\n1,25\\n2,30", "inline")
        >>> suite = create_suite("age_validation", dataset.handle)
        >>> print(suite.suite_name)  # "age_validation"

        # Create a suite for product data quality
        >>> dataset = load_dataset("/data/products.csv", "file")
        >>> suite = create_suite("product_quality_checks", dataset.handle)

        # Then add expectations
        >>> add_expectation("product_quality_checks",
        ...                 "expect_column_values_to_not_be_null",
        ...                 {"column": "product_id"})
    """
    import warnings

    logger.info("Creating suite '%s' (profiler=%s)", suite_name, profiler)
    context = get_shared_context()

    with _lock:
        # Initialize an empty suite
        suite = ExpectationSuite(suite_name)
        context.suites.add(suite)
    logger.info("Suite '%s' registered in context", suite_name)

    if profiler:
        warnings.warn(
            "The 'profiler' argument is deprecated and will be removed in a future release.",
            DeprecationWarning,
        )
        # NOTE: Profiler functionality has been deprecated in Great Expectations 1.5+
        # For now, we'll log a warning and create an empty suite
        logger.warning(
            "Profiler functionality is deprecated in Great Expectations 1.5+. "
            "Creating empty suite instead. Please add expectations manually."
        )

    return schema.SuiteHandle(suite_name=suite_name)


def add_expectation(
    suite_name: str,
    expectation_type: str,
    kwargs: Dict[str, Any],
) -> schema.ToolResponse:
    """Add a validation rule (expectation) to an expectation suite.

    This is the CORE tool for defining data quality rules. Each expectation
    specifies a condition that the data should meet. Failed expectations
    indicate data quality issues.

    WHEN TO USE:
    - After creating a suite with create_suite()
    - To define specific data quality rules
    - Before running validation with run_checkpoint()
    - Can be called multiple times to add multiple expectations

    COMMON EXPECTATION TYPES:

    Column Value Checks:
    - expect_column_values_to_not_be_null - No NULL values allowed
    - expect_column_values_to_be_unique - All values must be unique
    - expect_column_values_to_be_in_set - Values must be from a specific set
    - expect_column_values_to_be_between - Numeric values within range
    - expect_column_values_to_match_regex - String values match pattern

    Column Type Checks:
    - expect_column_values_to_be_of_type - Values must be specific type
    - expect_column_values_to_be_in_type_list - Values in allowed types

    Table-Level Checks:
    - expect_table_row_count_to_be_between - Row count within range
    - expect_table_row_count_to_equal - Exact row count
    - expect_column_to_exist - Column must be present

    Aggregate Checks:
    - expect_column_mean_to_be_between - Average within range
    - expect_column_sum_to_be_between - Sum within range
    - expect_column_min_to_be_between - Minimum within range
    - expect_column_max_to_be_between - Maximum within range

    Args:
        suite_name: Name of the expectation suite to add to.
            Must match a suite created with create_suite().
            If suite doesn't exist, it will be created automatically.
            Example: "age_validation"

        expectation_type: The type of expectation to add.
            Must be a valid Great Expectations expectation type.
            See COMMON EXPECTATION TYPES above for frequently used ones.
            Full list: https://greatexpectations.io/expectations/

        kwargs: Parameters for the expectation as a dictionary.
            Required keys depend on expectation_type.

            Common kwargs:
            - column: (str) Column name to validate
            - value_set: (list) Allowed values for _to_be_in_set
            - min_value: (number) Minimum for _to_be_between
            - max_value: (number) Maximum for _to_be_between
            - regex: (str) Pattern for _to_match_regex
            - mostly: (float 0-1) Allow some failures (e.g., 0.95 = 95% must pass)

    Returns:
        ToolResponse containing:
        - success: True if expectation was added successfully
        - message: Description of result or error

    Error Cases:
        - Invalid expectation_type: Returns success=False with error
        - Missing required kwargs: Returns success=False with details
        - Invalid kwargs values: Returns success=False with error

    Examples:
        # Ensure column has no NULL values
        >>> add_expectation("my_suite", "expect_column_values_to_not_be_null",
        ...                 {"column": "customer_id"})

        # Ensure ages are between 18 and 120
        >>> add_expectation("my_suite", "expect_column_values_to_be_between",
        ...                 {"column": "age", "min_value": 18, "max_value": 120})

        # Ensure status is one of allowed values
        >>> add_expectation("my_suite", "expect_column_values_to_be_in_set",
        ...                 {"column": "status", "value_set": ["active", "pending", "closed"]})

        # Ensure table has at least 1 row but no more than 10000
        >>> add_expectation("my_suite", "expect_table_row_count_to_be_between",
        ...                 {"min_value": 1, "max_value": 10000})

        # Ensure all values are unique
        >>> add_expectation("my_suite", "expect_column_values_to_be_unique",
        ...                 {"column": "order_id"})

        # Ensure email format is valid (regex)
        >>> add_expectation("my_suite", "expect_column_values_to_match_regex",
        ...                 {"column": "email", "regex": r"^[\\w.-]+@[\\w.-]+\\.\\w+$"})

        # Allow 5% failures (95% must pass)
        >>> add_expectation("my_suite", "expect_column_values_to_not_be_null",
        ...                 {"column": "middle_name", "mostly": 0.95})

        # Complete workflow example:
        >>> dataset = load_dataset("id,age,status\\n1,25,active\\n2,17,pending", "inline")
        >>> create_suite("validation", dataset.handle)
        >>> add_expectation("validation", "expect_column_values_to_be_between",
        ...                 {"column": "age", "min_value": 18, "max_value": 65})
        >>> result = run_checkpoint("validation", dataset.handle)
        >>> details = get_validation_result(result.validation_id)
        >>> print(f"Passed: {details.success}")  # False - age 17 is below 18
    """
    logger.info(
        "Adding expectation '%s' to suite '%s' with keys=%s",
        expectation_type,
        suite_name,
        list(kwargs.keys()),
    )
    context = get_shared_context()
    with _lock:
        try:
            try:
                suite = context.suites.get(name=suite_name)
            except DataContextError:
                logger.info("Suite '%s' not found, creating a new one.", suite_name)
                suite = ExpectationSuite(suite_name)

            # Instantiate the expectation and add it
            impl = gx.expectations.registry.get_expectation_impl(expectation_type)
            expectation = impl(**kwargs)
            suite.add_expectation(expectation)
            context.suites.add_or_update(suite)
            logger.info(
                "Expectation '%s' added to suite '%s'",
                expectation_type,
                suite_name,
            )
            return schema.ToolResponse(success=True, message="Expectation added")
        except Exception as e:
            logger.error("Failed to add expectation: %s", str(e))
            return schema.ToolResponse(
                success=False, message=f"Expectation addition failed: {str(e)}"
            )


def register(mcp_instance: "FastMCP") -> None:
    """Register expectation tools with the MCP instance."""
    mcp_instance.tool()(create_suite)
    mcp_instance.tool()(add_expectation)
    mcp_instance.tool()(get_version)
