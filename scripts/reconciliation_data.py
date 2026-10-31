
"""Read order and payment-attempt records from Exasol."""

from scripts.analytics_connection import get_analytics_connection


def fetch_order_attempt_data(connection=None):
    """Fetch reconciliation source records and processor row lineage."""

    owns_connection = connection is None
    if owns_connection:
        connection = get_analytics_connection()

    try:
        # Fetch order records directly through pyexasol.
        order_statement = connection.execute("""
            SELECT
                ORDER_ID,
                ORDER_AMOUNT,
                CURRENCY
            FROM SARVAGYA.ORDERS
            WHERE ORDER_ID NOT LIKE 'BMK-%'
        """)

        order_columns = order_statement.column_names()

        orders = [
            dict(zip(order_columns, row))
            for row in order_statement.fetchall()
        ]

        # Fetch payment-attempt records.
        attempt_statement = connection.execute("""
            SELECT
                ATTEMPT_ID,
                ORDER_ID,
                MERCHANT_PAYMENT_REF,
                ATTEMPT_AMOUNT,
                ATTEMPT_STATUS
            FROM SARVAGYA.PAYMENT_ATTEMPTS
            WHERE ATTEMPT_ID NOT LIKE 'BMK-%'
        """)

        attempt_columns = attempt_statement.column_names()

        attempts = [
            dict(zip(attempt_columns, row))
            for row in attempt_statement.fetchall()
        ]

        processor_statement = connection.execute("""
            SELECT
                PROCESSOR_TXN_ID,
                PROCESSOR_NAME,
                ORDER_ID,
                MERCHANT_PAYMENT_REF,
                TRANSACTION_AMOUNT,
                CURRENCY,
                TRANSACTION_STATUS,
                TRANSACTION_AT
            FROM SARVAGYA.PROCESSOR_TRANSACTIONS
            WHERE PROCESSOR_TXN_ID NOT LIKE 'SL-GT07-BMK-%'
        """)
        processor_columns = processor_statement.column_names()
        processor_transactions = [
            dict(zip(processor_columns, row))
            for row in processor_statement.fetchall()
        ]

        source_statement = connection.execute("""
            SELECT
                SOURCE_ROW_ID,
                PROCESSOR_TXN_ID,
                SOURCE_FILE,
                SOURCE_ROW_NUMBER,
                IMPORTED_AT
            FROM SARVAGYA.PROCESSOR_SOURCE_ROWS
            WHERE SOURCE_ROW_ID NOT LIKE 'BMK-%'
        """)
        source_columns = source_statement.column_names()
        processor_source_rows = [
            dict(zip(source_columns, row))
            for row in source_statement.fetchall()
        ]

        settlement_statement = connection.execute("""
            SELECT
                BATCH_ID,
                GROSS_AMOUNT,
                FEE_AMOUNT,
                REFUND_AMOUNT,
                CHARGEBACK_AMOUNT,
                ADJUSTMENT_AMOUNT,
                REPORTED_NET_AMOUNT,
                CURRENCY,
                EXPECTED_SETTLEMENT_DATE,
                SETTLED_AT,
                SETTLEMENT_STATUS
            FROM SARVAGYA.SETTLEMENTS
            WHERE BATCH_ID NOT LIKE 'SL-GT07-BMK-%'
        """)
        settlement_columns = settlement_statement.column_names()
        settlements = [
            dict(zip(settlement_columns, row))
            for row in settlement_statement.fetchall()
        ]

        settlement_transaction_statement = connection.execute("""
            SELECT BATCH_ID, PROCESSOR_TXN_ID
            FROM SARVAGYA.SETTLEMENT_TRANSACTIONS
            WHERE BATCH_ID NOT LIKE 'SL-GT07-BMK-%'
        """)
        settlement_transaction_columns = settlement_transaction_statement.column_names()
        settlement_transactions = [
            dict(zip(settlement_transaction_columns, row))
            for row in settlement_transaction_statement.fetchall()
        ]

        bank_statement = connection.execute("""
            SELECT
                BANK_TXN_ID,
                BANK_REFERENCE,
                AMOUNT,
                CURRENCY,
                TRANSACTION_AT,
                DESCRIPTION,
                SOURCE_FILE
            FROM SARVAGYA.BANK_TRANSACTIONS
            WHERE BANK_TXN_ID NOT LIKE 'BMK-%'
        """)
        bank_columns = bank_statement.column_names()
        bank_transactions = [
            dict(zip(bank_columns, row))
            for row in bank_statement.fetchall()
        ]

        return (
            orders,
            attempts,
            processor_transactions,
            processor_source_rows,
            settlements,
            settlement_transactions,
            bank_transactions,
        )

    finally:
        if owns_connection:
            connection.close()
