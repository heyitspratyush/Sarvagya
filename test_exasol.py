"""Manual Exasol connection smoke test; not executed during pytest collection."""

from scripts.analytics_connection import get_analytics_connection


def main():
    connection = get_analytics_connection()
    try:
        result = connection.execute("SELECT 1").fetchall()
        print("Connection successful!")
        print("Query result:", result)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
