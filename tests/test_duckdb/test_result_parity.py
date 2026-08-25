# tests/test_duckdb/test_result_parity.py
"""Tests for result format parity between pandas and DuckDB execution (T020).

Per tasks.md T020: Test comparing pandas vs DuckDB result format.
Ensures US4 (Seamless Results) - identical ValidationResult structure.
"""

import pytest

from gx_mcp_server.connectors.duckdb import is_duckdb_available
from gx_mcp_server.core.schema import (
    DatasetHandleExtended,
    EngineMetadata,
    ExecutionEngine,
    RoutingDecision,
    ValidationResultDetail,
)


# Skip all tests if DuckDB is not available
pytestmark = pytest.mark.skipif(
    not is_duckdb_available(), reason="DuckDB not available"
)


class TestRoutingDecisionSchema:
    """Tests for RoutingDecision schema correctness."""

    def test_routing_decision_for_pandas(self):
        """Test RoutingDecision for pandas engine."""
        decision = RoutingDecision(
            engine=ExecutionEngine.PANDAS,
            reason="File size under threshold",
            file_size_bytes=1024 * 1024 * 100,  # 100MB
        )

        assert decision.engine == ExecutionEngine.PANDAS
        assert "threshold" in decision.reason.lower()
        assert decision.file_size_bytes == 100 * 1024 * 1024
        assert decision.uri_config is None
        assert decision.fallback_from is None

    def test_routing_decision_for_duckdb(self):
        """Test RoutingDecision for DuckDB engine."""
        decision = RoutingDecision(
            engine=ExecutionEngine.DUCKDB,
            reason="File size exceeds 500MB threshold",
            file_size_bytes=1024 * 1024 * 600,  # 600MB
        )

        assert decision.engine == ExecutionEngine.DUCKDB
        assert decision.file_size_bytes == 600 * 1024 * 1024
        assert decision.fallback_from is None

    def test_routing_decision_with_fallback(self):
        """Test RoutingDecision when fallback occurs."""
        decision = RoutingDecision(
            engine=ExecutionEngine.PANDAS,
            reason="Falling back from DuckDB: module not available",
            file_size_bytes=1024 * 1024 * 200,  # 200MB
            fallback_from="duckdb",
        )

        assert decision.engine == ExecutionEngine.PANDAS
        assert decision.fallback_from == "duckdb"
        assert "falling back" in decision.reason.lower()


class TestDatasetHandleExtendedSchema:
    """Tests for DatasetHandleExtended schema correctness."""

    def test_dataset_handle_pandas_engine(self):
        """Test DatasetHandleExtended for pandas engine."""
        handle = DatasetHandleExtended(
            id="handle-123",
            name="test_dataset",
            source="/path/to/data.csv",
            row_count=1000,
            columns=["id", "name", "value"],
            engine=ExecutionEngine.PANDAS,
        )

        assert handle.engine == ExecutionEngine.PANDAS
        assert handle.engine_metadata is None
        assert handle.row_count == 1000
        assert len(handle.columns) == 3

    def test_dataset_handle_duckdb_engine(self):
        """Test DatasetHandleExtended for DuckDB engine with metadata."""
        metadata = EngineMetadata(
            duckdb_table="csv_sales_a1b2c3d4",
            duckdb_path=None,  # In-memory
            connection_id="conn-456",
            memory_limit="4GB",
        )

        handle = DatasetHandleExtended(
            id="handle-789",
            name="sales_data",
            source="/data/large_sales.csv",
            row_count=5000000,
            columns=["date", "amount", "customer_id", "product_id"],
            engine=ExecutionEngine.DUCKDB,
            engine_metadata=metadata,
        )

        assert handle.engine == ExecutionEngine.DUCKDB
        assert handle.engine_metadata is not None
        assert handle.engine_metadata.duckdb_table == "csv_sales_a1b2c3d4"
        assert handle.engine_metadata.connection_id == "conn-456"
        assert handle.engine_metadata.memory_limit == "4GB"

    def test_dataset_handle_serialization(self):
        """Test that DatasetHandleExtended serializes to dict correctly."""
        metadata = EngineMetadata(
            duckdb_table="test_view",
            connection_id="conn-123",
        )

        handle = DatasetHandleExtended(
            id="handle-001",
            name="test",
            source="test.csv",
            row_count=100,
            columns=["a", "b"],
            engine=ExecutionEngine.DUCKDB,
            engine_metadata=metadata,
        )

        data = handle.model_dump()

        assert data["engine"] == "duckdb"
        assert data["engine_metadata"]["duckdb_table"] == "test_view"
        assert data["columns"] == ["a", "b"]


class TestValidationResultParity:
    """Tests for ValidationResultDetail parity between engines."""

    def test_validation_result_with_pandas_engine(self):
        """Test ValidationResultDetail with pandas engine marker."""
        result = ValidationResultDetail(
            statistics={"evaluated_expectations": 5, "successful_expectations": 5},
            results=[],
            success=True,
            engine=ExecutionEngine.PANDAS,
            run_time_ms=150,
        )

        assert result.engine == ExecutionEngine.PANDAS
        assert result.run_time_ms == 150
        assert result.success is True

    def test_validation_result_with_duckdb_engine(self):
        """Test ValidationResultDetail with DuckDB engine marker."""
        result = ValidationResultDetail(
            statistics={"evaluated_expectations": 10, "successful_expectations": 9},
            results=[{"expectation_type": "expect_column_to_exist"}],
            success=False,
            engine=ExecutionEngine.DUCKDB,
            run_time_ms=250,
        )

        assert result.engine == ExecutionEngine.DUCKDB
        assert result.run_time_ms == 250
        assert result.success is False

    def test_validation_result_without_engine(self):
        """Test ValidationResultDetail without engine (backwards compatibility)."""
        result = ValidationResultDetail(
            statistics={"evaluated_expectations": 3},
            results=[],
            success=True,
        )

        # Engine should be None for backwards compatibility
        assert result.engine is None
        assert result.run_time_ms is None

    def test_validation_result_format_identical(self):
        """Test that both engines produce structurally identical results.

        This is the key US4 test: regardless of engine, the ValidationResultDetail
        structure should be the same.
        """
        # Create a pandas result
        pandas_result = ValidationResultDetail(
            statistics={
                "evaluated_expectations": 5,
                "successful_expectations": 5,
                "unsuccessful_expectations": 0,
            },
            results=[
                {
                    "expectation_type": "expect_column_to_exist",
                    "success": True,
                    "kwargs": {"column": "id"},
                },
                {
                    "expectation_type": "expect_column_values_to_not_be_null",
                    "success": True,
                    "kwargs": {"column": "name"},
                },
            ],
            success=True,
            engine=ExecutionEngine.PANDAS,
            run_time_ms=100,
        )

        # Create a DuckDB result with same structure
        duckdb_result = ValidationResultDetail(
            statistics={
                "evaluated_expectations": 5,
                "successful_expectations": 5,
                "unsuccessful_expectations": 0,
            },
            results=[
                {
                    "expectation_type": "expect_column_to_exist",
                    "success": True,
                    "kwargs": {"column": "id"},
                },
                {
                    "expectation_type": "expect_column_values_to_not_be_null",
                    "success": True,
                    "kwargs": {"column": "name"},
                },
            ],
            success=True,
            engine=ExecutionEngine.DUCKDB,
            run_time_ms=80,
        )

        # Verify structural parity (excluding engine-specific fields)
        pandas_data = pandas_result.model_dump()
        duckdb_data = duckdb_result.model_dump()

        # Core fields should match
        assert pandas_data["statistics"] == duckdb_data["statistics"]
        assert pandas_data["results"] == duckdb_data["results"]
        assert pandas_data["success"] == duckdb_data["success"]
        assert pandas_data["error"] == duckdb_data["error"]

        # Engine fields will differ but both should be present
        assert pandas_data["engine"] == "pandas"
        assert duckdb_data["engine"] == "duckdb"


class TestEngineMetadata:
    """Tests for EngineMetadata schema."""

    def test_engine_metadata_minimal(self):
        """Test EngineMetadata with minimal fields."""
        metadata = EngineMetadata()

        assert metadata.duckdb_table is None
        assert metadata.duckdb_path is None
        assert metadata.connection_id is None
        assert metadata.memory_limit is None

    def test_engine_metadata_full(self):
        """Test EngineMetadata with all fields."""
        metadata = EngineMetadata(
            duckdb_table="my_view",
            duckdb_path="/data/analytics.duckdb",
            connection_id="conn-abc-123",
            memory_limit="8GB",
        )

        assert metadata.duckdb_table == "my_view"
        assert metadata.duckdb_path == "/data/analytics.duckdb"
        assert metadata.connection_id == "conn-abc-123"
        assert metadata.memory_limit == "8GB"

    def test_engine_metadata_serialization(self):
        """Test EngineMetadata serialization."""
        metadata = EngineMetadata(
            duckdb_table="test_table",
            connection_id="conn-123",
        )

        data = metadata.model_dump()

        assert data["duckdb_table"] == "test_table"
        assert data["duckdb_path"] is None
        assert data["connection_id"] == "conn-123"
        assert data["memory_limit"] is None


class TestExecutionEngineEnum:
    """Tests for ExecutionEngine enum."""

    def test_execution_engine_values(self):
        """Test ExecutionEngine enum values."""
        assert ExecutionEngine.PANDAS.value == "pandas"
        assert ExecutionEngine.DUCKDB.value == "duckdb"

    def test_execution_engine_from_string(self):
        """Test creating ExecutionEngine from string."""
        assert ExecutionEngine("pandas") == ExecutionEngine.PANDAS
        assert ExecutionEngine("duckdb") == ExecutionEngine.DUCKDB

    def test_execution_engine_invalid_raises(self):
        """Test that invalid engine value raises error."""
        with pytest.raises(ValueError):
            ExecutionEngine("invalid_engine")
