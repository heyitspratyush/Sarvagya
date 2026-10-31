"""Human-readable presentation helpers for persisted reconciliation findings.

This module deliberately formats engine results without changing their decisions,
identifiers, monetary values, or evidence.
"""

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


TYPE_LAYERS = {
    "ORDER_ATTEMPT_LINK": "Order and payment attempt",
    "PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION": "Payment and processor",
    "PROCESSOR_SETTLEMENT_RECONCILIATION": "Processor and settlement",
    "SETTLEMENT_FINANCIAL_RECONCILIATION": "Settlement amounts",
    "SETTLEMENT_BANK_RECONCILIATION": "Settlement and bank payout",
    "SETTLEMENT_TIMING_RECONCILIATION": "Settlement timing",
}


CLASSIFICATIONS = {
    "ATTEMPT_REFERENCES_UNKNOWN_ORDER": (
        "Payment attempt references an unavailable order",
        "The payment attempt refers to an order that is not present in the available order records.",
        "Check the order reference and confirm that the relevant order data was loaded.",
    ),
    "NO_PROCESSOR_TRANSACTION_CANDIDATE": (
        "No processor transaction matches the payment references",
        "No processor transaction shares a non-conflicting explicit order or merchant payment reference with this payment attempt.",
        "Check the merchant payment reference and order reference in the source records.",
    ),
    "MULTIPLE_PROCESSOR_TRANSACTION_CANDIDATES": (
        "Multiple processor transactions match the payment references",
        "More than one processor transaction shares explicit references with this payment attempt. All candidates are preserved; none was selected.",
        "Review each processor candidate and the source references that link it to the payment attempt.",
    ),
    "MULTIPLE_PAYMENT_ATTEMPT_CANDIDATES": (
        "Processor transaction could match multiple payment attempts",
        "The processor transaction references the order but does not distinguish among its payment attempts.",
        "Review the processor and payment reference details to determine whether another explicit identifier is available.",
    ),
    "COLLECTION_EVIDENCE_MISSING": (
        "Processor collection is not confirmed by the available status",
        "The processor transaction status does not provide the configured CAPTURED evidence for a confirmed collection.",
        "Check the processor transaction status and its source record.",
    ),
    "PROCESSOR_AMOUNT_DISCREPANCY": (
        "Processor amount differs from the payment attempt",
        "The linked processor transaction amount differs from the payment attempt amount. The displayed difference follows the engine convention: observed processor amount minus expected attempt amount.",
        "Review both source amounts and confirm that they refer to the same currency and transaction.",
    ),
    "PROCESSOR_CURRENCY_DISCREPANCY": (
        "Processor currency differs from the order currency",
        "The linked processor transaction and order have different currencies. No currency conversion was applied.",
        "Check the currency values in the order and processor source records.",
    ),
    "PROCESSOR_TRANSACTION_MISSING_FROM_SETTLEMENT": (
        "Processor transaction not found in available settlement records",
        "The processor transaction exists, but no available settlement transaction entry references it. Settlement cannot be confirmed from the current evidence.",
        "Check the settlement files and transaction references for this processor transaction.",
    ),
    "AMBIGUOUS_PROCESSOR_SETTLEMENT_REFERENCE": (
        "Processor transaction has ambiguous settlement references",
        "Multiple processor records or settlement entries share this transaction ID. All candidates are preserved; no relationship was selected.",
        "Review the duplicate processor records and settlement entries for this transaction ID.",
    ),
    "PROCESSOR_TRANSACTION_IN_WRONG_SETTLEMENT_BATCH": (
        "Processor transaction batch reference differs from the expected business date",
        "The actual and expected batch references differ under the dated synthetic batch naming rule. This naming convention does not independently verify which batch assignment is correct.",
        "Verify the processor transaction timestamp and the settlement batch reference against their source records.",
    ),
    "SETTLEMENT_ENTRY_WITHOUT_PROCESSOR_TRANSACTION": (
        "Settlement entry has no matching processor transaction",
        "A settlement entry references a processor transaction ID that is absent from the available processor data.",
        "Check the processor data load and the transaction ID in the settlement entry.",
    ),
    "SETTLEMENT_FINANCIAL_EVIDENCE_INVALID": (
        "Settlement amount evidence is incomplete or invalid",
        "The available settlement header does not contain valid values for the configured net amount calculation.",
        "Review the settlement header fields and correct or reload any missing or invalid source values.",
    ),
    "SETTLEMENT_AMOUNT_MISMATCH": (
        "Reported settlement amount differs from the calculated net amount",
        "The expected net amount is gross amount minus fees, refunds, and chargebacks, plus adjustments. The signed difference is expected net amount minus reported net amount.",
        "Compare the gross amount, fees, refunds, chargebacks, adjustments, and reported net amount with the settlement source.",
    ),
    "UNVERIFIED": (
        "Settlement could not be verified from available evidence",
        "No bank transaction references this settlement batch, so the payout status is unverified. This does not establish that the payout failed.",
        "Check the bank transaction data and confirm whether a transaction references this settlement batch.",
    ),
    "AMBIGUOUS_BANK_REFERENCE": (
        "Multiple bank transactions match this settlement",
        "The system found more than one bank transaction matching the settlement reference. It has preserved all candidates and has not selected one arbitrarily.",
        "Review each bank candidate and compare its source reference, amount, currency, and date with the settlement.",
    ),
    "CURRENCY_MISMATCH": (
        "Bank transaction currency differs from the settlement currency",
        "The uniquely referenced bank transaction and settlement use different currencies. Amounts were not compared and no conversion was applied.",
        "Check the currency values in the settlement and bank source records.",
    ),
    "AMOUNT_MISMATCH": (
        "Bank amount differs from the reported settlement amount",
        "The uniquely referenced bank transaction amount differs from the settlement reported net amount. The signed difference follows the engine convention: observed bank amount minus expected reported net amount.",
        "Review the bank amount and settlement reported net amount in their source records.",
    ),
    "UNRESOLVED": (
        "Settlement timing could not be established",
        "The available settlement, processor, or date evidence is insufficient to determine settlement timing.",
        "Review the explanation and check for missing settlement headers, transaction links, or date values.",
    ),
    "CONFIRMED_LATE": (
        "Settlement occurred after the expected date",
        "The settlement timestamp falls on a later calendar date than the expected settlement date. No cause is inferred.",
        "Review the expected date, settlement timestamp, and linked settlement evidence.",
    ),
    "ON_TIME": (
        "Settlement confirmed by the expected date",
        "The available settlement timestamp is on or before the expected settlement date.",
        "Review the expected date and settlement timestamp if you need to confirm the underlying source records.",
    ),
}


def _as_decimal(value):
    if value is None or isinstance(value, (bool, float)):
        return None
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() else None


def format_amount(value, currency=None):
    """Format Decimal-safe amounts with Indian grouping and two decimals."""
    amount = _as_decimal(value)
    if amount is None:
        return "Not available"
    rendered = f"{abs(amount):.2f}"
    integer, fraction = rendered.split(".")
    if len(integer) > 3:
        last_three = integer[-3:]
        leading = integer[:-3]
        groups = []
        while leading:
            groups.insert(0, leading[-2:])
            leading = leading[:-2]
        integer = ",".join([*groups, last_three])
    sign = "-" if amount < 0 else ""
    code = currency.strip().upper() if isinstance(currency, str) and currency.strip() else None
    prefix = "₹" if code == "INR" else (f"{code} " if code else "")
    return f"{sign}{prefix}{integer}.{fraction}"


def format_date(value):
    if value is None:
        return "Not available"
    parsed = value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                return str(value)
    if isinstance(parsed, datetime):
        return parsed.strftime("%d %b %Y, %H:%M:%S")
    if isinstance(parsed, date):
        return parsed.strftime("%d %b %Y")
    return str(value)


def _json_payload(value):
    if isinstance(value, dict):
        return value, None
    if value is None:
        return {}, None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}, "Stored finding summary is not valid JSON."
    if not isinstance(parsed, dict):
        return {}, "Stored finding summary is JSON, but is not an object."
    return parsed, None


def _first(payload, *keys):
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def _references(payload, evidence):
    references = []
    for key, label in (
        ("order_id", "Order"),
        ("attempt_id", "Payment attempt"),
        ("processor_transaction_id", "Processor transaction"),
        ("processor_transaction_ids", "Processor transactions"),
        ("batch_id", "Settlement batch"),
        ("settlement_batch_id", "Settlement batch"),
        ("batch_ids", "Settlement batches"),
        ("actual_batch_id", "Actual batch"),
        ("expected_batch_id", "Expected batch"),
        ("bank_transaction_ids", "Bank transactions"),
    ):
        value = payload.get(key)
        values = value if isinstance(value, (list, tuple, set)) else [value]
        for item in values:
            if item is not None and not any(ref["value"] == item for ref in references):
                references.append({"label": label, "value": item})
    for item in evidence:
        if not isinstance(item, dict):
            continue
        entity_type = item.get("entity_type", "Evidence")
        entity_id = item.get("entity_id")
        if entity_id is not None and not any(ref["value"] == entity_id for ref in references):
            references.append({"label": str(entity_type).replace("_", " ").title(), "value": entity_id})
    return references


def present_finding(record, evidence=()):
    """Build a resilient presentation object from a DB row or engine payload.

    The record may use database uppercase column names, engine lowercase keys,
    or both. Original classification is recovered only from an explicit JSON
    payload field; no hash-to-classification inference is attempted.
    """
    if not isinstance(record, dict):
        record = {}
    payload_value = _first(record, "evidence_summary", "EVIDENCE_SUMMARY")
    if payload_value is None and "finding_type" in record:
        payload_value = record
    payload, parse_error = _json_payload(payload_value)

    def value(lower, upper=None):
        return _first(record, lower, upper or lower.upper(), payload.get(lower))

    finding_id = value("finding_id")
    finding_type = value("finding_type")
    stored_alias = value("classification")
    original_classification = payload.get("classification")
    classification = (
        original_classification if isinstance(original_classification, str)
        else stored_alias if isinstance(stored_alias, str) else None
    )
    title, default_explanation, suggested_check = CLASSIFICATIONS.get(
        classification,
        ("Reconciliation finding needs review", "The available finding details do not provide a recognized classification explanation.", "Review the preserved evidence and technical details."),
    )
    explanation = payload.get("explanation")
    if isinstance(explanation, dict):
        explanation = "; ".join(str(item) for item in explanation.values())
    if not isinstance(explanation, str) or not explanation.strip():
        explanation = default_explanation

    status = value("resolution_status")
    status = status if isinstance(status, str) else "UNRESOLVED"
    status_labels = {"RESOLVED": "Resolved", "UNRESOLVED": "Unresolved"}
    outcome_labels = {
        "UNVERIFIED": "Unverified",
        "AMBIGUOUS_BANK_REFERENCE": "Ambiguous evidence",
        "AMBIGUOUS_PROCESSOR_SETTLEMENT_REFERENCE": "Ambiguous evidence",
        "MULTIPLE_PROCESSOR_TRANSACTION_CANDIDATES": "Ambiguous evidence",
        "MULTIPLE_PAYMENT_ATTEMPT_CANDIDATES": "Ambiguous evidence",
        "CONFIRMED_LATE": "Confirmed late",
        "ON_TIME": "On time",
        "SETTLEMENT_AMOUNT_MISMATCH": "Confirmed amount discrepancy",
        "AMOUNT_MISMATCH": "Confirmed amount discrepancy",
        "PROCESSOR_AMOUNT_DISCREPANCY": "Confirmed amount discrepancy",
        "CURRENCY_MISMATCH": "Confirmed currency discrepancy",
        "PROCESSOR_CURRENCY_DISCREPANCY": "Confirmed currency discrepancy",
    }
    status_label = outcome_labels.get(
        classification,
        status_labels.get(status.upper(), status.replace("_", " ").title()),
    )
    layer = payload.get("layer") or TYPE_LAYERS.get(finding_type, "Reconciliation")

    expected = _first(payload, "expected_amount", "expected_net_amount")
    if expected is None:
        expected = _first(record, "EXPECTED_AMOUNT", "expected_amount")
    if expected is None and classification == "SETTLEMENT_AMOUNT_MISMATCH":
        expected = payload.get("expected_net_amount")
    observed = _first(payload, "observed_amount", "reported_net_amount")
    if observed is None:
        observed = _first(record, "OBSERVED_AMOUNT", "observed_amount")
    difference = _first(payload, "difference_amount", "discrepancy")
    if difference is None:
        difference = _first(record, "DIFFERENCE_AMOUNT", "difference_amount")
    expected_currency = payload.get("expected_currency") or payload.get("currency")
    observed_currency = payload.get("observed_currency") or payload.get("currency")
    currency = expected_currency or observed_currency or _first(record, "CURRENCY", "currency")

    amount_convention = None
    if classification == "SETTLEMENT_AMOUNT_MISMATCH":
        amount_convention = "Expected net minus reported net"
    elif classification in ("PROCESSOR_AMOUNT_DISCREPANCY", "AMOUNT_MISMATCH"):
        amount_convention = "Observed amount minus expected amount"
    elif difference is not None:
        amount_convention = "Signed difference as calculated by the reconciliation engine"

    dates = {
        "expected": payload.get("expected_settlement_date", payload.get("expected_business_date")),
        "actual": payload.get("actual_settlement_timestamp", payload.get("settled_at")),
    }
    if dates["expected"] is None:
        dates["expected"] = _first(record, "EXPECTED_AT", "expected_at")
    if dates["actual"] is None:
        dates["actual"] = _first(record, "OBSERVED_AT", "observed_at")
    delay = payload.get("delay_days")
    if delay is None and classification == "CONFIRMED_LATE" and dates["expected"] and dates["actual"]:
        try:
            expected_day = date.fromisoformat(str(dates["expected"])[:10])
            actual_day = date.fromisoformat(str(dates["actual"])[:10])
            delay = (actual_day - expected_day).days
        except ValueError:
            pass
    delay_minutes = payload.get("delay_minutes")
    if delay_minutes is None:
        delay_minutes = _first(record, "DELAY_MINUTES", "delay_minutes")

    evidence_items = list(evidence) if isinstance(evidence, (list, tuple)) else []
    if not evidence_items:
        raw_evidence = payload.get("evidence")
        if isinstance(raw_evidence, list):
            evidence_items = raw_evidence
    lineage = payload.get("source_row_lineage")
    if not isinstance(lineage, list):
        lineage = []
    limitation = payload.get("limitation")
    if limitation is None:
        limitation = value("limitation")
    if isinstance(limitation, str):
        limitations = [limitation] if limitation.strip() else []
    elif isinstance(limitation, list):
        limitations = [str(item) for item in limitation if item is not None]
    else:
        limitations = []
    if parse_error:
        limitations.append(parse_error)

    display_ref = str(finding_id) if finding_id is not None else "Finding reference unavailable"
    technical_json = payload_value if isinstance(payload_value, str) else json.dumps(payload, default=str, sort_keys=True)
    technical = {
        "finding_id": finding_id,
        "original_classification": original_classification,
        "stored_classification": stored_alias,
        "classification": classification,
        "finding_type": finding_type,
        "raw_record": record,
        "evidence_summary": technical_json,
        "parse_error": parse_error,
    }
    component_names = {
        "gross_amount": "Gross",
        "fee_amount": "Fees",
        "refund_amount": "Refunds",
        "chargeback_amount": "Chargebacks",
        "adjustment_amount": "Adjustments",
    }
    financial_components = [
        {
            "label": label,
            "value": payload.get(key),
            "display": format_amount(payload.get(key), currency),
        }
        for key, label in component_names.items()
        if key in payload
    ]
    candidates = []
    for key in ("bank_candidates", "settlement_transaction_candidates", "settlement_header_candidates"):
        candidate_value = payload.get(key)
        if isinstance(candidate_value, list):
            candidates.extend(candidate_value)
    return {
        "title": title,
        "summary": f"{layer}: {title}.",
        "explanation": explanation,
        "category": finding_type,
        "layer": layer,
        "status": status_label,
        "status_code": status.upper(),
        "classification": classification,
        "finding_reference": display_ref,
        "short_finding_reference": display_ref[:12] if len(display_ref) > 20 else display_ref,
        "references": _references(payload, evidence_items),
        "expected_amount": expected,
        "expected_amount_display": format_amount(expected, expected_currency),
        "observed_amount": observed,
        "observed_amount_display": format_amount(observed, observed_currency),
        "difference": difference,
        "difference_display": format_amount(difference, currency),
        "difference_convention": amount_convention,
        "financial_components": financial_components,
        "currency": currency,
        "expected_date": dates["expected"],
        "expected_date_display": format_date(dates["expected"]),
        "actual_date": dates["actual"],
        "actual_date_display": format_date(dates["actual"]),
        "delay_days": delay,
        "delay_minutes": delay_minutes,
        "evidence": evidence_items,
        "candidates": candidates,
        "source_row_lineage": lineage,
        "limitations": limitations,
        "suggested_checks": [suggested_check],
        "technical_details": technical,
    }


def summarize_findings(findings):
    """Return overview metrics with timing and financial counts kept distinct."""
    items = list(findings)
    presented = [present_finding(item) for item in items]
    return {
        "total_findings": len(presented),
        "unresolved_findings": sum(item["status_code"] == "UNRESOLVED" for item in presented),
        "confirmed_late_settlements": sum(item["classification"] == "CONFIRMED_LATE" for item in presented),
        "on_time_settlements": sum(item["classification"] == "ON_TIME" for item in presented),
        "settlement_amount_discrepancies": sum(item["classification"] == "SETTLEMENT_AMOUNT_MISMATCH" for item in presented),
        "bank_amount_discrepancies": sum(item["classification"] == "AMOUNT_MISMATCH" and item["category"] == "SETTLEMENT_BANK_RECONCILIATION" for item in presented),
        "unverified_settlements": sum(item["classification"] == "UNVERIFIED" for item in presented),
        "findings_by_layer": {
            layer: sum(item["layer"] == layer for item in presented)
            for layer in sorted({item["layer"] for item in presented})
        },
    }
