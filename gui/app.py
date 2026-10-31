"""SettlementLens Merchant Web Dashboard Application.

Provides a merchant-friendly interface and API atop the existing
deterministic Python reconciliation engine and presentation formatters.
"""

import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

# Ensure Sarvagya root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, jsonify, render_template, request, Response

from gui.scenario_fixtures import (
    get_available_scenarios,
    load_combined_scenarios,
    load_scenario,
    parse_csv_file,
    empty_dataset,
)
from scripts.finding_presentation import format_amount, present_finding
from scripts.reconciliation_engine import reconcile_orders_attempts_processor_and_settlement

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)
app.config["JSON_SORT_KEYS"] = False


def _safe_decimal(val: Any) -> Decimal:
    if val is None or val == "":
        return Decimal("0.00")
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0.00")


def _compute_reconciliation_summary(
    dataset: Dict[str, List[Dict[str, Any]]],
    engine_result: Dict[str, Any],
    presented_findings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    orders = dataset.get("ORDERS", [])
    attempts = dataset.get("PAYMENT_ATTEMPTS", [])
    processor_txns = dataset.get("PROCESSOR_TRANSACTIONS", [])
    settlements = dataset.get("SETTLEMENTS", [])
    bank_txns = dataset.get("BANK_TRANSACTIONS", [])

    total_order_volume = sum((_safe_decimal(o.get("ORDER_AMOUNT")) for o in orders), Decimal("0.00"))
    total_bank_volume = sum((_safe_decimal(b.get("AMOUNT")) for b in bank_txns), Decimal("0.00"))

    # Categorize findings
    unresolved_count = 0
    discrepancy_count = 0
    late_count = 0
    resolved_count = 0
    total_delta = Decimal("0.00")

    for pf in presented_findings:
        status = (pf.get("status") or "").lower()
        classification = (pf.get("classification") or "").upper()
        if "discrepancy" in status or "mismatch" in status:
            discrepancy_count += 1
        elif "late" in status:
            late_count += 1
        elif "unresolved" in status or "unverified" in status:
            unresolved_count += 1
        else:
            resolved_count += 1

        # Financial delta
        fin = pf.get("financials", {})
        diff = fin.get("difference_amount")
        if diff is not None:
            total_delta += _safe_decimal(diff)

    # Lifecycle stage health
    stages = [
        {
            "id": "orders",
            "name": "1. Merchant Orders",
            "count": len(orders),
            "amount": format_amount(total_order_volume, "INR"),
            "status": "success" if len(orders) > 0 else "empty",
            "description": "Commercial order obligations recorded",
        },
        {
            "id": "attempts",
            "name": "2. Payment Attempts",
            "count": len(attempts),
            "amount": format_amount(
                sum((_safe_decimal(a.get("ATTEMPT_AMOUNT")) for a in attempts), Decimal("0.00")), "INR"
            ),
            "status": "success" if len(attempts) >= len(orders) else "warning",
            "description": "Gateway payment checkout tries",
        },
        {
            "id": "processor",
            "name": "3. Processor Captures",
            "count": len(processor_txns),
            "amount": format_amount(
                sum((_safe_decimal(p.get("TRANSACTION_AMOUNT")) for p in processor_txns), Decimal("0.00")), "INR"
            ),
            "status": "danger" if discrepancy_count > 0 else ("success" if len(processor_txns) > 0 else "neutral"),
            "description": "Confirmed collection by payment processor",
        },
        {
            "id": "settlements",
            "name": "4. Settlement Batches",
            "count": len(settlements),
            "amount": format_amount(
                sum((_safe_decimal(s.get("REPORTED_NET_AMOUNT")) for s in settlements), Decimal("0.00")), "INR"
            ),
            "status": "warning" if late_count > 0 else ("success" if len(settlements) > 0 else "neutral"),
            "description": "Processor net settlement payout feeds",
        },
        {
            "id": "bank",
            "name": "5. Bank Deposits",
            "count": len(bank_txns),
            "amount": format_amount(total_bank_volume, "INR"),
            "status": "success" if len(bank_txns) > 0 else "warning",
            "description": "Actual credit entries in merchant bank statement",
        },
    ]

    return {
        "orders_count": len(orders),
        "attempts_count": len(attempts),
        "processor_count": len(processor_txns),
        "settlements_count": len(settlements),
        "bank_count": len(bank_txns),
        "gross_order_volume": format_amount(total_order_volume, "INR"),
        "total_bank_volume": format_amount(total_bank_volume, "INR"),
        "total_findings": len(presented_findings),
        "unresolved_count": unresolved_count,
        "discrepancy_count": discrepancy_count,
        "late_count": late_count,
        "resolved_count": resolved_count,
        "net_financial_discrepancy": format_amount(total_delta, "INR"),
        "net_discrepancy_raw": float(total_delta),
        "lifecycle_stages": stages,
    }


def _run_and_format_reconciliation(dataset: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    engine_result = reconcile_orders_attempts_processor_and_settlement(
        dataset.get("ORDERS", []),
        dataset.get("PAYMENT_ATTEMPTS", []),
        dataset.get("PROCESSOR_TRANSACTIONS", []),
        dataset.get("PROCESSOR_SOURCE_ROWS", []),
        dataset.get("SETTLEMENTS", []),
        dataset.get("SETTLEMENT_TRANSACTIONS", []),
        dataset.get("BANK_TRANSACTIONS", []),
    )

    findings = engine_result.get("findings", [])
    presented = []
    for f in findings:
        item = present_finding(f)
        # Format human monetary values
        fin = item.get("financials", {})
        if fin.get("expected_amount") is not None:
            fin["expected_amount_formatted"] = format_amount(fin["expected_amount"], "INR")
        if fin.get("observed_amount") is not None:
            fin["observed_amount_formatted"] = format_amount(fin["observed_amount"], "INR")
        if fin.get("difference_amount") is not None:
            fin["difference_amount_formatted"] = format_amount(fin["difference_amount"], "INR")
        item["financials"] = fin
        presented.append(item)

    summary = _compute_reconciliation_summary(dataset, engine_result, presented)

    return {
        "status": "success",
        "summary": summary,
        "findings": presented,
        "source_data": {
            "orders": dataset.get("ORDERS", []),
            "attempts": dataset.get("PAYMENT_ATTEMPTS", []),
            "processor": dataset.get("PROCESSOR_TRANSACTIONS", []),
            "settlements": dataset.get("SETTLEMENTS", []),
            "bank": dataset.get("BANK_TRANSACTIONS", []),
        },
    }


# ----------------- ROUTES ----------------- #


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scenarios", methods=["GET"])
def api_list_scenarios():
    return jsonify({
        "status": "success",
        "scenarios": get_available_scenarios(),
    })


@app.route("/api/reconcile/scenario", methods=["POST"])
def api_reconcile_scenario():
    data = request.get_json(silent=True) or {}
    scenario_id = data.get("scenario_id")
    scenario_ids = data.get("scenario_ids")

    if scenario_ids and isinstance(scenario_ids, list):
        dataset = load_combined_scenarios(scenario_ids)
        scenario_name = f"Combined ({len(scenario_ids)} scenarios)"
    elif scenario_id:
        dataset = load_scenario(scenario_id)
        scenario_name = scenario_id
    else:
        # Default to GT01
        dataset = load_scenario("gt01_normal_payment")
        scenario_name = "gt01_normal_payment"

    response = _run_and_format_reconciliation(dataset)
    response["active_scenario"] = scenario_name
    return jsonify(response)


@app.route("/api/reconcile/custom", methods=["POST"])
def api_reconcile_custom():
    payload = request.get_json(silent=True) or {}
    dataset = empty_dataset()
    for tbl in dataset:
        if tbl in payload and isinstance(payload[tbl], list):
            dataset[tbl] = payload[tbl]

    response = _run_and_format_reconciliation(dataset)
    response["active_scenario"] = "Custom Merchant Upload"
    return jsonify(response)


@app.route("/api/upload/csv", methods=["POST"])
def api_upload_csv():
    """Accepts uploaded CSV files mapped to table names."""
    dataset = empty_dataset()
    for tbl in dataset:
        file = request.files.get(tbl.lower()) or request.files.get(tbl)
        if file:
            content = file.read().decode("utf-8", errors="replace")
            dataset[tbl] = parse_csv_file(content, tbl)

    response = _run_and_format_reconciliation(dataset)
    response["active_scenario"] = "Uploaded Files"
    return jsonify(response)


@app.route("/api/exasol/status", methods=["GET"])
def api_exasol_status():
    env_file = PROJECT_ROOT / "config" / "exasol.env"
    configured = env_file.is_file()
    has_pyexasol = "pyexasol" in sys.modules or False
    try:
        import pyexasol
        has_pyexasol = True
    except ImportError:
        has_pyexasol = False

    return jsonify({
        "status": "success",
        "configured": configured,
        "driver_available": has_pyexasol,
        "message": (
            "Exasol credentials configured." if configured
            else "config/exasol.env not found. Using offline fixtures and CSV uploads."
        ),
    })


@app.route("/api/templates/<table_name>", methods=["GET"])
def api_csv_template(table_name: str):
    headers_map = {
        "orders": "ORDER_ID,ORDER_AMOUNT,CURRENCY,CREATED_AT,MERCHANT_ID\nORD-001,1500.00,INR,2026-10-20 10:00:00,MERCHANT-01\n",
        "attempts": "ATTEMPT_ID,ORDER_ID,MERCHANT_PAYMENT_REF,ATTEMPT_AMOUNT,ATTEMPT_STATUS,CREATED_AT\nATT-001,ORD-001,REF-001,1500.00,SUCCESS,2026-10-20 10:01:00\n",
        "processor": "PROCESSOR_TXN_ID,PROCESSOR_NAME,ORDER_ID,MERCHANT_PAYMENT_REF,TRANSACTION_AMOUNT,CURRENCY,TRANSACTION_STATUS,TRANSACTION_AT\nPTX-001,STRIPE,ORD-001,REF-001,1500.00,INR,CAPTURED,2026-10-20 10:02:00\n",
        "settlements": "BATCH_ID,GROSS_AMOUNT,FEE_AMOUNT,REFUND_AMOUNT,CHARGEBACK_AMOUNT,ADJUSTMENT_AMOUNT,REPORTED_NET_AMOUNT,CURRENCY,EXPECTED_SETTLEMENT_DATE,SETTLED_AT,SETTLEMENT_STATUS\nBAT-001,1500.00,30.00,0.00,0.00,0.00,1470.00,INR,2026-10-21,2026-10-21 12:00:00,SETTLED\n",
        "bank": "BANK_TXN_ID,BANK_REFERENCE,AMOUNT,CURRENCY,TRANSACTION_AT,DESCRIPTION,SOURCE_FILE\nBNK-001,BAT-001,1470.00,INR,2026-10-21 14:00:00,NEFT SETTLEMENT BATCH,hday_statement.csv\n",
    }
    key = table_name.lower().replace("_transactions", "").replace("payment_", "")
    content = headers_map.get(key, "ID,AMOUNT,CURRENCY,CREATED_AT\n")
    return Response(
        content,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=template_{key}.csv"},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("\n==========================================================")
    print("SettlementLens Merchant Interface running at:")
    print(f"   http://127.0.0.1:{port}")
    print("==========================================================\n")
    app.run(host="127.0.0.1", port=port, debug=False)
