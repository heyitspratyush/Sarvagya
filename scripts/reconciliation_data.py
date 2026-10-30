
"""Read order and payment-attempt records from Exasol."""

from scripts.analytics_connection import get_analytics_connection


def fetch_order_attempt_data():
    """Fetch orders and payment attempts for reconciliation."""

    connection = get_analytics_connection()

    try:
        # Fetch order records directly through pyexasol.
        order_statement = connection.execute("""
            SELECT
                ORDER_ID,
                ORDER_AMOUNT,
                CURRENCY
            FROM SARVAGYA.ORDERS
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
                ATTEMPT_AMOUNT,
                ATTEMPT_STATUS
            FROM SARVAGYA.PAYMENT_ATTEMPTS
        """)

        attempt_columns = attempt_statement.column_names()

        attempts = [
            dict(zip(attempt_columns, row))
            for row in attempt_statement.fetchall()
        ]

        return orders, attempts

    finally:
        connection.close()
