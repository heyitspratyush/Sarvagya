"""Scenario fixtures loader and custom data importer for SettlementLens GUI.

Provides offline access to GT01-GT15 fixtures and CSV import utilities
without requiring an active database connection.
"""

import csv
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = PROJECT_ROOT / "seed" / "data"

INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+(?:SARVAGYA\.)?([A-Za-z_]+)\s*\((.*?)\)\s*VALUES\s*\((.*?)\);",
    re.DOTALL | re.IGNORECASE,
)

SCENARIO_METADATA = {
    "gt01_normal_payment": {
        "name": "GT-01: Normal Payment",
        "category": "Baseline",
        "description": "Standard order captured cleanly by processor without discrepancy.",
        "expected_status": "Clean capture (Awaiting settlement feed)",
    },
    "gt02_amount_mismatch": {
        "name": "GT-02: Amount Mismatch",
        "category": "Discrepancy",
        "description": "Processor captured amount differs from the merchant order amount.",
        "expected_status": "Discrepancy flagged",
    },
    "gt03_payment_retry": {
        "name": "GT-03: Payment Retry",
        "category": "Retry Flow",
        "description": "First attempt failed, second attempt succeeded with processor candidate.",
        "expected_status": "Retry tracked",
    },
    "gt04_duplicate_collection": {
        "name": "GT-04: Duplicate Collection",
        "category": "Risk",
        "description": "Multiple successful processor collections for a single payment attempt.",
        "expected_status": "Multiple candidates preserved",
    },
    "gt05_duplicate_source_row": {
        "name": "GT-05: Duplicate Source Row",
        "category": "Data Quality",
        "description": "Identical transaction feed rows imported multiple times.",
        "expected_status": "Preserves source row lineage",
    },
    "gt06_unmatched_processor": {
        "name": "GT-06: Unmatched Processor Transaction",
        "category": "Orphan Record",
        "description": "Processor transaction received without matching merchant order or attempt.",
        "expected_status": "Orphan transaction flagged",
    },
    "gt07_wrong_batch": {
        "name": "GT-07: Wrong Settlement Batch",
        "category": "Settlement",
        "description": "Processor transaction assigned to a batch differing from expected date.",
        "expected_status": "Batch anomaly flagged",
    },
    "gt08_late_settlement": {
        "name": "GT-08: Late Settlement",
        "category": "Timing",
        "description": "Settlement completed after the contracted expected settlement date.",
        "expected_status": "Confirmed late settlement",
    },
    "gt09_missing_bank_payout": {
        "name": "GT-09: Missing Bank Payout",
        "category": "Bank Reconciliation",
        "description": "Settlement batch reported settled but no bank transaction reference exists.",
        "expected_status": "Unverified payout status",
    },
    "gt10_settlement_component_discrepancy": {
        "name": "GT-10: Settlement Component Calculation Mismatch",
        "category": "Financial",
        "description": "Reported net differs from calculated (Gross - Fees - Refunds + Adjustments).",
        "expected_status": "Net calculation discrepancy",
    },
    "gt11_gt12_bank_mismatches": {
        "name": "GT-11 & GT-12: Bank Amount & Currency Mismatches",
        "category": "Bank Reconciliation",
        "description": "Bank deposit differs in amount and currency from settlement report.",
        "expected_status": "Amount & currency mismatches",
    },
    "gt13_duplicate_bank_reference": {
        "name": "GT-13: Ambiguous Bank Reference",
        "category": "Bank Reconciliation",
        "description": "Multiple bank transaction lines reference the same settlement batch ID.",
        "expected_status": "Ambiguous evidence preserved",
    },
    "gt14_collection_currency_mismatch": {
        "name": "GT-14: Collection Currency Discrepancy",
        "category": "Currency",
        "description": "Processor captured in a currency different from the order currency.",
        "expected_status": "Currency mismatch flagged",
    },
    "gt15_missing_processor_transaction": {
        "name": "GT-15: Missing Processor Confirmation",
        "category": "Discrepancy",
        "description": "Payment marked successful by merchant commerce system but processor missing.",
        "expected_status": "Unverified collection",
    },
}


def _parse_sql_tokens(val_str: str) -> List[Any]:
    tokens = []
    current = []
    in_quote = False
    i = 0
    s = val_str.strip()
    while i < len(s):
        c = s[i]
        if c == "'" and (i == 0 or s[i - 1] != "\\"):
            in_quote = not in_quote
            current.append(c)
        elif c == "," and not in_quote:
            tokens.append("".join(current).strip())
            current = []
        else:
            current.append(c)
        i += 1
    if current:
        tokens.append("".join(current).strip())

    cleaned = []
    for tok in tokens:
        ts_match = re.match(r"(?:TIMESTAMP|DATE)\s*'([^']+)'", tok, re.IGNORECASE)
        if ts_match:
            cleaned.append(ts_match.group(1))
        elif tok.startswith("'") and tok.endswith("'"):
            cleaned.append(tok[1:-1])
        elif tok.upper() == "NULL":
            cleaned.append(None)
        else:
            cleaned.append(tok)
    return cleaned


def empty_dataset() -> Dict[str, List[Dict[str, Any]]]:
    return {
        "ORDERS": [],
        "PAYMENT_ATTEMPTS": [],
        "PROCESSOR_TRANSACTIONS": [],
        "PROCESSOR_SOURCE_ROWS": [],
        "SETTLEMENTS": [],
        "SETTLEMENT_TRANSACTIONS": [],
        "BANK_TRANSACTIONS": [],
    }


def parse_scenario_sql(file_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    text = file_path.read_text(encoding="utf-8")
    dataset = empty_dataset()
    for match in INSERT_RE.finditer(text):
        tbl = match.group(1).upper()
        cols = [c.strip().upper() for c in match.group(2).split(",")]
        vals = _parse_sql_tokens(match.group(3))
        if len(cols) == len(vals) and tbl in dataset:
            dataset[tbl].append(dict(zip(cols, vals)))
    return dataset


def get_available_scenarios() -> List[Dict[str, Any]]:
    scenarios = []
    for key, meta in SCENARIO_METADATA.items():
        file_path = SEED_DIR / f"{key}.sql"
        scenarios.append({
            "id": key,
            "name": meta["name"],
            "category": meta["category"],
            "description": meta["description"],
            "expected_status": meta["expected_status"],
            "available": file_path.is_file(),
        })
    return scenarios


def load_scenario(scenario_id: str) -> Dict[str, List[Dict[str, Any]]]:
    safe_name = scenario_id.replace("-", "_").lower()
    file_path = SEED_DIR / f"{safe_name}.sql"
    if not file_path.is_file():
        raise FileNotFoundError(f"Scenario fixture '{scenario_id}' not found.")
    return parse_scenario_sql(file_path)


def load_combined_scenarios(scenario_ids: List[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    combined = empty_dataset()
    targets = scenario_ids or list(SCENARIO_METADATA.keys())
    for s_id in targets:
        try:
            scenario_data = load_scenario(s_id)
            for tbl, rows in scenario_data.items():
                combined[tbl].extend(rows)
        except Exception:
            continue
    return combined


def parse_csv_file(content_str: str, table_name: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(content_str))
    rows = []
    for row in reader:
        clean_row = {k.strip().upper(): (v.strip() if v is not None else None) for k, v in row.items()}
        rows.append(clean_row)
    return rows
