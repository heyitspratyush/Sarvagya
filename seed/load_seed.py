
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = PROJECT_ROOT / "seed" / "data"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analytics_connection import get_analytics_connection


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

    conn = get_analytics_connection()

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
