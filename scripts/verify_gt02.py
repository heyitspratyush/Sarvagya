
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
        SELECT 'ORDERS' AS SOURCE_TABLE,
               ORDER_ID AS RECORD_ID,
               ORDER_AMOUNT AS AMOUNT
        FROM SARVAGYA.ORDERS
        WHERE ORDER_ID = 'SL-GT02-ORDER'

        UNION ALL

        SELECT 'PAYMENT_ATTEMPTS',
               ATTEMPT_ID,
               ATTEMPT_AMOUNT
        FROM SARVAGYA.PAYMENT_ATTEMPTS
        WHERE ATTEMPT_ID = 'SL-GT02-ATT'

        UNION ALL

        SELECT 'PROCESSOR_TRANSACTIONS',
               PROCESSOR_TXN_ID,
               TRANSACTION_AMOUNT
        FROM SARVAGYA.PROCESSOR_TRANSACTIONS
        WHERE PROCESSOR_TXN_ID = 'SL-GT02-PTX'
    """

    rows = conn.execute(query).fetchall()

    for row in rows:
        print(row)

    print(f"\nTotal records found: {len(rows)}")

    if len(rows) != 3:
        raise AssertionError(
            f"Expected 3 records, but found {len(rows)}"
        )

finally:
    conn.close()
