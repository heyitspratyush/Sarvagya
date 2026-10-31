
from analytics_connection import get_analytics_connection

conn = get_analytics_connection()

try:
    query = """
        SELECT
            'ORDER' AS RECORD_TYPE,
            ORDER_ID AS RECORD_ID,
            CAST(ORDER_AMOUNT AS DECIMAL(18, 2)) AS AMOUNT,
            CAST(NULL AS VARCHAR(20)) AS STATUS
        FROM SARVAGYA.ORDERS
        WHERE ORDER_ID = 'SL-GT03-ORDER'

        UNION ALL

        SELECT
            'PAYMENT_ATTEMPT',
            ATTEMPT_ID,
            CAST(ATTEMPT_AMOUNT AS DECIMAL(18, 2)),
            ATTEMPT_STATUS
        FROM SARVAGYA.PAYMENT_ATTEMPTS
        WHERE ORDER_ID = 'SL-GT03-ORDER'

        UNION ALL

        SELECT
            'PROCESSOR_TRANSACTION',
            PROCESSOR_TXN_ID,
            CAST(TRANSACTION_AMOUNT AS DECIMAL(18, 2)),
            TRANSACTION_STATUS
        FROM SARVAGYA.PROCESSOR_TRANSACTIONS
        WHERE PROCESSOR_TXN_ID = 'SL-GT03-PTX'
    """

    rows = conn.execute(query).fetchall()

    for row in rows:
        print(row)

    print(f"\nTotal records found: {len(rows)}")

    if len(rows) != 4:
        raise AssertionError(
            f"Expected 4 records, but found {len(rows)}"
        )

finally:
    conn.close()
