"""Tests for SettlementLens Merchant GUI module."""

import pytest
from pathlib import Path

from gui.scenario_fixtures import (
    get_available_scenarios,
    load_scenario,
    load_combined_scenarios,
    parse_csv_file,
)
from gui.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_get_available_scenarios():
    scenarios = get_available_scenarios()
    assert len(scenarios) == 14
    ids = [s["id"] for s in scenarios]
    assert "gt01_normal_payment" in ids
    assert "gt02_amount_mismatch" in ids
    assert "gt08_late_settlement" in ids
    assert "gt10_settlement_component_discrepancy" in ids


def test_load_scenario_gt01():
    data = load_scenario("gt01_normal_payment")
    assert len(data["ORDERS"]) == 1
    assert data["ORDERS"][0]["ORDER_ID"] == "SL-GT01-ORDER"
    assert len(data["PAYMENT_ATTEMPTS"]) == 1
    assert len(data["PROCESSOR_TRANSACTIONS"]) == 1


def test_api_scenarios(client):
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data["status"] == "success"
    assert len(json_data["scenarios"]) == 14


def test_api_reconcile_scenario_gt01(client):
    res = client.post("/api/reconcile/scenario", json={"scenario_id": "gt01_normal_payment"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["summary"]["orders_count"] == 1
    assert "findings" in data
    assert len(data["summary"]["lifecycle_stages"]) == 5


def test_api_reconcile_scenario_gt02_discrepancy(client):
    res = client.post("/api/reconcile/scenario", json={"scenario_id": "gt02_amount_mismatch"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["summary"]["discrepancy_count"] > 0
    diff_findings = [f for f in data["findings"] if "discrepancy" in (f.get("status") or "").lower()]
    assert len(diff_findings) > 0


def test_api_reconcile_combined_scenarios(client):
    res = client.post("/api/reconcile/scenario", json={"scenario_ids": ["gt01_normal_payment", "gt08_late_settlement"]})
    assert res.status_code == 200
    data = res.get_json()
    assert data["summary"]["orders_count"] == 2
    assert data["summary"]["late_count"] >= 1


def test_api_csv_template(client):
    res = client.get("/api/templates/orders")
    assert res.status_code == 200
    assert b"ORDER_ID,ORDER_AMOUNT" in res.data
