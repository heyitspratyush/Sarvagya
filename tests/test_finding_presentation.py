import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from scripts.finding_presentation import (
    CLASSIFICATIONS,
    format_amount,
    format_date,
    present_finding,
    summarize_findings,
)
from scripts import inspect_reconciliation_state


@pytest.mark.parametrize("classification", sorted(CLASSIFICATIONS))
def test_every_engine_classification_has_a_readable_finding(classification):
    item = present_finding({
        "finding_id": "FND-0123456789012345678901234567890123456789",
        "finding_type": "UNKNOWN_TYPE",
        "classification": classification,
        "resolution_status": "UNRESOLVED",
        "evidence": [],
    })
    assert item["title"]
    assert item["explanation"]
    assert item["suggested_checks"]
    assert classification not in item["title"]
    assert item["finding_reference"].startswith("FND-")
    assert item["finding_reference"].startswith(item["short_finding_reference"])
    assert item["technical_details"]["finding_id"].endswith("6789")


def test_alias_recovers_original_classification_only_from_payload():
    stored = {
        "FINDING_ID": "FND-full-id",
        "FINDING_TYPE": "PROCESSOR_SETTLEMENT_RECONCILIATION",
        "CLASSIFICATION": "CLS-1234",
        "RESOLUTION_STATUS": "UNRESOLVED",
        "EVIDENCE_SUMMARY": json.dumps({
            "classification": "PROCESSOR_TRANSACTION_MISSING_FROM_SETTLEMENT",
            "evidence": [{"entity_type": "PROCESSOR_TRANSACTION", "entity_id": "PTX-1"}],
            "limitation": "No settlement link was available.",
        }),
    }
    item = present_finding(stored)
    assert item["classification"] == "PROCESSOR_TRANSACTION_MISSING_FROM_SETTLEMENT"
    assert item["technical_details"]["stored_classification"] == "CLS-1234"
    assert item["technical_details"]["original_classification"] == item["classification"]
    assert item["references"] == [{"label": "Processor Transaction", "value": "PTX-1"}]


def test_missing_original_classification_does_not_guess_from_alias():
    item = present_finding({
        "FINDING_ID": "FND-1",
        "FINDING_TYPE": "PROCESSOR_SETTLEMENT_RECONCILIATION",
        "CLASSIFICATION": "CLS-not-recoverable",
        "EVIDENCE_SUMMARY": '{"finding_id":"FND-1"}',
    })
    assert item["classification"] == "CLS-not-recoverable"
    assert item["title"] == "Reconciliation finding needs review"


def test_malformed_summary_keeps_record_and_reports_parse_problem():
    item = present_finding({
        "FINDING_ID": "FND-malformed",
        "FINDING_TYPE": "SETTLEMENT_FINANCIAL_RECONCILIATION",
        "CLASSIFICATION": "SETTLEMENT_AMOUNT_MISMATCH",
        "RESOLUTION_STATUS": "UNRESOLVED",
        "EXPECTED_AMOUNT": Decimal("915.00"),
        "OBSERVED_AMOUNT": Decimal("925.00"),
        "DIFFERENCE_AMOUNT": Decimal("-10.00"),
        "CURRENCY": "INR",
        "EVIDENCE_SUMMARY": '{broken',
    })
    assert item["expected_amount"] == Decimal("915.00")
    assert item["observed_amount"] == Decimal("925.00")
    assert item["difference"] == Decimal("-10.00")
    assert item["limitations"] == ["Stored finding summary is not valid JSON."]
    assert item["technical_details"]["evidence_summary"] == "{broken"


@pytest.mark.parametrize(("value", "expected"), [
    (Decimal("0"), "₹0.00"),
    (Decimal("0.00"), "₹0.00"),
    (Decimal("9.99"), "₹9.99"),
    (Decimal("999.99"), "₹999.99"),
    (Decimal("1000"), "₹1,000.00"),
    (Decimal("10000"), "₹10,000.00"),
    (Decimal("100000"), "₹1,00,000.00"),
    (Decimal("1000000"), "₹10,00,000.00"),
    (Decimal("12345678.9"), "₹1,23,45,678.90"),
    (Decimal("-10"), "-₹10.00"),
    (Decimal("-100000"), "-₹1,00,000.00"),
    (Decimal("-12345678.9"), "-₹1,23,45,678.90"),
    (None, "Not available"),
    (10.1, "Not available"),
])
def test_indian_amount_formatting_preserves_zero_and_sign(value, expected):
    assert format_amount(value, "INR") == expected


def test_difference_sign_conventions_are_described_without_recalculation():
    settlement = present_finding({
        "finding_type": "SETTLEMENT_FINANCIAL_RECONCILIATION",
        "classification": "SETTLEMENT_AMOUNT_MISMATCH",
        "expected_net_amount": Decimal("915.00"),
        "reported_net_amount": Decimal("925.00"),
        "discrepancy": Decimal("-10.00"),
        "currency": "INR",
        "gross_amount": Decimal("1000.00"),
        "fee_amount": Decimal("50.00"),
        "refund_amount": Decimal("20.00"),
        "chargeback_amount": Decimal("0.00"),
        "adjustment_amount": Decimal("-15.00"),
    })
    assert settlement["difference"] == Decimal("-10.00")
    assert settlement["difference_convention"] == "Expected net minus reported net"
    assert [part["display"] for part in settlement["financial_components"]] == [
        "₹1,000.00", "₹50.00", "₹20.00", "₹0.00", "-₹15.00",
    ]
    processor = present_finding({
        "finding_type": "PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION",
        "classification": "PROCESSOR_AMOUNT_DISCREPANCY",
        "expected_amount": Decimal("100"),
        "observed_amount": Decimal("90"),
        "difference_amount": Decimal("-10"),
        "currency": "INR",
    })
    assert processor["difference"] == Decimal("-10")
    assert processor["difference_convention"] == "Observed amount minus expected amount"


def test_null_fields_missing_evidence_and_unknown_classification_are_safe():
    item = present_finding({
        "finding_id": "FND-long-reference-000000000000000000000000000000000000",
        "finding_type": "NEW_FINDING_TYPE",
        "classification": "FUTURE_CLASSIFICATION",
        "expected_amount": None,
        "observed_amount": None,
        "evidence": None,
    })
    assert item["expected_amount_display"] == "Not available"
    assert item["observed_amount_display"] == "Not available"
    assert item["evidence"] == []
    assert item["references"] == []
    assert item["technical_details"]["finding_id"].startswith("FND-long-reference")
    assert item["short_finding_reference"].startswith("FND-long-ref")


def test_ambiguous_bank_candidates_are_preserved_individually():
    item = present_finding({
        "finding_type": "SETTLEMENT_BANK_RECONCILIATION",
        "classification": "AMBIGUOUS_BANK_REFERENCE",
        "batch_id": "BATCH-1",
        "bank_candidates": [
            {"BANK_TXN_ID": "BANK-1", "AMOUNT": Decimal("100")},
            {"BANK_TXN_ID": "BANK-2", "AMOUNT": Decimal("100")},
        ],
        "bank_transaction_ids": ["BANK-1", "BANK-2"],
    })
    assert len(item["candidates"]) == 2
    assert [candidate["BANK_TXN_ID"] for candidate in item["candidates"]] == ["BANK-1", "BANK-2"]
    assert "has not selected one arbitrarily" in item["explanation"]


def test_detail_render_shows_each_bank_candidate_inr_formatted(capsys):
    item = present_finding({
        "finding_id": "FND-1",
        "finding_type": "SETTLEMENT_BANK_RECONCILIATION",
        "classification": "AMBIGUOUS_BANK_REFERENCE",
        "currency": "INR",
        "bank_candidates": [
            {"BANK_TXN_ID": "BANK-1", "AMOUNT": Decimal("1000.00"), "CURRENCY": "INR"},
            {"BANK_TXN_ID": "BANK-2", "AMOUNT": Decimal("1000.00"), "CURRENCY": "INR"},
        ],
    })
    inspect_reconciliation_state._print_finding_detail(item)
    output = capsys.readouterr().out
    assert "Candidate 1: Bank transaction: BANK-1; Amount: ₹1,000.00" in output
    assert "Candidate 2: Bank transaction: BANK-2; Amount: ₹1,000.00" in output


def test_detail_render_labels_evidence_in_plain_language(capsys):
    item = present_finding({
        "finding_id": "FND-1",
        "finding_type": "PROCESSOR_SETTLEMENT_RECONCILIATION",
        "classification": "PROCESSOR_TRANSACTION_MISSING_FROM_SETTLEMENT",
        "evidence": [{
            "entity_type": "PROCESSOR_TRANSACTION",
            "entity_id": "PTX-1",
            "evidence_role": "RELATED_ENTITY",
        }],
    })
    inspect_reconciliation_state._print_finding_detail(item)
    output = capsys.readouterr().out
    assert "Processor Transaction: PTX-1; Role: Related Entity" in output
    assert "entity_type=" not in output


def test_findings_view_has_clear_empty_state_and_uses_only_select(capsys):
    class Statement:
        def __init__(self, columns, rows):
            self._columns = columns
            self._rows = rows

        def column_names(self):
            return self._columns

        def fetchall(self):
            return self._rows

    class ReadOnlyConnection:
        def __init__(self):
            self.queries = []

        def execute(self, query):
            self.queries.append(query.strip())
            if "FROM SARVAGYA.FINDING_EVIDENCE" in query:
                return Statement(("FINDING_ID", "ENTITY_TYPE", "ENTITY_ID", "EVIDENCE_ROLE"), [])
            return Statement(("FINDING_ID", "FINDING_TYPE", "CLASSIFICATION", "RESOLUTION_STATUS", "EXPECTED_AMOUNT", "OBSERVED_AMOUNT", "DIFFERENCE_AMOUNT", "CURRENCY", "EVIDENCE_SUMMARY", "LIMITATION", "EXPECTED_AT", "OBSERVED_AT", "DELAY_MINUTES"), [])

    connection = ReadOnlyConnection()
    assert inspect_reconciliation_state._render_findings(connection) == 0
    output = capsys.readouterr().out
    assert "No persisted findings are available." in output
    assert connection.queries
    assert all(query.startswith("SELECT") for query in connection.queries)


def test_dates_delay_and_source_lineage_are_preserved():
    item = present_finding({
        "finding_type": "SETTLEMENT_TIMING_RECONCILIATION",
        "classification": "CONFIRMED_LATE",
        "expected_settlement_date": date(2026, 10, 21),
        "actual_settlement_timestamp": datetime(2026, 10, 23, 12, 0),
        "delay_days": 2,
        "source_row_lineage": [{"SOURCE_ROW_ID": "ROW-1"}],
    })
    assert item["expected_date_display"] == "21 Oct 2026"
    assert item["actual_date_display"] == "23 Oct 2026, 12:00:00"
    assert item["delay_days"] == 2
    assert item["source_row_lineage"] == [{"SOURCE_ROW_ID": "ROW-1"}]
    assert format_date(None) == "Not available"


def test_overview_keeps_timing_and_amount_counts_separate_and_handles_empty():
    assert summarize_findings([]) == {
        "total_findings": 0,
        "unresolved_findings": 0,
        "confirmed_late_settlements": 0,
        "on_time_settlements": 0,
        "settlement_amount_discrepancies": 0,
        "bank_amount_discrepancies": 0,
        "unverified_settlements": 0,
        "findings_by_layer": {},
    }
    summary = summarize_findings([
        {"finding_type": "SETTLEMENT_TIMING_RECONCILIATION", "classification": "CONFIRMED_LATE", "resolution_status": "RESOLVED"},
        {"finding_type": "SETTLEMENT_FINANCIAL_RECONCILIATION", "classification": "SETTLEMENT_AMOUNT_MISMATCH", "resolution_status": "UNRESOLVED"},
    ])
    assert summary["confirmed_late_settlements"] == 1
    assert summary["settlement_amount_discrepancies"] == 1
    assert summary["unresolved_findings"] == 1
    assert summary["findings_by_layer"] == {"Settlement amounts": 1, "Settlement timing": 1}
