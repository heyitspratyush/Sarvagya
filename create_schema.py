
from pathlib import Path

from scripts.analytics_connection import get_analytics_connection


ROOT = Path(__file__).resolve().parent
SQL_DIR = ROOT / "sql"

# ORDERS already exists and has been verified.
TABLE_FILES = [
    
    "payment_attempts.sql",
    "processor_transactions.sql",
    "processor_source_rows.sql",
    "settlement.sql",
    "settlement_transactions.sql",
    "bank_transactions.sql",
    "reconciliation_findings.sql",
    "finding_evidence.sql",
]


def main():
    conn = get_analytics_connection()

    try:
        for filename in TABLE_FILES:
            sql_path = SQL_DIR / filename
            sql = sql_path.read_text(encoding="utf-8").strip()

            if not sql:
                raise ValueError(f"Empty SQL file: {filename}")

            print(f"Executing {filename}...")
            conn.execute(sql)
            print(f"Completed {filename}")

        print("\nAll requested SQL definitions executed.")

    finally:
        conn.close()
        print("Database connection closed.")


if __name__ == "__main__":
    main()
