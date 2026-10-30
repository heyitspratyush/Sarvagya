
"""Run reconciliation and persist supported findings."""

from scripts.reconciliation_data import fetch_order_attempt_data
from scripts.reconciliation_engine import reconcile_order_attempts
from scripts.reconciliation_persistence import (
    persist_unlinked_attempt_finding,
)


def run_reconciliation():
    """Fetch data, reconcile it, and persist supported findings."""

    # 1. Retrieve source records from Exasol.
    orders, attempts = fetch_order_attempt_data()

    # 2. Run deterministic reconciliation.
    result = reconcile_order_attempts(orders, attempts)

    findings = result["findings"]

    # 3. Persist findings supported by the current persistence layer.
    persisted_count = 0
    already_existing_count = 0
    unsupported_findings = []

    for finding in findings:

        if finding["classification"] != "ATTEMPT_REFERENCES_UNKNOWN_ORDER":
            unsupported_findings.append(finding)
            continue

        persistence_result = persist_unlinked_attempt_finding(finding)

        if (
            persistence_result["finding_inserted"]
            or persistence_result["evidence_inserted"]
        ):
            persisted_count += 1
        else:
            already_existing_count += 1

    # 4. Return a summary of the complete run.
    return {
        "orders_processed": len(orders),
        "attempts_processed": len(attempts),
        "findings_generated": len(findings),
        "findings_persisted": persisted_count,
        "findings_already_existing": already_existing_count,
        "unsupported_findings": unsupported_findings,
        "reconciliation_result": result,
    }


if __name__ == "__main__":
    summary = run_reconciliation()

    print("\n========== SETTLEMENTLENS RECONCILIATION ==========")
    print("Orders processed:", summary["orders_processed"])
    print("Attempts processed:", summary["attempts_processed"])
    print("Findings generated:", summary["findings_generated"])
    print("New findings persisted:", summary["findings_persisted"])
    print("Existing findings:", summary["findings_already_existing"])
    print("Unsupported findings:", len(summary["unsupported_findings"]))
    print("===================================================")
