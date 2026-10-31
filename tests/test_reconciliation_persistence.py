import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from pyexasol.exceptions import ExaCommunicationError

from scripts import analytics_connection, reconciliation_persistence


class FakeStatement:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class FakeConnection:
    def __init__(
        self, fail_on_evidence_insert=False, fail_entity_ids=(),
        fail_on_close=False, fail_on_connection=False,
    ):
        self.findings = {}
        self.evidence = set()
        self.finding_inserts = []
        self.evidence_inserts = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.fail_on_evidence_insert = fail_on_evidence_insert
        self.fail_entity_ids = set(fail_entity_ids)
        self.fail_on_close = fail_on_close
        self.fail_on_connection = fail_on_connection
        self.options = {"autocommit": False}
        self.autocommit_changes = []
        self._snapshot = (dict(self.findings), set(self.evidence))

    def set_autocommit(self, value):
        self.autocommit_changes.append(value)
        self.options["autocommit"] = value

    def execute(self, query, params):
        if "SELECT EVIDENCE_SUMMARY" in query:
            if self.fail_on_connection:
                raise ExaCommunicationError(self, "connection failure")
            if params["finding_id"] in self.findings:
                return FakeStatement([(self.findings[params["finding_id"]],)])
            return FakeStatement([])
        if "SELECT COUNT(*)" in query:
            key = (
                params["finding_id"], params["entity_type"],
                params["entity_id"], params["evidence_role"],
            )
            return FakeStatement([(int(key in self.evidence),)])
        if "INSERT INTO SARVAGYA.RECONCILIATION_FINDINGS" in query:
            self.findings[params["finding_id"]] = params["evidence_summary"]
            self.finding_inserts.append(dict(params))
            return FakeStatement([])
        if "INSERT INTO SARVAGYA.FINDING_EVIDENCE" in query:
            if self.fail_on_evidence_insert or params["entity_id"] in self.fail_entity_ids:
                raise RuntimeError("evidence insert failed")
            key = (
                params["finding_id"], params["entity_type"],
                params["entity_id"], params["evidence_role"],
            )
            self.evidence.add(key)
            self.evidence_inserts.append(dict(params))
            return FakeStatement([])
        raise AssertionError(f"Unexpected query: {query}")

    def commit(self):
        self.commits += 1
        self._snapshot = (dict(self.findings), set(self.evidence))

    def rollback(self):
        self.rollbacks += 1
        self.findings, self.evidence = self._snapshot

    def close(self):
        self.closed = True
        if self.fail_on_close:
            raise RuntimeError("connection close failed")


def _finding(**overrides):
    finding = {
        "finding_id": "FND-0000000000000000000000000000000000000000",
        "finding_type": "SETTLEMENT_FINANCIAL_RECONCILIATION",
        "classification": "SETTLEMENT_AMOUNT_MISMATCH",
        "resolution_status": "UNRESOLVED",
        "layer": "SETTLEMENT",
        "batch_id": "BATCH-10",
        "currency": "INR",
        "gross_amount": Decimal("1000.00"),
        "fee_amount": Decimal("20.00"),
        "refund_amount": Decimal("50.00"),
        "chargeback_amount": Decimal("10.00"),
        "adjustment_amount": Decimal("-5.00"),
        "expected_net_amount": Decimal("915.00"),
        "reported_net_amount": Decimal("925.00"),
        "discrepancy": Decimal("-10.00"),
        "evidence": [{"entity_type": "SETTLEMENT_HEADER", "entity_id": "BATCH-10"}],
        "limitation": "Reported net differs from calculated expected net.",
    }
    finding.update(overrides)
    return finding


def _patch_connection(monkeypatch, connection):
    calls = []
    monkeypatch.setattr(
        reconciliation_persistence,
        "get_analytics_connection",
        lambda autocommit=True: calls.append(autocommit) or connection,
    )
    return calls


def test_generic_persistence_maps_compatible_financial_fields(monkeypatch):
    connection = FakeConnection()
    _patch_connection(monkeypatch, connection)
    finding = _finding(
        expected_settlement_date=date(2026, 10, 21),
        actual_settlement_timestamp=datetime(2026, 10, 23, 12, 0),
        delay_days=2,
    )

    result = reconciliation_persistence.persist_reconciliation_finding(finding)

    stored = connection.finding_inserts[0]
    assert result["persistence_error"] is None
    assert stored["expected_amount"] == Decimal("915.00")
    assert stored["observed_amount"] == Decimal("925.00")
    assert stored["difference_amount"] == Decimal("-10.00")
    assert stored["expected_at"] == "2026-10-21 00:00:00"
    assert stored["observed_at"] == "2026-10-23 12:00:00"
    assert stored["delay_minutes"] is None
    summary = json.loads(stored["evidence_summary"])
    assert summary["delay_days"] == 2
    assert summary["classification"] == "SETTLEMENT_AMOUNT_MISMATCH"


def test_persistence_reuses_caller_connection_without_opening_or_closing_it(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(
        reconciliation_persistence,
        "get_analytics_connection",
        lambda **kwargs: pytest.fail("shared connection should be reused"),
    )

    result = reconciliation_persistence.persist_reconciliation_finding(
        _finding(), connection=connection
    )

    assert result["finding_committed"] is True
    assert connection.commits == 1
    assert connection.closed is False


def test_generic_persistence_inserts_every_evidence_reference_with_roles(monkeypatch):
    connection = FakeConnection()
    _patch_connection(monkeypatch, connection)
    finding = _finding(evidence=[
        {"entity_type": "SETTLEMENT_HEADER", "entity_id": "BATCH-10", "role": "RELATED_BATCH"},
        {"entity_type": "BANK_TRANSACTION", "entity_id": "BANK-10", "evidence_role": "PAYOUT_CANDIDATE"},
    ])

    result = reconciliation_persistence.persist_reconciliation_finding(finding)

    assert result["evidence_inserted_count"] == 2
    assert {item["entity_id"] for item in connection.evidence_inserts} == {"BATCH-10", "BANK-10"}
    assert {item["evidence_role"] for item in connection.evidence_inserts} == {
        "RELATED_BATCH", "PAYOUT_CANDIDATE",
    }


def test_long_classification_uses_deterministic_alias_and_preserves_original(monkeypatch):
    connection = FakeConnection()
    _patch_connection(monkeypatch, connection)
    finding = _finding(classification="PROCESSOR_TRANSACTION_IN_WRONG_SETTLEMENT_BATCH")

    reconciliation_persistence.persist_reconciliation_finding(finding)
    first_alias = connection.finding_inserts[0]["classification"]
    summary = json.loads(connection.finding_inserts[0]["evidence_summary"])

    assert len(first_alias) == 40
    assert first_alias.startswith("CLS-")
    assert summary["classification"] == "PROCESSOR_TRANSACTION_IN_WRONG_SETTLEMENT_BATCH"

    second_connection = FakeConnection()
    _patch_connection(monkeypatch, second_connection)
    reconciliation_persistence.persist_reconciliation_finding(finding)
    assert second_connection.finding_inserts[0]["classification"] == first_alias


def test_evidence_summary_overlength_returns_structured_error_without_connecting(monkeypatch):
    monkeypatch.setattr(
        reconciliation_persistence, "get_analytics_connection",
        lambda **kwargs: pytest.fail("connection should not be opened for invalid payload"),
    )
    finding = _finding(extra_detail="x" * 3000)

    result = reconciliation_persistence.persist_reconciliation_finding(finding)

    assert result["persistence_error"]["code"] == "INVALID_FINDING"
    assert "EVIDENCE_SUMMARY allows 2000" in result["persistence_error"]["message"]


@pytest.mark.parametrize("evidence", [
    [{"entity_type": "E" * 31, "entity_id": "id"}],
    [{"entity_type": "TYPE", "entity_id": "I" * 101}],
    [{"entity_type": "TYPE", "entity_id": "id", "role": "R" * 41}],
    [{"entity_type": "TYPE", "entity_id": ""}],
])
def test_invalid_evidence_fields_return_structured_error(monkeypatch, evidence):
    monkeypatch.setattr(
        reconciliation_persistence, "get_analytics_connection",
        lambda **kwargs: pytest.fail("connection should not be opened for invalid evidence"),
    )
    result = reconciliation_persistence.persist_reconciliation_finding(_finding(evidence=evidence))
    assert result["persistence_error"]["code"] == "INVALID_FINDING"


def test_duplicate_finding_and_evidence_are_idempotent(monkeypatch):
    connection = FakeConnection()
    _patch_connection(monkeypatch, connection)
    finding = _finding(evidence=[
        {"entity_type": "SETTLEMENT_HEADER", "entity_id": "BATCH-10"},
        {"entity_type": "SETTLEMENT_HEADER", "entity_id": "BATCH-10"},
    ])

    first = reconciliation_persistence.persist_reconciliation_finding(finding)
    second = reconciliation_persistence.persist_reconciliation_finding(finding)

    assert first["finding_inserted"] is True
    assert first["evidence_inserted_count"] == 1
    assert second["finding_inserted"] is False
    assert second["evidence_inserted_count"] == 0
    assert len(connection.finding_inserts) == 1
    assert len(connection.evidence_inserts) == 1


def test_existing_finding_details_are_not_overwritten_and_conflict_is_reported(monkeypatch):
    connection = FakeConnection()
    finding_id = "FND-0000000000000000000000000000000000000000"
    connection.findings[finding_id] = "legacy summary"
    existing_evidence = (finding_id, "BANK_TRANSACTION", "BANK-OLD", "RELATED_ENTITY")
    connection.evidence.add(existing_evidence)
    connection._snapshot = (dict(connection.findings), set(connection.evidence))
    _patch_connection(monkeypatch, connection)

    result = reconciliation_persistence.persist_reconciliation_finding(_finding())

    assert result["persistence_error"]["code"] == "FINDING_ID_CONFLICT"
    assert "legacy summary" in connection.findings.values()
    assert connection.finding_inserts == []
    assert connection.evidence == {existing_evidence}
    assert connection.evidence_inserts == []


def test_identical_existing_finding_reconciles_missing_evidence(monkeypatch):
    connection = FakeConnection()
    _patch_connection(monkeypatch, connection)
    finding = _finding(evidence=[
        {"entity_type": "SETTLEMENT_HEADER", "entity_id": "BATCH-10"},
        {"entity_type": "BANK_TRANSACTION", "entity_id": "BANK-10"},
    ])

    first = reconciliation_persistence.persist_reconciliation_finding(finding)
    connection.evidence.remove((
        finding["finding_id"], "BANK_TRANSACTION", "BANK-10", "RELATED_ENTITY",
    ))
    second = reconciliation_persistence.persist_reconciliation_finding(finding)

    assert first["finding_inserted"] is True
    assert second["finding_inserted"] is False
    assert second["evidence_inserted_count"] == 1
    assert len(connection.finding_inserts) == 1
    assert len(connection.evidence_inserts) == 3


def test_failed_finding_rolls_back_without_undoing_other_finding_commits(monkeypatch):
    connection = FakeConnection(fail_entity_ids={"BANK-FAIL"})
    _patch_connection(monkeypatch, connection)

    first = reconciliation_persistence.persist_reconciliation_finding(
        _finding(finding_id="FND-FIRST", evidence=[
            {"entity_type": "BANK_TRANSACTION", "entity_id": "BANK-FIRST"},
        ])
    )
    failed = reconciliation_persistence.persist_reconciliation_finding(
        _finding(finding_id="FND-FAIL", evidence=[
            {"entity_type": "BANK_TRANSACTION", "entity_id": "BANK-FAIL"},
        ])
    )
    third = reconciliation_persistence.persist_reconciliation_finding(
        _finding(finding_id="FND-THIRD", evidence=[
            {"entity_type": "BANK_TRANSACTION", "entity_id": "BANK-THIRD"},
        ])
    )

    assert first["finding_committed"] is True
    assert failed["persistence_error"]["code"] == "DATABASE_PERSISTENCE_ERROR"
    assert failed["connection_usable"] is True
    assert third["finding_committed"] is True
    assert set(connection.findings) == {"FND-FIRST", "FND-THIRD"}
    assert {item[2] for item in connection.evidence} == {"BANK-FIRST", "BANK-THIRD"}
    assert connection.commits == 2
    assert connection.rollbacks == 1


def test_evidence_failure_rolls_back_finding_insert(monkeypatch):
    connection = FakeConnection(fail_on_evidence_insert=True)
    _patch_connection(monkeypatch, connection)

    result = reconciliation_persistence.persist_reconciliation_finding(_finding())

    assert result["persistence_error"]["code"] == "DATABASE_PERSISTENCE_ERROR"
    assert connection.rollbacks == 1
    assert connection.commits == 0
    assert connection.findings == {}
    assert connection.closed


def test_connection_level_persistence_failure_marks_shared_connection_unusable(monkeypatch):
    connection = FakeConnection(fail_on_connection=True)
    monkeypatch.setattr(
        reconciliation_persistence,
        "get_analytics_connection",
        lambda **kwargs: pytest.fail("shared connection should be reused"),
    )

    result = reconciliation_persistence.persist_reconciliation_finding(
        _finding(), connection=connection
    )

    assert result["persistence_error"]["code"] == "CONNECTION_ERROR"
    assert result["connection_usable"] is False
    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_source_row_lineage_is_summary_only_not_finding_evidence(monkeypatch):
    connection = FakeConnection()
    _patch_connection(monkeypatch, connection)
    finding = _finding(
        evidence=[{"entity_type": "PROCESSOR_TRANSACTION", "entity_id": "PTX-1"}],
        source_row_lineage=[{"SOURCE_ROW_ID": "ROW-1", "PROCESSOR_TXN_ID": "PTX-1"}],
    )

    reconciliation_persistence.persist_reconciliation_finding(finding)

    summary = json.loads(connection.finding_inserts[0]["evidence_summary"])
    assert summary["source_row_lineage"][0]["SOURCE_ROW_ID"] == "ROW-1"
    assert {evidence["entity_id"] for evidence in connection.evidence_inserts} == {"PTX-1"}
    assert all(evidence["entity_id"] != "ROW-1" for evidence in connection.evidence_inserts)


def test_analytics_connection_forwards_autocommit_setting(monkeypatch, tmp_path):
    calls = {}
    config = tmp_path / "exasol.env"
    config.write_text(
        "EXASOL_HOST=127.0.0.1\nEXASOL_PORT=8563\n"
        "EXASOL_USER=sys\nEXASOL_PASSWORD=unit-test-password\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(analytics_connection, "DEFAULT_CONFIG_PATH", config)
    monkeypatch.setattr(
        analytics_connection.pyexasol, "connect",
        lambda **kwargs: calls.update(kwargs) or object(),
    )

    analytics_connection.get_analytics_connection(autocommit=False)

    assert calls["autocommit"] is False


def test_runner_attempts_to_persist_each_finding_type(monkeypatch):
    from scripts import run_reconciliation

    findings = [
        {"finding_id": f"FND-{index}", "finding_type": kind, "classification": classification}
        for index, (kind, classification) in enumerate([
            ("ORDER_ATTEMPT_LINK", "ATTEMPT_REFERENCES_UNKNOWN_ORDER"),
            ("PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION", "PROCESSOR_AMOUNT_DISCREPANCY"),
            ("PROCESSOR_SETTLEMENT_RECONCILIATION", "PROCESSOR_TRANSACTION_MISSING_FROM_SETTLEMENT"),
            ("SETTLEMENT_FINANCIAL_RECONCILIATION", "SETTLEMENT_AMOUNT_MISMATCH"),
            ("SETTLEMENT_BANK_RECONCILIATION", "UNVERIFIED"),
            ("SETTLEMENT_TIMING_RECONCILIATION", "CONFIRMED_LATE"),
        ])
    ]
    runner_connection = FakeConnection()
    connection_factory_calls = []
    monkeypatch.setattr(
        run_reconciliation,
        "get_analytics_connection",
        lambda autocommit=False: connection_factory_calls.append(autocommit) or runner_connection,
    )
    monkeypatch.setattr(
        run_reconciliation,
        "fetch_order_attempt_data",
        lambda connection=None: ([], [], [], [], [], [], []),
    )
    monkeypatch.setattr(
        run_reconciliation,
        "reconcile_orders_attempts_processor_and_settlement",
        lambda *args: {"findings": findings},
    )
    calls = []

    def persist(finding, connection=None):
        assert connection is runner_connection
        calls.append(finding["finding_id"])
        return {
            "finding_inserted": True,
            "evidence_inserted": True,
            "persistence_error": None,
        }

    monkeypatch.setattr(run_reconciliation, "persist_reconciliation_finding", persist)

    summary = run_reconciliation.run_reconciliation()

    assert calls == [finding["finding_id"] for finding in findings]
    assert summary["findings_persisted"] == len(findings)
    assert summary["persistence_errors"] == []
    assert connection_factory_calls == [False]
    assert runner_connection.closed


def test_runner_continues_after_structured_persistence_error(monkeypatch):
    from scripts import run_reconciliation

    findings = [
        {"finding_id": "FND-FIRST", "finding_type": "TYPE", "classification": "FIRST"},
        {"finding_id": "FND-ERROR", "finding_type": "TYPE", "classification": "ERROR"},
        {"finding_id": "FND-THIRD", "finding_type": "TYPE", "classification": "THIRD"},
    ]
    persistence_error = {
        "code": "INVALID_FINDING",
        "message": "The finding cannot be represented safely.",
        "finding_id": "FND-ERROR",
    }
    runner_connection = FakeConnection()
    monkeypatch.setattr(
        run_reconciliation,
        "get_analytics_connection",
        lambda autocommit=False: runner_connection,
    )
    monkeypatch.setattr(
        run_reconciliation,
        "fetch_order_attempt_data",
        lambda connection=None: ([], [], [], [], [], [], []),
    )
    monkeypatch.setattr(
        run_reconciliation,
        "reconcile_orders_attempts_processor_and_settlement",
        lambda *args: {"findings": findings},
    )
    calls = []

    def persist(finding, connection=None):
        assert connection is runner_connection
        calls.append(finding["finding_id"])
        if finding["finding_id"] == "FND-ERROR":
            return {
                "finding_inserted": False,
                "evidence_inserted": False,
                "persistence_error": persistence_error,
            }
        return {
            "finding_inserted": True,
            "evidence_inserted": True,
            "persistence_error": None,
        }

    monkeypatch.setattr(run_reconciliation, "persist_reconciliation_finding", persist)

    summary = run_reconciliation.run_reconciliation()

    assert calls == ["FND-FIRST", "FND-ERROR", "FND-THIRD"]
    assert summary["persistence_errors"] == [persistence_error]
    assert summary["findings_generated"] == 3
    assert summary["findings_persisted"] == 2
    assert summary["findings_already_existing"] == 0
    assert runner_connection.closed


def test_runner_stops_after_connection_becomes_unusable(monkeypatch):
    from scripts import run_reconciliation

    findings = [
        {"finding_id": "FND-FIRST", "finding_type": "TYPE", "classification": "FIRST"},
        {"finding_id": "FND-CONNECTION", "finding_type": "TYPE", "classification": "CONNECTION"},
        {"finding_id": "FND-THIRD", "finding_type": "TYPE", "classification": "THIRD"},
    ]
    runner_connection = FakeConnection()
    monkeypatch.setattr(
        run_reconciliation,
        "get_analytics_connection",
        lambda autocommit=False: runner_connection,
    )
    monkeypatch.setattr(
        run_reconciliation,
        "fetch_order_attempt_data",
        lambda connection=None: ([], [], [], [], [], [], []),
    )
    monkeypatch.setattr(
        run_reconciliation,
        "reconcile_orders_attempts_processor_and_settlement",
        lambda *args: {"findings": findings},
    )
    calls = []

    def persist(finding, connection=None):
        calls.append(finding["finding_id"])
        if finding["finding_id"] == "FND-CONNECTION":
            return {
                "finding_inserted": False,
                "evidence_inserted": False,
                "finding_committed": False,
                "connection_usable": False,
                "persistence_error": {
                    "code": "CONNECTION_ERROR",
                    "message": "Connection lost.",
                    "finding_id": "FND-CONNECTION",
                },
            }
        return {
            "finding_inserted": True,
            "evidence_inserted": True,
            "finding_committed": True,
            "connection_usable": True,
            "persistence_error": None,
        }

    monkeypatch.setattr(run_reconciliation, "persist_reconciliation_finding", persist)

    summary = run_reconciliation.run_reconciliation()

    assert calls == ["FND-FIRST", "FND-CONNECTION"]
    assert summary["findings_persisted"] == 1
    assert summary["persistence_errors"][0]["code"] == "CONNECTION_ERROR"
    assert summary["findings_not_attempted"] == ["FND-THIRD"]
    assert runner_connection.closed


def test_runner_closes_connection_after_unexpected_failure(monkeypatch):
    from scripts import run_reconciliation

    runner_connection = FakeConnection()
    monkeypatch.setattr(
        run_reconciliation,
        "get_analytics_connection",
        lambda autocommit=False: runner_connection,
    )
    monkeypatch.setattr(
        run_reconciliation,
        "fetch_order_attempt_data",
        lambda connection=None: ([], [], [], [], [], [], []),
    )
    monkeypatch.setattr(
        run_reconciliation,
        "reconcile_orders_attempts_processor_and_settlement",
        lambda *args: (_ for _ in ()).throw(RuntimeError("engine failure")),
    )

    with pytest.raises(RuntimeError, match="engine failure"):
        run_reconciliation.run_reconciliation()

    assert runner_connection.closed


def test_runner_preserves_persistence_errors_if_connection_close_fails(monkeypatch):
    from scripts import run_reconciliation

    finding = {"finding_id": "FND-ERROR", "finding_type": "TYPE", "classification": "ERROR"}
    runner_connection = FakeConnection(fail_on_close=True)
    monkeypatch.setattr(
        run_reconciliation,
        "get_analytics_connection",
        lambda autocommit=False: runner_connection,
    )
    monkeypatch.setattr(
        run_reconciliation,
        "fetch_order_attempt_data",
        lambda connection=None: ([], [], [], [], [], [], []),
    )
    monkeypatch.setattr(
        run_reconciliation,
        "reconcile_orders_attempts_processor_and_settlement",
        lambda *args: {"findings": [finding]},
    )
    persistence_error = {
        "code": "INVALID_FINDING",
        "message": "Not safely representable.",
        "finding_id": "FND-ERROR",
    }
    monkeypatch.setattr(
        run_reconciliation,
        "persist_reconciliation_finding",
        lambda *args, **kwargs: {
            "finding_inserted": False,
            "evidence_inserted": False,
            "connection_usable": True,
            "persistence_error": persistence_error,
        },
    )

    summary = run_reconciliation.run_reconciliation()

    assert summary["persistence_errors"] == [persistence_error]
    assert summary["cleanup_errors"] == [{
        "code": "CONNECTION_CLOSE_ERROR",
        "message": "The reconciliation connection did not close cleanly.",
    }]
