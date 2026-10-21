
import getpass
from pathlib import Path

import pyexasol


# Resolve the project root from this script's location.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main():
    sql_file = PROJECT_ROOT / "seed" / "data" / "gt01_normal_payment.sql"

    if not sql_file.is_file():
        raise FileNotFoundError(
            f"SQL file not found: {sql_file}"
        )

    password = getpass.getpass("Enter Exasol SYS password: ")

    conn = pyexasol.connect(
        dsn="127.0.0.1:8563",
        user="sys",
        password=password,
        websocket_sslopt={"cert_reqs": 0},
    )

    try:
        sql_text = sql_file.read_text(encoding="utf-8")

        statements = [
            statement.strip()
            for statement in sql_text.split(";")
            if statement.strip()
        ]

        for index, statement in enumerate(statements, start=1):
            conn.execute(statement)
            print(f"Statement {index}/{len(statements)} executed.")

        print("\nGT-01 seed data loaded successfully.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
