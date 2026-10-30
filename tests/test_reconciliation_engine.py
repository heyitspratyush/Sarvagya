from scripts.reconciliation_engine import (
    build_order_lookup,
    group_attempts_by_order,
    make_unlinked_attempt_finding,
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
