from copy import deepcopy
from decimal import Decimal

import pytest

from scripts.reconciliation_engine import (
    build_order_lookup,
    group_attempts_by_order,
    make_unlinked_attempt_finding,
    reconcile_attempts_to_processor,
    reconcile_orders_attempts_and_processor,
    reconcile_orders_attempts_processor_and_settlement,
    reconcile_processor_to_settlement,
    calculate_settlement_amounts,
    reconcile_settlement_financials,
    reconcile_settlement_to_bank,
    reconcile_settlement_timing,
)


def test_groups_multiple_attempts_for_one_order():
    orders = [
        {"ORDER_ID": "ORD-101"},
        {"ORDER_ID": "ORD-102"},
    ]
    orders_by_id = build_order_lookup(orders)

    attempts = [
        {"ATTEMPT_ID": "ATT-101", "ORDER_ID": "ORD-101"},
        {"ATTEMPT_ID": "ATT-102", "ORDER_ID": "ORD-101"},
    ]

    grouped, unlinked = group_attempts_by_order(orders_by_id, attempts)

    assert len(grouped["ORD-101"]) == 2
    assert grouped["ORD-102"] == []
    assert unlinked == []


def test_preserves_attempt_with_unknown_order():
    orders_by_id = build_order_lookup([{"ORDER_ID": "ORD-101"}])
    attempts = [{"ATTEMPT_ID": "ATT-999", "ORDER_ID": "ORD-999"}]

    grouped, unlinked = group_attempts_by_order(orders_by_id, attempts)

    assert grouped["ORD-101"] == []
    assert [item["ATTEMPT_ID"] for item in unlinked] == ["ATT-999"]


def test_duplicate_order_id_raises_error():
    orders = [
        {"ORDER_ID": "ORD-101"},
        {"ORDER_ID": "ORD-101"},
    ]

    try:
        build_order_lookup(orders)
    except ValueError as error:
        assert str(error) == "Duplicate order ID: ORD-101"
    else:
        raise AssertionError("Expected duplicate order ID to be rejected")


def test_unlinked_finding_preserves_observed_amount():
    attempt = {
        "ATTEMPT_ID": "ATT-999",
        "ORDER_ID": "ORD-999",
        "ATTEMPT_STATUS": "SUCCESS",
        "ATTEMPT_AMOUNT": "500.00",
    }

    finding = make_unlinked_attempt_finding(attempt)

    assert finding["classification"] == "ATTEMPT_REFERENCES_UNKNOWN_ORDER"
    assert finding["resolution_status"] == "UNRESOLVED"
    assert finding["expected_amount"] is None
    assert finding["observed_amount"] == "500.00"
    assert finding["difference_amount"] is None


def _sample_records():
    orders = [{"ORDER_ID": "ORD-1", "ORDER_AMOUNT": "100.00", "CURRENCY": "INR"}]
    attempts = [{"ATTEMPT_ID": "ATT-1", "ORDER_ID": "ORD-1", "MERCHANT_PAYMENT_REF": "REF-1", "ATTEMPT_AMOUNT": "100.00", "ATTEMPT_STATUS": "SUCCESS"}]
    transactions = [{"PROCESSOR_TXN_ID": "PTX-1", "ORDER_ID": "ORD-1", "MERCHANT_PAYMENT_REF": "REF-1", "TRANSACTION_AMOUNT": "100.00", "CURRENCY": "INR", "TRANSACTION_STATUS": "CAPTURED"}]
    return orders, attempts, transactions


def test_processor_normal_match_uses_explicit_references():
    orders, attempts, transactions = _sample_records()
    result = reconcile_attempts_to_processor(orders, attempts, transactions)
    assert result["processor_candidates_by_attempt"]["ATT-1"] == transactions
    assert result["findings"] == []


def test_processor_missing_transaction_candidate():
    orders, attempts, _ = _sample_records()
    result = reconcile_attempts_to_processor(orders, attempts, [])
    finding, = result["findings"]
    assert finding["classification"] == "NO_PROCESSOR_TRANSACTION_CANDIDATE"
    assert finding["processor_transaction_id"] is None


def test_processor_ambiguous_candidates_are_preserved():
    orders, attempts, transactions = _sample_records()
    duplicate = {**transactions[0], "PROCESSOR_TXN_ID": "PTX-2"}
    result = reconcile_attempts_to_processor(orders, attempts, transactions + [duplicate])
    finding, = result["findings"]
    assert finding["classification"] == "MULTIPLE_PROCESSOR_TRANSACTION_CANDIDATES"
    assert finding["processor_transaction_ids"] == ["PTX-1", "PTX-2"]
    assert finding["processor_transaction_id"] is None


def test_processor_amount_discrepancy_uses_decimal_signed_difference():
    orders, attempts, transactions = _sample_records()
    transactions[0]["TRANSACTION_AMOUNT"] = "115.25"
    finding, = reconcile_attempts_to_processor(orders, attempts, transactions)["findings"]
    assert finding["classification"] == "PROCESSOR_AMOUNT_DISCREPANCY"
    assert finding["difference_amount"] == Decimal("15.25")


def test_processor_currency_discrepancy():
    orders, attempts, transactions = _sample_records()
    transactions[0]["CURRENCY"] = "USD"
    finding, = reconcile_attempts_to_processor(orders, attempts, transactions)["findings"]
    assert finding["classification"] == "PROCESSOR_CURRENCY_DISCREPANCY"
    assert finding["expected_currency"] == "INR"
    assert finding["observed_currency"] == "USD"


def test_success_attempt_without_captured_processor_evidence_is_unresolved():
    orders, attempts, transactions = _sample_records()
    transactions[0]["TRANSACTION_STATUS"] = "SUCCESS"
    finding, = reconcile_attempts_to_processor(orders, attempts, transactions)["findings"]
    assert finding["classification"] == "COLLECTION_EVIDENCE_MISSING"
    assert finding["collection_confirmed"] is False


def test_source_row_lineage_is_separate_from_reconciliation_evidence():
    orders, attempts, transactions = _sample_records()
    lineage = [{"SOURCE_ROW_ID": "ROW-1", "PROCESSOR_TXN_ID": "PTX-1", "SOURCE_FILE": "x.csv", "SOURCE_ROW_NUMBER": 3}]
    result = reconcile_orders_attempts_and_processor(orders, attempts, transactions, lineage)
    assert result["processor_source_rows_by_transaction"]["PTX-1"] == lineage
    assert result["findings"] == []


def test_order_only_processor_reference_is_ambiguous_across_attempts():
    orders, attempts, transactions = _sample_records()
    attempts.append({
        "ATTEMPT_ID": "ATT-2", "ORDER_ID": "ORD-1",
        "MERCHANT_PAYMENT_REF": "REF-2", "ATTEMPT_AMOUNT": "100.00",
        "ATTEMPT_STATUS": "SUCCESS",
    })
    transactions[0]["MERCHANT_PAYMENT_REF"] = None

    result = reconcile_attempts_to_processor(orders, attempts, transactions)

    assert result["processor_candidates_by_attempt"]["ATT-1"] == transactions
    assert result["processor_candidates_by_attempt"]["ATT-2"] == transactions
    assert [item["classification"] for item in result["findings"]] == [
        "MULTIPLE_PAYMENT_ATTEMPT_CANDIDATES",
        "MULTIPLE_PAYMENT_ATTEMPT_CANDIDATES",
    ]
    assert all(item["resolution_status"] == "UNRESOLVED" for item in result["findings"])
    assert all(item["candidate_attempt_ids"] == ["ATT-1", "ATT-2"] for item in result["findings"])
    assert all(
        {"entity_type": "PROCESSOR_TRANSACTION", "entity_id": "PTX-1"} in item["evidence"]
        for item in result["findings"]
    )


def test_unknown_processor_reference_does_not_resolve_attempt_missing_reference():
    orders, attempts, transactions = _sample_records()
    attempts[0]["MERCHANT_PAYMENT_REF"] = None
    attempts.append({
        "ATTEMPT_ID": "ATT-2", "ORDER_ID": "ORD-1",
        "MERCHANT_PAYMENT_REF": "REF-2", "ATTEMPT_AMOUNT": "100.00",
        "ATTEMPT_STATUS": "SUCCESS",
    })
    transactions[0]["MERCHANT_PAYMENT_REF"] = "REF-UNKNOWN"

    result = reconcile_attempts_to_processor(orders, attempts, transactions)

    ambiguous, = [
        finding for finding in result["findings"]
        if finding["classification"] == "MULTIPLE_PAYMENT_ATTEMPT_CANDIDATES"
    ]
    assert ambiguous["attempt_id"] == "ATT-1"
    assert ambiguous["candidate_attempt_ids"] == ["ATT-1", "ATT-2"]
    assert ambiguous["processor_transaction_ids"] == ["PTX-1"]
    assert ambiguous["processor_transaction_id"] is None
    assert ambiguous["observed_amount"] is None
    assert ambiguous["difference_amount"] is None
    assert {"entity_type": "PROCESSOR_TRANSACTION", "entity_id": "PTX-1"} in ambiguous["evidence"]


def test_processor_reference_identifies_explicit_attempt_not_sibling_missing_reference():
    orders, attempts, transactions = _sample_records()
    attempts[0]["MERCHANT_PAYMENT_REF"] = None
    attempts[0]["ATTEMPT_AMOUNT"] = "115.25"
    attempts.append({
        "ATTEMPT_ID": "ATT-2", "ORDER_ID": "ORD-1",
        "MERCHANT_PAYMENT_REF": "REF-1", "ATTEMPT_AMOUNT": "100.00",
        "ATTEMPT_STATUS": "SUCCESS",
    })
    transactions[0]["TRANSACTION_AMOUNT"] = "115.25"

    result = reconcile_attempts_to_processor(orders, attempts, transactions)

    assert result["processor_candidates_by_attempt"]["ATT-1"] == []
    assert result["processor_candidates_by_attempt"]["ATT-2"] == transactions
    findings_by_attempt = {
        finding["attempt_id"]: finding for finding in result["findings"]
    }
    assert findings_by_attempt["ATT-1"]["classification"] == "NO_PROCESSOR_TRANSACTION_CANDIDATE"
    assert findings_by_attempt["ATT-2"]["classification"] == "PROCESSOR_AMOUNT_DISCREPANCY"
    assert findings_by_attempt["ATT-2"]["difference_amount"] == Decimal("15.25")


def test_conflicting_merchant_reference_rules_out_order_id_candidate():
    orders, attempts, transactions = _sample_records()
    transactions[0]["MERCHANT_PAYMENT_REF"] = "OTHER-REF"
    result = reconcile_attempts_to_processor(orders, attempts, transactions)

    assert result["processor_candidates_by_attempt"]["ATT-1"] == []
    assert result["findings"][0]["classification"] == "NO_PROCESSOR_TRANSACTION_CANDIDATE"


def _settlement_records(transaction_at="2026-10-20 10:02:00"):
    processor = [{
        "PROCESSOR_TXN_ID": "PTX-1", "TRANSACTION_AMOUNT": "90.00",
        "CURRENCY": "INR", "TRANSACTION_STATUS": "CAPTURED",
        "TRANSACTION_AT": transaction_at,
    }]
    source_rows = [{
        "SOURCE_ROW_ID": "ROW-1", "PROCESSOR_TXN_ID": "PTX-1",
        "SOURCE_FILE": "processor.csv", "SOURCE_ROW_NUMBER": 4,
    }]
    settlements = [{
        "BATCH_ID": "BATCH-20261020", "GROSS_AMOUNT": "90.00",
        "EXPECTED_SETTLEMENT_DATE": "2026-10-21",
    }]
    entries = [{"BATCH_ID": "BATCH-20261020", "PROCESSOR_TXN_ID": "PTX-1"}]
    return processor, source_rows, settlements, entries


def test_processor_transaction_matches_settlement_by_exact_transaction_id():
    processor, rows, settlements, entries = _settlement_records()
    result = reconcile_processor_to_settlement(processor, rows, settlements, entries)

    assert result["settlement_entries_by_processor_transaction"]["PTX-1"] == entries
    assert result["findings"] == []
    assert result["settlements_by_batch"]["BATCH-20261020"] == settlements[0]


def test_processor_transaction_missing_from_settlement_entry():
    processor, rows, settlements, _ = _settlement_records()
    result = reconcile_processor_to_settlement(processor, rows, settlements, [])

    finding, = result["findings"]
    assert finding["classification"] == "PROCESSOR_TRANSACTION_MISSING_FROM_SETTLEMENT"
    assert finding["processor_transaction_ids"] == ["PTX-1"]
    assert finding["source_row_lineage"] == rows
    assert all(item["entity_type"] != "PROCESSOR_SOURCE_ROW" for item in finding["evidence"])


def test_settlement_entry_without_supported_processor_transaction():
    processor, rows, settlements, entries = _settlement_records()
    entries[0]["PROCESSOR_TXN_ID"] = "PTX-UNKNOWN"
    result = reconcile_processor_to_settlement(processor, rows, settlements, entries)

    finding = next(
        item for item in result["findings"]
        if item["classification"] == "SETTLEMENT_ENTRY_WITHOUT_PROCESSOR_TRANSACTION"
    )
    assert finding["classification"] == "SETTLEMENT_ENTRY_WITHOUT_PROCESSOR_TRANSACTION"
    assert finding["processor_transaction_ids"] == ["PTX-UNKNOWN"]
    assert finding["batch_ids"] == ["BATCH-20261020"]


def test_wrong_dated_settlement_batch_is_reported():
    processor, rows, settlements, entries = _settlement_records("2026-10-20 16:02:00")
    processor[0]["PROCESSOR_TXN_ID"] = "SL-GT07-PTX"
    entries[0]["PROCESSOR_TXN_ID"] = "SL-GT07-PTX"
    entries[0]["BATCH_ID"] = "SL-GT07-BATCH-20261020"
    settlements[0]["BATCH_ID"] = "SL-GT07-BATCH-20261020"
    result = reconcile_processor_to_settlement(processor, rows, settlements, entries)

    finding, = result["findings"]
    assert finding["classification"] == "PROCESSOR_TRANSACTION_IN_WRONG_SETTLEMENT_BATCH"
    assert finding["actual_batch_id"] == "SL-GT07-BATCH-20261020"
    assert finding["expected_batch_id"] == "SL-GT07-BATCH-20261021"
    assert finding["batch_ids"] == ["SL-GT07-BATCH-20261020"]


def test_cutoff_rule_is_limited_to_gt07_and_gt08_and_keeps_settlement_date():
    processor, rows, settlements, entries = _settlement_records("2026-10-20 16:02:00")
    processor[0]["PROCESSOR_TXN_ID"] = "OTHER-PTX"
    entries[0]["PROCESSOR_TXN_ID"] = "OTHER-PTX"
    result = reconcile_processor_to_settlement(processor, rows, settlements, entries)
    assert result["findings"] == []

    processor, rows, settlements, entries = _settlement_records("2026-10-20 16:02:00")
    processor[0]["PROCESSOR_TXN_ID"] = "SL-GT07-PTX"
    entries[0]["PROCESSOR_TXN_ID"] = "SL-GT07-PTX"
    entries[0]["BATCH_ID"] = "SL-GT07-BATCH-20261020"
    settlements[0]["BATCH_ID"] = "SL-GT07-BATCH-20261020"
    result = reconcile_processor_to_settlement(processor, rows, settlements, entries)

    finding, = result["findings"]
    assert finding["expected_business_date"].isoformat() == "2026-10-21"
    assert finding["settlement"]["EXPECTED_SETTLEMENT_DATE"] == "2026-10-21"
    assert finding["actual_batch_id"] == "SL-GT07-BATCH-20261020"

    processor, rows, settlements, entries = _settlement_records("2026-10-20 10:02:00")
    processor[0]["PROCESSOR_TXN_ID"] = "SL-GT08-PTX"
    entries[0]["PROCESSOR_TXN_ID"] = "SL-GT08-PTX"
    entries[0]["BATCH_ID"] = "SL-GT08-BATCH-20261020"
    settlements[0]["BATCH_ID"] = "SL-GT08-BATCH-20261020"
    result = reconcile_processor_to_settlement(processor, rows, settlements, entries)
    assert result["findings"] == []


def test_duplicate_processor_source_rows_do_not_inflate_transaction_candidates():
    processor, rows, settlements, entries = _settlement_records()
    rows.append({**rows[0], "SOURCE_ROW_ID": "ROW-2", "SOURCE_ROW_NUMBER": 5})
    result = reconcile_processor_to_settlement(processor, rows, settlements, entries)

    assert len(result["settlement_entries_by_processor_transaction"]["PTX-1"]) == 1
    assert result["findings"] == []
    assert {row["SOURCE_ROW_ID"] for row in result["processor_source_rows_by_transaction"]["PTX-1"]} == {"ROW-1", "ROW-2"}


def test_ambiguous_settlement_entries_are_preserved_without_selection():
    processor, rows, settlements, entries = _settlement_records()
    entries.append({"BATCH_ID": "BATCH-20261021", "PROCESSOR_TXN_ID": "PTX-1"})
    result = reconcile_processor_to_settlement(processor, rows, settlements, entries)

    finding, = result["findings"]
    assert finding["classification"] == "AMBIGUOUS_PROCESSOR_SETTLEMENT_REFERENCE"
    assert finding["batch_ids"] == ["BATCH-20261020", "BATCH-20261021"]
    assert len(finding["settlement_transaction_candidates"]) == 2
    assert finding["resolution_status"] == "UNRESOLVED"


def _settlement_header(**overrides):
    settlement = {
        "BATCH_ID": "SL-GT10-BATCH",
        "CURRENCY": "INR",
        "GROSS_AMOUNT": "1000.00",
        "FEE_AMOUNT": "20.00",
        "REFUND_AMOUNT": "50.00",
        "CHARGEBACK_AMOUNT": "10.00",
        "ADJUSTMENT_AMOUNT": "-5.00",
        "REPORTED_NET_AMOUNT": "925.00",
    }
    settlement.update(overrides)
    return settlement


def test_calculate_settlement_amounts_matches_gt10():
    result = calculate_settlement_amounts(_settlement_header())

    assert result["expected_net_amount"] == Decimal("915.00")
    assert result["discrepancy"] == Decimal("-10.00")
    assert result["batch_id"] == "SL-GT10-BATCH"
    assert result["currency"] == "INR"
    assert all(isinstance(result[field], Decimal) for field in (
        "gross_amount", "fee_amount", "refund_amount", "chargeback_amount",
        "adjustment_amount", "expected_net_amount", "reported_net_amount",
        "discrepancy",
    ))


def test_negative_settlement_adjustment_reduces_expected_net():
    with_adjustment = calculate_settlement_amounts(_settlement_header())
    without_adjustment = calculate_settlement_amounts(
        _settlement_header(ADJUSTMENT_AMOUNT="0.00")
    )

    assert with_adjustment["expected_net_amount"] == Decimal("915.00")
    assert without_adjustment["expected_net_amount"] == Decimal("920.00")


def test_calculate_settlement_amounts_zero_discrepancy():
    result = calculate_settlement_amounts(_settlement_header(REPORTED_NET_AMOUNT="915.00"))
    assert result["discrepancy"] == Decimal("0.00")


def test_calculate_settlement_amounts_preserves_positive_discrepancy_sign():
    result = calculate_settlement_amounts(_settlement_header(REPORTED_NET_AMOUNT="900.00"))
    assert result["discrepancy"] == Decimal("15.00")


def test_calculate_settlement_amounts_rejects_missing_monetary_field():
    settlement = _settlement_header()
    del settlement["FEE_AMOUNT"]

    with pytest.raises(ValueError, match="Missing required settlement field: FEE_AMOUNT"):
        calculate_settlement_amounts(settlement)


def test_calculate_settlement_amounts_rejects_invalid_monetary_value():
    with pytest.raises(ValueError, match="Invalid monetary value"):
        calculate_settlement_amounts(_settlement_header(FEE_AMOUNT="not-money"))


def test_calculate_settlement_amounts_rejects_float_input():
    with pytest.raises(TypeError, match="floats"):
        calculate_settlement_amounts(_settlement_header(FEE_AMOUNT=0.1))


def test_calculate_settlement_amounts_does_not_mutate_input():
    settlement = _settlement_header()
    original = deepcopy(settlement)

    calculate_settlement_amounts(settlement)

    assert settlement == original


def test_gt10_settlement_header_creates_batch_amount_mismatch_finding():
    result = reconcile_settlement_financials([_settlement_header()])
    finding, = result["findings"]

    assert finding["classification"] == "SETTLEMENT_AMOUNT_MISMATCH"
    assert finding["layer"] == "SETTLEMENT"
    assert finding["batch_id"] == "SL-GT10-BATCH"
    assert finding["currency"] == "INR"
    assert finding["expected_net_amount"] == Decimal("915.00")
    assert finding["reported_net_amount"] == Decimal("925.00")
    assert finding["discrepancy"] == Decimal("-10.00")
    assert finding["gross_amount"] == Decimal("1000.00")
    assert finding["fee_amount"] == Decimal("20.00")
    assert finding["refund_amount"] == Decimal("50.00")
    assert finding["chargeback_amount"] == Decimal("10.00")
    assert finding["adjustment_amount"] == Decimal("-5.00")
    assert finding["evidence"] == [{"entity_type": "SETTLEMENT_HEADER", "entity_id": "SL-GT10-BATCH"}]
    assert finding["finding_id"]


def test_correct_settlement_batch_creates_no_amount_mismatch():
    result = reconcile_settlement_financials([
        _settlement_header(REPORTED_NET_AMOUNT="915.00")
    ])
    assert result["findings"] == []


def test_positive_settlement_discrepancy_is_expected_minus_reported():
    result = reconcile_settlement_financials([
        _settlement_header(REPORTED_NET_AMOUNT="900.00")
    ])
    finding, = result["findings"]
    assert finding["discrepancy"] == Decimal("15.00")


def test_negative_settlement_discrepancy_is_expected_minus_reported():
    finding, = reconcile_settlement_financials([_settlement_header()])["findings"]
    assert finding["discrepancy"] == Decimal("-10.00")


def test_missing_settlement_component_is_unresolved_and_other_batches_continue():
    incomplete = _settlement_header(BATCH_ID="BATCH-MISSING")
    del incomplete["FEE_AMOUNT"]
    complete = _settlement_header(BATCH_ID="BATCH-COMPLETE")

    result = reconcile_settlement_financials([incomplete, complete])

    unresolved = next(item for item in result["findings"] if item["batch_id"] == "BATCH-MISSING")
    mismatch = next(item for item in result["findings"] if item["batch_id"] == "BATCH-COMPLETE")
    assert unresolved["classification"] == "SETTLEMENT_FINANCIAL_EVIDENCE_INVALID"
    assert unresolved["resolution_status"] == "UNRESOLVED"
    assert "FEE_AMOUNT" in unresolved["limitation"]
    assert unresolved["fee_amount"] is None
    assert mismatch["classification"] == "SETTLEMENT_AMOUNT_MISMATCH"
    assert "BATCH-MISSING" not in result["settlement_financial_calculations"]


def test_invalid_settlement_component_is_unresolved():
    result = reconcile_settlement_financials([
        _settlement_header(FEE_AMOUNT="not-money")
    ])
    finding, = result["findings"]
    assert finding["classification"] == "SETTLEMENT_FINANCIAL_EVIDENCE_INVALID"
    assert finding["resolution_status"] == "UNRESOLVED"
    assert "Invalid monetary value" in finding["limitation"]
    assert finding["fee_amount"] == "not-money"


def test_multiple_settlement_batches_are_calculated_independently():
    first = _settlement_header(BATCH_ID="BATCH-1", CURRENCY="INR")
    second = _settlement_header(
        BATCH_ID="BATCH-2", CURRENCY="USD", REPORTED_NET_AMOUNT="915.00"
    )
    result = reconcile_settlement_financials([first, second])

    assert set(result["settlement_financial_calculations"]) == {"BATCH-1", "BATCH-2"}
    assert [finding["batch_id"] for finding in result["findings"]] == ["BATCH-1"]
    assert result["settlement_financial_calculations"]["BATCH-2"]["currency"] == "USD"


def test_financial_findings_do_not_compare_different_currencies():
    inr = _settlement_header(BATCH_ID="BATCH-INR", CURRENCY="INR")
    usd = _settlement_header(
        BATCH_ID="BATCH-USD", CURRENCY="USD", REPORTED_NET_AMOUNT="915.00"
    )
    result = reconcile_settlement_financials([inr, usd])

    assert len(result["findings"]) == 1
    assert result["findings"][0]["currency"] == "INR"
    assert "BATCH-USD" not in [finding["batch_id"] for finding in result["findings"]]


def test_combined_reconciliation_preserves_identity_findings_and_lineage():
    orders, attempts, processor = _sample_records()
    processor[0]["PROCESSOR_TXN_ID"] = "PTX-SETTLED"
    source_rows = [{
        "SOURCE_ROW_ID": "ROW-SETTLEMENT", "PROCESSOR_TXN_ID": "PTX-SETTLED",
    }]
    settlement = _settlement_header(BATCH_ID="BATCH-FINANCIAL")
    result = reconcile_orders_attempts_processor_and_settlement(
        orders,
        attempts,
        processor,
        source_rows,
        [settlement],
        [],
    )

    assert any(
        finding["classification"] == "PROCESSOR_TRANSACTION_MISSING_FROM_SETTLEMENT"
        for finding in result["findings"]
    )
    financial, = result["settlement_financial_findings"]
    assert financial["classification"] == "SETTLEMENT_AMOUNT_MISMATCH"
    assert result["findings"].count(financial) == 1
    assert result["settlement_findings"][0]["source_row_lineage"] == source_rows
    assert all(
        evidence["entity_type"] != "PROCESSOR_SOURCE_ROW"
        for finding in result["findings"]
        for evidence in finding.get("evidence", [])
    )


def _bank_record(bank_txn_id, reference, amount="925.00", currency="INR", at="2026-10-21 18:30:00"):
    return {
        "BANK_TXN_ID": bank_txn_id,
        "BANK_REFERENCE": reference,
        "AMOUNT": amount,
        "CURRENCY": currency,
        "TRANSACTION_AT": at,
        "DESCRIPTION": "Synthetic payout",
        "SOURCE_FILE": "bank.csv",
    }


def test_gt09_missing_bank_evidence_is_unverified():
    settlement = _settlement_header(BATCH_ID="SL-GT09-BATCH-20261020")
    result = reconcile_settlement_to_bank([settlement], [])
    finding, = result["findings"]

    assert result["bank_reconciliation_by_batch"][settlement["BATCH_ID"]]["status"] == "UNVERIFIED"
    assert finding["classification"] == "UNVERIFIED"
    assert finding["resolution_status"] == "UNRESOLVED"
    assert finding["bank_transaction_ids"] == []
    assert "not failed" not in finding["explanation"].lower()


def test_gt11_bank_amount_mismatch_and_signed_difference():
    settlement = _settlement_header(BATCH_ID="SL-GT11-BATCH", REPORTED_NET_AMOUNT="1000.00")
    bank = _bank_record("SL-GT11-BANK", "SL-GT11-BATCH", amount="990.00")
    result = reconcile_settlement_to_bank([settlement], [bank])
    finding, = result["findings"]

    assert finding["classification"] == "AMOUNT_MISMATCH"
    assert finding["expected_amount"] == "1000.00"
    assert finding["observed_amount"] == "990.00"
    assert finding["difference_amount"] == Decimal("-10.00")
    assert finding["bank_transaction_ids"] == ["SL-GT11-BANK"]


def test_gt12_currency_mismatch_skips_amount_comparison():
    settlement = _settlement_header(BATCH_ID="SL-GT12-BATCH", REPORTED_NET_AMOUNT="1000.00")
    bank = _bank_record("SL-GT12-BANK", "SL-GT12-BATCH", amount="1000.00", currency="USD")
    result = reconcile_settlement_to_bank([settlement], [bank])
    finding, = result["findings"]

    assert finding["classification"] == "CURRENCY_MISMATCH"
    assert finding["expected_currency"] == "INR"
    assert finding["observed_currency"] == "USD"
    assert finding["difference_amount"] is None


def test_gt13_duplicate_bank_reference_is_ambiguous_not_duplicate_payout_proof():
    settlement = _settlement_header(BATCH_ID="SL-GT13-BATCH")
    banks = [
        _bank_record("SL-GT13-BANK-A", "SL-GT13-BATCH"),
        _bank_record("SL-GT13-BANK-B", "SL-GT13-BATCH", at="2026-10-21 18:31:00"),
    ]
    result = reconcile_settlement_to_bank([settlement], banks)
    finding, = result["findings"]

    assert finding["classification"] == "AMBIGUOUS_BANK_REFERENCE"
    assert finding["bank_transaction_ids"] == ["SL-GT13-BANK-A", "SL-GT13-BANK-B"]
    assert len(finding["bank_candidates"]) == 2
    assert finding["difference_amount"] is None
    assert "duplicate payout" not in finding["explanation"].lower()


def test_unique_bank_reference_with_matching_amount_is_matched_without_finding():
    settlement = _settlement_header(BATCH_ID="BATCH-MATCH", REPORTED_NET_AMOUNT="915.00")
    bank = _bank_record("BANK-MATCH", "BATCH-MATCH", amount="915.00")
    result = reconcile_settlement_to_bank([settlement], [bank])

    outcome = result["bank_reconciliation_by_batch"]["BATCH-MATCH"]
    assert outcome["status"] == "MATCHED"
    assert outcome["difference_amount"] == Decimal("0.00")
    assert result["findings"] == []


def test_equal_amount_with_different_reference_does_not_match():
    settlement = _settlement_header(BATCH_ID="BATCH-A", REPORTED_NET_AMOUNT="915.00")
    bank = _bank_record("BANK-OTHER", "BATCH-B", amount="915.00")
    result = reconcile_settlement_to_bank([settlement], [bank])

    assert result["bank_reconciliation_by_batch"]["BATCH-A"]["status"] == "UNVERIFIED"
    assert result["bank_reconciliation_by_batch"]["BATCH-A"]["bank_transaction_ids"] == []


def test_positive_bank_difference_is_bank_amount_minus_reported_net():
    settlement = _settlement_header(BATCH_ID="BATCH-POSITIVE", REPORTED_NET_AMOUNT="915.00")
    bank = _bank_record("BANK-POSITIVE", "BATCH-POSITIVE", amount="925.00")
    finding, = reconcile_settlement_to_bank([settlement], [bank])["findings"]
    assert finding["difference_amount"] == Decimal("10.00")


def test_multiple_bank_candidates_preserve_ids_and_evidence():
    settlement = _settlement_header(BATCH_ID="BATCH-DUP")
    banks = [
        _bank_record("BANK-Z", "BATCH-DUP"),
        _bank_record("BANK-A", "BATCH-DUP"),
    ]
    result = reconcile_settlement_to_bank([settlement], banks)
    finding, = result["findings"]

    assert finding["bank_transaction_ids"] == ["BANK-A", "BANK-Z"]
    assert {item["entity_id"] for item in finding["evidence"] if item["entity_type"] == "BANK_TRANSACTION"} == {"BANK-A", "BANK-Z"}
    assert all(candidate in finding["bank_candidates"] for candidate in banks)


def test_bank_finding_ids_are_deterministic():
    settlement = _settlement_header(BATCH_ID="BATCH-STABLE")
    bank = _bank_record("BANK-STABLE", "BATCH-STABLE", amount="900.00")
    first = reconcile_settlement_to_bank([settlement], [bank])["findings"][0]
    second = reconcile_settlement_to_bank([settlement], [bank])["findings"][0]

    assert first["finding_id"] == second["finding_id"]


def test_combined_pipeline_keeps_processor_financial_bank_findings_and_lineage():
    orders, attempts, processors = _sample_records()
    processors[0]["PROCESSOR_TXN_ID"] = "PTX-COMBINED"
    source_rows = [{"SOURCE_ROW_ID": "ROW-COMBINED", "PROCESSOR_TXN_ID": "PTX-COMBINED"}]
    settlement = _settlement_header(BATCH_ID="BATCH-COMBINED")
    bank = _bank_record("BANK-COMBINED", "BATCH-COMBINED", amount="900.00")

    result = reconcile_orders_attempts_processor_and_settlement(
        orders, attempts, processors, source_rows, [settlement], [], [bank]
    )

    classes = {finding["classification"] for finding in result["findings"]}
    assert "PROCESSOR_TRANSACTION_MISSING_FROM_SETTLEMENT" in classes
    assert "SETTLEMENT_AMOUNT_MISMATCH" in classes
    assert "AMOUNT_MISMATCH" in classes
    assert result["bank_findings"][0]["bank_transaction_ids"] == ["BANK-COMBINED"]
    processor_finding = next(
        finding for finding in result["settlement_findings"]
        if finding["classification"] == "PROCESSOR_TRANSACTION_MISSING_FROM_SETTLEMENT"
    )
    assert processor_finding["source_row_lineage"] == source_rows
    assert all(
        evidence["entity_type"] != "PROCESSOR_SOURCE_ROW"
        for finding in result["findings"]
        for evidence in finding.get("evidence", [])
    )


def _timing_records(batch_id, processor_id, expected_date="2026-10-21", settled_at="2026-10-21 18:00:00"):
    processors = [{"PROCESSOR_TXN_ID": processor_id}]
    settlements = [{
        "BATCH_ID": batch_id,
        "EXPECTED_SETTLEMENT_DATE": expected_date,
        "SETTLED_AT": settled_at,
    }]
    links = [{"BATCH_ID": batch_id, "PROCESSOR_TXN_ID": processor_id}]
    return processors, settlements, links


def test_gt07_is_on_time_even_when_batch_assignment_is_wrong():
    processors, settlements, links = _timing_records(
        "SL-GT07-BATCH-20261020", "SL-GT07-PTX"
    )
    timing = reconcile_settlement_timing(processors, settlements, links)
    batch_finding, = timing["findings"]

    assert batch_finding["classification"] == "ON_TIME"
    assert batch_finding["expected_settlement_date"] == "2026-10-21"
    assert batch_finding["actual_settlement_timestamp"] == "2026-10-21 18:00:00"
    assert batch_finding["batch_id"] == "SL-GT07-BATCH-20261020"
    wrong_batch, = reconcile_processor_to_settlement(
        [{"PROCESSOR_TXN_ID": "SL-GT07-PTX", "TRANSACTION_AT": "2026-10-20 16:02:00"}],
        [],
        settlements,
        links,
    )["findings"]
    assert wrong_batch["classification"] == "PROCESSOR_TRANSACTION_IN_WRONG_SETTLEMENT_BATCH"


def test_gt08_is_confirmed_late_by_two_calendar_days():
    processors, settlements, links = _timing_records(
        "SL-GT08-BATCH-20261020", "SL-GT08-PTX", settled_at="2026-10-23 12:00:00"
    )
    finding, = reconcile_settlement_timing(processors, settlements, links)["findings"]

    assert finding["classification"] == "CONFIRMED_LATE"
    assert finding["delay_days"] == 2
    assert finding["expected_settlement_date"] == "2026-10-21"
    assert finding["actual_settlement_timestamp"] == "2026-10-23 12:00:00"


def test_same_day_and_early_settlement_are_on_time():
    same_day = _timing_records("BATCH-SAME", "PTX-SAME", settled_at="2026-10-21 00:01:00")
    early = _timing_records("BATCH-EARLY", "PTX-EARLY", settled_at="2026-10-20 23:59:00")

    same_finding, = reconcile_settlement_timing(*same_day)["findings"]
    early_finding, = reconcile_settlement_timing(*early)["findings"]

    assert same_finding["classification"] == "ON_TIME"
    assert same_finding["delay_days"] == 0
    assert early_finding["classification"] == "ON_TIME"
    assert early_finding["delay_days"] == 0


def test_missing_settlement_timestamp_is_unresolved():
    processors, settlements, links = _timing_records(
        "BATCH-NO-ACTUAL", "PTX-NO-ACTUAL", settled_at=None
    )
    finding, = reconcile_settlement_timing(processors, settlements, links)["findings"]

    assert finding["classification"] == "UNRESOLVED"
    assert "SETTLED_AT is missing" in finding["explanation"]
    assert finding["delay_days"] is None


def test_missing_expected_settlement_date_is_unresolved():
    processors, settlements, links = _timing_records(
        "BATCH-NO-EXPECTED", "PTX-NO-EXPECTED", expected_date=None
    )
    finding, = reconcile_settlement_timing(processors, settlements, links)["findings"]

    assert finding["classification"] == "UNRESOLVED"
    assert "EXPECTED_SETTLEMENT_DATE is missing" in finding["explanation"]


def test_duplicate_settlement_headers_remain_unresolved():
    processors, settlements, links = _timing_records("BATCH-DUP", "PTX-DUP")
    settlements.append(dict(settlements[0], SETTLED_AT="2026-10-30 12:00:00"))
    finding, = reconcile_settlement_timing(processors, settlements, links)["findings"]

    assert finding["classification"] == "UNRESOLVED"
    assert "Multiple settlement headers" in finding["explanation"]
    assert len(finding["settlement_transaction_candidates"]) == 1
    assert len(finding["settlement_header_candidates"]) == 2


def test_missing_settlement_link_or_processor_identity_is_unresolved():
    processors, settlements, _ = _timing_records("BATCH-NOLINK", "PTX-NOLINK")
    findings = reconcile_settlement_timing(processors, settlements, [])["findings"]

    assert all(finding["classification"] == "UNRESOLVED" for finding in findings)
    assert any("No settlement transaction link" in finding["explanation"] for finding in findings)
    assert any("No settlement transaction entry references" in finding["explanation"] for finding in findings)


def test_processor_linked_to_multiple_batches_preserves_all_candidates_as_unresolved():
    processors = [{"PROCESSOR_TXN_ID": "PTX-MULTI-BATCH"}]
    settlements = [
        {"BATCH_ID": "BATCH-EARLIER", "EXPECTED_SETTLEMENT_DATE": "2026-10-21", "SETTLED_AT": "2026-10-21 18:00:00"},
        {"BATCH_ID": "BATCH-LATER", "EXPECTED_SETTLEMENT_DATE": "2026-10-21", "SETTLED_AT": "2026-10-23 18:00:00"},
    ]
    links = [
        {"BATCH_ID": "BATCH-EARLIER", "PROCESSOR_TXN_ID": "PTX-MULTI-BATCH"},
        {"BATCH_ID": "BATCH-LATER", "PROCESSOR_TXN_ID": "PTX-MULTI-BATCH"},
    ]

    result = reconcile_settlement_timing(processors, settlements, links)

    assert len(result["findings"]) == 2
    assert all(finding["classification"] == "UNRESOLVED" for finding in result["findings"])
    assert all(finding["candidate_batch_ids"] == ["BATCH-EARLIER", "BATCH-LATER"] for finding in result["findings"])
    assert all(len(finding["settlement_transaction_candidates"]) == 2 for finding in result["findings"])


def test_timing_preserves_financial_and_bank_findings_and_does_not_change_calculation():
    orders, attempts, processors = _sample_records()
    processors[0]["PROCESSOR_TXN_ID"] = "PTX-TIMING-COMBINED"
    settlement = _settlement_header(BATCH_ID="BATCH-TIMING-COMBINED")
    settlement.update({
        "EXPECTED_SETTLEMENT_DATE": "2026-10-21",
        "SETTLED_AT": "2026-10-23 12:00:00",
    })
    link = {"BATCH_ID": settlement["BATCH_ID"], "PROCESSOR_TXN_ID": processors[0]["PROCESSOR_TXN_ID"]}
    bank = _bank_record("BANK-TIMING", settlement["BATCH_ID"], amount="900.00")
    result = reconcile_orders_attempts_processor_and_settlement(
        orders, attempts, processors, [], [settlement], [link], [bank]
    )

    assert result["settlement_financial_calculations"][settlement["BATCH_ID"]]["discrepancy"] == Decimal("-10.00")
    assert any(f["classification"] == "SETTLEMENT_AMOUNT_MISMATCH" for f in result["findings"])
    assert any(f["classification"] == "AMOUNT_MISMATCH" for f in result["findings"])
    timing, = result["settlement_timing_findings"]
    assert timing["classification"] == "CONFIRMED_LATE"
    assert timing["delay_days"] == 2
    assert timing["actual_batch_id"] == settlement["BATCH_ID"]
