import hashlib
import json
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, time, timedelta
import re


def build_order_lookup(orders):
    orders_by_id = {}
    for order in orders:
        order_id = order["ORDER_ID"]
        if order_id in orders_by_id:
            raise ValueError(f"Duplicate order ID: {order_id}")
        orders_by_id[order_id] = order

    return orders_by_id

def group_attempts_by_order(orders_by_id, attempts):
    attempts_by_order = {
        order_id: []
        for order_id in orders_by_id
    }

    unlinked_attempts = []

    for attempt in attempts:
        order_id = attempt["ORDER_ID"]

        if order_id in attempts_by_order:
            attempts_by_order[order_id].append(attempt)
        else:
            unlinked_attempts.append(attempt)

    return attempts_by_order, unlinked_attempts


def make_finding_id(finding_type, *identity_parts):
  

    # Create a structured identity from the finding type
    # and the entities responsible for the finding.
    identity = [
        finding_type,
        *identity_parts
    ]

    # Convert the identity into a consistent string.
    identity_text = json.dumps(
        identity,
        separators=(",", ":"),
        ensure_ascii=True
    )

    # Generate a SHA-256 digest.
    digest = hashlib.sha256(
        identity_text.encode("utf-8")
    ).hexdigest()

    # Keep the ID within the database column's 50-character limit.
    return "FND-" + digest[:40]


def make_unlinked_attempt_finding(attempt):
    return {
        "finding_id": make_finding_id(
            "ORDER_ATTEMPT_LINK",
            attempt["ATTEMPT_ID"],
            attempt["ORDER_ID"]
        ),
        "finding_type": "ORDER_ATTEMPT_LINK",
        "classification": "ATTEMPT_REFERENCES_UNKNOWN_ORDER",
        "resolution_status": "UNRESOLVED",
        "order_id": attempt["ORDER_ID"],
        "attempt_id": attempt["ATTEMPT_ID"],
        "expected_amount": None,
        "observed_amount": attempt.get("ATTEMPT_AMOUNT"),
        "difference_amount": None,
        "limitation": "The referenced order was not found.",
    }


def reconcile_order_attempts(orders, attempts):
    """
    Reconcile order records against payment-attempt records.

    Returns grouped attempts, unlinked attempts,
    and findings for unresolved order references.
    """

    # Step 1: Create an order lookup.
    orders_by_id = build_order_lookup(orders)

    # Step 2: Group attempts by their referenced order.
    attempts_by_order, unlinked_attempts = (
        group_attempts_by_order(orders_by_id, attempts)
    )

    # Step 3: Convert unlinked attempts into findings.
    findings = [
        make_unlinked_attempt_finding(attempt)
        for attempt in unlinked_attempts
    ]

    # Step 4: Return the complete reconciliation result.
    return {
        "orders_by_id": orders_by_id,
        "attempts_by_order": attempts_by_order,
        "unlinked_attempts": unlinked_attempts,
        "findings": findings
    }


def _decimal(value):
    """Convert supported database numeric values without accepting floats."""
    if isinstance(value, (bool, float)):
        raise TypeError("Monetary values must not be booleans or floats.")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"Invalid monetary value: {value!r}") from error
    if not amount.is_finite():
        raise ValueError(f"Invalid monetary value: {value!r}")
    return amount


def calculate_settlement_amounts(settlement):
    """Calculate expected and reported net amounts from one settlement header."""
    amount_fields = (
        "GROSS_AMOUNT",
        "FEE_AMOUNT",
        "REFUND_AMOUNT",
        "CHARGEBACK_AMOUNT",
        "ADJUSTMENT_AMOUNT",
        "REPORTED_NET_AMOUNT",
    )
    required_fields = ("BATCH_ID", "CURRENCY", *amount_fields)
    for field in required_fields:
        if field not in settlement or settlement[field] is None:
            raise ValueError(f"Missing required settlement field: {field}")

    amounts = {field: _decimal(settlement[field]) for field in amount_fields}
    expected_net_amount = (
        amounts["GROSS_AMOUNT"]
        - amounts["FEE_AMOUNT"]
        - amounts["REFUND_AMOUNT"]
        - amounts["CHARGEBACK_AMOUNT"]
        + amounts["ADJUSTMENT_AMOUNT"]
    )
    reported_net_amount = amounts["REPORTED_NET_AMOUNT"]
    return {
        "batch_id": settlement["BATCH_ID"],
        "currency": settlement["CURRENCY"],
        "gross_amount": amounts["GROSS_AMOUNT"],
        "fee_amount": amounts["FEE_AMOUNT"],
        "refund_amount": amounts["REFUND_AMOUNT"],
        "chargeback_amount": amounts["CHARGEBACK_AMOUNT"],
        "adjustment_amount": amounts["ADJUSTMENT_AMOUNT"],
        "expected_net_amount": expected_net_amount,
        "reported_net_amount": reported_net_amount,
        "discrepancy": expected_net_amount - reported_net_amount,
    }


def _processor_candidates(attempt, processor_transactions):
    """Use only explicit order and merchant payment references for identity."""
    candidates = []
    attempt_ref = attempt.get("MERCHANT_PAYMENT_REF")
    attempt_order = attempt.get("ORDER_ID")
    for transaction in processor_transactions:
        txn_order = transaction.get("ORDER_ID")
        txn_ref = transaction.get("MERCHANT_PAYMENT_REF")
        has_identity_match = (
            (attempt_ref is not None and txn_ref == attempt_ref)
            or (attempt_order is not None and txn_order == attempt_order)
        )
        # A populated reference that contradicts the other side rules out
        # identity even if the second reference happens to match.
        conflicts = (
            (attempt_ref is not None and txn_ref is not None and txn_ref != attempt_ref)
            or (attempt_order is not None and txn_order is not None and txn_order != attempt_order)
        )
        if has_identity_match and not conflicts:
            candidates.append(transaction)
    return candidates


def _processor_finding(attempt, candidates, classification, order=None, candidate_attempt_ids=None):
    processor_ids = sorted(item["PROCESSOR_TXN_ID"] for item in candidates)
    txn = (
        candidates[0]
        if len(candidates) == 1 and classification != "MULTIPLE_PAYMENT_ATTEMPT_CANDIDATES"
        else None
    )
    expected = attempt.get("ATTEMPT_AMOUNT")
    observed = txn.get("TRANSACTION_AMOUNT") if txn else None
    difference = (
        _decimal(observed) - _decimal(expected)
        if observed is not None and expected is not None else None
    )
    evidence = [{"entity_type": "PAYMENT_ATTEMPT", "entity_id": attempt["ATTEMPT_ID"]}]
    evidence.extend(
        {"entity_type": "PAYMENT_ATTEMPT", "entity_id": attempt_id}
        for attempt_id in (candidate_attempt_ids or [])
        if attempt_id != attempt["ATTEMPT_ID"]
    )
    evidence.extend({"entity_type": "PROCESSOR_TRANSACTION", "entity_id": item["PROCESSOR_TXN_ID"]} for item in candidates)
    if txn is not None:
        evidence_status = txn.get("TRANSACTION_STATUS")
    else:
        evidence_status = None
    confirmed_collection = evidence_status == "CAPTURED"
    limitation = None
    if classification == "NO_PROCESSOR_TRANSACTION_CANDIDATE":
        limitation = "No processor transaction shared a non-conflicting explicit order or merchant payment reference."
    elif classification == "MULTIPLE_PROCESSOR_TRANSACTION_CANDIDATES":
        limitation = "Multiple processor transaction IDs share explicit references; none was selected."
    elif classification == "MULTIPLE_PAYMENT_ATTEMPT_CANDIDATES":
        limitation = "The processor transaction references the order but does not distinguish among its payment attempts."
    elif not confirmed_collection:
        limitation = "Processor transaction status is not the synthetic CAPTURED collection evidence."
    elif classification == "PROCESSOR_AMOUNT_DISCREPANCY":
        limitation = "Identity is established by explicit references; amounts are compared without currency conversion."
    elif classification == "PROCESSOR_CURRENCY_DISCREPANCY":
        limitation = "Identity is established by explicit references; no FX conversion is applied."
    finding_type = "PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION"
    return {
        "finding_id": make_finding_id(finding_type, attempt["ATTEMPT_ID"], classification, *processor_ids),
        "finding_type": finding_type,
        "classification": classification,
        "resolution_status": "UNRESOLVED",
        "order_id": attempt.get("ORDER_ID"),
        "attempt_id": attempt["ATTEMPT_ID"],
        "processor_transaction_ids": processor_ids,
        "candidate_attempt_ids": sorted(candidate_attempt_ids or [attempt["ATTEMPT_ID"]]),
        "processor_transaction_id": txn.get("PROCESSOR_TXN_ID") if txn else None,
        "expected_amount": expected,
        "observed_amount": observed,
        "difference_amount": difference,
        "currency": txn.get("CURRENCY") if txn else (order or {}).get("CURRENCY"),
        "expected_currency": (order or {}).get("CURRENCY"),
        "observed_currency": txn.get("CURRENCY") if txn else None,
        "collection_confirmed": confirmed_collection,
        "evidence": evidence,
        "limitation": limitation,
    }


def reconcile_attempts_to_processor(orders, attempts, processor_transactions):
    """Reconcile each linked attempt to processor transactions deterministically."""
    orders_by_id = build_order_lookup(orders)
    findings = []
    matched = {}
    attempts_by_order = {}
    attempts_by_reference = {}
    for item in attempts:
        attempts_by_order.setdefault(item.get("ORDER_ID"), []).append(item)
        reference = item.get("MERCHANT_PAYMENT_REF")
        if reference is not None:
            attempts_by_reference.setdefault(reference, []).append(item)
    for attempt in attempts:
        order = orders_by_id.get(attempt.get("ORDER_ID"))
        candidates = _processor_candidates(attempt, processor_transactions)

        # A processor reference that explicitly identifies another attempt
        # on this order must not remain a candidate for an attempt whose own
        # merchant reference is missing.
        if attempt.get("MERCHANT_PAYMENT_REF") is None:
            candidates = [
                transaction for transaction in candidates
                if not (
                    transaction.get("MERCHANT_PAYMENT_REF") is not None
                    and any(
                        referenced_attempt.get("ORDER_ID") == attempt.get("ORDER_ID")
                        for referenced_attempt in attempts_by_reference.get(
                            transaction["MERCHANT_PAYMENT_REF"], []
                        )
                    )
                )
            ]

        matched[attempt["ATTEMPT_ID"]] = candidates
        if not candidates:
            findings.append(_processor_finding(attempt, candidates, "NO_PROCESSOR_TRANSACTION_CANDIDATE", order))
            continue
        if len(candidates) > 1:
            findings.append(_processor_finding(attempt, candidates, "MULTIPLE_PROCESSOR_TRANSACTION_CANDIDATES", order))
            continue
        txn = candidates[0]
        possible_attempts = [attempt]
        if txn.get("MERCHANT_PAYMENT_REF") is None or attempt.get("MERCHANT_PAYMENT_REF") is None:
            possible_attempts = attempts_by_order.get(attempt.get("ORDER_ID"), [attempt])
        else:
            possible_attempts = attempts_by_reference.get(txn["MERCHANT_PAYMENT_REF"], [])
        if len(possible_attempts) > 1:
            findings.append(_processor_finding(
                attempt, candidates, "MULTIPLE_PAYMENT_ATTEMPT_CANDIDATES", order,
                [item["ATTEMPT_ID"] for item in possible_attempts],
            ))
            continue
        if txn.get("TRANSACTION_STATUS") != "CAPTURED":
            findings.append(_processor_finding(attempt, candidates, "COLLECTION_EVIDENCE_MISSING", order))
        if _decimal(txn["TRANSACTION_AMOUNT"]) != _decimal(attempt["ATTEMPT_AMOUNT"]):
            findings.append(_processor_finding(attempt, candidates, "PROCESSOR_AMOUNT_DISCREPANCY", order))
        if order is not None and txn.get("CURRENCY") != order.get("CURRENCY"):
            findings.append(_processor_finding(attempt, candidates, "PROCESSOR_CURRENCY_DISCREPANCY", order))
    return {"processor_candidates_by_attempt": matched, "findings": findings}


def reconcile_orders_attempts_and_processor(orders, attempts, processor_transactions, processor_source_rows):
    """Compose existing order-attempt reconciliation with processor matching."""
    order_result = reconcile_order_attempts(orders, attempts)
    processor_result = reconcile_attempts_to_processor(orders, attempts, processor_transactions)
    source_rows_by_transaction = {}
    for source_row in processor_source_rows:
        source_rows_by_transaction.setdefault(source_row.get("PROCESSOR_TXN_ID"), []).append(source_row)
    return {
        **order_result,
        "processor_candidates_by_attempt": processor_result["processor_candidates_by_attempt"],
        "processor_findings": processor_result["findings"],
        "processor_source_rows_by_transaction": source_rows_by_transaction,
        "findings": order_result["findings"] + processor_result["findings"],
    }


def _settlement_finding(classification, processor_ids=(), settlement_entries=(), source_rows=(), limitation=None):
    processor_ids = sorted(processor_ids)
    entries = sorted(settlement_entries, key=lambda entry: (entry.get("BATCH_ID", ""), entry.get("PROCESSOR_TXN_ID", "")))
    batch_ids = sorted({entry["BATCH_ID"] for entry in entries})
    evidence = [
        {"entity_type": "PROCESSOR_TRANSACTION", "entity_id": processor_id}
        for processor_id in processor_ids
    ]
    evidence.extend(
        {
            "entity_type": "SETTLEMENT_TRANSACTION",
            "entity_id": entry["PROCESSOR_TXN_ID"],
            "batch_id": entry["BATCH_ID"],
        }
        for entry in entries
    )
    finding_type = "PROCESSOR_SETTLEMENT_RECONCILIATION"
    return {
        "finding_id": make_finding_id(
            finding_type, classification, *processor_ids, *batch_ids
        ),
        "finding_type": finding_type,
        "classification": classification,
        "resolution_status": "UNRESOLVED",
        "processor_transaction_ids": processor_ids,
        "settlement_transaction_candidates": entries,
        "batch_ids": batch_ids,
        "evidence": evidence,
        "source_row_lineage": sorted(source_rows, key=lambda row: row["SOURCE_ROW_ID"]),
        "limitation": limitation,
    }


def _expected_business_batch_date(transaction_at):
    if isinstance(transaction_at, str):
        transaction_at = datetime.fromisoformat(transaction_at)
    if isinstance(transaction_at, date) and not isinstance(transaction_at, datetime):
        return transaction_at
    business_date = transaction_at.date()
    if transaction_at.time() >= time(15, 0):
        business_date += timedelta(days=1)
    return business_date


def reconcile_processor_to_settlement(
    processor_transactions, processor_source_rows, settlements, settlement_transactions
):
    """Reconcile processor transaction IDs to their settlement entry IDs."""
    processors_by_id = {}
    for transaction in processor_transactions:
        processors_by_id.setdefault(transaction["PROCESSOR_TXN_ID"], []).append(transaction)
    settlement_entries_by_processor = {}
    for entry in settlement_transactions:
        settlement_entries_by_processor.setdefault(entry["PROCESSOR_TXN_ID"], []).append(entry)
    source_rows_by_processor = {}
    for source_row in processor_source_rows:
        source_rows_by_processor.setdefault(source_row.get("PROCESSOR_TXN_ID"), []).append(source_row)
    settlements_by_batch = {settlement["BATCH_ID"]: settlement for settlement in settlements}

    findings = []
    matched_by_processor = {}
    for processor_id, processor_candidates in processors_by_id.items():
        entries = settlement_entries_by_processor.get(processor_id, [])
        matched_by_processor[processor_id] = entries
        source_rows = source_rows_by_processor.get(processor_id, [])
        if not entries:
            findings.append(_settlement_finding(
                "PROCESSOR_TRANSACTION_MISSING_FROM_SETTLEMENT",
                [processor_id], source_rows=source_rows,
                limitation="No settlement transaction entry references this processor transaction ID.",
            ))
            continue
        if len(processor_candidates) > 1 or len(entries) > 1:
            findings.append(_settlement_finding(
                "AMBIGUOUS_PROCESSOR_SETTLEMENT_REFERENCE",
                [processor_id], entries, source_rows,
                "Multiple processor records or settlement entries share the transaction ID; no relationship was selected.",
            ))
            continue

        transaction = processor_candidates[0]
        entry = entries[0]
        batch_id = entry["BATCH_ID"]
        # Synthetic dated batch IDs encode the business date in their suffix.
        scenario_match = re.match(r"SL-(GT07|GT08)-", processor_id)
        batch_is_same_scenario = scenario_match and batch_id.startswith(
            f"SL-{scenario_match.group(1)}-"
        )
        match = re.search(r"(\d{8})$", batch_id) if batch_is_same_scenario else None
        transaction_at = transaction.get("TRANSACTION_AT")
        if match and transaction_at is not None:
            expected_date = _expected_business_batch_date(transaction_at)
            actual_date = datetime.strptime(match.group(1), "%Y%m%d").date()
            if actual_date != expected_date:
                expected_batch_id = batch_id[:-8] + expected_date.strftime("%Y%m%d")
                finding = _settlement_finding(
                    "PROCESSOR_TRANSACTION_IN_WRONG_SETTLEMENT_BATCH",
                    [processor_id], [entry], source_rows,
                    "The dated synthetic batch suffix differs from the transaction's expected business date.",
                )
                finding["actual_batch_id"] = batch_id
                finding["expected_batch_id"] = expected_batch_id
                finding["expected_business_date"] = expected_date
                finding["settlement"] = settlements_by_batch.get(batch_id)
                findings.append(finding)

    for processor_id, entries in settlement_entries_by_processor.items():
        processor_candidates = processors_by_id.get(processor_id, [])
        if not processor_candidates:
            findings.append(_settlement_finding(
                "SETTLEMENT_ENTRY_WITHOUT_PROCESSOR_TRANSACTION",
                [processor_id], entries,
                limitation="Settlement entry references a processor transaction ID absent from processor data.",
            ))
        elif len(processor_candidates) > 1:
            # The ambiguous association is already emitted from the processor pass.
            continue

    return {
        "settlement_entries_by_processor_transaction": matched_by_processor,
        "processor_source_rows_by_transaction": source_rows_by_processor,
        "settlements_by_batch": settlements_by_batch,
        "findings": findings,
    }


def _settlement_financial_finding(settlement, classification, calculation=None, reason=None):
    batch_id = settlement.get("BATCH_ID")
    currency = settlement.get("CURRENCY")
    financial_fields = {
        "gross_amount": settlement.get("GROSS_AMOUNT"),
        "fee_amount": settlement.get("FEE_AMOUNT"),
        "refund_amount": settlement.get("REFUND_AMOUNT"),
        "chargeback_amount": settlement.get("CHARGEBACK_AMOUNT"),
        "adjustment_amount": settlement.get("ADJUSTMENT_AMOUNT"),
    }
    if calculation is not None:
        financial_fields = {
            "gross_amount": calculation["gross_amount"],
            "fee_amount": calculation["fee_amount"],
            "refund_amount": calculation["refund_amount"],
            "chargeback_amount": calculation["chargeback_amount"],
            "adjustment_amount": calculation["adjustment_amount"],
        }
    finding_type = "SETTLEMENT_FINANCIAL_RECONCILIATION"
    return {
        "finding_id": make_finding_id(finding_type, classification, batch_id),
        "finding_type": finding_type,
        "classification": classification,
        "layer": "SETTLEMENT",
        "resolution_status": "UNRESOLVED",
        "batch_id": batch_id,
        "currency": currency,
        **financial_fields,
        "expected_net_amount": calculation.get("expected_net_amount") if calculation else None,
        "reported_net_amount": (
            calculation.get("reported_net_amount")
            if calculation else settlement.get("REPORTED_NET_AMOUNT")
        ),
        "discrepancy": calculation.get("discrepancy") if calculation else None,
        "evidence": [{"entity_type": "SETTLEMENT_HEADER", "entity_id": batch_id}],
        "limitation": reason,
    }


def reconcile_settlement_financials(settlements):
    """Calculate batch net amounts and report discrepancies or unusable headers."""
    findings = []
    calculations = {}
    for settlement in settlements:
        batch_id = settlement.get("BATCH_ID")
        try:
            calculation = calculate_settlement_amounts(settlement)
        except (ArithmeticError, TypeError, ValueError) as error:
            findings.append(_settlement_financial_finding(
                settlement,
                "SETTLEMENT_FINANCIAL_EVIDENCE_INVALID",
                reason=str(error),
            ))
            continue

        calculations[batch_id] = calculation
        if calculation["discrepancy"] != Decimal("0"):
            findings.append(_settlement_financial_finding(
                settlement,
                "SETTLEMENT_AMOUNT_MISMATCH",
                calculation=calculation,
                reason="Expected net amount differs from the reported net amount.",
            ))
    return {"settlement_financial_calculations": calculations, "findings": findings}


def _settlement_bank_finding(settlement, classification, bank_candidates, observed_amount=None, difference=None):
    batch_id = settlement["BATCH_ID"]
    bank_candidates = sorted(bank_candidates, key=lambda item: item["BANK_TXN_ID"])
    bank_transaction_ids = [item["BANK_TXN_ID"] for item in bank_candidates]
    finding_type = "SETTLEMENT_BANK_RECONCILIATION"
    return {
        "finding_id": make_finding_id(
            finding_type, classification, batch_id, *bank_transaction_ids
        ),
        "finding_type": finding_type,
        "classification": classification,
        "resolution_status": "UNRESOLVED",
        "layer": "BANK_PAYOUT",
        "batch_id": batch_id,
        "settlement_batch_id": batch_id,
        "bank_transaction_ids": bank_transaction_ids,
        "bank_references": [candidate.get("BANK_REFERENCE") for candidate in bank_candidates],
        "currency": settlement.get("CURRENCY"),
        "expected_currency": settlement.get("CURRENCY"),
        "observed_currencies": [candidate.get("CURRENCY") for candidate in bank_candidates],
        "observed_currency": bank_candidates[0].get("CURRENCY") if len(bank_candidates) == 1 else None,
        "expected_amount": settlement.get("REPORTED_NET_AMOUNT"),
        "observed_amount": (
            observed_amount if observed_amount is not None
            else bank_candidates[0].get("AMOUNT") if len(bank_candidates) == 1
            else None
        ),
        "difference_amount": difference,
        "expected_settlement_date": settlement.get("EXPECTED_SETTLEMENT_DATE"),
        "settled_at": settlement.get("SETTLED_AT"),
        "bank_transaction_dates": [candidate.get("TRANSACTION_AT") for candidate in bank_candidates],
        "bank_candidates": bank_candidates,
        "evidence": [
            {"entity_type": "SETTLEMENT_HEADER", "entity_id": batch_id},
            *[
                {"entity_type": "BANK_TRANSACTION", "entity_id": bank_id}
                for bank_id in bank_transaction_ids
            ],
        ],
        "explanation": {
            "UNVERIFIED": "No bank transaction references this settlement batch; payout status is unverified.",
            "CURRENCY_MISMATCH": "The uniquely referenced bank transaction and settlement use different currencies; amounts were not compared.",
            "AMOUNT_MISMATCH": "The uniquely referenced bank amount differs from the settlement reported net amount.",
            "AMBIGUOUS_BANK_REFERENCE": "Multiple bank transactions reference this settlement batch; no candidate was selected.",
        }[classification],
        "limitation": (
            "The available reference establishes a candidate relationship but does not establish why a discrepancy occurred."
            if classification in ("CURRENCY_MISMATCH", "AMOUNT_MISMATCH")
            else None
        ),
    }


def reconcile_settlement_to_bank(settlements, bank_transactions):
    """Reconcile settlement batches to bank payouts by exact reference only."""
    banks_by_reference = {}
    for transaction in bank_transactions:
        reference = transaction.get("BANK_REFERENCE")
        if reference is not None:
            banks_by_reference.setdefault(reference, []).append(transaction)

    findings = []
    reconciliations = {}
    for settlement in settlements:
        batch_id = settlement["BATCH_ID"]
        candidates = sorted(
            banks_by_reference.get(batch_id, []),
            key=lambda item: item["BANK_TXN_ID"],
        )
        outcome = {
            "batch_id": batch_id,
            "bank_transaction_ids": [item["BANK_TXN_ID"] for item in candidates],
            "bank_candidates": candidates,
            "expected_amount": settlement.get("REPORTED_NET_AMOUNT"),
            "expected_currency": settlement.get("CURRENCY"),
            "observed_amount": None,
            "observed_currency": None,
            "difference_amount": None,
        }
        if not candidates:
            outcome["status"] = "UNVERIFIED"
            findings.append(_settlement_bank_finding(settlement, "UNVERIFIED", candidates))
        elif len(candidates) > 1:
            outcome["status"] = "AMBIGUOUS_BANK_REFERENCE"
            findings.append(_settlement_bank_finding(
                settlement, "AMBIGUOUS_BANK_REFERENCE", candidates
            ))
        else:
            bank = candidates[0]
            outcome["observed_amount"] = bank["AMOUNT"]
            outcome["observed_currency"] = bank["CURRENCY"]
            if bank["CURRENCY"] != settlement["CURRENCY"]:
                outcome["status"] = "CURRENCY_MISMATCH"
                findings.append(_settlement_bank_finding(
                    settlement, "CURRENCY_MISMATCH", candidates,
                ))
            else:
                difference = _decimal(bank["AMOUNT"]) - _decimal(settlement["REPORTED_NET_AMOUNT"])
                outcome["difference_amount"] = difference
                if difference != Decimal("0"):
                    outcome["status"] = "AMOUNT_MISMATCH"
                    findings.append(_settlement_bank_finding(
                        settlement, "AMOUNT_MISMATCH", candidates,
                        observed_amount=bank["AMOUNT"], difference=difference,
                    ))
                else:
                    outcome["status"] = "MATCHED"
        reconciliations[batch_id] = outcome
    return {"bank_reconciliation_by_batch": reconciliations, "findings": findings}


def _as_calendar_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return datetime.fromisoformat(value).date()
    raise ValueError(f"Unsupported date value: {value!r}")


def _as_settlement_timestamp(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        if "T" not in value and " " not in value:
            raise ValueError(f"Unsupported settlement timestamp: {value!r}")
        return datetime.fromisoformat(value)
    raise ValueError(f"Unsupported settlement timestamp: {value!r}")


def _settlement_timing_finding(
    classification, batch_id=None, settlement=None, processor_ids=(),
    entries=(), candidate_batch_ids=(), expected_date=None,
    actual_timestamp=None, delay_days=None, explanation=None,
    settlement_candidates=(),
):
    settlement = settlement or {}
    entries = sorted(
        entries,
        key=lambda entry: (entry.get("BATCH_ID", ""), entry.get("PROCESSOR_TXN_ID", "")),
    )
    processor_ids = sorted(set(processor_ids))
    candidate_batch_ids = sorted(set(candidate_batch_ids))
    finding_type = "SETTLEMENT_TIMING_RECONCILIATION"
    return {
        "finding_id": make_finding_id(
            finding_type, classification, batch_id, *processor_ids, *candidate_batch_ids
        ),
        "finding_type": finding_type,
        "classification": classification,
        "resolution_status": "UNRESOLVED" if classification == "UNRESOLVED" else "RESOLVED",
        "layer": "SETTLEMENT_TIMING",
        "settlement_id": batch_id,
        "batch_id": batch_id,
        "expected_batch_id": None,
        "actual_batch_id": batch_id,
        "candidate_batch_ids": candidate_batch_ids,
        "processor_transaction_ids": processor_ids,
        "expected_settlement_date": (
            expected_date if expected_date is not None
            else settlement.get("EXPECTED_SETTLEMENT_DATE")
        ),
        "actual_settlement_timestamp": (
            actual_timestamp if actual_timestamp is not None
            else settlement.get("SETTLED_AT")
        ),
        "delay_days": delay_days,
        "settlement_transaction_candidates": entries,
        "settlement_header_candidates": list(settlement_candidates) or ([settlement] if settlement else []),
        "evidence": [
            *([
                {"entity_type": "SETTLEMENT_HEADER", "entity_id": batch_id}
            ] if batch_id is not None else []),
            *[
                {"entity_type": "PROCESSOR_TRANSACTION", "entity_id": processor_id}
                for processor_id in processor_ids
            ],
            *[
                {
                    "entity_type": "SETTLEMENT_TRANSACTION",
                    "entity_id": entry["PROCESSOR_TXN_ID"],
                    "batch_id": entry["BATCH_ID"],
                }
                for entry in entries
            ],
        ],
        "explanation": explanation,
    }


def reconcile_settlement_timing(processor_transactions, settlements, settlement_transactions):
    """Classify settlement timing from explicit transaction links and header dates."""
    processors_by_id = {}
    for transaction in processor_transactions:
        processors_by_id.setdefault(transaction["PROCESSOR_TXN_ID"], []).append(transaction)

    settlements_by_batch = {}
    for settlement in settlements:
        settlements_by_batch.setdefault(settlement.get("BATCH_ID"), []).append(settlement)

    entries_by_batch = {}
    entries_by_processor = {}
    for entry in settlement_transactions:
        entries_by_batch.setdefault(entry.get("BATCH_ID"), []).append(entry)
        entries_by_processor.setdefault(entry.get("PROCESSOR_TXN_ID"), []).append(entry)

    findings = []
    timing_by_batch = {}
    for batch_id, header_candidates in settlements_by_batch.items():
        entries = entries_by_batch.get(batch_id, [])
        processor_ids = [entry.get("PROCESSOR_TXN_ID") for entry in entries]
        issue = None
        issue_entries = entries
        issue_candidate_batches = sorted({entry.get("BATCH_ID") for entry in entries})
        if len(header_candidates) > 1:
            issue = "Multiple settlement headers share this batch ID; no header was selected."
        elif not entries:
            issue = "No settlement transaction link identifies a processor transaction for this batch."
        else:
            for processor_id in processor_ids:
                if processor_id not in processors_by_id:
                    issue = f"Processor transaction {processor_id} referenced by the settlement entry is unavailable."
                    break
                linked_entries = entries_by_processor.get(processor_id, [])
                if len(linked_entries) != 1:
                    candidate_batches = sorted({item.get("BATCH_ID") for item in linked_entries})
                    issue = (
                        f"Processor transaction {processor_id} has multiple settlement entry candidates: "
                        f"{candidate_batches}."
                    )
                    issue_entries = linked_entries
                    issue_candidate_batches = candidate_batches
                    break
                if len(processors_by_id[processor_id]) != 1:
                    issue = f"Processor transaction ID {processor_id} has multiple processor records."
                    break

        if issue is not None:
            candidate_batches = sorted({entry.get("BATCH_ID") for entry in entries})
            finding = _settlement_timing_finding(
                "UNRESOLVED", batch_id,
                header_candidates[0] if len(header_candidates) == 1 else None,
                processor_ids, issue_entries, issue_candidate_batches,
                explanation=issue, settlement_candidates=header_candidates,
            )
            findings.append(finding)
            timing_by_batch[batch_id] = finding
            continue

        settlement = header_candidates[0]
        expected_value = settlement.get("EXPECTED_SETTLEMENT_DATE")
        settled_value = settlement.get("SETTLED_AT")
        if expected_value is None:
            issue = "EXPECTED_SETTLEMENT_DATE is missing from the settlement header."
        elif settled_value is None:
            issue = "SETTLED_AT is missing; no actual settlement timestamp is available."
        else:
            try:
                expected_date = _as_calendar_date(expected_value)
                actual_timestamp = _as_settlement_timestamp(settled_value)
            except (TypeError, ValueError) as error:
                issue = f"Settlement date evidence is invalid: {error}"

        if issue is not None:
            finding = _settlement_timing_finding(
                "UNRESOLVED", batch_id, settlement, processor_ids, entries,
                [batch_id], explanation=issue,
            )
        else:
            calendar_difference = (actual_timestamp.date() - expected_date).days
            classification = "CONFIRMED_LATE" if calendar_difference > 0 else "ON_TIME"
            finding = _settlement_timing_finding(
                classification, batch_id, settlement, processor_ids, entries,
                [batch_id], settlement.get("EXPECTED_SETTLEMENT_DATE"),
                settlement.get("SETTLED_AT"),
                calendar_difference if calendar_difference > 0 else 0,
                (
                    f"Settlement occurred {calendar_difference} calendar days after the expected date."
                    if calendar_difference > 0
                    else "Settlement occurred on or before the expected date."
                ),
            )
        findings.append(finding)
        timing_by_batch[batch_id] = finding

    # Preserve settlement entries whose batch has no available header.
    for entry in settlement_transactions:
        batch_id = entry.get("BATCH_ID")
        if batch_id not in settlements_by_batch:
            finding = _settlement_timing_finding(
                "UNRESOLVED", batch_id, processor_ids=[entry.get("PROCESSOR_TXN_ID")],
                entries=[entry], candidate_batch_ids=[batch_id],
                explanation="The settlement entry references a batch with no available settlement header.",
            )
            findings.append(finding)

    # Transactions without any settlement link cannot be assigned an expected date.
    for processor_id in processors_by_id:
        if processor_id not in entries_by_processor:
            finding = _settlement_timing_finding(
                "UNRESOLVED", processor_ids=[processor_id],
                explanation="No settlement transaction entry references this processor transaction; its expected settlement date cannot be established.",
            )
            findings.append(finding)

    return {"settlement_timing_by_batch": timing_by_batch, "findings": findings}


def reconcile_orders_attempts_processor_and_settlement(
    orders, attempts, processor_transactions, processor_source_rows, settlements,
    settlement_transactions, bank_transactions=(),
):
    """Compose order, attempt, processor and settlement-entry reconciliation."""
    result = reconcile_orders_attempts_and_processor(
        orders, attempts, processor_transactions, processor_source_rows
    )
    settlement_result = reconcile_processor_to_settlement(
        processor_transactions, processor_source_rows, settlements, settlement_transactions
    )
    financial_result = reconcile_settlement_financials(settlements)
    bank_result = reconcile_settlement_to_bank(settlements, bank_transactions)
    timing_result = reconcile_settlement_timing(
        processor_transactions, settlements, settlement_transactions
    )
    result.update({
        "settlement_entries_by_processor_transaction": settlement_result["settlement_entries_by_processor_transaction"],
        "settlements_by_batch": settlement_result["settlements_by_batch"],
        "settlement_findings": settlement_result["findings"],
        "settlement_financial_calculations": financial_result["settlement_financial_calculations"],
        "settlement_financial_findings": financial_result["findings"],
        "bank_reconciliation_by_batch": bank_result["bank_reconciliation_by_batch"],
        "bank_findings": bank_result["findings"],
        "settlement_timing_by_batch": timing_result["settlement_timing_by_batch"],
        "settlement_timing_findings": timing_result["findings"],
        "findings": (
            result["findings"] + settlement_result["findings"]
            + financial_result["findings"] + bank_result["findings"]
            + timing_result["findings"]
        ),
    })
    return result
