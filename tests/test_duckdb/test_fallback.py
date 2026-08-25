# tests/test_duckdb/test_fallback.py
"""Tests for DuckDB fallback behavior (T044-T050).

Per tasks.md Phase 6: Error Handling & Fallback
- T044: Test for DuckDB unavailable scenario
- T045: Test for fallback with file under pandas limit
- T046: Test for clear error when file too large and DuckDB unavailable
"""

from unittest.mock import patch

import pytest

from gx_mcp_server.connectors.duckdb import is_duckdb_available
from gx_mcp_server.core.schema import ExecutionEngine
from gx_mcp_server.tools.datasets import should_use_duckdb


# Skip all tests if DuckDB is not available (for baseline verification)
pytestmark = pytest.mark.skipif(
    not is_duckdb_available(), reason="DuckDB not available for fallback tests"
)


class TestDuckDBUnavailableScenario:
    """T044: Tests for DuckDB unavailable scenario."""

    def test_explicit_duckdb_uri_falls_back_when_unavailable(self, tmp_path):
        """Test that explicit duckdb:// URI falls back to pandas when DuckDB unavailable."""
        # Create a test CSV file
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("id,name\n1,foo\n2,bar\n")

        # Mock DuckDB as unavailable
        with patch(
            "gx_mcp_server.tools.datasets.is_duckdb_available", return_value=False
        ):
            decision = should_use_duckdb(f"duckdb:///{csv_path}", "file")

            assert decision.engine == ExecutionEngine.PANDAS
            assert decision.fallback_from == "duckdb"
            assert "not available" in decision.reason.lower()

    def test_fallback_from_field_set_when_duckdb_unavailable(self, tmp_path):
        """Test that fallback_from field is set correctly when DuckDB unavailable."""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("a,b\n1,2\n")

        with patch(
            "gx_mcp_server.tools.datasets.is_duckdb_available", return_value=False
        ):
            decision = should_use_duckdb(f"duckdb:///{csv_path}", "file")

            assert decision.fallback_from == "duckdb"
            # URI config should still be parsed successfully
            assert decision.uri_config is not None

    def test_invalid_duckdb_uri_falls_back_with_error_message(self):
        """Test that invalid duckdb:// URI falls back with clear error message."""
        decision = should_use_duckdb("duckdb://invalid-uri-no-path", "file")

        assert decision.engine == ExecutionEngine.PANDAS
        assert decision.fallback_from == "duckdb"
        assert "invalid" in decision.reason.lower()


class TestFallbackWithFileUnderPandasLimit:
    """T045: Tests for fallback with file under pandas limit."""

    def test_small_file_uses_pandas_without_fallback(self, tmp_path):
        """Test that files under threshold use pandas without setting fallback_from."""
        csv_path = tmp_path / "small.csv"
        csv_path.write_text("x,y\n1,2\n3,4\n")

        decision = should_use_duckdb(str(csv_path), "file")

        assert decision.engine == ExecutionEngine.PANDAS
        assert decision.fallback_from is None  # No fallback, intentional pandas
        assert "below threshold" in decision.reason.lower()

    def test_small_file_reports_correct_size(self, tmp_path):
        """Test that small file size is correctly reported."""
        csv_path = tmp_path / "small.csv"
        csv_content = "id,value\n" + "\n".join(f"{i},{i * 10}" for i in range(100))
        csv_path.write_text(csv_content)

        expected_size = csv_path.stat().st_size

        decision = should_use_duckdb(str(csv_path), "file")

        assert decision.file_size_bytes == expected_size

    def test_inline_source_uses_pandas_without_fallback(self):
        """Test that inline sources always use pandas without fallback."""
        decision = should_use_duckdb("id,name\n1,foo\n", "inline")

        assert decision.engine == ExecutionEngine.PANDAS
        assert decision.fallback_from is None
        assert "inline" in decision.reason.lower()

    def test_url_source_uses_pandas_without_fallback(self):
        """Test that URL sources always use pandas without fallback."""
        decision = should_use_duckdb("https://example.com/data.csv", "url")

        assert decision.engine == ExecutionEngine.PANDAS
        assert decision.fallback_from is None
        assert "url" in decision.reason.lower()


class TestLargeFileDuckDBUnavailable:
    """T046: Tests for clear error when file too large and DuckDB unavailable."""

    def test_large_file_falls_back_with_clear_message_when_duckdb_unavailable(
        self, tmp_path
    ):
        """Test that large file falls back with clear message when DuckDB unavailable."""
        # Create a CSV file
        csv_path = tmp_path / "large.csv"
        csv_path.write_text("id,data\n1,test\n")

        # Patch threshold to 1 byte so our small file is "large"
        with (
            patch(
                "gx_mcp_server.tools.datasets.is_duckdb_available", return_value=False
            ),
            patch("gx_mcp_server.tools.datasets.get_config") as mock_config,
        ):
            mock_config.return_value.enabled = True
            mock_config.return_value.size_threshold_bytes = 1  # 1 byte threshold
            mock_config.return_value.size_threshold_mb = 0.000001

            decision = should_use_duckdb(str(csv_path), "file")

            assert decision.engine == ExecutionEngine.PANDAS
            assert decision.fallback_from == "duckdb"
            assert "exceeds threshold" in decision.reason.lower()
            assert "not available" in decision.reason.lower()

    def test_large_file_reports_size_when_falling_back(self, tmp_path):
        """Test that file size is reported when falling back from large file."""
        csv_path = tmp_path / "data.csv"
        csv_content = "a,b,c\n" + "\n".join(f"{i},{i * 2},{i * 3}" for i in range(1000))
        csv_path.write_text(csv_content)
        expected_size = csv_path.stat().st_size

        with (
            patch(
                "gx_mcp_server.tools.datasets.is_duckdb_available", return_value=False
            ),
            patch("gx_mcp_server.tools.datasets.get_config") as mock_config,
        ):
            mock_config.return_value.enabled = True
            mock_config.return_value.size_threshold_bytes = 1  # Make file "large"
            mock_config.return_value.size_threshold_mb = 0.000001

            decision = should_use_duckdb(str(csv_path), "file")

            assert decision.file_size_bytes == expected_size

    def test_fallback_reason_contains_actionable_info(self, tmp_path):
        """Test that fallback reason contains actionable information."""
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("x,y\n1,2\n")

        with (
            patch(
                "gx_mcp_server.tools.datasets.is_duckdb_available", return_value=False
            ),
            patch("gx_mcp_server.tools.datasets.get_config") as mock_config,
        ):
            mock_config.return_value.enabled = True
            mock_config.return_value.size_threshold_bytes = 1
            mock_config.return_value.size_threshold_mb = 0.000001

            decision = should_use_duckdb(str(csv_path), "file")

            # Reason should explain both the situation and why fallback occurred
            reason_lower = decision.reason.lower()
            assert "file size" in reason_lower or "exceeds" in reason_lower
            assert "duckdb" in reason_lower


class TestDuckDBDisabledConfiguration:
    """Tests for GX_DUCKDB_ENABLED=false configuration."""

    def test_duckdb_disabled_uses_pandas_without_fallback(self, tmp_path):
        """Test that disabled DuckDB uses pandas without fallback_from field."""
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("id,value\n1,100\n")

        with patch("gx_mcp_server.tools.datasets.get_config") as mock_config:
            mock_config.return_value.enabled = False

            decision = should_use_duckdb(str(csv_path), "file")

            assert decision.engine == ExecutionEngine.PANDAS
            # When disabled by config, it's not a "fallback" - it's intentional
            assert decision.fallback_from is None
            assert "disabled" in decision.reason.lower()

    def test_duckdb_disabled_reason_mentions_env_var(self, tmp_path):
        """Test that disabled reason mentions the environment variable."""
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("id,value\n1,100\n")

        with patch("gx_mcp_server.tools.datasets.get_config") as mock_config:
            mock_config.return_value.enabled = False

            decision = should_use_duckdb(str(csv_path), "file")

            # Should mention the env var name for discoverability
            assert "gx_duckdb_enabled" in decision.reason.lower()


class TestWarningLogging:
    """T049: Tests for warning logging when falling back from DuckDB."""

    def test_invalid_uri_logs_warning(self, caplog):
        """Test that invalid URI logs a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            should_use_duckdb("duckdb://bad-uri", "file")

        # Should have logged a warning about the invalid URI
        assert any("invalid" in record.message.lower() for record in caplog.records)


class TestDuckDBAvailabilityCheck:
    """T047: Tests for DuckDB availability check function."""

    def test_is_duckdb_available_returns_bool(self):
        """Test that is_duckdb_available returns a boolean."""
        result = is_duckdb_available()
        assert isinstance(result, bool)

    def test_is_duckdb_available_true_when_duckdb_installed(self):
        """Test that is_duckdb_available returns True when DuckDB is installed."""
        # Since we skip tests if DuckDB unavailable, this should be True
        assert is_duckdb_available() is True


class TestRoutingDecisionSchema:
    """Tests for RoutingDecision schema correctness with fallback."""

    def test_routing_decision_fallback_from_type(self, tmp_path):
        """Test that fallback_from field has correct type."""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("id\n1\n")

        with patch(
            "gx_mcp_server.tools.datasets.is_duckdb_available", return_value=False
        ):
            decision = should_use_duckdb(f"duckdb:///{csv_path}", "file")

            # fallback_from should be a string literal "duckdb" or None
            assert decision.fallback_from in ("duckdb", None)

    def test_routing_decision_serializes_fallback_correctly(self, tmp_path):
        """Test that RoutingDecision serializes fallback_from correctly."""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("id\n1\n")

        with patch(
            "gx_mcp_server.tools.datasets.is_duckdb_available", return_value=False
        ):
            decision = should_use_duckdb(f"duckdb:///{csv_path}", "file")

            data = decision.model_dump()

            assert "fallback_from" in data
            assert data["fallback_from"] == "duckdb"
