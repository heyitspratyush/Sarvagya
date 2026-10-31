
from analytics_connection import get_analytics_connection

conn = get_analytics_connection()

try:
    query = """
        SELECT 'ORDERS' AS SOURCE_TABLE,
               ORDER_ID AS RECORD_ID
        FROM SARVAGYA.ORDERS
        WHERE ORDER_ID = 'SL-GT01-ORDER'

        UNION ALL

        SELECT 'PAYMENT_ATTEMPTS',
               ATTEMPT_ID
        FROM SARVAGYA.PAYMENT_ATTEMPTS
        WHERE ATTEMPT_ID = 'SL-GT01-ATT'

        UNION ALL

        SELECT 'PROCESSOR_TRANSACTIONS',
               PROCESSOR_TXN_ID
        FROM SARVAGYA.PROCESSOR_TRANSACTIONS
        WHERE PROCESSOR_TXN_ID = 'SL-GT01-PTX'
    """

    rows = conn.execute(query).fetchall()

    for row in rows:
        print(row)

    print(f"\nTotal records found: {len(rows)}")

finally:
    conn.close()
