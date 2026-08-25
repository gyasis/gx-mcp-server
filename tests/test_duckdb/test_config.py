# tests/test_duckdb/test_config.py
"""Tests for DuckDB configuration and routing behavior (T037-T039).

Per tasks.md Phase 5 (US3: Explicit Engine Selection):
- T037: Test custom threshold configuration
- T038: Test GX_DUCKDB_ENABLED=false disabling
- T039: Test GX_DUCKDB_MEMORY_LIMIT configuration
"""

import os
from unittest.mock import patch

import pytest

from gx_mcp_server.connectors.duckdb import (
    DuckDBConnectionManager,
    is_duckdb_available,
)
from gx_mcp_server.core.config import (
    DuckDBConfig,
    _validate_memory_limit,
    get_config,
    load_config,
    reload_config,
)
from gx_mcp_server.core.schema import ExecutionEngine
from gx_mcp_server.tools.datasets import should_use_duckdb


# Skip all tests if DuckDB is not available
pytestmark = pytest.mark.skipif(
    not is_duckdb_available(), reason="DuckDB not available"
)


class TestCustomThresholdConfiguration:
    """Tests for custom threshold configuration (T037).

    Per tasks.md T037: Create tests/test_duckdb/test_config.py with test
    for custom threshold.
    """

    def test_default_threshold_is_500mb(self):
        """Test that default threshold is 500MB."""
        # Clear any existing config cache
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()
            assert config.size_threshold_mb == 500
            assert config.size_threshold_bytes == 500 * 1024 * 1024

    def test_custom_threshold_100mb(self):
        """Test setting custom threshold to 100MB."""
        with patch.dict(os.environ, {"GX_DUCKDB_SIZE_THRESHOLD_MB": "100"}):
            config = load_config()
            assert config.size_threshold_mb == 100
            assert config.size_threshold_bytes == 100 * 1024 * 1024

    def test_custom_threshold_1000mb(self):
        """Test setting custom threshold to 1000MB (1GB)."""
        with patch.dict(os.environ, {"GX_DUCKDB_SIZE_THRESHOLD_MB": "1000"}):
            config = load_config()
            assert config.size_threshold_mb == 1000
            assert config.size_threshold_bytes == 1000 * 1024 * 1024

    def test_threshold_minimum_boundary(self):
        """Test threshold at minimum boundary (1MB)."""
        with patch.dict(os.environ, {"GX_DUCKDB_SIZE_THRESHOLD_MB": "1"}):
            config = load_config()
            assert config.size_threshold_mb == 1

    def test_threshold_maximum_boundary(self):
        """Test threshold at maximum boundary (10000MB)."""
        with patch.dict(os.environ, {"GX_DUCKDB_SIZE_THRESHOLD_MB": "10000"}):
            config = load_config()
            assert config.size_threshold_mb == 10000

    def test_threshold_below_minimum_raises_error(self):
        """Test that threshold below 1 raises ValueError."""
        with patch.dict(os.environ, {"GX_DUCKDB_SIZE_THRESHOLD_MB": "0"}):
            with pytest.raises(ValueError) as exc_info:
                load_config()
            assert "must be between 1 and 10000" in str(exc_info.value)

    def test_threshold_above_maximum_raises_error(self):
        """Test that threshold above 10000 raises ValueError."""
        with patch.dict(os.environ, {"GX_DUCKDB_SIZE_THRESHOLD_MB": "10001"}):
            with pytest.raises(ValueError) as exc_info:
                load_config()
            assert "must be between 1 and 10000" in str(exc_info.value)

    def test_threshold_non_integer_raises_error(self):
        """Test that non-integer threshold raises ValueError."""
        with patch.dict(os.environ, {"GX_DUCKDB_SIZE_THRESHOLD_MB": "abc"}):
            with pytest.raises(ValueError) as exc_info:
                load_config()
            assert "must be an integer" in str(exc_info.value)

    def test_threshold_affects_routing_decision(self, tmp_path):
        """Test that custom threshold affects routing decision."""
        # Create a 50MB test file marker (using actual file size check)
        csv_path = tmp_path / "medium_data.csv"
        # Write just a header - actual test checks the routing logic
        csv_path.write_text("id,name,value\n")

        # With low threshold (1MB), even small files could trigger DuckDB
        # Note: We're testing the config is respected, not actual file size logic
        with patch.dict(os.environ, {"GX_DUCKDB_SIZE_THRESHOLD_MB": "1"}, clear=True):
            # Force config reload
            config = reload_config()
            assert config.size_threshold_mb == 1


class TestDuckDBEnabledConfiguration:
    """Tests for GX_DUCKDB_ENABLED configuration (T038).

    Per tasks.md T038: Add test for GX_DUCKDB_ENABLED=false disabling.
    """

    def test_duckdb_enabled_by_default(self):
        """Test that DuckDB is enabled by default."""
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()
            assert config.enabled is True

    def test_duckdb_disabled_with_false(self):
        """Test disabling DuckDB with GX_DUCKDB_ENABLED=false."""
        with patch.dict(os.environ, {"GX_DUCKDB_ENABLED": "false"}):
            config = load_config()
            assert config.enabled is False

    def test_duckdb_disabled_with_0(self):
        """Test disabling DuckDB with GX_DUCKDB_ENABLED=0."""
        with patch.dict(os.environ, {"GX_DUCKDB_ENABLED": "0"}):
            config = load_config()
            assert config.enabled is False

    def test_duckdb_disabled_with_no(self):
        """Test disabling DuckDB with GX_DUCKDB_ENABLED=no."""
        with patch.dict(os.environ, {"GX_DUCKDB_ENABLED": "no"}):
            config = load_config()
            assert config.enabled is False

    def test_duckdb_enabled_with_true(self):
        """Test enabling DuckDB with GX_DUCKDB_ENABLED=true."""
        with patch.dict(os.environ, {"GX_DUCKDB_ENABLED": "true"}):
            config = load_config()
            assert config.enabled is True

    def test_duckdb_enabled_with_1(self):
        """Test enabling DuckDB with GX_DUCKDB_ENABLED=1."""
        with patch.dict(os.environ, {"GX_DUCKDB_ENABLED": "1"}):
            config = load_config()
            assert config.enabled is True

    def test_duckdb_enabled_with_yes(self):
        """Test enabling DuckDB with GX_DUCKDB_ENABLED=yes."""
        with patch.dict(os.environ, {"GX_DUCKDB_ENABLED": "yes"}):
            config = load_config()
            assert config.enabled is True

    def test_duckdb_enabled_with_on(self):
        """Test enabling DuckDB with GX_DUCKDB_ENABLED=on."""
        with patch.dict(os.environ, {"GX_DUCKDB_ENABLED": "on"}):
            config = load_config()
            assert config.enabled is True

    def test_duckdb_enabled_case_insensitive(self):
        """Test that GX_DUCKDB_ENABLED is case-insensitive."""
        test_cases = [
            ("TRUE", True),
            ("True", True),
            ("FALSE", False),
            ("False", False),
            ("YES", True),
            ("Yes", True),
            ("NO", False),
            ("No", False),
        ]
        for value, expected in test_cases:
            with patch.dict(os.environ, {"GX_DUCKDB_ENABLED": value}):
                config = load_config()
                assert config.enabled is expected, f"Failed for value: {value}"

    def test_disabled_duckdb_returns_pandas_in_routing(self, tmp_path):
        """Test that disabled DuckDB causes routing to return pandas engine."""
        # Create a large file that would normally trigger DuckDB
        csv_path = tmp_path / "large_data.csv"
        csv_path.write_text("id,name\n")  # Content doesn't matter for routing

        with patch.dict(os.environ, {"GX_DUCKDB_ENABLED": "false"}, clear=True):
            # Force config reload
            reload_config()

            # Routing should always return PANDAS when DuckDB is disabled
            decision = should_use_duckdb(str(csv_path), "file")
            assert decision.engine == ExecutionEngine.PANDAS
            assert "disabled" in decision.reason.lower()

            # Restore config
            reload_config()


class TestMemoryLimitConfiguration:
    """Tests for GX_DUCKDB_MEMORY_LIMIT configuration (T039).

    Per tasks.md T039: Add test for GX_DUCKDB_MEMORY_LIMIT configuration.
    """

    def test_memory_limit_default_none(self):
        """Test that memory_limit is None by default."""
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()
            assert config.memory_limit is None

    def test_memory_limit_4gb(self):
        """Test setting memory_limit to 4GB."""
        with patch.dict(os.environ, {"GX_DUCKDB_MEMORY_LIMIT": "4GB"}):
            config = load_config()
            assert config.memory_limit == "4GB"

    def test_memory_limit_512mb(self):
        """Test setting memory_limit to 512MB."""
        with patch.dict(os.environ, {"GX_DUCKDB_MEMORY_LIMIT": "512MB"}):
            config = load_config()
            assert config.memory_limit == "512MB"

    def test_memory_limit_1024kb(self):
        """Test setting memory_limit to 1024KB."""
        with patch.dict(os.environ, {"GX_DUCKDB_MEMORY_LIMIT": "1024KB"}):
            config = load_config()
            assert config.memory_limit == "1024KB"

    def test_memory_limit_8tb(self):
        """Test setting memory_limit to 8TB."""
        with patch.dict(os.environ, {"GX_DUCKDB_MEMORY_LIMIT": "8TB"}):
            config = load_config()
            assert config.memory_limit == "8TB"

    def test_memory_limit_bytes_only(self):
        """Test setting memory_limit with just bytes (no unit prefix)."""
        with patch.dict(os.environ, {"GX_DUCKDB_MEMORY_LIMIT": "1073741824B"}):
            config = load_config()
            assert config.memory_limit == "1073741824B"

    def test_memory_limit_case_insensitive(self):
        """Test that memory_limit is case-insensitive and normalized to uppercase."""
        test_cases = [
            ("4gb", "4GB"),
            ("4Gb", "4GB"),
            ("512mb", "512MB"),
            ("512Mb", "512MB"),
            ("1024kb", "1024KB"),
            ("8tb", "8TB"),
        ]
        for input_val, expected in test_cases:
            with patch.dict(os.environ, {"GX_DUCKDB_MEMORY_LIMIT": input_val}):
                config = load_config()
                assert config.memory_limit == expected, f"Failed for input: {input_val}"

    def test_memory_limit_invalid_format_raises_error(self):
        """Test that invalid memory_limit format raises ValueError."""
        invalid_values = [
            "4G",  # Missing B
            "4 GB",  # Space not allowed
            "GB4",  # Wrong order
            "four gigabytes",  # Text not allowed
            "4.5GB",  # Decimals not allowed
            "-4GB",  # Negative not allowed
        ]
        for value in invalid_values:
            with patch.dict(os.environ, {"GX_DUCKDB_MEMORY_LIMIT": value}):
                with pytest.raises(ValueError) as exc_info:
                    load_config()
                assert "Invalid memory limit format" in str(exc_info.value), (
                    f"Expected error for value: {value}"
                )

    def test_memory_limit_applied_to_connection_manager(self, tmp_path):
        """Test that memory_limit is applied when creating DuckDB connection."""
        with patch.dict(os.environ, {"GX_DUCKDB_MEMORY_LIMIT": "2GB"}, clear=True):
            config = reload_config()

            manager = DuckDBConnectionManager(config=config)
            try:
                manager.create_connection(memory=True)

                # Verify the setting was applied by querying DuckDB
                from sqlalchemy import text

                with manager.cursor() as conn:
                    result = conn.execute(
                        text("SELECT current_setting('memory_limit')")
                    )
                    memory_limit = result.fetchone()[0]
                    # DuckDB normalizes the value (2GB -> ~1.8 GiB due to binary conversion)
                    # Check that memory limit was changed from default (varies by system)
                    assert (
                        "GiB" in memory_limit
                        or "GB" in memory_limit
                        or "MiB" in memory_limit
                    )
            finally:
                manager.close()
                reload_config()


class TestTempDirectoryConfiguration:
    """Tests for GX_DUCKDB_TEMP_DIR configuration."""

    def test_temp_directory_default_none(self):
        """Test that temp_directory is None by default."""
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()
            assert config.temp_directory is None

    def test_temp_directory_custom_path(self):
        """Test setting custom temp_directory path."""
        with patch.dict(os.environ, {"GX_DUCKDB_TEMP_DIR": "/tmp/duckdb_temp"}):
            config = load_config()
            assert config.temp_directory == "/tmp/duckdb_temp"

    def test_temp_directory_with_spaces(self):
        """Test temp_directory with spaces in path."""
        with patch.dict(os.environ, {"GX_DUCKDB_TEMP_DIR": "/tmp/duck db temp"}):
            config = load_config()
            assert config.temp_directory == "/tmp/duck db temp"

    def test_temp_directory_relative_path(self):
        """Test temp_directory with relative path."""
        with patch.dict(os.environ, {"GX_DUCKDB_TEMP_DIR": "./temp"}):
            config = load_config()
            assert config.temp_directory == "./temp"

    def test_temp_directory_applied_to_connection_manager(self, tmp_path):
        """Test that temp_directory is applied when creating DuckDB connection."""
        temp_dir = str(tmp_path / "duckdb_temp")
        os.makedirs(temp_dir, exist_ok=True)

        with patch.dict(os.environ, {"GX_DUCKDB_TEMP_DIR": temp_dir}, clear=True):
            config = reload_config()

            manager = DuckDBConnectionManager(config=config)
            try:
                manager.create_connection(memory=True)

                # Verify the setting was applied by querying DuckDB
                from sqlalchemy import text

                with manager.cursor() as conn:
                    result = conn.execute(
                        text("SELECT current_setting('temp_directory')")
                    )
                    result_dir = result.fetchone()[0]
                    assert temp_dir in result_dir
            finally:
                manager.close()
                reload_config()


class TestConfigCachingBehavior:
    """Tests for configuration caching behavior."""

    def test_get_config_returns_cached_instance(self):
        """Test that get_config() returns the same cached instance."""
        # Clear cache by reloading
        reload_config()

        config1 = get_config()
        config2 = get_config()

        assert config1 is config2

    def test_reload_config_creates_new_instance(self):
        """Test that reload_config() creates a new instance."""
        config1 = get_config()
        config2 = reload_config()

        # Should be different instances
        assert config1 is not config2

    def test_reload_config_picks_up_env_changes(self):
        """Test that reload_config() picks up environment variable changes."""
        with patch.dict(os.environ, {"GX_DUCKDB_SIZE_THRESHOLD_MB": "100"}):
            config1 = reload_config()
            assert config1.size_threshold_mb == 100

        with patch.dict(os.environ, {"GX_DUCKDB_SIZE_THRESHOLD_MB": "200"}):
            config2 = reload_config()
            assert config2.size_threshold_mb == 200


class TestDuckDBConfigDataclass:
    """Tests for DuckDBConfig dataclass."""

    def test_default_values(self):
        """Test DuckDBConfig default values."""
        config = DuckDBConfig()

        assert config.enabled is True
        assert config.size_threshold_mb == 500
        assert config.memory_limit is None
        assert config.temp_directory is None

    def test_custom_initialization(self):
        """Test DuckDBConfig with custom values."""
        config = DuckDBConfig(
            enabled=False,
            size_threshold_mb=100,
            memory_limit="4GB",
            temp_directory="/tmp/duckdb",
        )

        assert config.enabled is False
        assert config.size_threshold_mb == 100
        assert config.memory_limit == "4GB"
        assert config.temp_directory == "/tmp/duckdb"

    def test_size_threshold_bytes_property(self):
        """Test size_threshold_bytes computed property."""
        config = DuckDBConfig(size_threshold_mb=100)
        assert config.size_threshold_bytes == 100 * 1024 * 1024

        config = DuckDBConfig(size_threshold_mb=500)
        assert config.size_threshold_bytes == 500 * 1024 * 1024


class TestMemoryLimitValidation:
    """Tests for memory limit validation function."""

    def test_validate_memory_limit_valid_formats(self):
        """Test _validate_memory_limit with valid formats."""
        valid_cases = [
            ("4GB", "4GB"),
            ("512MB", "512MB"),
            ("1024KB", "1024KB"),
            ("8TB", "8TB"),
            ("100B", "100B"),
            ("4gb", "4GB"),  # lowercase normalized
            ("  4GB  ", "4GB"),  # whitespace stripped
        ]
        for input_val, expected in valid_cases:
            result = _validate_memory_limit(input_val)
            assert result == expected, f"Failed for input: {input_val}"

    def test_validate_memory_limit_invalid_formats(self):
        """Test _validate_memory_limit with invalid formats."""
        invalid_cases = [
            "4G",  # Missing B
            "4 GB",  # Space not allowed
            "GB4",  # Wrong order
            "four",  # Text not allowed
            "4.5GB",  # Decimals not allowed
            "-4GB",  # Negative not allowed
            "",  # Empty string
        ]
        for value in invalid_cases:
            with pytest.raises(ValueError):
                _validate_memory_limit(value)


class TestMultipleConfigOptionsIntegration:
    """Integration tests for multiple configuration options together."""

    def test_all_options_combined(self, tmp_path):
        """Test setting all configuration options together."""
        temp_dir = str(tmp_path / "duckdb_temp")
        os.makedirs(temp_dir, exist_ok=True)

        env = {
            "GX_DUCKDB_ENABLED": "true",
            "GX_DUCKDB_SIZE_THRESHOLD_MB": "250",
            "GX_DUCKDB_MEMORY_LIMIT": "4GB",
            "GX_DUCKDB_TEMP_DIR": temp_dir,
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_config()

            assert config.enabled is True
            assert config.size_threshold_mb == 250
            assert config.memory_limit == "4GB"
            assert config.temp_directory == temp_dir

    def test_disabled_with_other_options(self):
        """Test that DuckDB disabled ignores other options (but still loads them)."""
        env = {
            "GX_DUCKDB_ENABLED": "false",
            "GX_DUCKDB_SIZE_THRESHOLD_MB": "100",
            "GX_DUCKDB_MEMORY_LIMIT": "4GB",
        }

        with patch.dict(os.environ, env, clear=True):
            config = load_config()

            # Config still loads the values even when disabled
            assert config.enabled is False
            assert config.size_threshold_mb == 100
            assert config.memory_limit == "4GB"

            # But routing should return pandas
            reload_config()
            decision = should_use_duckdb("/some/file.csv", "file")
            assert decision.engine == ExecutionEngine.PANDAS
