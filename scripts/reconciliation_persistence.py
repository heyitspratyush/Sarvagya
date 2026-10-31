"""Persist deterministic reconciliation findings and their evidence."""

import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from pyexasol.exceptions import ExaCommunicationError, ExaConnectionError

from scripts.analytics_connection import (
    ExasolAuthenticationError,
    ExasolConnectionError,
    get_analytics_connection,
)


FINDING_SUMMARY_LIMIT = 2000
LIMITATION_LIMIT = 2000
DEFAULT_EVIDENCE_ROLE = "RELATED_ENTITY"


class PersistenceValidationError(ValueError):
    """A finding cannot be represented safely in the existing schema."""


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Unsupported summary value: {type(value).__name__}")


def _serialize_finding(finding):
    """Create deterministic JSON while retaining evidence and lineage separately."""
    payload = dict(finding)
    # These remain separate properties in the summary: source observations are
    # provenance, not FINDING_EVIDENCE entities.
    summary = json.dumps(
        payload,
        default=_json_default,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    if len(summary) > FINDING_SUMMARY_LIMIT:
        raise PersistenceValidationError(
            f"Serialized finding summary is {len(summary)} characters; "
            f"EVIDENCE_SUMMARY allows {FINDING_SUMMARY_LIMIT}."
        )
    return summary


def _required_string(finding, field, max_length):
    value = finding.get(field)
    if not isinstance(value, str) or not value:
        raise PersistenceValidationError(f"{field} must be a non-empty string.")
    if len(value) > max_length:
        raise PersistenceValidationError(
            f"{field} is {len(value)} characters; schema allows {max_length}."
        )
    return value


def _classification_for_storage(classification):
    """Store long classifications as CLS-<sha256>; full value stays in JSON."""
    if len(classification) <= 40:
        return classification
    return "CLS-" + hashlib.sha256(classification.encode("utf-8")).hexdigest()[:36]


def _decimal_column(value, field):
    if value is None:
        return None
    if isinstance(value, (bool, float)):
        raise PersistenceValidationError(f"{field} must not be a boolean or float.")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise PersistenceValidationError(f"{field} is not a valid Decimal value.") from error
    if not amount.is_finite():
        raise PersistenceValidationError(f"{field} must be finite.")
    if abs(amount) >= Decimal("10000000000"):
        raise PersistenceValidationError(f"{field} exceeds DECIMAL(12,2) range.")
    try:
        if amount.quantize(Decimal("0.01")) != amount:
            raise PersistenceValidationError(f"{field} has more than two fractional digits.")
    except InvalidOperation as error:
        raise PersistenceValidationError(f"{field} cannot fit DECIMAL(12,2).") from error
    return amount


def _timestamp_column(value, field):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return datetime.combine(value, time.min).isoformat(sep=" ")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            try:
                parsed_date = date.fromisoformat(value)
            except ValueError as error:
                raise PersistenceValidationError(f"{field} is not a valid date or timestamp.") from error
            return datetime.combine(parsed_date, time.min).isoformat(sep=" ")
        return parsed.isoformat(sep=" ")
    raise PersistenceValidationError(f"{field} is not a supported date or timestamp.")


def _finding_evidence(finding):
    evidence = finding.get("evidence")
    if evidence is None:
        # Preserve the original unknown-order persistence behavior for the
        # legacy finding, whose engine structure predates evidence arrays.
        attempt_id = finding.get("attempt_id")
        if attempt_id:
            evidence = [{
                "entity_type": "PAYMENT_ATTEMPT",
                "entity_id": attempt_id,
                "evidence_role": "RELATED_ATTEMPT",
            }]
        else:
            evidence = []
    if not isinstance(evidence, (list, tuple)):
        raise PersistenceValidationError("evidence must be a list of entity references.")

    normalized = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise PersistenceValidationError("Each evidence reference must be an object.")
        entity_type = _required_string(item, "entity_type", 30)
        entity_id = _required_string(item, "entity_id", 100)
        role_value = item.get("evidence_role", item.get("role", DEFAULT_EVIDENCE_ROLE))
        if not isinstance(role_value, str) or not role_value:
            raise PersistenceValidationError("evidence_role must be a non-empty string.")
        if len(role_value) > 40:
            raise PersistenceValidationError(
                f"evidence_role is {len(role_value)} characters; schema allows 40."
            )
        normalized.add((entity_type, entity_id, role_value))
    return sorted(normalized)


def _build_persistence_payload(finding):
    finding_id = _required_string(finding, "finding_id", 50)
    finding_type = _required_string(finding, "finding_type", 40)
    classification = _required_string(finding, "classification", 10_000)
    resolution_status = _required_string(finding, "resolution_status", 20)
    stored_classification = _classification_for_storage(classification)

    currency = finding.get("currency")
    if currency is not None:
        if not isinstance(currency, str) or not currency:
            raise PersistenceValidationError("currency must be a non-empty string when supplied.")
        if len(currency) > 3:
            raise PersistenceValidationError("currency exceeds CHAR(3).")

    expected_amount = finding.get("expected_amount")
    if expected_amount is None and "expected_amount" not in finding:
        expected_amount = finding.get("expected_net_amount")
    observed_amount = finding.get("observed_amount")
    if observed_amount is None and "observed_amount" not in finding:
        observed_amount = finding.get("reported_net_amount")
    difference_amount = finding.get("difference_amount")
    if difference_amount is None and "difference_amount" not in finding:
        difference_amount = finding.get("discrepancy")

    limitation = finding.get("limitation")
    if limitation is not None:
        if not isinstance(limitation, str):
            raise PersistenceValidationError("limitation must be text when supplied.")
        if len(limitation) > LIMITATION_LIMIT:
            raise PersistenceValidationError(
                f"LIMITATION is {len(limitation)} characters; schema allows {LIMITATION_LIMIT}."
            )

    summary = _serialize_finding(finding)
    evidence = _finding_evidence(finding)
    return {
        "finding_id": finding_id,
        "finding_type": finding_type,
        "classification": stored_classification,
        "resolution_status": resolution_status,
        "expected_amount": _decimal_column(expected_amount, "expected_amount"),
        "observed_amount": _decimal_column(observed_amount, "observed_amount"),
        "difference_amount": _decimal_column(difference_amount, "difference_amount"),
        "currency": currency,
        "evidence_summary": summary,
        "limitation": limitation,
        "expected_at": _timestamp_column(
            finding.get("expected_at", finding.get("expected_settlement_date")),
            "expected_at",
        ),
        "observed_at": _timestamp_column(
            finding.get("observed_at", finding.get("actual_settlement_timestamp")),
            "observed_at",
        ),
        # delay_days is deliberately retained only in evidence_summary.
        "delay_minutes": _decimal_column(finding.get("delay_minutes"), "delay_minutes"),
        "evidence": evidence,
    }


def _record_exists(connection, query, params):
    statement = connection.execute(query, params)
    return statement.fetchall()[0][0] > 0


def _persistence_error(finding, code, message, connection_usable=True):
    return {
        "finding_inserted": False,
        "evidence_inserted": False,
        "evidence_inserted_count": 0,
        "finding_committed": False,
        "connection_usable": connection_usable,
        "persistence_error": {
            "code": code,
            "message": str(message),
            "finding_id": finding.get("finding_id") if isinstance(finding, dict) else None,
        },
    }


def _is_connection_error(error):
    return isinstance(
        error,
        (ExasolAuthenticationError, ExasolConnectionError, ExaCommunicationError, ExaConnectionError),
    )


def persist_reconciliation_finding(finding, connection=None):
    """Persist one finding atomically, reusing a caller-owned connection when supplied."""
    if not isinstance(finding, dict):
        return _persistence_error({}, "INVALID_FINDING", "finding must be a dictionary.")
    try:
        payload = _build_persistence_payload(finding)
    except (PersistenceValidationError, TypeError, ValueError) as error:
        return _persistence_error(finding, "INVALID_FINDING", error)

    owns_connection = connection is None
    if owns_connection:
        try:
            connection = get_analytics_connection(autocommit=False)
        except ExasolAuthenticationError:
            return _persistence_error(
                finding,
                "AUTHENTICATION_ERROR",
                "Exasol authentication failed or could not be completed securely.",
                connection_usable=False,
            )
        except ExasolConnectionError:
            return _persistence_error(
                finding,
                "CONNECTION_ERROR",
                "Could not connect to Exasol for finding persistence.",
                connection_usable=False,
            )
        except Exception:
            return _persistence_error(
                finding,
                "CONNECTION_ERROR",
                "Exasol connection setup failed.",
                connection_usable=False,
            )

    finding_inserted = False
    evidence_inserted_count = 0
    finding_committed = False
    original_autocommit = getattr(connection, "options", {}).get("autocommit", False)
    restore_autocommit = bool(original_autocommit)
    result = None
    transaction_usable = True
    try:
        connection.set_autocommit(False)
        existing_statement = connection.execute(
            """
            SELECT EVIDENCE_SUMMARY
            FROM SARVAGYA.RECONCILIATION_FINDINGS
            WHERE FINDING_ID = {finding_id}
            """,
            {"finding_id": payload["finding_id"]},
        )
        existing_rows = existing_statement.fetchall()
        if existing_rows:
            existing_summary = existing_rows[0][0]
            if existing_summary != payload["evidence_summary"]:
                connection.rollback()
                result = _persistence_error(
                    finding,
                    "FINDING_ID_CONFLICT",
                    "The finding ID already exists with different serialized details; "
                    "existing finding and evidence were left unchanged.",
                )
                return result
        else:
            connection.execute(
                """
                INSERT INTO SARVAGYA.RECONCILIATION_FINDINGS (
                    FINDING_ID, FINDING_TYPE, CLASSIFICATION, RESOLUTION_STATUS,
                    EXPECTED_AMOUNT, OBSERVED_AMOUNT, DIFFERENCE_AMOUNT, CURRENCY,
                    EVIDENCE_SUMMARY, LIMITATION, CREATED_AT, EXPECTED_AT,
                    OBSERVED_AT, DELAY_MINUTES
                )
                VALUES (
                    {finding_id}, {finding_type}, {classification}, {resolution_status},
                    CAST({expected_amount} AS DECIMAL(12,2)),
                    CAST({observed_amount} AS DECIMAL(12,2)),
                    CAST({difference_amount} AS DECIMAL(12,2)),
                    {currency}, {evidence_summary}, {limitation}, CURRENT_TIMESTAMP,
                    CAST({expected_at} AS TIMESTAMP), CAST({observed_at} AS TIMESTAMP),
                    CAST({delay_minutes} AS DECIMAL(12,2))
                )
                """,
                {key: payload[key] for key in (
                    "finding_id", "finding_type", "classification", "resolution_status",
                    "expected_amount", "observed_amount", "difference_amount", "currency",
                    "evidence_summary", "limitation", "expected_at", "observed_at",
                    "delay_minutes",
                )},
            )
            finding_inserted = True

        for entity_type, entity_id, evidence_role in payload["evidence"]:
            exists = _record_exists(
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
                    "finding_id": payload["finding_id"],
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "evidence_role": evidence_role,
                },
            )
            if exists:
                continue
            connection.execute(
                """
                INSERT INTO SARVAGYA.FINDING_EVIDENCE (
                    FINDING_ID, ENTITY_TYPE, ENTITY_ID, EVIDENCE_ROLE
                )
                VALUES ({finding_id}, {entity_type}, {entity_id}, {evidence_role})
                """,
                {
                    "finding_id": payload["finding_id"],
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "evidence_role": evidence_role,
                },
            )
            evidence_inserted_count += 1

        connection.commit()
        finding_committed = True
        result = {
            "finding_inserted": finding_inserted,
            "evidence_inserted": evidence_inserted_count > 0,
            "evidence_inserted_count": evidence_inserted_count,
            "finding_committed": True,
            "connection_usable": True,
            "persistence_error": None,
        }
    except Exception as error:
        try:
            connection.rollback()
        except Exception:
            transaction_usable = False
        connection_failure = _is_connection_error(error) or not transaction_usable
        safe_message = (
            "Exasol connection failed during finding persistence; the connection is not safe to reuse."
            if connection_failure
            else f"Finding persistence failed ({type(error).__name__}); this finding was rolled back."
        )
        result = _persistence_error(
            finding,
            "CONNECTION_ERROR" if connection_failure else "DATABASE_PERSISTENCE_ERROR",
            safe_message,
            connection_usable=not connection_failure,
        )
    finally:
        if restore_autocommit and transaction_usable:
            try:
                connection.set_autocommit(True)
            except Exception:
                transaction_usable = False
                if result is None:
                    result = {
                        "finding_inserted": finding_inserted,
                        "evidence_inserted": evidence_inserted_count > 0,
                        "evidence_inserted_count": evidence_inserted_count,
                        "finding_committed": finding_committed,
                        "connection_usable": False,
                        "persistence_error": {
                            "code": "CONNECTION_STATE_ERROR",
                            "message": "Could not restore the Exasol connection's autocommit setting.",
                            "finding_id": payload["finding_id"],
                        },
                    }
                else:
                    result["connection_usable"] = False
                    result["connection_state_error"] = (
                        "Could not restore the Exasol connection's autocommit setting."
                    )
        if owns_connection:
            try:
                connection.close()
            except Exception:
                if result is None:
                    result = {
                        "finding_inserted": finding_inserted,
                        "evidence_inserted": evidence_inserted_count > 0,
                        "evidence_inserted_count": evidence_inserted_count,
                        "finding_committed": finding_committed,
                        "connection_usable": False,
                        "persistence_error": None,
                        "cleanup_error": {
                            "code": "CONNECTION_CLOSE_ERROR",
                            "message": "Finding persistence completed, but the Exasol connection did not close cleanly.",
                            "finding_id": payload["finding_id"],
                        },
                    }
                else:
                    result["cleanup_error"] = {
                        "code": "CONNECTION_CLOSE_ERROR",
                        "message": "The Exasol connection did not close cleanly.",
                        "finding_id": payload["finding_id"],
                    }
    return result


def persist_unlinked_attempt_finding(finding, connection=None):
    """Backward-compatible wrapper for the generic finding persister."""
    return persist_reconciliation_finding(finding, connection=connection)
