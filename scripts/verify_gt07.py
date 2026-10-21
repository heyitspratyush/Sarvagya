
import getpass
from datetime import datetime, time, timedelta
import pyexasol

CUTOFF = time(15, 0)

password = getpass.getpass("Enter Exasol SYS password: ")

conn = pyexasol.connect(
    dsn="127.0.0.1:8563",
    user="sys",
    password=password,
    websocket_sslopt={"cert_reqs": 0},
)

try:
    rows = conn.execute("""
        SELECT
            p.PROCESSOR_TXN_ID,
            p.TRANSACTION_AMOUNT,
            p.TRANSACTION_STATUS,
            p.TRANSACTION_AT,
            st.BATCH_ID,
            s.EXPECTED_SETTLEMENT_DATE,
            s.SETTLED_AT
        FROM SARVAGYA.PROCESSOR_TRANSACTIONS p
        JOIN SARVAGYA.SETTLEMENT_TRANSACTIONS st
          ON st.PROCESSOR_TXN_ID = p.PROCESSOR_TXN_ID
        JOIN SARVAGYA.SETTLEMENTS s
          ON s.BATCH_ID = st.BATCH_ID
        WHERE p.PROCESSOR_TXN_ID = 'SL-GT07-PTX'
    """).fetchall()

    if len(rows) != 1:
        raise AssertionError(
            f"Expected one transaction-to-batch assignment, found {len(rows)}"
        )

    txn_id, amount, status, capture, actual_batch_id, expected_settlement_date, settled_at = rows[0]

    if isinstance(capture, str):
        capture = datetime.fromisoformat(capture)

    if txn_id != "SL-GT07-PTX":
        raise AssertionError("Unexpected transaction ID.")

    if float(amount) != 1000.0 or status != "CAPTURED":
        raise AssertionError("Expected a captured INR 1000 transaction.")

    # Derive the expected business date from the capture timestamp.
    expected_business_date = capture.date()
    if capture.time() >= CUTOFF:
        expected_business_date += timedelta(days=1)

    expected_batch_id = (
        f"SL-GT07-BATCH-{expected_business_date:%Y%m%d}"
    )

    print(f"Capture timestamp: {capture}")
    print(f"Cutoff: {CUTOFF}")
    print(f"Expected business date: {expected_business_date}")
    print(f"Expected batch ID: {expected_batch_id}")
    print(f"Actual batch ID: {actual_batch_id}")
    print(f"Expected settlement date: {expected_settlement_date}")
    print(f"Actual settled timestamp: {settled_at}")

    if expected_batch_id == actual_batch_id:
        raise AssertionError(
            "GT-07 should contain a wrong-batch assignment, but IDs match."
        )

    if actual_batch_id != "SL-GT07-BATCH-20261020":
        raise AssertionError("Unexpected actual batch ID.")

    if expected_batch_id != "SL-GT07-BATCH-20261021":
        raise AssertionError("Expected batch should be October 21.")

    print("\nGT-07 verification passed: wrong batch assignment detected.")

finally:
    conn.close()
