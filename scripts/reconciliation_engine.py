import hashlib
import json


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
