
import getpass
import pyexasol


EXPECTED_SCHEMA = {
    "ORDERS": {
        "ORDER_ID",
        "ORDER_AMOUNT",
        "CURRENCY",
        "CREATED_AT",
        "MERCHANT_ID",
    },
    "PAYMENT_ATTEMPTS": {
        "ATTEMPT_ID",
        "ORDER_ID",
        "MERCHANT_PAYMENT_REF",
        "ATTEMPT_AMOUNT",
        "ATTEMPT_STATUS",
        "CREATED_AT",
    },
    "PROCESSOR_TRANSACTIONS": {
        "PROCESSOR_TXN_ID",
        "PROCESSOR_NAME",
        "ORDER_ID",
        "MERCHANT_PAYMENT_REF",
        "TRANSACTION_AMOUNT",
        "CURRENCY",
        "TRANSACTION_STATUS",
        "TRANSACTION_AT",
    },
    "PROCESSOR_SOURCE_ROWS": {
        "SOURCE_ROW_ID",
        "PROCESSOR_TXN_ID",
        "SOURCE_FILE",
        "SOURCE_ROW_NUMBER",
        "IMPORTED_AT",
    },
    "SETTLEMENTS": {
        "BATCH_ID",
        "GROSS_AMOUNT",
        "FEE_AMOUNT",
        "REFUND_AMOUNT",
        "CHARGEBACK_AMOUNT",
        "ADJUSTMENT_AMOUNT",
        "REPORTED_NET_AMOUNT",
        "CURRENCY",
        "EXPECTED_SETTLEMENT_DATE",
        "SETTLED_AT",
        "SETTLEMENT_STATUS",
    },
    "SETTLEMENT_TRANSACTIONS": {
        "BATCH_ID",
        "PROCESSOR_TXN_ID",
    },
    "BANK_TRANSACTIONS": {
        "BANK_TXN_ID",
        "BANK_REFERENCE",
        "AMOUNT",
        "CURRENCY",
        "TRANSACTION_AT",
        "DESCRIPTION",
        "SOURCE_FILE",
    },
    "RECONCILIATION_FINDINGS": {
        "FINDING_ID",
        "FINDING_TYPE",
        "CLASSIFICATION",
        "RESOLUTION_STATUS",
        "EXPECTED_AMOUNT",
        "OBSERVED_AMOUNT",
        "DIFFERENCE_AMOUNT",
        "CURRENCY",
        "EVIDENCE_SUMMARY",
        "LIMITATION",
        "CREATED_AT",
        "EXPECTED_AT",
        "OBSERVED_AT",
        "DELAY_MINUTES",
    },
    "FINDING_EVIDENCE": {
        "FINDING_ID",
        "ENTITY_TYPE",
        "ENTITY_ID",
        "EVIDENCE_ROLE",
    },
}


def main():
    password = getpass.getpass("Enter Exasol SYS password: ")

    conn = pyexasol.connect(
        dsn="127.0.0.1:8563",
        user="sys",
        password=password,
        websocket_sslopt={"cert_reqs": 0},
    )

    all_passed = True

    try:
        for table_name, expected_columns in EXPECTED_SCHEMA.items():
            columns = conn.execute(
                f"""
                SELECT column_name
                FROM exa_all_columns
                WHERE column_schema = 'SARVAGYA'
                AND column_table = '{table_name}'
                ORDER BY column_ordinal_position
                """
            ).fetchall()

            actual_columns = {column[0] for column in columns}

            missing = expected_columns - actual_columns
            unexpected = actual_columns - expected_columns

            if not actual_columns:
                print(f"\n{table_name}: TABLE NOT FOUND")
                all_passed = False
                continue

            print(f"\n{table_name}:")
            print("  Actual columns:", ", ".join(sorted(actual_columns)))

            if missing:
                print("  Missing columns:", ", ".join(sorted(missing)))
                all_passed = False

            if unexpected:
                print("  Unexpected columns:", ", ".join(sorted(unexpected)))

            if not missing:
                print("  Required-column check: PASSED")

    finally:
        conn.close()
        print("\nDatabase connection closed.")

    print(
        "\nOverall schema verification:",
        "PASSED" if all_passed else "REVIEW REQUIRED",
    )


if __name__ == "__main__":
    main()
