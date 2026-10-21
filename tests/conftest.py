
import getpass

import pyexasol
import pytest


@pytest.fixture(scope="session")
def exasol_connection():
    """Provide one Exasol connection for the test session."""
    password = getpass.getpass("Enter Exasol SYS password: ")

    conn = pyexasol.connect(
        dsn="127.0.0.1:8563",
        user="sys",
        password=password,
        websocket_sslopt={"cert_reqs": 0},
    )

    try:
        yield conn
    finally:
        conn.close()
