
import getpass
import pyexasol

password = getpass.getpass("Enter Exasol SYS password: ")

conn = pyexasol.connect(
    dsn="127.0.0.1:8563",
    user="sys",
    password=password,
    websocket_sslopt={"cert_reqs": 0},
)

try:
    query = """
        SELECT
            'ORDER' AS RECORD_TYPE,
            ORDER_ID AS RECORD_ID,
            CAST(ORDER_AMOUNT AS DECIMAL(18, 2)) AS AMOUNT,
            CAST(NULL AS VARCHAR(20)) AS STATUS
        FROM SARVAGYA.ORDERS
        WHERE ORDER_ID = 'SL-GT04-ORDER'

        UNION ALL

        SELECT
            'PAYMENT_ATTEMPT',
            ATTEMPT_ID,
            CAST(ATTEMPT_AMOUNT AS DECIMAL(18, 2)),
            ATTEMPT_STATUS
        FROM SARVAGYA.PAYMENT_ATTEMPTS
        WHERE ORDER_ID = 'SL-GT04-ORDER'

        UNION ALL

        SELECT
            'PROCESSOR_TRANSACTION',
            PROCESSOR_TXN_ID,
            CAST(TRANSACTION_AMOUNT AS DECIMAL(18, 2)),
            TRANSACTION_STATUS
        FROM SARVAGYA.PROCESSOR_TRANSACTIONS
        WHERE PROCESSOR_TXN_ID IN (
            'SL-GT04-PTX1',
            'SL-GT04-PTX2'
        )

        ORDER BY RECORD_TYPE, RECORD_ID
    """

    rows = conn.execute(query).fetchall()

    for row in rows:
        print(row)

    print(f"\nTotal records found: {len(rows)}")

    if len(rows) != 5:
        raise AssertionError(
            f"Expected 5 records, but found {len(rows)}"
        )

    captured = conn.execute("""
        SELECT COUNT(*), SUM(TRANSACTION_AMOUNT)
        FROM SARVAGYA.PROCESSOR_TRANSACTIONS
        WHERE PROCESSOR_TXN_ID IN (
            'SL-GT04-PTX1',
            'SL-GT04-PTX2'
        )
        AND TRANSACTION_STATUS = 'CAPTURED'
    """).fetchone()

    print(f"Captured transaction count: {captured[0]}")
    print(f"Total captured amount: {captured[1]}")

    if captured[0] != 2 or float(captured[1]) != 2000.0:
        raise AssertionError(
            "Expected 2 captured transactions totaling INR 2000."
        )

    print("GT-04 verification passed.")

finally:
    conn.close()
