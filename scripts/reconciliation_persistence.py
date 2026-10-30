
"""Persist reconciliation findings and their supporting evidence."""

from scripts.analytics_connection import get_analytics_connection


def _record_exists(connection, query, params):
    """Check whether a record already exists in Exasol."""
    statement = connection.execute(query, params)
    return statement.fetchall()[0][0] > 0


def persist_unlinked_attempt_finding(finding):
    """
    Persist an unknown-order finding and its supporting payment-attempt
    evidence in one transaction.

    Repeated executions avoid inserting records that already exist.
    """
    required_fields = (
        "finding_id",
        "finding_type",
        "classification",
        "resolution_status",
        "attempt_id",
        "order_id",
    )

    for field in required_fields:
        if not finding.get(field):
            raise ValueError(f"Missing required finding field: {field}")

    connection = get_analytics_connection(autocommit=False)

    try:
        finding_exists = _record_exists(
            connection,
            """
            SELECT COUNT(*)
            FROM SARVAGYA.RECONCILIATION_FINDINGS
            WHERE FINDING_ID = {finding_id}
            """,
            {"finding_id": finding["finding_id"]},
        )

        finding_inserted = False

        if not finding_exists:
            connection.execute(
                """
                INSERT INTO SARVAGYA.RECONCILIATION_FINDINGS (
                    FINDING_ID,
                    FINDING_TYPE,
                    CLASSIFICATION,
                    RESOLUTION_STATUS,
                    EXPECTED_AMOUNT,
                    OBSERVED_AMOUNT,
                    DIFFERENCE_AMOUNT,
                    CURRENCY,
                    EVIDENCE_SUMMARY,
                    LIMITATION,
                    CREATED_AT,
                    EXPECTED_AT,
                    OBSERVED_AT,
                    DELAY_MINUTES
                )
                VALUES (
                    {finding_id},
                    {finding_type},
                    {classification},
                    {resolution_status},
                    CAST({expected_amount} AS DECIMAL(12,2)),
                    CAST({observed_amount} AS DECIMAL(12,2)),
                    CAST({difference_amount} AS DECIMAL(12,2)),
                    {currency},
                    {evidence_summary},
                    {limitation},
                    CURRENT_TIMESTAMP,
                    NULL,
                    NULL,
                    NULL
                )
                """,
                {
                    "finding_id": finding["finding_id"],
                    "finding_type": finding["finding_type"],
                    "classification": finding["classification"],
                    "resolution_status": finding["resolution_status"],
                    "expected_amount": finding.get("expected_amount"),
                    "observed_amount": finding.get("observed_amount"),
                    "difference_amount": finding.get("difference_amount"),
                    "currency": finding.get("currency"),
                    "evidence_summary": (
                        f"Payment attempt {finding['attempt_id']} "
                        f"references order {finding['order_id']}, "
                        "which was not found."
                    ),
                    "limitation": finding.get("limitation"),
                },
            )

            finding_inserted = True

        evidence_exists = _record_exists(
            connection,
            """
            SELECT COUNT(*)
            FROM SARVAGYA.FINDING_EVIDENCE
            WHERE FINDING_ID = {finding_id}
              AND ENTITY_TYPE = {entity_type}
              AND ENTITY_ID = {entity_id}
              AND EVIDENCE_ROLE = {evidence_role}
            """,
            {
                "finding_id": finding["finding_id"],
                "entity_type": "PAYMENT_ATTEMPT",
                "entity_id": finding["attempt_id"],
                "evidence_role": "RELATED_ATTEMPT",
            },
        )

        evidence_inserted = False

        if not evidence_exists:
            connection.execute(
                """
                INSERT INTO SARVAGYA.FINDING_EVIDENCE (
                    FINDING_ID,
                    ENTITY_TYPE,
                    ENTITY_ID,
                    EVIDENCE_ROLE
                )
                VALUES (
                    {finding_id},
                    {entity_type},
                    {entity_id},
                    {evidence_role}
                )
                """,
                {
                    "finding_id": finding["finding_id"],
                    "entity_type": "PAYMENT_ATTEMPT",
                    "entity_id": finding["attempt_id"],
                    "evidence_role": "RELATED_ATTEMPT",
                },
            )

            evidence_inserted = True

        connection.commit()

        return {
            "finding_inserted": finding_inserted,
            "evidence_inserted": evidence_inserted,
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()
