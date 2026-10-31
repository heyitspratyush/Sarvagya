from datetime import date, datetime
from decimal import Decimal

from scripts import reconciliation_data, run_reconciliation


class FakeStatement:
    def __init__(self, columns, rows):
        self._columns = columns
        self._rows = rows

    def column_names(self):
        return self._columns

    def fetchall(self):
        return self._rows


class FakeFetchConnection:
    def __init__(self, processor_rows=None):
        self.processor_rows = processor_rows or []
        self.queries = []
        self.commits = 0
        self.closed = False
        self.options = {"autocommit": False}

    def execute(self, query, params=None):
        self.queries.append(query)
        if "FROM SARVAGYA.ORDERS" in query:
            return FakeStatement(["ORDER_ID", "ORDER_AMOUNT", "CURRENCY"], [])
        if "FROM SARVAGYA.PAYMENT_ATTEMPTS" in query:
            return FakeStatement(
                ["ATTEMPT_ID", "ORDER_ID", "MERCHANT_PAYMENT_REF", "ATTEMPT_AMOUNT", "ATTEMPT_STATUS"],
                [],
            )
        if "FROM SARVAGYA.PROCESSOR_TRANSACTIONS" in query:
            return FakeStatement([
                "PROCESSOR_TXN_ID", "PROCESSOR_NAME", "ORDER_ID",
                "MERCHANT_PAYMENT_REF", "TRANSACTION_AMOUNT", "CURRENCY",
                "TRANSACTION_STATUS", "TRANSACTION_AT",
            ], self.processor_rows)
        if "FROM SARVAGYA.PROCESSOR_SOURCE_ROWS" in query:
            return FakeStatement(
                ["SOURCE_ROW_ID", "PROCESSOR_TXN_ID", "SOURCE_FILE", "SOURCE_ROW_NUMBER", "IMPORTED_AT"],
                [],
            )
        if "FROM SARVAGYA.SETTLEMENT_TRANSACTIONS" in query:
            return FakeStatement(["BATCH_ID", "PROCESSOR_TXN_ID"], [[
                "SL-GT07-BATCH-20261020", "SL-GT07-PTX",
            ]] if self.processor_rows else [])
        if "FROM SARVAGYA.SETTLEMENTS" in query:
            return FakeStatement([
                "BATCH_ID", "GROSS_AMOUNT", "FEE_AMOUNT", "REFUND_AMOUNT",
                "CHARGEBACK_AMOUNT", "ADJUSTMENT_AMOUNT", "REPORTED_NET_AMOUNT",
                "CURRENCY", "EXPECTED_SETTLEMENT_DATE", "SETTLED_AT", "SETTLEMENT_STATUS",
            ], [[
                "SL-GT07-BATCH-20261020", Decimal("1000.00"), Decimal("0.00"),
                Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("1000.00"),
                "INR", date(2026, 10, 21), datetime(2026, 10, 21, 18, 0), "SETTLED",
            ]] if self.processor_rows else [])
        if "FROM SARVAGYA.BANK_TRANSACTIONS" in query:
            return FakeStatement([
                "BANK_TXN_ID", "BANK_REFERENCE", "AMOUNT", "CURRENCY",
                "TRANSACTION_AT", "DESCRIPTION", "SOURCE_FILE",
            ], [])
        raise AssertionError(f"Unexpected query: {query}")

    def commit(self):
        self.commits += 1

    def set_autocommit(self, value):
        self.options["autocommit"] = value

    def close(self):
        self.closed = True


def test_fetch_preserves_processor_transaction_at():
    timestamp = datetime(2026, 10, 20, 16, 2)
    connection = FakeFetchConnection(processor_rows=[[
        "SL-GT07-PTX", "SYNTHETIC", "SL-GT07-ORDER", "SL-GT07-REF",
        Decimal("1000.00"), "INR", "CAPTURED", timestamp,
    ]])

    data = reconciliation_data.fetch_order_attempt_data(connection=connection)

    assert data[2][0]["TRANSACTION_AT"] is timestamp
    processor_query = next(query for query in connection.queries if "FROM SARVAGYA.PROCESSOR_TRANSACTIONS" in query)
    assert "TRANSACTION_AT" in processor_query
    assert connection.closed is False


def test_runner_passes_fetched_processor_timestamp_into_gt07_batch_check(monkeypatch):
    timestamp = datetime(2026, 10, 20, 16, 2)
    connection = FakeFetchConnection(processor_rows=[[
        "SL-GT07-PTX", "SYNTHETIC", "SL-GT07-ORDER", "SL-GT07-REF",
        Decimal("1000.00"), "INR", "CAPTURED", timestamp,
    ]])
    monkeypatch.setattr(
        run_reconciliation,
        "get_analytics_connection",
        lambda autocommit=False: connection,
    )
    processor_records_seen = []
    real_engine = run_reconciliation.reconcile_orders_attempts_processor_and_settlement

    def record_processor_data(*args):
        processor_records_seen.append(args[2])
        return real_engine(*args)

    monkeypatch.setattr(
        run_reconciliation,
        "reconcile_orders_attempts_processor_and_settlement",
        record_processor_data,
    )
    persisted_connections = []

    def persist(finding, connection=None):
        persisted_connections.append(connection)
        return {
            "finding_inserted": True,
            "evidence_inserted": True,
            "finding_committed": True,
            "connection_usable": True,
            "persistence_error": None,
        }

    monkeypatch.setattr(run_reconciliation, "persist_reconciliation_finding", persist)

    summary = run_reconciliation.run_reconciliation()

    processor_records = processor_records_seen[0]
    assert processor_records[0]["TRANSACTION_AT"] is timestamp
    assert any(
        finding["classification"] == "PROCESSOR_TRANSACTION_IN_WRONG_SETTLEMENT_BATCH"
        for finding in summary["reconciliation_result"]["findings"]
    )
    assert persisted_connections and all(item is connection for item in persisted_connections)
    assert connection.commits == 1
    assert connection.closed is True
