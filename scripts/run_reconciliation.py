
"""Run reconciliation and persist supported findings."""

import sys

from scripts.analytics_connection import ExasolConnectionError, get_analytics_connection
from scripts.reconciliation_data import fetch_order_attempt_data
from scripts.reconciliation_engine import reconcile_orders_attempts_processor_and_settlement
from scripts.reconciliation_persistence import persist_reconciliation_finding


def run_reconciliation():
    """Fetch data, reconcile it, and persist supported findings."""

    connection = None
    run_summary = None
    try:
        connection = get_analytics_connection(autocommit=False)

        # Fetch all source tables over this one authenticated connection.
        (
            orders,
            attempts,
            processor_transactions,
            processor_source_rows,
            settlements,
            settlement_transactions,
            bank_transactions,
        ) = fetch_order_attempt_data(connection=connection)
        # Close the read phase before beginning the independent finding writes.
        connection.commit()

        result = reconcile_orders_attempts_processor_and_settlement(
            orders, attempts, processor_transactions, processor_source_rows,
            settlements, settlement_transactions, bank_transactions,
        )
        findings = result["findings"]

        persisted_count = 0
        already_existing_count = 0
        persistence_errors = []
        findings_not_attempted = []

        for index, finding in enumerate(findings):
            persistence_result = persist_reconciliation_finding(
                finding, connection=connection
            )
            error = persistence_result.get("persistence_error")
            if error:
                persistence_errors.append(error)
                if persistence_result.get("finding_committed"):
                    persisted_count += 1
                if not persistence_result.get("connection_usable", True):
                    findings_not_attempted = [
                        item.get("finding_id") for item in findings[index + 1:]
                    ]
                    break
                continue

            if (
                persistence_result["finding_inserted"]
                or persistence_result["evidence_inserted"]
            ):
                persisted_count += 1
            else:
                already_existing_count += 1

        run_summary = {
            "orders_processed": len(orders),
            "attempts_processed": len(attempts),
            "findings_generated": len(findings),
            "findings_persisted": persisted_count,
            "findings_already_existing": already_existing_count,
            "unsupported_findings": [],
            "persistence_errors": persistence_errors,
            "findings_not_attempted": findings_not_attempted,
            "cleanup_errors": [],
            "reconciliation_result": result,
        }
        return run_summary
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                # Preserve any active reconciliation/persistence exception.
                active_error = sys.exc_info()[1]
                if run_summary is not None:
                    run_summary["cleanup_errors"].append({
                        "code": "CONNECTION_CLOSE_ERROR",
                        "message": "The reconciliation connection did not close cleanly.",
                    })
                elif active_error is None:
                    raise ExasolConnectionError(
                        "The reconciliation run completed, but its Exasol connection did not close cleanly."
                    ) from None
                if hasattr(active_error, "add_note"):
                    active_error.add_note(
                        "The Exasol connection also failed to close cleanly."
                    )


if __name__ == "__main__":
    summary = run_reconciliation()

    print("\n========== SETTLEMENTLENS RECONCILIATION ==========")
    print("Orders processed:", summary["orders_processed"])
    print("Attempts processed:", summary["attempts_processed"])
    print("Findings generated:", summary["findings_generated"])
    print("New findings persisted:", summary["findings_persisted"])
    print("Existing findings:", summary["findings_already_existing"])
    print("Persistence errors:", len(summary["persistence_errors"]))
    print("===================================================")
