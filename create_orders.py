
from pathlib import Path

from scripts.analytics_connection import get_analytics_connection

# Locate the SQL file relative to this Python script.
SQL_FILE = Path(__file__).parent / "sql" / "create_schema.sql"


def main():
    conn = get_analytics_connection()

    try:
        conn.execute("CREATE SCHEMA IF NOT EXISTS SARVAGYA")
        # Read the SQL instructions from the file.
        sql = SQL_FILE.read_text(encoding="utf-8")

        # Send the SQL to Exasol for execution.
        statements = [
            statement.strip()
            for statement in sql.split(";")
            if statement.strip()
        ]

        for statement in statements:
            conn.execute(statement)
            print("Executed:", statement.splitlines()[0])

        # Verify that ORDERS exists in the current schema.
        result = conn.execute("""
            SELECT table_name
            FROM exa_all_tables
            WHERE table_schema = CURRENT_SCHEMA
            AND table_name = 'ORDERS'
        """).fetchall()

        
        if result:
            print("ORDERS table found: True")
            
        else:
            print("ORDERS table found: False")
            print("Check the current schema and SQL execution.")

    finally:
        # Close the connection even if an error occurs.
        conn.close()
        print("Database connection closed.")


if __name__ == "__main__":
    main()
