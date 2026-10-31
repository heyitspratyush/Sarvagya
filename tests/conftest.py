import pytest

from scripts.analytics_connection import get_analytics_connection


@pytest.fixture(scope="session")
def exasol_connection():
    """Provide one centrally authenticated connection to live schema tests."""
    connection = get_analytics_connection()
    try:
        yield connection
    finally:
        connection.close()
