
import getpass
import sys
from pathlib import Path

import pyexasol


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = PROJECT_ROOT / "seed" / "data"


def main():
    if len(sys.argv) != 2:
        print("Usage: python seed/load_seed.py <scenario_name>")
        raise SystemExit(2)

    scenario_name = sys.argv[1]

    # Allow only simple scenario names, not arbitrary filesystem paths.
    if not scenario_name.replace("_", "").isalnum():
        raise ValueError("Scenario name may contain only letters, numbers, and underscores.")

    sql_file = SEED_DIR / f"{scenario_name}.sql"

    if not sql_file.is_file():
        raise FileNotFoundError(f"Seed file not found: {sql_file}")

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
            print(f"Executed statement {index}/{len(statements)}")

        print(f"Seed scenario loaded: {scenario_name}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
