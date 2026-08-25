# tests/test_duckdb/conftest.py
"""Pytest fixtures for DuckDB integration tests.

Provides test isolation for configuration cache and environment variables.
"""

import pytest

import gx_mcp_server.core.config as config_module


@pytest.fixture(autouse=True)
def reset_duckdb_config():
    """Reset DuckDB configuration cache before and after each test.

    This ensures test isolation - configuration changes in one test
    don't leak into subsequent tests.
    """
    # Reset before test
    config_module._config = None

    yield

    # Reset after test (cleanup)
    config_module._config = None
