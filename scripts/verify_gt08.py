
import getpass
from datetime import date, datetime
import pyexasol

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
            p.TRANSACTION_AT,
            st.BATCH_ID,
            s.EXPECTED_SETTLEMENT_DATE,
            s.SETTLED_AT,
            s.SETTLEMENT_STATUS
        FROM SARVAGYA.PROCESSOR_TRANSACTIONS p
        JOIN SARVAGYA.SETTLEMENT_TRANSACTIONS st
          ON st.PROCESSOR_TXN_ID = p.PROCESSOR_TXN_ID
        JOIN SARVAGYA.SETTLEMENTS s
          ON s.BATCH_ID = st.BATCH_ID
        WHERE p.PROCESSOR_TXN_ID = 'SL-GT08-PTX'
    """).fetchall()

    if len(rows) != 1:
        raise AssertionError(
            f"Expected one transaction-to-batch assignment, found {len(rows)}"
        )

    txn_id, capture, batch_id, expected_date, settled_at, status = rows[0]

    if isinstance(capture, str):
        capture = datetime.fromisoformat(capture)

    if isinstance(expected_date, str):
        expected_date = date.fromisoformat(expected_date[:10])
    elif isinstance(expected_date, datetime):
        expected_date = expected_date.date()

    if isinstance(settled_at, str):
        settled_at = datetime.fromisoformat(settled_at)

    if txn_id != "SL-GT08-PTX":
        raise AssertionError("Unexpected processor transaction.")

    if batch_id != "SL-GT08-BATCH-20261020":
        raise AssertionError("Incorrect batch assignment for GT-08.")

    # This scenario's explicit synthetic settlement schedule.
    expected_business_date = date(2026, 10, 20)
    expected_payout_date = date(2026, 10, 21)

    if capture.date() != expected_business_date:
        raise AssertionError("Unexpected capture date.")

    if expected_date != expected_payout_date:
        raise AssertionError("Expected settlement date should be Oct 21.")

    if settled_at.date() <= expected_date:
        raise AssertionError("Expected this settlement to be late.")

    delay_days = (settled_at.date() - expected_date).days

    if delay_days != 2:
        raise AssertionError(f"Expected 2 calendar days late, got {delay_days}.")

    if status != "SETTLED":
        raise AssertionError("Expected settlement status SETTLED.")

    print(f"Transaction: {txn_id}")
    print(f"Capture timestamp: {capture}")
    print(f"Assigned batch: {batch_id}")
    print(f"Expected settlement date: {expected_date}")
    print(f"Actual settlement timestamp: {settled_at}")
    print(f"Settlement delay: {delay_days} calendar days")
    print("\nGT-08 verification passed: late settlement detected.")

finally:
    conn.close()
