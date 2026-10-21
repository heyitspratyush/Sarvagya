
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
            s.BATCH_ID,
            s.REPORTED_NET_AMOUNT,
            s.CURRENCY,
            s.EXPECTED_SETTLEMENT_DATE,
            s.SETTLED_AT,
            s.SETTLEMENT_STATUS
        FROM SARVAGYA.SETTLEMENTS s
        JOIN SARVAGYA.SETTLEMENT_TRANSACTIONS st
          ON st.BATCH_ID = s.BATCH_ID
        WHERE st.PROCESSOR_TXN_ID = 'SL-GT09-PTX'
    """).fetchall()

    if len(rows) != 1:
        raise AssertionError(
            f"Expected one settlement batch, found {len(rows)}"
        )

    batch_id, net_amount, currency, expected_date, settled_at, status = rows[0]

    if isinstance(expected_date, str):
        expected_date = date.fromisoformat(expected_date[:10])
    elif isinstance(expected_date, datetime):
        expected_date = expected_date.date()

    if isinstance(settled_at, str):
        settled_at = datetime.fromisoformat(settled_at)

    if batch_id != "SL-GT09-BATCH-20261020":
        raise AssertionError("Unexpected settlement batch.")

    if float(net_amount) != 1200.0 or currency != "INR":
        raise AssertionError("Expected a reported net settlement of INR 1200.")

    if status != "SETTLED":
        raise AssertionError("Expected the processor settlement status SETTLED.")

    if expected_date != date(2026, 10, 21):
        raise AssertionError("Unexpected expected settlement date.")

    if settled_at.date() != date(2026, 10, 21):
        raise AssertionError("Expected settlement to occur on October 21.")

    bank_rows = conn.execute("""
        SELECT BANK_TXN_ID, AMOUNT, CURRENCY
        FROM SARVAGYA.BANK_TRANSACTIONS
        WHERE BANK_TXN_ID = 'SL-GT09-BANK'
    """).fetchall()

    if bank_rows:
        raise AssertionError(
            "GT-09 should not contain the designated bank transaction."
        )

    print(f"Settlement batch: {batch_id}")
    print(f"Processor-reported net: {currency} {float(net_amount):.2f}")
    print(f"Expected settlement date: {expected_date}")
    print(f"Actual settlement timestamp: {settled_at}")
    print(f"Matching designated bank records: {len(bank_rows)}")
    print("\nGT-09 verification passed: bank payout remains unverified.")

finally:
    conn.close()
