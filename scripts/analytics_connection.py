import getpass

import pyexasol


def get_analytics_connection(autocommit=True):
    """Open a connection to Exasol for analytical SQL queries."""
    password = getpass.getpass("Enter Exasol SYS password: ")

    return pyexasol.connect(
        dsn="127.0.0.1:8563",
        user="sys",
        password=password,
        websocket_sslopt={"cert_reqs": 0},
    )
