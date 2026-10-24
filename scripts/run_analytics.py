import sys
from pathlib import Path

from analytics_connection import get_analytics_connection


ANALYTICS_DIR = Path("sql/analytics")


def main():
    if len(sys.argv) != 2:
        print(
            "Usage: python scripts/run_analytics.py <query_name>"
        )
        return 1

    query_name = sys.argv[1]

    # Accept a query name, not an arbitrary filesystem path.
    if not query_name.replace("_", "").replace("-", "").isalnum():
        print("Invalid query name.")
        return 1

    sql_path = ANALYTICS_DIR / f"{query_name}.sql"

    if not sql_path.is_file():
        print(f"Query not found: {sql_path}")
        print("Available queries:")

        for path in sorted(ANALYTICS_DIR.glob("*.sql")):
            print(f"  {path.stem}")

        return 1

    sql = sql_path.read_text(encoding="utf-8").strip()

    if not sql:
        print(f"Query file is empty: {sql_path}")
        return 1

    conn = get_analytics_connection()

    try:
        cursor = conn.execute(sql)

        columns = cursor.column_names()

        if not columns:
            print("SQL executed successfully; no result set returned.")
            return 0

        rows = cursor.fetchall()
        print(f"\nQuery: {query_name}")
        print(" | ".join(columns))
        print("-" * 80)

        for row in rows:
            print(" | ".join(str(value) for value in row))

        print(f"\nRows returned: {len(rows)}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
