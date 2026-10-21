
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
    # 1. Verify the order, payment attempt, and logical transaction.
    records = conn.execute("""
        SELECT 'ORDER' AS RECORD_TYPE, ORDER_ID AS RECORD_ID
        FROM SARVAGYA.ORDERS
        WHERE ORDER_ID = 'SL-GT05-ORDER'

        UNION ALL

        SELECT 'PAYMENT_ATTEMPT', ATTEMPT_ID
        FROM SARVAGYA.PAYMENT_ATTEMPTS
        WHERE ATTEMPT_ID = 'SL-GT05-ATT'

        UNION ALL

        SELECT 'PROCESSOR_TRANSACTION', PROCESSOR_TXN_ID
        FROM SARVAGYA.PROCESSOR_TRANSACTIONS
        WHERE PROCESSOR_TXN_ID = 'SL-GT05-PTX'
    """).fetchall()

    print("Core records:")
    for record in records:
        print(record)

    if len(records) != 3:
        raise AssertionError(
            f"Expected 3 core records, found {len(records)}"
        )

    # 2. Verify two source rows point to the same transaction.
    source_rows = conn.execute("""
        SELECT SOURCE_ROW_ID, PROCESSOR_TXN_ID,
               SOURCE_FILE, SOURCE_ROW_NUMBER
        FROM SARVAGYA.PROCESSOR_SOURCE_ROWS
        WHERE PROCESSOR_TXN_ID = 'SL-GT05-PTX'
        ORDER BY SOURCE_ROW_ID
    """).fetchall()

    print("\nSource rows:")
    for row in source_rows:
        print(row)

    if len(source_rows) != 2:
        raise AssertionError(
            f"Expected 2 source rows, found {len(source_rows)}"
        )

    # 3. Confirm there is still only one logical captured transaction.
    transaction = conn.execute("""
        SELECT COUNT(*), SUM(TRANSACTION_AMOUNT)
        FROM SARVAGYA.PROCESSOR_TRANSACTIONS
        WHERE PROCESSOR_TXN_ID = 'SL-GT05-PTX'
          AND TRANSACTION_STATUS = 'CAPTURED'
    """).fetchone()

    print(f"\nCaptured transaction count: {transaction[0]}")
    print(f"Captured amount: {transaction[1]}")

    if transaction[0] != 1 or float(transaction[1]) != 1000.0:
        raise AssertionError(
            "Expected one captured transaction totaling INR 1000."
        )

    print("\nGT-05 verification passed.")

finally:
    conn.close()
