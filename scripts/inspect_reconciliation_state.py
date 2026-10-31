"""Read-only SettlementLens state inspector and human-readable findings view."""

import argparse
import json

from scripts.analytics_connection import get_analytics_connection
from scripts.finding_presentation import (
    format_amount,
    format_date,
    present_finding,
    summarize_findings,
)


QUERIES = (
    (
        "Total findings",
        "SELECT COUNT(*) AS FINDING_COUNT "
        "FROM SARVAGYA.RECONCILIATION_FINDINGS",
    ),
    (
        "Total finding evidence",
        "SELECT COUNT(*) AS EVIDENCE_COUNT "
        "FROM SARVAGYA.FINDING_EVIDENCE",
    ),
    (
        "Findings by type, classification and resolution status",
        """SELECT FINDING_TYPE, CLASSIFICATION, RESOLUTION_STATUS,
                  COUNT(*) AS RECORD_COUNT
           FROM SARVAGYA.RECONCILIATION_FINDINGS
           GROUP BY FINDING_TYPE, CLASSIFICATION, RESOLUTION_STATUS
           ORDER BY FINDING_TYPE, CLASSIFICATION, RESOLUTION_STATUS""",
    ),
    (
        "Evidence by entity type and role",
        """SELECT ENTITY_TYPE, EVIDENCE_ROLE, COUNT(*) AS EVIDENCE_COUNT
           FROM SARVAGYA.FINDING_EVIDENCE
           GROUP BY ENTITY_TYPE, EVIDENCE_ROLE
           ORDER BY ENTITY_TYPE, EVIDENCE_ROLE""",
    ),
    (
        "Findings without evidence",
        """SELECT F.FINDING_ID, F.FINDING_TYPE, F.CLASSIFICATION,
                  F.RESOLUTION_STATUS
           FROM SARVAGYA.RECONCILIATION_FINDINGS F
           LEFT JOIN SARVAGYA.FINDING_EVIDENCE E
               ON F.FINDING_ID = E.FINDING_ID
           WHERE E.FINDING_ID IS NULL""",
    ),
    (
        "Evidence without findings",
        """SELECT E.*
           FROM SARVAGYA.FINDING_EVIDENCE E
           LEFT JOIN SARVAGYA.RECONCILIATION_FINDINGS F
               ON E.FINDING_ID = F.FINDING_ID
           WHERE F.FINDING_ID IS NULL""",
    ),
    (
        "Findings and evidence details",
        """SELECT F.FINDING_ID, F.FINDING_TYPE, F.CLASSIFICATION,
                  E.ENTITY_TYPE, E.ENTITY_ID, E.EVIDENCE_ROLE
           FROM SARVAGYA.RECONCILIATION_FINDINGS F
           LEFT JOIN SARVAGYA.FINDING_EVIDENCE E
               ON F.FINDING_ID = E.FINDING_ID
           ORDER BY F.FINDING_ID, E.ENTITY_TYPE, E.ENTITY_ID""",
    ),
    (
        "Orders",
        "SELECT COUNT(*) AS RECORD_COUNT FROM SARVAGYA.ORDERS",
    ),
    (
        "Payment attempts",
        "SELECT COUNT(*) AS RECORD_COUNT FROM SARVAGYA.PAYMENT_ATTEMPTS",
    ),
    (
        "Processor transactions",
        "SELECT COUNT(*) AS RECORD_COUNT FROM SARVAGYA.PROCESSOR_TRANSACTIONS",
    ),
    (
        "Settlements",
        "SELECT COUNT(*) AS RECORD_COUNT FROM SARVAGYA.SETTLEMENTS",
    ),
    (
        "Bank transactions",
        "SELECT COUNT(*) AS RECORD_COUNT FROM SARVAGYA.BANK_TRANSACTIONS",
    ),
)


EVIDENCE_REFERENCE_QUERY = """SELECT E.FINDING_ID, E.ENTITY_TYPE, E.ENTITY_ID,
       E.EVIDENCE_ROLE, 'PAYMENT_ATTEMPTS' AS SOURCE_TABLE,
       COALESCE(S.MATCH_COUNT, 0) AS SOURCE_MATCH_COUNT
FROM SARVAGYA.FINDING_EVIDENCE E
LEFT JOIN (
    SELECT ATTEMPT_ID, COUNT(*) AS MATCH_COUNT
    FROM SARVAGYA.PAYMENT_ATTEMPTS
    GROUP BY ATTEMPT_ID
) S ON E.ENTITY_TYPE = 'PAYMENT_ATTEMPT' AND E.ENTITY_ID = S.ATTEMPT_ID
WHERE E.ENTITY_TYPE = 'PAYMENT_ATTEMPT'
UNION ALL
SELECT E.FINDING_ID, E.ENTITY_TYPE, E.ENTITY_ID,
       E.EVIDENCE_ROLE, 'PROCESSOR_TRANSACTIONS',
       COALESCE(S.MATCH_COUNT, 0)
FROM SARVAGYA.FINDING_EVIDENCE E
LEFT JOIN (
    SELECT PROCESSOR_TXN_ID, COUNT(*) AS MATCH_COUNT
    FROM SARVAGYA.PROCESSOR_TRANSACTIONS
    GROUP BY PROCESSOR_TXN_ID
) S ON E.ENTITY_TYPE = 'PROCESSOR_TRANSACTION'
   AND E.ENTITY_ID = S.PROCESSOR_TXN_ID
WHERE E.ENTITY_TYPE = 'PROCESSOR_TRANSACTION'
UNION ALL
SELECT E.FINDING_ID, E.ENTITY_TYPE, E.ENTITY_ID,
       E.EVIDENCE_ROLE, 'SETTLEMENTS',
       COALESCE(S.MATCH_COUNT, 0)
FROM SARVAGYA.FINDING_EVIDENCE E
LEFT JOIN (
    SELECT BATCH_ID, COUNT(*) AS MATCH_COUNT
    FROM SARVAGYA.SETTLEMENTS
    GROUP BY BATCH_ID
) S ON E.ENTITY_TYPE = 'SETTLEMENT_HEADER' AND E.ENTITY_ID = S.BATCH_ID
WHERE E.ENTITY_TYPE = 'SETTLEMENT_HEADER'
UNION ALL
SELECT E.FINDING_ID, E.ENTITY_TYPE, E.ENTITY_ID,
       E.EVIDENCE_ROLE, 'SETTLEMENT_TRANSACTIONS',
       COALESCE(S.MATCH_COUNT, 0)
FROM SARVAGYA.FINDING_EVIDENCE E
LEFT JOIN (
    SELECT PROCESSOR_TXN_ID, COUNT(*) AS MATCH_COUNT
    FROM SARVAGYA.SETTLEMENT_TRANSACTIONS
    GROUP BY PROCESSOR_TXN_ID
) S ON E.ENTITY_TYPE = 'SETTLEMENT_TRANSACTION'
   AND E.ENTITY_ID = S.PROCESSOR_TXN_ID
WHERE E.ENTITY_TYPE = 'SETTLEMENT_TRANSACTION'
UNION ALL
SELECT E.FINDING_ID, E.ENTITY_TYPE, E.ENTITY_ID,
       E.EVIDENCE_ROLE, 'BANK_TRANSACTIONS',
       COALESCE(S.MATCH_COUNT, 0)
FROM SARVAGYA.FINDING_EVIDENCE E
LEFT JOIN (
    SELECT BANK_TXN_ID, COUNT(*) AS MATCH_COUNT
    FROM SARVAGYA.BANK_TRANSACTIONS
    GROUP BY BANK_TXN_ID
) S ON E.ENTITY_TYPE = 'BANK_TRANSACTION' AND E.ENTITY_ID = S.BANK_TXN_ID
WHERE E.ENTITY_TYPE = 'BANK_TRANSACTION'
UNION ALL
SELECT E.FINDING_ID, E.ENTITY_TYPE, E.ENTITY_ID,
       E.EVIDENCE_ROLE, CAST(NULL AS VARCHAR(128)) AS SOURCE_TABLE,
       CAST(NULL AS DECIMAL(18, 0)) AS SOURCE_MATCH_COUNT
FROM SARVAGYA.FINDING_EVIDENCE E
WHERE E.ENTITY_TYPE NOT IN (
    'PAYMENT_ATTEMPT', 'PROCESSOR_TRANSACTION', 'SETTLEMENT_HEADER',
    'SETTLEMENT_TRANSACTION', 'BANK_TRANSACTION'
)
ORDER BY FINDING_ID, ENTITY_TYPE, ENTITY_ID, EVIDENCE_ROLE"""


def inspect_evidence_references(connection):
    """Print a per-evidence-row referential-integrity report and summary."""
    statement = connection.execute(EVIDENCE_REFERENCE_QUERY)
    rows = statement.fetchall()

    valid = sum(match_count == 1 for *_, match_count in rows if match_count is not None)
    missing = sum(match_count == 0 for *_, match_count in rows if match_count is not None)
    duplicates = sum(match_count > 1 for *_, match_count in rows if match_count is not None)
    unknown = sum(match_count is None for *_, match_count in rows)

    print("\nEvidence referential integrity")
    print("Columns: FINDING_ID, ENTITY_TYPE, ENTITY_ID, EVIDENCE_ROLE, "
          "SOURCE_TABLE, SOURCE_MATCH_COUNT, REFERENCE_STATUS")
    for finding_id, entity_type, entity_id, role, source_table, match_count in rows:
        if match_count is None:
            status = "UNKNOWN_ENTITY_TYPE"
        elif match_count == 0:
            status = "MISSING_REFERENCE"
        elif match_count > 1:
            status = "DUPLICATE_SOURCE_IDENTITY"
        else:
            status = "VALID"
        print((finding_id, entity_type, entity_id, role, source_table, match_count, status))
    if not rows:
        print("(no evidence rows)")

    print("Total evidence records checked:", len(rows))
    print("Valid references:", valid)
    print("Missing references:", missing)
    print("Unknown entity types:", unknown)
    print("Duplicate source identity matches:", duplicates)


def fetch_persisted_findings(connection):
    """Read persisted finding rows and evidence without changing database state."""
    statement = connection.execute("""
        SELECT FINDING_ID, FINDING_TYPE, CLASSIFICATION, RESOLUTION_STATUS,
               EXPECTED_AMOUNT, OBSERVED_AMOUNT, DIFFERENCE_AMOUNT, CURRENCY,
               EVIDENCE_SUMMARY, LIMITATION, EXPECTED_AT, OBSERVED_AT,
               DELAY_MINUTES
        FROM SARVAGYA.RECONCILIATION_FINDINGS
        ORDER BY CREATED_AT DESC, FINDING_ID
    """)
    columns = statement.column_names()
    findings = [dict(zip(columns, row)) for row in statement.fetchall()]
    evidence_statement = connection.execute("""
        SELECT FINDING_ID, ENTITY_TYPE, ENTITY_ID, EVIDENCE_ROLE
        FROM SARVAGYA.FINDING_EVIDENCE
        ORDER BY FINDING_ID, ENTITY_TYPE, ENTITY_ID, EVIDENCE_ROLE
    """)
    evidence_by_finding = {}
    for finding_id, entity_type, entity_id, role in evidence_statement.fetchall():
        evidence_by_finding.setdefault(finding_id, []).append({
            "entity_type": entity_type,
            "entity_id": entity_id,
            "evidence_role": role,
        })
    for finding in findings:
        finding["evidence"] = evidence_by_finding.get(finding["FINDING_ID"], [])
    return findings


def _safe_text(value):
    """Avoid terminal control sequences in values originating from source data."""
    text = str(value)
    return "".join(char if char.isprintable() else " " for char in text)


def _finding_matches(item, status=None, layer=None, search=None):
    if status and item["status"].casefold() != status.casefold():
        return False
    if layer and item["layer"].casefold() != layer.casefold():
        return False
    if search:
        haystack = " ".join((
            item["title"], item["summary"], item["explanation"],
            item["finding_reference"], item["classification"] or "",
            " ".join(str(ref["value"]) for ref in item["references"]),
        )).casefold()
        if search.casefold() not in haystack:
            return False
    return True


def _render_findings(connection, status=None, layer=None, search=None, detail=None, technical=False):
    rows = fetch_persisted_findings(connection)
    presented = [present_finding(row, row.get("evidence", [])) for row in rows]
    by_id = {item["finding_reference"]: item for item in presented}
    if detail:
        selected = by_id.get(detail)
        if selected is None:
            prefix_matches = [item for key, item in by_id.items() if key.startswith(detail)]
            if len(prefix_matches) == 1:
                selected = prefix_matches[0]
            elif len(prefix_matches) > 1:
                print("That reference prefix matches multiple findings; use a longer or full ID.")
                return 1
        if selected is None:
            print(f"No finding matches reference: {_safe_text(detail)}")
            return 1
        _print_finding_detail(selected, technical=technical)
        return 0

    matches = [item for item in presented if _finding_matches(item, status, layer, search)]
    overview = summarize_findings(rows)
    print("SettlementLens terminal investigation report")
    print(f"Total findings: {overview['total_findings']}")
    print(f"Unresolved findings: {overview['unresolved_findings']}")
    print(f"Confirmed late settlements: {overview['confirmed_late_settlements']}")
    print(f"On-time settlements: {overview['on_time_settlements']}")
    print(f"Settlement amount discrepancies: {overview['settlement_amount_discrepancies']}")
    print(f"Bank amount discrepancies: {overview['bank_amount_discrepancies']}")
    print(f"Unverified settlements: {overview['unverified_settlements']}")
    print(
        "Count definitions: unresolved uses stored UNRESOLVED status; late, on-time, "
        "unverified and amount discrepancies use their finding classifications. "
        "Settlement-header and bank amount discrepancies are counted separately."
    )
    print("Findings by layer:")
    for name, count in overview["findings_by_layer"].items():
        print(f"  {_safe_text(name)}: {count}")
    print(f"\nFindings ({len(matches)} shown of {len(presented)}; use --help for filters)")
    if not matches:
        print("No findings match these filters." if any((status, layer, search)) else "No persisted findings are available.")
        return 0
    for item in matches:
        refs = ", ".join(
            f"{_safe_text(ref['label'])}: {_safe_text(ref['value'])}"
            for ref in item["references"][:3]
        ) or "Business reference unavailable"
        amount_parts = []
        if item["expected_amount"] is not None:
            amount_parts.append(f"expected {item['expected_amount_display']}")
        if item["observed_amount"] is not None:
            amount_parts.append(f"observed {item['observed_amount_display']}")
        if item["difference"] is not None:
            amount_parts.append(f"difference {item['difference_display']}")
        amount_text = " | ".join(amount_parts)
        print(f"\n{_safe_text(item['title'])} [{_safe_text(item['status'])}]")
        print(f"  Layer: {_safe_text(item['layer'])}")
        print(f"  Reference: {_safe_text(item['short_finding_reference'])}")
        print(f"  Affected: {refs}")
        if amount_text:
            print(f"  Amounts: {amount_text}")
        if item["expected_date_display"] != "Not available" or item["actual_date_display"] != "Not available":
            print(f"  Dates: expected {item['expected_date_display']}; actual {item['actual_date_display']}")
        print(f"  { _safe_text(item['summary']) }")
    return 0


def _print_finding_detail(item, technical=False):
    print(_safe_text(item["title"]))
    print(f"Status: {_safe_text(item['status'])}")
    print(f"Layer: {_safe_text(item['layer'])}")
    print(f"Finding reference: {_safe_text(item['short_finding_reference'])}")
    print(f"\nWhat happened: {_safe_text(item['explanation'])}")
    print("\nAffected references:")
    if item["references"]:
        for ref in item["references"]:
            print(f"  { _safe_text(ref['label']) }: {_safe_text(ref['value'])}")
    else:
        print("  Not available")
    print("\nAmounts:")
    print(f"  Expected: {item['expected_amount_display']}")
    print(f"  Observed: {item['observed_amount_display']}")
    print(f"  Difference: {item['difference_display']}")
    if item["difference_convention"]:
        print(f"  Sign convention: {_safe_text(item['difference_convention'])}")
    if item["currency"]:
        print(f"  Currency: {_safe_text(item['currency'])}")
    for component in item["financial_components"]:
        print(f"  {component['label']}: {component['display']}")
    print("\nDates:")
    print(f"  Expected: {item['expected_date_display']}")
    print(f"  Actual: {item['actual_date_display']}")
    if item["delay_days"] is not None:
        print(f"  Delay: {_safe_text(item['delay_days'])} calendar days")
    elif item["delay_minutes"] is not None:
        print(f"  Delay: {_safe_text(item['delay_minutes'])} minutes")
    print("\nEvidence:")
    if item["evidence"]:
        for evidence in item["evidence"]:
            print(f"  {_format_evidence(evidence)}")
    else:
        print("  No evidence references are available.")
    if item["candidates"]:
        print("\nPreserved candidates (no candidate selected by presentation):")
        for index, candidate in enumerate(item["candidates"], 1):
            if isinstance(candidate, dict):
                details = _candidate_details(candidate)
            else:
                details = _safe_text(candidate)
            print(f"  Candidate {index}: {details}")
    print("\nSource-row lineage:")
    if item["source_row_lineage"]:
        for source in item["source_row_lineage"]:
            if isinstance(source, dict):
                labels = {
                    "SOURCE_ROW_ID": "Source row",
                    "SOURCE_FILE": "Source file",
                    "SOURCE_ROW_NUMBER": "Source row number",
                    "PROCESSOR_TXN_ID": "Processor transaction",
                    "IMPORTED_AT": "Imported at",
                }
                details = ", ".join(
                    f"{labels.get(key, key.replace('_', ' ').title())}: {_safe_text(value)}"
                    for key, value in source.items()
                )
                print(f"  {details}")
            else:
                print(f"  {_safe_text(source)}")
    else:
        print("  Not available")
    print("\nLimitations and unresolved questions:")
    if item["limitations"]:
        for limitation in item["limitations"]:
            print(f"  {_safe_text(limitation)}")
    else:
        print("  No additional limitation was stored.")
    print("\nSuggested checks:")
    for check in item["suggested_checks"]:
        print(f"  {_safe_text(check)}")
    if technical:
        print("\nTechnical details:")
        for key, value in item["technical_details"].items():
            if key == "evidence_summary":
                print("  EVIDENCE_SUMMARY:")
                try:
                    parsed = json.loads(value) if isinstance(value, str) else value
                    print(json.dumps(parsed, indent=2, ensure_ascii=False, default=str))
                except (json.JSONDecodeError, TypeError):
                    print(_safe_text(value))
            else:
                print(f"  {key}: {_safe_text(value)}")


def _candidate_details(candidate):
    labels = {
        "BANK_TXN_ID": "Bank transaction",
        "BANK_REFERENCE": "Bank reference",
        "AMOUNT": "Amount",
        "CURRENCY": "Currency",
        "TRANSACTION_AT": "Transaction date",
        "BATCH_ID": "Settlement batch",
        "PROCESSOR_TXN_ID": "Processor transaction",
        "GROSS_AMOUNT": "Gross",
        "FEE_AMOUNT": "Fees",
        "REFUND_AMOUNT": "Refunds",
        "CHARGEBACK_AMOUNT": "Chargebacks",
        "ADJUSTMENT_AMOUNT": "Adjustments",
        "REPORTED_NET_AMOUNT": "Reported net",
        "EXPECTED_SETTLEMENT_DATE": "Expected date",
        "SETTLED_AT": "Settled at",
    }
    currency = candidate.get("CURRENCY")
    details = []
    for key, value in candidate.items():
        if key in {"AMOUNT", "GROSS_AMOUNT", "FEE_AMOUNT", "REFUND_AMOUNT", "CHARGEBACK_AMOUNT", "ADJUSTMENT_AMOUNT", "REPORTED_NET_AMOUNT"}:
            rendered = format_amount(value, currency)
        elif key in {"TRANSACTION_AT", "EXPECTED_SETTLEMENT_DATE", "SETTLED_AT"}:
            rendered = format_date(value)
        else:
            rendered = _safe_text(value)
        details.append(f"{labels.get(key, key.replace('_', ' ').title())}: {rendered}")
    return "; ".join(details)


def _format_evidence(evidence):
    if not isinstance(evidence, dict):
        return _safe_text(evidence)
    entity_type = evidence.get("entity_type", evidence.get("ENTITY_TYPE", "Evidence"))
    entity_id = evidence.get("entity_id", evidence.get("ENTITY_ID"))
    role = evidence.get("evidence_role", evidence.get("EVIDENCE_ROLE"))
    batch_id = evidence.get("batch_id", evidence.get("BATCH_ID"))
    pieces = [str(entity_type).replace("_", " ").title()]
    if entity_id is not None:
        pieces[-1] += f": {_safe_text(entity_id)}"
    if batch_id is not None:
        pieces.append(f"Settlement batch: {_safe_text(batch_id)}")
    if role is not None:
        pieces.append(f"Role: {str(role).replace('_', ' ').title()}")
    return "; ".join(pieces)


def _arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only terminal report for SettlementLens findings. This is not a graphical UI."
    )
    parser.add_argument("view", nargs="?", choices=("state", "findings"), default="state")
    parser.add_argument("--status", help="Filter by displayed status, e.g. Unresolved or Confirmed late")
    parser.add_argument("--layer", help="Filter by reconciliation layer")
    parser.add_argument("--search", help="Search titles, explanations and business references")
    parser.add_argument("--show", help="Show a finding detail by full or unique ID prefix")
    parser.add_argument("--technical", action="store_true", help="With --show, include full IDs and raw serialized payload")
    return parser.parse_args(argv)


def main(argv=None):
    args = _arguments(argv)
    if args.technical and (args.view != "findings" or not args.show):
        raise SystemExit("Use --technical with 'findings --show <finding-id>'.")
    if args.view == "state" and any((args.status, args.layer, args.search, args.show)):
        raise SystemExit("Findings filters require the 'findings' view.")
    connection = get_analytics_connection()
    try:
        if args.view == "findings":
            return _render_findings(
                connection, args.status, args.layer, args.search, args.show, args.technical
            )
        for title, query in QUERIES:
            statement = connection.execute(query)
            print(f"\n{title}")
            print("Columns:", ", ".join(statement.column_names()))
            rows = statement.fetchall()
            if rows:
                for row in rows:
                    print(row)
            else:
                print("(no rows)")
        inspect_evidence_references(connection)
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
