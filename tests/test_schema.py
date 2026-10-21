
import pytest

from inspect_schema import EXPECTED_SCHEMA


@pytest.mark.parametrize(
    "table_name, expected_columns",
    EXPECTED_SCHEMA.items(),
)
def test_required_schema_columns(
    exasol_connection,
    table_name,
    expected_columns,
):
    """Check that every required table and column exists in Exasol."""

    rows = exasol_connection.execute(
        f"""
        SELECT COLUMN_NAME
        FROM EXA_ALL_COLUMNS
        WHERE COLUMN_SCHEMA = 'SARVAGYA'
          AND COLUMN_TABLE = '{table_name}'
        """
    ).fetchall()

    actual_columns = {row[0] for row in rows}
    missing_columns = expected_columns - actual_columns

    assert actual_columns, (
        f"Table SARVAGYA.{table_name} was not found or is not visible."
    )

    assert not missing_columns, (
        f"Table SARVAGYA.{table_name} is missing required columns: "
        f"{sorted(missing_columns)}"
    )
