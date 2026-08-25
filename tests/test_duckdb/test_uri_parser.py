# tests/test_duckdb/test_uri_parser.py
"""Comprehensive tests for DuckDB URI parser.

Tests parse_duckdb_uri() function which parses duckdb:// URIs into DuckDBURIConfig.

Covers:
- CSV file URIs: duckdb:///path/to/file.csv
- Database URIs: duckdb:///path/to/db.duckdb?table=name
- In-memory URIs: duckdb:///:memory:?csv=/path/to/file.csv
- Query parameters: memory_limit, read_only
- Error cases: invalid scheme, missing path, missing table param, invalid extension
"""

import pytest

from gx_mcp_server.connectors.duckdb import is_duckdb_available, parse_duckdb_uri
from gx_mcp_server.core.schema import DuckDBURIConfig, URIType
from gx_mcp_server.exceptions import DuckDBURIParseError


# Skip all tests if DuckDB is not available
pytestmark = pytest.mark.skipif(
    not is_duckdb_available(), reason="DuckDB not available"
)


class TestCSVFileURIs:
    """Tests for CSV file URI parsing: duckdb:///path/to/file.csv"""

    def test_basic_csv_uri(self):
        """Test parsing a basic CSV file URI."""
        config = parse_duckdb_uri("duckdb:///data/sales.csv")

        assert isinstance(config, DuckDBURIConfig)
        assert config.uri_type == URIType.CSV
        assert config.path == "/data/sales.csv"
        assert config.table is None
        assert config.view is None
        assert config.csv_source is None
        assert config.read_only is False
        assert config.memory_limit is None

    def test_csv_uri_with_nested_path(self):
        """Test parsing CSV URI with deeply nested path."""
        config = parse_duckdb_uri(
            "duckdb:///home/user/projects/data/raw/2024/q1/sales.csv"
        )

        assert config.uri_type == URIType.CSV
        assert config.path == "/home/user/projects/data/raw/2024/q1/sales.csv"

    def test_csv_uri_with_special_characters_in_filename(self):
        """Test parsing CSV URI with special characters in filename."""
        config = parse_duckdb_uri("duckdb:///data/my-sales_data-2024.csv")

        assert config.uri_type == URIType.CSV
        assert config.path == "/data/my-sales_data-2024.csv"

    def test_csv_uri_with_read_only_true(self):
        """Test parsing CSV URI with read_only=true parameter."""
        config = parse_duckdb_uri("duckdb:///data/sales.csv?read_only=true")

        assert config.uri_type == URIType.CSV
        assert config.path == "/data/sales.csv"
        assert config.read_only is True

    def test_csv_uri_with_read_only_false(self):
        """Test parsing CSV URI with read_only=false parameter."""
        config = parse_duckdb_uri("duckdb:///data/sales.csv?read_only=false")

        assert config.uri_type == URIType.CSV
        assert config.read_only is False

    def test_csv_uri_with_memory_limit(self):
        """Test parsing CSV URI with memory_limit parameter."""
        config = parse_duckdb_uri("duckdb:///data/sales.csv?memory_limit=4GB")

        assert config.uri_type == URIType.CSV
        assert config.path == "/data/sales.csv"
        assert config.memory_limit == "4GB"

    def test_csv_uri_with_memory_limit_mb(self):
        """Test parsing CSV URI with memory_limit in MB."""
        config = parse_duckdb_uri("duckdb:///data/sales.csv?memory_limit=512MB")

        assert config.memory_limit == "512MB"

    def test_csv_uri_with_multiple_params(self):
        """Test parsing CSV URI with multiple query parameters."""
        config = parse_duckdb_uri(
            "duckdb:///data/large.csv?read_only=true&memory_limit=8GB"
        )

        assert config.uri_type == URIType.CSV
        assert config.path == "/data/large.csv"
        assert config.read_only is True
        assert config.memory_limit == "8GB"

    def test_csv_uri_uppercase_extension(self):
        """Test that CSV extension is case-insensitive."""
        # The parser uses .lower() on extension
        config = parse_duckdb_uri("duckdb:///data/SALES.CSV")

        assert config.uri_type == URIType.CSV
        assert config.path == "/data/SALES.CSV"


class TestDatabaseURIs:
    """Tests for database URI parsing: duckdb:///path/to/db.duckdb?table=name"""

    def test_basic_database_uri_with_table(self):
        """Test parsing a basic database URI with table parameter."""
        config = parse_duckdb_uri("duckdb:///data/warehouse.duckdb?table=customers")

        assert isinstance(config, DuckDBURIConfig)
        assert config.uri_type == URIType.DATABASE
        assert config.path == "/data/warehouse.duckdb"
        assert config.table == "customers"
        assert config.view is None
        assert config.read_only is False
        assert config.memory_limit is None

    def test_database_uri_with_db_extension(self):
        """Test parsing database URI with .db extension."""
        config = parse_duckdb_uri("duckdb:///data/analytics.db?table=metrics")

        assert config.uri_type == URIType.DATABASE
        assert config.path == "/data/analytics.db"
        assert config.table == "metrics"

    def test_database_uri_with_view(self):
        """Test parsing database URI with view parameter instead of table."""
        config = parse_duckdb_uri(
            "duckdb:///data/warehouse.duckdb?view=customer_summary"
        )

        assert config.uri_type == URIType.DATABASE
        assert config.path == "/data/warehouse.duckdb"
        assert config.table is None
        assert config.view == "customer_summary"

    def test_database_uri_with_read_only(self):
        """Test parsing database URI with read_only parameter."""
        config = parse_duckdb_uri(
            "duckdb:///data/warehouse.duckdb?table=orders&read_only=true"
        )

        assert config.uri_type == URIType.DATABASE
        assert config.table == "orders"
        assert config.read_only is True

    def test_database_uri_with_memory_limit(self):
        """Test parsing database URI with memory_limit parameter."""
        config = parse_duckdb_uri(
            "duckdb:///data/warehouse.duckdb?table=orders&memory_limit=16GB"
        )

        assert config.uri_type == URIType.DATABASE
        assert config.table == "orders"
        assert config.memory_limit == "16GB"

    def test_database_uri_with_all_params(self):
        """Test parsing database URI with all supported parameters."""
        config = parse_duckdb_uri(
            "duckdb:///data/warehouse.duckdb?table=transactions&read_only=true&memory_limit=32GB"
        )

        assert config.uri_type == URIType.DATABASE
        assert config.path == "/data/warehouse.duckdb"
        assert config.table == "transactions"
        assert config.read_only is True
        assert config.memory_limit == "32GB"

    def test_database_uri_nested_path(self):
        """Test parsing database URI with nested directory path."""
        config = parse_duckdb_uri(
            "duckdb:///var/lib/duckdb/production/main.duckdb?table=users"
        )

        assert config.uri_type == URIType.DATABASE
        assert config.path == "/var/lib/duckdb/production/main.duckdb"
        assert config.table == "users"


class TestInMemoryURIs:
    """Tests for in-memory URI parsing: duckdb:///:memory:?csv=/path/to/file.csv"""

    def test_basic_memory_uri(self):
        """Test parsing basic in-memory URI without csv source."""
        config = parse_duckdb_uri("duckdb:///:memory:")

        assert isinstance(config, DuckDBURIConfig)
        assert config.uri_type == URIType.MEMORY
        assert config.path is None
        assert config.csv_source is None
        assert config.memory_limit is None

    def test_memory_uri_with_csv_source(self):
        """Test parsing in-memory URI with csv parameter."""
        config = parse_duckdb_uri("duckdb:///:memory:?csv=/path/to/data.csv")

        assert config.uri_type == URIType.MEMORY
        assert config.path is None
        assert config.csv_source == "/path/to/data.csv"

    def test_memory_uri_with_memory_limit(self):
        """Test parsing in-memory URI with memory_limit parameter."""
        config = parse_duckdb_uri("duckdb:///:memory:?memory_limit=2GB")

        assert config.uri_type == URIType.MEMORY
        assert config.memory_limit == "2GB"

    def test_memory_uri_with_csv_and_memory_limit(self):
        """Test parsing in-memory URI with both csv and memory_limit parameters."""
        config = parse_duckdb_uri(
            "duckdb:///:memory:?csv=/data/large.csv&memory_limit=8GB"
        )

        assert config.uri_type == URIType.MEMORY
        assert config.csv_source == "/data/large.csv"
        assert config.memory_limit == "8GB"

    def test_memory_uri_alternate_format_not_supported(self):
        """Test that alternate :memory: format (no leading slash) raises error.

        The parser only supports duckdb:///:memory: with the leading slash.
        duckdb://:memory: is treated as an empty path.
        """
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("duckdb://:memory:")

        assert "requires a path" in str(exc_info.value)


class TestQueryParameters:
    """Tests for query parameter handling."""

    def test_read_only_case_insensitive(self):
        """Test that read_only parameter value is case-insensitive."""
        config_lower = parse_duckdb_uri("duckdb:///data/test.csv?read_only=true")
        config_upper = parse_duckdb_uri("duckdb:///data/test.csv?read_only=TRUE")
        config_mixed = parse_duckdb_uri("duckdb:///data/test.csv?read_only=True")

        assert config_lower.read_only is True
        assert config_upper.read_only is True
        assert config_mixed.read_only is True

    def test_read_only_default_false(self):
        """Test that read_only defaults to False when not specified."""
        config = parse_duckdb_uri("duckdb:///data/test.csv")
        assert config.read_only is False

    def test_unknown_params_ignored(self):
        """Test that unknown query parameters are silently ignored."""
        config = parse_duckdb_uri(
            "duckdb:///data/test.csv?unknown_param=value&another=123"
        )

        assert config.uri_type == URIType.CSV
        assert config.path == "/data/test.csv"
        # Unknown params should not cause errors

    def test_memory_limit_various_formats(self):
        """Test that various memory_limit formats are accepted."""
        test_cases = [
            ("duckdb:///data/test.csv?memory_limit=4GB", "4GB"),
            ("duckdb:///data/test.csv?memory_limit=512MB", "512MB"),
            ("duckdb:///data/test.csv?memory_limit=1024KB", "1024KB"),
            ("duckdb:///data/test.csv?memory_limit=2048", "2048"),
        ]

        for uri, expected_limit in test_cases:
            config = parse_duckdb_uri(uri)
            assert config.memory_limit == expected_limit, f"Failed for URI: {uri}"


class TestErrorCases:
    """Tests for error cases and invalid URIs."""

    def test_invalid_scheme_http(self):
        """Test that http:// scheme raises DuckDBURIParseError."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("http:///data/sales.csv")

        assert "Invalid URI scheme" in str(exc_info.value)
        assert "expected 'duckdb://'" in str(exc_info.value)
        assert exc_info.value.uri == "http:///data/sales.csv"

    def test_invalid_scheme_file(self):
        """Test that file:// scheme raises DuckDBURIParseError."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("file:///data/sales.csv")

        assert "Invalid URI scheme" in str(exc_info.value)
        assert exc_info.value.uri == "file:///data/sales.csv"

    def test_invalid_scheme_postgres(self):
        """Test that postgresql:// scheme raises DuckDBURIParseError."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("postgresql://localhost/db")

        assert "Invalid URI scheme" in str(exc_info.value)

    def test_no_scheme(self):
        """Test that URI without scheme raises DuckDBURIParseError."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("/path/to/data.csv")

        assert "Invalid URI scheme" in str(exc_info.value)

    def test_missing_path_empty(self):
        """Test that empty path raises DuckDBURIParseError."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("duckdb://")

        assert "requires a path" in str(exc_info.value)

    def test_missing_path_root_only(self):
        """Test that root-only path raises DuckDBURIParseError."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("duckdb:///")

        assert "requires a path" in str(exc_info.value)

    def test_database_missing_table_param(self):
        """Test that database URI without table or view param raises error."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("duckdb:///data/warehouse.duckdb")

        assert "requires table parameter" in str(exc_info.value)
        assert exc_info.value.uri == "duckdb:///data/warehouse.duckdb"

    def test_database_missing_table_param_db_extension(self):
        """Test that .db file without table param raises error."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("duckdb:///data/analytics.db")

        assert "requires table parameter" in str(exc_info.value)

    def test_database_both_table_and_view(self):
        """Test that specifying both table and view raises error."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("duckdb:///data/db.duckdb?table=users&view=user_summary")

        assert "Cannot specify both 'table' and 'view'" in str(exc_info.value)

    def test_invalid_extension_txt(self):
        """Test that .txt extension raises DuckDBURIParseError."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("duckdb:///data/notes.txt")

        assert "Unsupported file type" in str(exc_info.value)
        assert "'.txt'" in str(exc_info.value)
        assert "expected .csv or .duckdb/.db" in str(exc_info.value)

    def test_invalid_extension_json(self):
        """Test that .json extension raises DuckDBURIParseError."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("duckdb:///data/config.json")

        assert "Unsupported file type" in str(exc_info.value)
        assert "'.json'" in str(exc_info.value)

    def test_invalid_extension_parquet(self):
        """Test that .parquet extension raises DuckDBURIParseError."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("duckdb:///data/analytics.parquet")

        assert "Unsupported file type" in str(exc_info.value)
        assert "'.parquet'" in str(exc_info.value)

    def test_invalid_extension_sqlite(self):
        """Test that .sqlite extension raises DuckDBURIParseError."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("duckdb:///data/app.sqlite")

        assert "Unsupported file type" in str(exc_info.value)
        assert "'.sqlite'" in str(exc_info.value)

    def test_no_extension(self):
        """Test that path without extension raises DuckDBURIParseError."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("duckdb:///data/datafile")

        assert "Unsupported file type" in str(exc_info.value)
        assert "''" in str(exc_info.value)  # Empty extension


class TestURIParseErrorException:
    """Tests for DuckDBURIParseError exception attributes."""

    def test_exception_stores_uri(self):
        """Test that DuckDBURIParseError stores the problematic URI."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("invalid:///path")

        assert exc_info.value.uri == "invalid:///path"

    def test_exception_message_contains_uri(self):
        """Test that error message provides useful context."""
        with pytest.raises(DuckDBURIParseError) as exc_info:
            parse_duckdb_uri("http:///data/sales.csv")

        error_str = str(exc_info.value)
        assert "http" in error_str
        assert "duckdb" in error_str


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_csv_with_dots_in_filename(self):
        """Test CSV URI with multiple dots in filename."""
        config = parse_duckdb_uri("duckdb:///data/sales.2024.01.15.csv")

        assert config.uri_type == URIType.CSV
        assert config.path == "/data/sales.2024.01.15.csv"

    def test_database_with_dots_in_filename(self):
        """Test database URI with multiple dots in filename."""
        config = parse_duckdb_uri(
            "duckdb:///data/warehouse.prod.v2.duckdb?table=orders"
        )

        assert config.uri_type == URIType.DATABASE
        assert config.path == "/data/warehouse.prod.v2.duckdb"
        assert config.table == "orders"

    def test_whitespace_in_table_name(self):
        """Test database URI with encoded whitespace in table name."""
        config = parse_duckdb_uri("duckdb:///data/db.duckdb?table=my%20table")

        assert config.uri_type == URIType.DATABASE
        # URL-decoded table name
        assert config.table == "my table"

    def test_special_chars_in_path(self):
        """Test URI with URL-encoded special characters in path."""
        config = parse_duckdb_uri("duckdb:///data/sales%20report.csv")

        assert config.uri_type == URIType.CSV
        # Note: urlparse doesn't decode path automatically
        assert "sales" in config.path

    def test_relative_like_path(self):
        """Test URI that looks like relative path but is absolute."""
        config = parse_duckdb_uri("duckdb:///./data/sales.csv")

        assert config.uri_type == URIType.CSV
        assert config.path == "/./data/sales.csv"

    def test_empty_query_string(self):
        """Test URI with empty query string (just ?)."""
        config = parse_duckdb_uri("duckdb:///data/sales.csv?")

        assert config.uri_type == URIType.CSV
        assert config.path == "/data/sales.csv"
        assert config.read_only is False
        assert config.memory_limit is None

    def test_memory_uri_with_empty_csv(self):
        """Test in-memory URI with empty csv parameter value."""
        config = parse_duckdb_uri("duckdb:///:memory:?csv=")

        assert config.uri_type == URIType.MEMORY
        # Empty string in query param results in empty list from parse_qs,
        # which becomes None after the [None] fallback
        assert config.csv_source is None


class TestReturnTypeValidation:
    """Tests to verify the return type is always DuckDBURIConfig."""

    def test_csv_returns_duckdb_uri_config(self):
        """Test that CSV URI returns DuckDBURIConfig instance."""
        result = parse_duckdb_uri("duckdb:///data/test.csv")
        assert isinstance(result, DuckDBURIConfig)

    def test_database_returns_duckdb_uri_config(self):
        """Test that database URI returns DuckDBURIConfig instance."""
        result = parse_duckdb_uri("duckdb:///data/test.duckdb?table=t")
        assert isinstance(result, DuckDBURIConfig)

    def test_memory_returns_duckdb_uri_config(self):
        """Test that memory URI returns DuckDBURIConfig instance."""
        result = parse_duckdb_uri("duckdb:///:memory:")
        assert isinstance(result, DuckDBURIConfig)

    def test_uri_type_is_enum(self):
        """Test that uri_type field is a URIType enum."""
        config = parse_duckdb_uri("duckdb:///data/test.csv")
        assert isinstance(config.uri_type, URIType)

    def test_all_uri_types_covered(self):
        """Test that parser can return all URIType values."""
        csv_config = parse_duckdb_uri("duckdb:///data/test.csv")
        db_config = parse_duckdb_uri("duckdb:///data/test.duckdb?table=t")
        mem_config = parse_duckdb_uri("duckdb:///:memory:")

        assert csv_config.uri_type == URIType.CSV
        assert db_config.uri_type == URIType.DATABASE
        assert mem_config.uri_type == URIType.MEMORY

        # Verify we covered all enum values
        returned_types = {csv_config.uri_type, db_config.uri_type, mem_config.uri_type}
        all_types = set(URIType)
        assert returned_types == all_types
