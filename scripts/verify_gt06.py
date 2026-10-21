
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
    # 1. Verify the captured processor transaction.
    transaction = conn.execute("""
        SELECT
            PROCESSOR_TXN_ID,
            ORDER_ID,
            MERCHANT_PAYMENT_REF,
            TRANSACTION_AMOUNT,
            CURRENCY,
            TRANSACTION_STATUS
        FROM SARVAGYA.PROCESSOR_TRANSACTIONS
        WHERE PROCESSOR_TXN_ID = 'SL-GT06-PTX'
    """).fetchall()

    print("Processor transaction:")
    for row in transaction:
        print(row)

    if len(transaction) != 1:
        raise AssertionError(
            f"Expected 1 processor transaction, found {len(transaction)}"
        )

    # 2. Verify its source-row provenance.
    source_rows = conn.execute("""
        SELECT SOURCE_ROW_ID, PROCESSOR_TXN_ID,
               SOURCE_FILE, SOURCE_ROW_NUMBER
        FROM SARVAGYA.PROCESSOR_SOURCE_ROWS
        WHERE SOURCE_ROW_ID = 'SL-GT06-ROW'
    """).fetchall()

    print("\nSource-row evidence:")
    for row in source_rows:
        print(row)

    if len(source_rows) != 1:
        raise AssertionError(
            f"Expected 1 source row, found {len(source_rows)}"
        )

    # 3. Verify there is no matching merchant order or payment attempt.
    merchant_records = conn.execute("""
        SELECT
            (SELECT COUNT(*)
             FROM SARVAGYA.ORDERS
             WHERE ORDER_ID = 'SL-GT06-UNKNOWN-ORDER')
          +
            (SELECT COUNT(*)
             FROM SARVAGYA.PAYMENT_ATTEMPTS
             WHERE MERCHANT_PAYMENT_REF = 'SL-GT06-UNKNOWN-REF')
        FROM DUAL
    """).fetchone()[0]

    print(f"\nMatching merchant records: {merchant_records}")

    if int(merchant_records) != 0:
        raise AssertionError(
            "Expected no matching merchant order or payment attempt."
        )

    amount = float(transaction[0][3])
    status = transaction[0][5]

    if amount != 750.0 or status != "CAPTURED":
        raise AssertionError(
            "Expected a captured INR 750 processor transaction."
        )

    print("\nGT-06 verification passed.")

finally:
    conn.close()
