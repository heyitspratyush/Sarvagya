
from scripts.analytics_connection import get_analytics_connection


def main():
    conn = get_analytics_connection()

    try:
        columns = conn.execute("""
            SELECT column_name
            FROM exa_all_columns
            WHERE column_schema = 'SARVAGYA'
              AND column_table = 'PAYMENT_ATTEMPTS'
        """).fetchall()

        actual_columns = {row[0] for row in columns}

        if "MERCHANT_PAYMENT_REF" not in actual_columns:
            conn.execute("""
                ALTER TABLE SARVAGYA.PAYMENT_ATTEMPTS
                ADD COLUMN MERCHANT_PAYMENT_REF VARCHAR(100)
            """)
            print("Added MERCHANT_PAYMENT_REF.")
        else:
            print("MERCHANT_PAYMENT_REF already exists; no change needed.")

    finally:
        conn.close()
        print("Database connection closed.")


if __name__ == "__main__":
    main()
