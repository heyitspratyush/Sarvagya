"""Streaming benchmark data generation and independent offline validation.

Ground truth is authored from the generator's scenario contract. This module
does not import or call the reconciliation engine.
"""

import csv
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import random
import re
import sqlite3
import tempfile
from pathlib import Path
from time import perf_counter


DATA_ROOT = Path(__file__).resolve().parent.parent / ".benchmark-data"
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
MAX_ORDERS = 100_000
DEFAULT_CHUNK_ROWS = 5_000
MERCHANT_ID = "BENCHMARK-MERCHANT-INR"
RUN_ID_PATTERN = re.compile(r"^[A-Z0-9]{4,10}$")

TABLE_COLUMNS = {
    "ORDERS": ("ORDER_ID", "ORDER_AMOUNT", "CURRENCY", "CREATED_AT", "MERCHANT_ID"),
    "PAYMENT_ATTEMPTS": (
        "ATTEMPT_ID", "ORDER_ID", "MERCHANT_PAYMENT_REF", "ATTEMPT_AMOUNT",
        "ATTEMPT_STATUS", "CREATED_AT",
    ),
    "PROCESSOR_TRANSACTIONS": (
        "PROCESSOR_TXN_ID", "PROCESSOR_NAME", "ORDER_ID", "MERCHANT_PAYMENT_REF",
        "TRANSACTION_AMOUNT", "CURRENCY", "TRANSACTION_STATUS", "TRANSACTION_AT",
    ),
    "PROCESSOR_SOURCE_ROWS": (
        "SOURCE_ROW_ID", "PROCESSOR_TXN_ID", "SOURCE_FILE", "SOURCE_ROW_NUMBER", "IMPORTED_AT",
    ),
    "SETTLEMENT_TRANSACTIONS": ("BATCH_ID", "PROCESSOR_TXN_ID"),
    "SETTLEMENTS": (
        "BATCH_ID", "GROSS_AMOUNT", "FEE_AMOUNT", "REFUND_AMOUNT", "CHARGEBACK_AMOUNT",
        "ADJUSTMENT_AMOUNT", "REPORTED_NET_AMOUNT", "CURRENCY", "EXPECTED_SETTLEMENT_DATE",
        "SETTLED_AT", "SETTLEMENT_STATUS",
    ),
    "BANK_TRANSACTIONS": (
        "BANK_TXN_ID", "BANK_REFERENCE", "AMOUNT", "CURRENCY", "TRANSACTION_AT",
        "DESCRIPTION", "SOURCE_FILE",
    ),
}

ID_COLUMNS = {
    "ORDERS": ("ORDER_ID", "BMK-{run_id}-ORD-"),
    "PAYMENT_ATTEMPTS": ("ATTEMPT_ID", "BMK-{run_id}-ATT-"),
    "PROCESSOR_TRANSACTIONS": ("PROCESSOR_TXN_ID", "SL-GT07-BMK-{run_id}-PTX-"),
    "PROCESSOR_SOURCE_ROWS": ("SOURCE_ROW_ID", "BMK-{run_id}-SRC-"),
    "SETTLEMENT_TRANSACTIONS": ("BATCH_ID", "SL-GT07-BMK-{run_id}-BAT-"),
    "SETTLEMENTS": ("BATCH_ID", "SL-GT07-BMK-{run_id}-BAT-"),
    "BANK_TRANSACTIONS": ("BANK_TXN_ID", "BMK-{run_id}-BNK-"),
}

DEFAULT_DISTRIBUTION = {
    "normal": "0.57",
    "payment_retry": "0.05",
    "missing_processor": "0.04",
    "duplicate_source_row": "0.03",
    "ambiguous_identity": "0.03",
    "processor_amount_discrepancy": "0.04",
    # INR-only is a locked constraint, so a currency mismatch is disabled.
    "processor_currency_discrepancy": "0.00",
    "missing_settlement_entry": "0.03",
    "wrong_batch": "0.03",
    "settlement_component_discrepancy": "0.03",
    "missing_bank_payout": "0.03",
    "duplicate_bank_reference": "0.02",
    "bank_amount_mismatch": "0.03",
    "late_settlement": "0.03",
    "incomplete_evidence": "0.02",
    "unresolved_identity": "0.02",
}

PRIMARY_FINDING = {
    "normal": ("PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION", "NONE", "NONE"),
    "payment_retry": (
        "PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION",
        "NO_PROCESSOR_TRANSACTION_CANDIDATE", "UNRESOLVED",
    ),
    "missing_processor": (
        "PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION",
        "NO_PROCESSOR_TRANSACTION_CANDIDATE", "UNRESOLVED",
    ),
    "duplicate_source_row": ("PROCESSOR_SETTLEMENT_RECONCILIATION", "NONE", "NONE"),
    "ambiguous_identity": (
        "PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION",
        "MULTIPLE_PROCESSOR_TRANSACTION_CANDIDATES", "UNRESOLVED",
    ),
    "processor_amount_discrepancy": (
        "PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION",
        "PROCESSOR_AMOUNT_DISCREPANCY", "UNRESOLVED",
    ),
    "processor_currency_discrepancy": (
        "PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION",
        "PROCESSOR_CURRENCY_DISCREPANCY", "UNRESOLVED",
    ),
    "missing_settlement_entry": (
        "PROCESSOR_SETTLEMENT_RECONCILIATION",
        "PROCESSOR_TRANSACTION_MISSING_FROM_SETTLEMENT", "UNRESOLVED",
    ),
    "wrong_batch": (
        "PROCESSOR_SETTLEMENT_RECONCILIATION",
        "PROCESSOR_TRANSACTION_IN_WRONG_SETTLEMENT_BATCH", "UNRESOLVED",
    ),
    "settlement_component_discrepancy": (
        "SETTLEMENT_FINANCIAL_RECONCILIATION", "SETTLEMENT_AMOUNT_MISMATCH", "UNRESOLVED",
    ),
    "missing_bank_payout": ("SETTLEMENT_BANK_RECONCILIATION", "UNVERIFIED", "UNRESOLVED"),
    "duplicate_bank_reference": (
        "SETTLEMENT_BANK_RECONCILIATION", "AMBIGUOUS_BANK_REFERENCE", "UNRESOLVED",
    ),
    "bank_amount_mismatch": (
        "SETTLEMENT_BANK_RECONCILIATION", "AMOUNT_MISMATCH", "UNRESOLVED",
    ),
    "late_settlement": ("SETTLEMENT_TIMING_RECONCILIATION", "CONFIRMED_LATE", "RESOLVED"),
    "incomplete_evidence": ("SETTLEMENT_TIMING_RECONCILIATION", "UNRESOLVED", "UNRESOLVED"),
    "unresolved_identity": (
        "PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION",
        "NO_PROCESSOR_TRANSACTION_CANDIDATE", "UNRESOLVED",
    ),
}

TIMING_CLASSIFICATION = {
    "normal": "ON_TIME",
    "payment_retry": "ON_TIME",
    "missing_processor": "UNRESOLVED",
    "duplicate_source_row": "ON_TIME",
    "ambiguous_identity": "ON_TIME",
    "processor_amount_discrepancy": "ON_TIME",
    "processor_currency_discrepancy": "ON_TIME",
    "missing_settlement_entry": "UNRESOLVED",
    "wrong_batch": "ON_TIME",
    "settlement_component_discrepancy": "ON_TIME",
    "missing_bank_payout": "ON_TIME",
    "duplicate_bank_reference": "ON_TIME",
    "bank_amount_mismatch": "ON_TIME",
    "late_settlement": "CONFIRMED_LATE",
    "incomplete_evidence": "UNRESOLVED",
    "unresolved_identity": "ON_TIME",
}

SCENARIO_COLUMNS = (
    "RUN_ID", "SCENARIO_ID", "SCENARIO_TYPE", "PRIMARY_FINDING_TYPE",
    "EXPECTED_CLASSIFICATION", "EXPECTED_RESOLUTION_STATUS", "ENTITY_IDS_JSON",
    "ORDER_ID", "ATTEMPT_IDS_JSON", "PROCESSOR_TXN_IDS_JSON", "ACTUAL_BATCH_ID",
    "EXPECTED_BATCH_ID", "EXPECTED_AMOUNT", "OBSERVED_AMOUNT", "DIFFERENCE_AMOUNT",
    "EXPECTED_SETTLEMENT_DATE", "ACTUAL_SETTLED_AT", "EXPECTED_TIMING_CLASSIFICATION",
    "EXPECTED_TIMING_STATUS", "EXPECTED_ENTRY_GROSS", "EXPECTED_EVIDENCE_JSON",
    "EXPECTED_TIMING_ENTITY_IDS_JSON", "EXPECTED_TIMING_EVIDENCE_JSON",
)
CSV_NULL = r"\N"


def validate_run_id(run_id):
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must be 4–10 uppercase letters or digits.")
    return run_id


def _normalize_distribution(distribution):
    values = dict(DEFAULT_DISTRIBUTION if distribution is None else distribution)
    if set(values) != set(DEFAULT_DISTRIBUTION):
        missing = sorted(set(DEFAULT_DISTRIBUTION) - set(values))
        unknown = sorted(set(values) - set(DEFAULT_DISTRIBUTION))
        raise ValueError(f"Scenario distribution keys differ; missing={missing}, unknown={unknown}.")
    try:
        values = {name: Decimal(str(weight)) for name, weight in values.items()}
    except Exception as error:
        raise ValueError("Scenario weights must be decimal-compatible values.") from error
    if any(not weight.is_finite() or weight < 0 for weight in values.values()):
        raise ValueError("Scenario weights must be finite and non-negative.")
    if sum(values.values(), Decimal("0")) != Decimal("1"):
        raise ValueError("Scenario weights must sum exactly to 1.")
    if values["processor_currency_discrepancy"] != 0:
        raise ValueError("INR-only benchmark runs cannot include currency-discrepancy records.")
    return values


def allocate_scenarios(order_count, distribution=None):
    weights = _normalize_distribution(distribution)
    exact = {name: weight * order_count for name, weight in weights.items()}
    counts = {name: int(value) for name, value in exact.items()}
    remainder = order_count - sum(counts.values())
    order = sorted(weights, key=lambda name: (-(exact[name] - counts[name]), name))
    for name in order[:remainder]:
        counts[name] += 1
    return counts


def _money(cents):
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))


def _iso(value):
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, Decimal):
        return format(value, ".2f")
    return value


class CsvShardWriter:
    """Write one table incrementally into bounded, deterministic CSV shards."""

    def __init__(self, directory, table, columns, chunk_rows):
        self.directory = directory
        self.table = table
        self.columns = columns
        self.chunk_rows = chunk_rows
        self.total_rows = 0
        self.files = []
        self._stream = None
        self._writer = None
        self._shard_rows = 0

    def _open_shard(self):
        self.close_shard()
        path = self.directory / f"{self.table.lower()}-{len(self.files) + 1:04d}.csv"
        self._stream = path.open("w", encoding="utf-8", newline="")
        self._writer = csv.writer(self._stream, lineterminator="\n")
        self._writer.writerow(self.columns)
        self._shard_rows = 0
        self._current_path = path

    def write(self, record):
        if self._writer is None or self._shard_rows >= self.chunk_rows:
            self._open_shard()
        values = [_iso(record.get(column)) for column in self.columns]
        self._writer.writerow([CSV_NULL if value is None else value for value in values])
        self._shard_rows += 1
        self.total_rows += 1

    def close_shard(self):
        if self._stream is None:
            return
        self._stream.flush()
        self._stream.close()
        path = self._current_path
        digest = _hash_file(path)
        self.files.append({
            "path": path.name,
            "rows": self._shard_rows,
            "bytes": path.stat().st_size,
            "sha256": digest,
        })
        self._stream = None
        self._writer = None
        self._shard_rows = 0

    def close(self):
        self.close_shard()


def _format_ids(run_id, index):
    marker = f"BMK-{run_id}"
    order_id = f"{marker}-ORD-{index:06d}"
    return marker, order_id


def _scenario_truth(run_id, index, scenario, order_id, attempts, processors, batch_id,
                    expected_batch_id, expected_amount, observed_amount, difference,
                    expected_date, settled_at, evidence, timing_entity_ids,
                    timing_evidence):
    finding_type, classification, status = PRIMARY_FINDING[scenario]
    ids = [order_id, *(item["ATTEMPT_ID"] for item in attempts)]
    ids.extend(item["PROCESSOR_TXN_ID"] for item in processors)
    ids.append(batch_id)
    if scenario == "duplicate_bank_reference":
        ids.extend(f"BMK-{run_id}-BNK-{index:06d}-{n:02d}" for n in (1, 2))
    elif scenario == "bank_amount_mismatch":
        ids.append(f"BMK-{run_id}-BNK-{index:06d}-01")
    if scenario == "normal":
        classification, status, evidence = "NONE", "NONE", []
        ids = [order_id, *(item["ATTEMPT_ID"] for item in attempts),
               *(item["PROCESSOR_TXN_ID"] for item in processors)]
    elif scenario == "duplicate_source_row":
        classification, status, evidence = "NONE", "NONE", []
        ids = [* (item["PROCESSOR_TXN_ID"] for item in processors), batch_id]
    elif scenario == "payment_retry":
        ids = [attempts[0]["ATTEMPT_ID"]]
        evidence = [{"entity_type": "PAYMENT_ATTEMPT", "entity_id": ids[0]}]
    elif scenario in {"missing_processor", "unresolved_identity"}:
        ids = [attempts[-1]["ATTEMPT_ID"]]
        evidence = [{"entity_type": "PAYMENT_ATTEMPT", "entity_id": ids[0]}]
    elif scenario == "ambiguous_identity":
        ids = [attempts[0]["ATTEMPT_ID"], *(item["PROCESSOR_TXN_ID"] for item in processors)]
        evidence = [
            {"entity_type": "PAYMENT_ATTEMPT", "entity_id": attempts[0]["ATTEMPT_ID"]},
            *({"entity_type": "PROCESSOR_TRANSACTION", "entity_id": item["PROCESSOR_TXN_ID"]} for item in processors),
        ]
    elif scenario == "processor_amount_discrepancy":
        ids = [attempts[0]["ATTEMPT_ID"], processors[0]["PROCESSOR_TXN_ID"]]
        evidence = [
            {"entity_type": "PAYMENT_ATTEMPT", "entity_id": ids[0]},
            {"entity_type": "PROCESSOR_TRANSACTION", "entity_id": ids[1]},
        ]
    elif scenario in {"missing_settlement_entry", "wrong_batch"}:
        ids = [processors[0]["PROCESSOR_TXN_ID"], batch_id]
        evidence = [{"entity_type": "PROCESSOR_TRANSACTION", "entity_id": ids[0]}]
        if scenario == "wrong_batch":
            evidence.append({"entity_type": "SETTLEMENT_TRANSACTION", "entity_id": ids[0], "batch_id": batch_id})
    elif scenario == "settlement_component_discrepancy":
        ids = [batch_id]
        evidence = [{"entity_type": "SETTLEMENT_HEADER", "entity_id": batch_id}]
    elif scenario in {"missing_bank_payout", "duplicate_bank_reference", "bank_amount_mismatch"}:
        ids = [batch_id]
        evidence = [{"entity_type": "SETTLEMENT_HEADER", "entity_id": batch_id}]
        if scenario != "missing_bank_payout":
            bank_count = 2 if scenario == "duplicate_bank_reference" else 1
            ids.extend(f"BMK-{run_id}-BNK-{index:06d}-{n:02d}" for n in range(1, bank_count + 1))
            evidence.extend(
                {"entity_type": "BANK_TRANSACTION", "entity_id": f"BMK-{run_id}-BNK-{index:06d}-{n:02d}"}
                for n in range(1, bank_count + 1)
            )
    elif scenario in {"late_settlement", "incomplete_evidence"}:
        ids = [batch_id, *(item["PROCESSOR_TXN_ID"] for item in processors)]
        evidence = [{"entity_type": "SETTLEMENT_HEADER", "entity_id": batch_id}]
        evidence.extend(
            {"entity_type": "PROCESSOR_TRANSACTION", "entity_id": item["PROCESSOR_TXN_ID"]}
            for item in processors
        )
        evidence.extend(
            {"entity_type": "SETTLEMENT_TRANSACTION", "entity_id": item["PROCESSOR_TXN_ID"], "batch_id": batch_id}
            for item in processors
        )
    return {
        "RUN_ID": run_id,
        "SCENARIO_ID": f"SCN-{index:06d}",
        "SCENARIO_TYPE": scenario,
        "PRIMARY_FINDING_TYPE": finding_type,
        "EXPECTED_CLASSIFICATION": classification,
        "EXPECTED_RESOLUTION_STATUS": status,
        "ENTITY_IDS_JSON": json.dumps(sorted(set(ids)), separators=(",", ":")),
        "ORDER_ID": order_id,
        "ATTEMPT_IDS_JSON": json.dumps([item["ATTEMPT_ID"] for item in attempts], separators=(",", ":")),
        "PROCESSOR_TXN_IDS_JSON": json.dumps([item["PROCESSOR_TXN_ID"] for item in processors], separators=(",", ":")),
        "ACTUAL_BATCH_ID": batch_id,
        "EXPECTED_BATCH_ID": expected_batch_id,
        "EXPECTED_AMOUNT": _iso(expected_amount),
        "OBSERVED_AMOUNT": _iso(observed_amount),
        "DIFFERENCE_AMOUNT": _iso(difference),
        "EXPECTED_SETTLEMENT_DATE": _iso(expected_date),
        "ACTUAL_SETTLED_AT": _iso(settled_at),
        "EXPECTED_TIMING_CLASSIFICATION": TIMING_CLASSIFICATION[scenario],
        "EXPECTED_EVIDENCE_JSON": json.dumps(evidence, separators=(",", ":")),
        "EXPECTED_TIMING_ENTITY_IDS_JSON": json.dumps(sorted(set(timing_entity_ids)), separators=(",", ":")),
        "EXPECTED_TIMING_EVIDENCE_JSON": json.dumps(timing_evidence, separators=(",", ":")),
    }


def generate_dataset(run_id, order_count, seed, output_root=DATA_ROOT,
                     distribution=None, chunk_rows=DEFAULT_CHUNK_ROWS):
    """Generate source CSV shards and independent ground truth with bounded RAM."""
    validate_run_id(run_id)
    if isinstance(order_count, bool) or not isinstance(order_count, int) or not 1 <= order_count <= MAX_ORDERS:
        raise ValueError(f"order_count must be an integer from 1 to {MAX_ORDERS}.")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer.")
    if not 1 <= chunk_rows <= 100_000:
        raise ValueError("chunk_rows must be between 1 and 100000.")
    started = perf_counter()
    weights = _normalize_distribution(distribution)
    counts = allocate_scenarios(order_count, weights)
    scenarios = [scenario for scenario, count in counts.items() for _ in range(count)]
    rng = random.Random(seed)
    rng.shuffle(scenarios)

    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / run_id
    run_dir.mkdir(exist_ok=False)
    writers = {
        table: CsvShardWriter(run_dir, table, columns, chunk_rows)
        for table, columns in TABLE_COLUMNS.items()
    }
    ground_truth_path = run_dir / "ground_truth.csv"
    with ground_truth_path.open("w", encoding="utf-8", newline="") as truth_stream:
        truth_writer = csv.DictWriter(truth_stream, fieldnames=SCENARIO_COLUMNS, lineterminator="\n")
        truth_writer.writeheader()

        for index, scenario in enumerate(scenarios, start=1):
            marker, order_id = _format_ids(run_id, index)
            order_amount = _money(rng.randrange(1_000, 5_000_001))
            created_at = datetime(2026, 1, 1) + timedelta(
                days=rng.randrange(365), seconds=rng.randrange(86_400)
            )
            attempts = []
            if scenario == "payment_retry":
                attempts.append({
                    "ATTEMPT_ID": f"{marker}-ATT-{index:06d}-01",
                    "ORDER_ID": order_id,
                    "MERCHANT_PAYMENT_REF": f"{marker}-REF-{index:06d}-01",
                    "ATTEMPT_AMOUNT": order_amount,
                    "ATTEMPT_STATUS": "FAILED",
                    "CREATED_AT": created_at + timedelta(minutes=1),
                })
                attempts.append({
                    "ATTEMPT_ID": f"{marker}-ATT-{index:06d}-02",
                    "ORDER_ID": order_id,
                    "MERCHANT_PAYMENT_REF": f"{marker}-REF-{index:06d}-02",
                    "ATTEMPT_AMOUNT": order_amount,
                    "ATTEMPT_STATUS": "SUCCESS",
                    "CREATED_AT": created_at + timedelta(minutes=20),
                })
            else:
                reference = None if scenario == "ambiguous_identity" else f"{marker}-REF-{index:06d}-01"
                attempts.append({
                    "ATTEMPT_ID": f"{marker}-ATT-{index:06d}-01",
                    "ORDER_ID": order_id,
                    "MERCHANT_PAYMENT_REF": reference,
                    "ATTEMPT_AMOUNT": order_amount,
                    "ATTEMPT_STATUS": "SUCCESS",
                    "CREATED_AT": created_at + timedelta(minutes=1),
                })
            writers["ORDERS"].write({
                "ORDER_ID": order_id,
                "ORDER_AMOUNT": order_amount,
                "CURRENCY": "INR",
                "CREATED_AT": created_at,
                "MERCHANT_ID": MERCHANT_ID,
            })
            for attempt in attempts:
                writers["PAYMENT_ATTEMPTS"].write(attempt)

            intended_processor_ids = []
            processors = []
            if scenario != "missing_processor":
                chosen_attempt = attempts[-1]
                candidate_count = 2 if scenario == "ambiguous_identity" else 1
                for candidate_number in range(1, candidate_count + 1):
                    processor_id = f"SL-GT07-BMK-{run_id}-PTX-{index:06d}-{candidate_number:02d}"
                    intended_processor_ids.append(processor_id)
                    if scenario == "unresolved_identity":
                        processor_order_id = None
                        processor_reference = None
                    elif scenario == "ambiguous_identity":
                        processor_order_id = order_id
                        processor_reference = f"{marker}-UNKNOWN-REF-{index:06d}-{candidate_number:02d}"
                    else:
                        processor_order_id = order_id
                        processor_reference = chosen_attempt["MERCHANT_PAYMENT_REF"]
                    processor_amount = order_amount
                    if scenario == "processor_amount_discrepancy":
                        processor_amount += Decimal("1.25")
                    processor = {
                        "PROCESSOR_TXN_ID": processor_id,
                        "PROCESSOR_NAME": "SYNTHETIC-INR",
                        "ORDER_ID": processor_order_id,
                        "MERCHANT_PAYMENT_REF": processor_reference,
                        "TRANSACTION_AMOUNT": processor_amount,
                        "CURRENCY": "INR",
                        "TRANSACTION_STATUS": "CAPTURED",
                        "TRANSACTION_AT": chosen_attempt["CREATED_AT"] + timedelta(minutes=2 + candidate_number),
                    }
                    processors.append(processor)
                    writers["PROCESSOR_TRANSACTIONS"].write(processor)

                    source_copies = 2 if scenario == "duplicate_source_row" else 1
                    for source_number in range(1, source_copies + 1):
                        writers["PROCESSOR_SOURCE_ROWS"].write({
                            "SOURCE_ROW_ID": f"{marker}-SRC-{index:06d}-{candidate_number:02d}-{source_number:02d}",
                            "PROCESSOR_TXN_ID": processor_id,
                            "SOURCE_FILE": f"BENCH_{run_id}_processor.csv",
                            "SOURCE_ROW_NUMBER": index * 10 + candidate_number * 2 + source_number,
                            "IMPORTED_AT": processor["TRANSACTION_AT"] + timedelta(minutes=5),
                        })

            if scenario == "missing_processor":
                missing_id = f"SL-GT07-BMK-{run_id}-PTX-{index:06d}-01"
                intended_processor_ids = [missing_id]
                writers["PROCESSOR_SOURCE_ROWS"].write({
                    "SOURCE_ROW_ID": f"{marker}-SRC-{index:06d}-01-01",
                    "PROCESSOR_TXN_ID": missing_id,
                    "SOURCE_FILE": f"BENCH_{run_id}_processor.csv",
                    "SOURCE_ROW_NUMBER": index * 10 + 1,
                    "IMPORTED_AT": attempts[-1]["CREATED_AT"] + timedelta(minutes=5),
                })

            capture_reference = processors[0]["TRANSACTION_AT"] if processors else attempts[-1]["CREATED_AT"]
            business_batch_date = capture_reference.date()
            if capture_reference.time() >= time(15, 0):
                business_batch_date += timedelta(days=1)
            expected_batch_id = (
                f"SL-GT07-BMK-{run_id}-BAT-{index:06d}-{business_batch_date:%Y%m%d}"
            )
            actual_batch_date = business_batch_date - timedelta(days=1) if scenario == "wrong_batch" else business_batch_date
            batch_id = f"SL-GT07-BMK-{run_id}-BAT-{index:06d}-{actual_batch_date:%Y%m%d}"

            include_settlement_entries = scenario != "missing_settlement_entry"
            if include_settlement_entries:
                for processor in processors:
                    writers["SETTLEMENT_TRANSACTIONS"].write({
                        "BATCH_ID": batch_id,
                        "PROCESSOR_TXN_ID": processor["PROCESSOR_TXN_ID"],
                    })
            entry_processors = processors if include_settlement_entries else []
            gross_amount = sum((item["TRANSACTION_AMOUNT"] for item in entry_processors), Decimal("0.00"))
            fee_amount = (gross_amount * Decimal("0.02")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            refund_amount = Decimal("0.00")
            chargeback_amount = Decimal("0.00")
            adjustment_amount = Decimal("0.00")
            expected_net = gross_amount - fee_amount - refund_amount - chargeback_amount + adjustment_amount
            reported_net = expected_net + Decimal("1.00") if scenario == "settlement_component_discrepancy" else expected_net
            difference = expected_net - reported_net
            settlement_lag = rng.choice((1, 2, 3))
            expected_settlement_date = created_at.date() + timedelta(days=settlement_lag)
            settled_at = datetime.combine(expected_settlement_date, time(rng.randrange(8, 19), rng.choice((0, 15, 30, 45))))
            if scenario == "late_settlement":
                settled_at += timedelta(days=2)
            if scenario in {"missing_processor", "incomplete_evidence"}:
                settled_at = None
            settlement = {
                "BATCH_ID": batch_id,
                "GROSS_AMOUNT": gross_amount,
                "FEE_AMOUNT": fee_amount,
                "REFUND_AMOUNT": refund_amount,
                "CHARGEBACK_AMOUNT": chargeback_amount,
                "ADJUSTMENT_AMOUNT": adjustment_amount,
                "REPORTED_NET_AMOUNT": reported_net,
                "CURRENCY": "INR",
                "EXPECTED_SETTLEMENT_DATE": expected_settlement_date,
                "SETTLED_AT": settled_at,
                "SETTLEMENT_STATUS": "SETTLED" if settled_at is not None else "PENDING",
            }
            writers["SETTLEMENTS"].write(settlement)

            bank_count = 0 if scenario == "missing_bank_payout" else (2 if scenario == "duplicate_bank_reference" else 1)
            for bank_number in range(1, bank_count + 1):
                bank_amount = reported_net
                if scenario == "bank_amount_mismatch":
                    bank_amount += Decimal("1.00")
                writers["BANK_TRANSACTIONS"].write({
                    "BANK_TXN_ID": f"{marker}-BNK-{index:06d}-{bank_number:02d}",
                    "BANK_REFERENCE": batch_id,
                    "AMOUNT": bank_amount,
                    "CURRENCY": "INR",
                    "TRANSACTION_AT": (settled_at or datetime.combine(expected_settlement_date, time(12, 0))) + timedelta(hours=1),
                    "DESCRIPTION": f"Synthetic INR settlement payout {index:06d}",
                    "SOURCE_FILE": f"BENCH_{run_id}_bank.csv",
                })

            timing_class = TIMING_CLASSIFICATION[scenario]
            timing_status = "RESOLVED" if timing_class in {"ON_TIME", "CONFIRMED_LATE"} else "UNRESOLVED"
            expected_ids = [batch_id, *intended_processor_ids]
            expected_evidence = [
                {"entity_type": "SETTLEMENT_HEADER", "entity_id": batch_id},
                *({"entity_type": "PROCESSOR_TRANSACTION", "entity_id": processor_id} for processor_id in intended_processor_ids if processor_id in {p["PROCESSOR_TXN_ID"] for p in processors}),
                *({"entity_type": "SETTLEMENT_TRANSACTION", "entity_id": p["PROCESSOR_TXN_ID"], "batch_id": batch_id} for p in entry_processors),
            ]
            timing_entity_ids = [batch_id, *(item["PROCESSOR_TXN_ID"] for item in entry_processors)]
            timing_evidence = [
                {"entity_type": "SETTLEMENT_HEADER", "entity_id": batch_id},
                *({"entity_type": "PROCESSOR_TRANSACTION", "entity_id": item["PROCESSOR_TXN_ID"]} for item in entry_processors),
                *({"entity_type": "SETTLEMENT_TRANSACTION", "entity_id": item["PROCESSOR_TXN_ID"], "batch_id": batch_id} for item in entry_processors),
            ]
            truth = _scenario_truth(
                run_id, index, scenario, order_id, attempts, processors, batch_id,
                expected_batch_id, expected_net, reported_net, difference,
                expected_settlement_date, settled_at, expected_evidence,
                timing_entity_ids, timing_evidence,
            )
            truth["EXPECTED_TIMING_CLASSIFICATION"] = timing_class
            truth["EXPECTED_TIMING_STATUS"] = timing_status
            truth["EXPECTED_ENTRY_GROSS"] = _iso(gross_amount)
            truth_writer.writerow(truth)

    for writer in writers.values():
        writer.close()

    table_files = {
        table: writer.files
        for table, writer in writers.items()
    }
    table_counts = {table: writer.total_rows for table, writer in writers.items()}
    all_files = [item for files in table_files.values() for item in files]
    all_files.extend([
        {"path": ground_truth_path.name, "rows": order_count, "bytes": ground_truth_path.stat().st_size,
         "sha256": _hash_file(ground_truth_path)},
    ])
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "run_id": run_id,
        "seed": seed,
        "order_count": order_count,
        "merchant_id": MERCHANT_ID,
        "currency": "INR",
        "distribution": {key: str(value) for key, value in weights.items()},
        "scenario_counts": counts,
        "table_columns": {table: list(columns) for table, columns in TABLE_COLUMNS.items()},
        "table_counts": table_counts,
        "total_source_records": sum(table_counts.values()),
        "total_files_bytes": sum(item["bytes"] for item in all_files),
        "chunk_rows": chunk_rows,
        "files": table_files,
        "metadata_files": [item for item in all_files if item["path"] == "ground_truth.csv"],
        "generation_seconds": round(perf_counter() - started, 6),
        "isolation": {
            "order_attempt_source_bank_prefix": f"BMK-{run_id}-",
            "processor_settlement_prefix": f"SL-GT07-BMK-{run_id}-",
            "gt_scenarios_modified": False,
        },
    }
    (run_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_manifest(run_id, data_root=DATA_ROOT):
    validate_run_id(run_id)
    path = Path(data_root) / run_id / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"Benchmark manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != MANIFEST_VERSION or manifest.get("run_id") != run_id:
        raise ValueError("Benchmark manifest version or run ID is invalid.")
    return manifest


def _hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_dataset(run_id, data_root=DATA_ROOT):
    """Validate files, identities, foreign references and Decimal arithmetic offline."""
    started = perf_counter()
    manifest = load_manifest(run_id, data_root)
    run_dir = Path(data_root) / run_id
    report = {"run_id": run_id, "checks": {}, "errors": [], "started_with_live_exasol": False}
    try:
        with tempfile.TemporaryDirectory(prefix="sarvagya-benchmark-validate-") as temp_dir:
            db = sqlite3.connect(Path(temp_dir) / "validation.sqlite")
            db.execute("PRAGMA journal_mode=OFF")
            db.execute("PRAGMA synchronous=OFF")
            db.execute("PRAGMA temp_store=MEMORY")
            db.executescript("""
                CREATE TABLE orders (id TEXT PRIMARY KEY, amount TEXT, currency TEXT, merchant TEXT, created TEXT);
                CREATE TABLE attempts (id TEXT PRIMARY KEY, order_id TEXT, ref TEXT, amount TEXT, status TEXT);
                CREATE TABLE processors (id TEXT PRIMARY KEY, order_id TEXT, ref TEXT, amount TEXT, currency TEXT, status TEXT, at TEXT);
                CREATE TABLE sources (id TEXT PRIMARY KEY, processor_id TEXT);
                CREATE TABLE entries (batch_id TEXT, processor_id TEXT PRIMARY KEY);
                CREATE TABLE settlements (batch_id TEXT PRIMARY KEY, gross TEXT, fee TEXT, refund TEXT, chargeback TEXT, adjustment TEXT, reported TEXT, currency TEXT, expected_date TEXT, settled_at TEXT);
                CREATE TABLE banks (id TEXT PRIMARY KEY, reference TEXT, amount TEXT, currency TEXT, at TEXT);
                CREATE TABLE scenarios (id TEXT PRIMARY KEY, kind TEXT, expected_class TEXT, timing TEXT, order_id TEXT, batch_id TEXT, expected_batch_id TEXT);
            """)

            unique_columns = {
                "ORDERS": "ORDER_ID", "PAYMENT_ATTEMPTS": "ATTEMPT_ID",
                "PROCESSOR_TRANSACTIONS": "PROCESSOR_TXN_ID", "PROCESSOR_SOURCE_ROWS": "SOURCE_ROW_ID",
                "SETTLEMENT_TRANSACTIONS": "PROCESSOR_TXN_ID", "SETTLEMENTS": "BATCH_ID",
                "BANK_TRANSACTIONS": "BANK_TXN_ID",
            }
            table_map = {
                "ORDERS": ("orders", ("ORDER_ID", "ORDER_AMOUNT", "CURRENCY", "MERCHANT_ID", "CREATED_AT")),
                "PAYMENT_ATTEMPTS": ("attempts", ("ATTEMPT_ID", "ORDER_ID", "MERCHANT_PAYMENT_REF", "ATTEMPT_AMOUNT", "ATTEMPT_STATUS")),
                "PROCESSOR_TRANSACTIONS": ("processors", ("PROCESSOR_TXN_ID", "ORDER_ID", "MERCHANT_PAYMENT_REF", "TRANSACTION_AMOUNT", "CURRENCY", "TRANSACTION_STATUS", "TRANSACTION_AT")),
                "PROCESSOR_SOURCE_ROWS": ("sources", ("SOURCE_ROW_ID", "PROCESSOR_TXN_ID")),
                "SETTLEMENT_TRANSACTIONS": ("entries", ("BATCH_ID", "PROCESSOR_TXN_ID")),
                "SETTLEMENTS": ("settlements", ("BATCH_ID", "GROSS_AMOUNT", "FEE_AMOUNT", "REFUND_AMOUNT", "CHARGEBACK_AMOUNT", "ADJUSTMENT_AMOUNT", "REPORTED_NET_AMOUNT", "CURRENCY", "EXPECTED_SETTLEMENT_DATE", "SETTLED_AT")),
                "BANK_TRANSACTIONS": ("banks", ("BANK_TXN_ID", "BANK_REFERENCE", "AMOUNT", "CURRENCY", "TRANSACTION_AT")),
            }
            observed_counts = {}
            observed_bytes = 0
            for table, (sqlite_table, columns) in table_map.items():
                files = manifest["files"].get(table, [])
                count = 0
                for file_info in files:
                    path = run_dir / file_info["path"]
                    if not path.is_file():
                        report["errors"].append(f"Missing data shard: {path.name}")
                        continue
                    if path.stat().st_size != file_info["bytes"] or _hash_file(path) != file_info["sha256"]:
                        report["errors"].append(f"Data shard size or checksum mismatch: {path.name}")
                    observed_bytes += path.stat().st_size
                    with path.open(encoding="utf-8", newline="") as stream:
                        reader = csv.DictReader(stream)
                        if tuple(reader.fieldnames or ()) != TABLE_COLUMNS[table]:
                            report["errors"].append(f"Column ordering mismatch in {path.name}")
                            continue
                        batch = []
                        placeholders = ",".join("?" for _ in columns)
                        insert = f"INSERT INTO {sqlite_table} VALUES ({placeholders})"
                        for row in reader:
                            values = [row.get(column) if row.get(column) != CSV_NULL else None for column in columns]
                            batch.append(tuple(values))
                            count += 1
                            if len(batch) >= 1000:
                                db.executemany(insert, batch)
                                batch.clear()
                        if batch:
                            db.executemany(insert, batch)
                observed_counts[table] = count
                expected_count = manifest["table_counts"].get(table)
                if count != expected_count:
                    report["errors"].append(f"{table} rows {count} != manifest {expected_count}")
            report["checks"]["table_counts"] = observed_counts
            report["checks"]["generated_files_bytes"] = observed_bytes

            metadata_manifest = {item["path"]: item for item in manifest["metadata_files"]}
            truth_path = run_dir / "ground_truth.csv"
            if not truth_path.is_file():
                report["errors"].append("Missing metadata file: ground_truth.csv")
            else:
                file_info = metadata_manifest.get(truth_path.name)
                if file_info and (
                    truth_path.stat().st_size != file_info["bytes"]
                    or _hash_file(truth_path) != file_info["sha256"]
                ):
                    report["errors"].append("Ground-truth size or checksum mismatch.")
                with truth_path.open(encoding="utf-8", newline="") as truth_stream:
                    truth_reader = csv.DictReader(truth_stream)
                    if tuple(truth_reader.fieldnames or ()) != SCENARIO_COLUMNS:
                        report["errors"].append("Ground-truth column ordering mismatch.")
                    truth_count = 0
                    for truth_row in truth_reader:
                        truth_count += 1
                        db.execute(
                            "INSERT INTO scenarios VALUES (?,?,?,?,?,?,?)",
                            (truth_row["SCENARIO_ID"], truth_row["SCENARIO_TYPE"],
                             truth_row["EXPECTED_CLASSIFICATION"], truth_row["EXPECTED_TIMING_CLASSIFICATION"],
                             truth_row["ORDER_ID"], truth_row["ACTUAL_BATCH_ID"], truth_row["EXPECTED_BATCH_ID"]),
                        )
                    if truth_count != manifest["order_count"]:
                        report["errors"].append("Ground-truth row count differs from order count.")

            foreign_checks = {
                "attempts_without_orders": "SELECT COUNT(*) FROM attempts a LEFT JOIN orders o ON o.id=a.order_id WHERE o.id IS NULL",
                "processor_orders_missing": "SELECT COUNT(*) FROM processors p LEFT JOIN orders o ON o.id=p.order_id WHERE p.order_id IS NOT NULL AND o.id IS NULL",
                "entries_without_batch": "SELECT COUNT(*) FROM entries e LEFT JOIN settlements s ON s.batch_id=e.batch_id WHERE s.batch_id IS NULL",
                "entries_without_processor": "SELECT COUNT(*) FROM entries e LEFT JOIN processors p ON p.id=e.processor_id WHERE p.id IS NULL",
                "banks_without_batch": "SELECT COUNT(*) FROM banks b LEFT JOIN settlements s ON s.batch_id=b.reference WHERE s.batch_id IS NULL",
            }
            for name, query in foreign_checks.items():
                count = db.execute(query).fetchone()[0]
                report["checks"][name] = count
                if count:
                    report["errors"].append(f"{name}: {count}")

            source_orphans = db.execute("""
                SELECT COUNT(*) FROM sources s LEFT JOIN processors p ON p.id=s.processor_id
                WHERE p.id IS NULL
            """).fetchone()[0]
            allowed_source_orphans = sum(
                count for kind, count in manifest["scenario_counts"].items()
                if kind == "missing_processor"
            )
            report["checks"]["source_rows_without_processor"] = source_orphans
            if source_orphans != allowed_source_orphans:
                report["errors"].append(
                    f"source rows without processor {source_orphans} != planned {allowed_source_orphans}"
                )

            currency_errors = db.execute("""
                SELECT
                  (SELECT COUNT(*) FROM orders WHERE currency <> 'INR' OR merchant <> ?)+
                  (SELECT COUNT(*) FROM processors WHERE currency <> 'INR')+
                  (SELECT COUNT(*) FROM settlements WHERE currency <> 'INR')+
                  (SELECT COUNT(*) FROM banks WHERE currency <> 'INR')
            """, (MERCHANT_ID,)).fetchone()[0]
            report["checks"]["non_inr_or_multiple_merchant_rows"] = currency_errors
            if currency_errors:
                report["errors"].append(f"INR-only/single-merchant rule violations: {currency_errors}")

            entry_gross_by_batch = {}
            entry_rows = db.execute("""
                SELECT e.batch_id, p.amount, p.status, p.currency
                FROM entries e JOIN processors p ON p.id=e.processor_id
            """).fetchall()
            for batch, amount, status, currency in entry_rows:
                if status == "CAPTURED" and currency == "INR":
                    entry_gross_by_batch[batch] = entry_gross_by_batch.get(batch, Decimal("0.00")) + Decimal(amount)
            financial_errors = 0
            for batch, gross, fee, refund, chargeback, adjustment, reported, scenario_kind in db.execute(
                """SELECT s.batch_id, s.gross, s.fee, s.refund, s.chargeback,
                          s.adjustment, s.reported, sc.kind
                   FROM settlements s LEFT JOIN scenarios sc ON sc.batch_id=s.batch_id"""
            ):
                gross_value = Decimal(gross)
                if gross_value != entry_gross_by_batch.get(batch, Decimal("0.00")):
                    financial_errors += 1
                expected_net = gross_value - Decimal(fee) - Decimal(refund) - Decimal(chargeback) + Decimal(adjustment)
                reported_net = Decimal(reported)
                expected_reported = expected_net + Decimal("1.00") if scenario_kind == "settlement_component_discrepancy" else expected_net
                if reported_net != expected_reported:
                    financial_errors += 1
            report["checks"]["entry_gross_or_decimal_errors"] = financial_errors
            if financial_errors:
                report["errors"].append(f"entry gross reconciliation or decimal errors: {financial_errors}")

            scenario_counts = dict(db.execute(
                "SELECT kind, COUNT(*) FROM scenarios GROUP BY kind"
            ).fetchall())
            scenario_counts = {
                scenario: scenario_counts.get(scenario, 0)
                for scenario in manifest["scenario_counts"]
            }
            report["checks"]["scenario_counts"] = scenario_counts
            if scenario_counts != manifest["scenario_counts"]:
                report["errors"].append("Scenario counts differ from manifest.")
            scenario_total = db.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0]
            report["checks"]["ground_truth_scenario_rows"] = scenario_total
            if scenario_total != manifest["order_count"]:
                report["errors"].append("Ground-truth scenario row count differs from order count.")

            attempts_by_order = dict(db.execute(
                "SELECT order_id, COUNT(*) FROM attempts GROUP BY order_id"
            ).fetchall())
            processors_by_index = dict(db.execute(
                f"""SELECT CAST(SUBSTR(id, {len(f'SL-GT07-BMK-{run_id}-PTX-') + 1}, 6) AS INTEGER), COUNT(*)
                    FROM processors GROUP BY 1"""
            ).fetchall())
            sources_by_index = dict(db.execute(
                f"""SELECT CAST(SUBSTR(id, {len(f'BMK-{run_id}-SRC-') + 1}, 6) AS INTEGER), COUNT(*)
                    FROM sources GROUP BY 1"""
            ).fetchall())
            entries_by_index = dict(db.execute(
                f"""SELECT CAST(SUBSTR(batch_id, {len(f'SL-GT07-BMK-{run_id}-BAT-') + 1}, 6) AS INTEGER), COUNT(*)
                    FROM entries GROUP BY 1"""
            ).fetchall())
            banks_by_index = dict(db.execute(
                f"""SELECT CAST(SUBSTR(reference, {len(f'SL-GT07-BMK-{run_id}-BAT-') + 1}, 6) AS INTEGER), COUNT(*)
                    FROM banks GROUP BY 1"""
            ).fetchall())
            relationship_errors = 0
            date_errors = 0
            batch_assignment_errors = 0
            for scenario_id, kind, order_id, batch_id, expected_batch in db.execute(
                "SELECT id, kind, order_id, batch_id, expected_batch_id FROM scenarios"
            ):
                index = int(scenario_id[4:])
                expected_attempts = 2 if kind == "payment_retry" else 1
                expected_processors = 0 if kind == "missing_processor" else (2 if kind == "ambiguous_identity" else 1)
                expected_sources = 2 if kind in {"duplicate_source_row", "ambiguous_identity"} else 1
                expected_entries = 0 if kind in {"missing_processor", "missing_settlement_entry"} else (2 if kind == "ambiguous_identity" else 1)
                expected_banks = 0 if kind == "missing_bank_payout" else (2 if kind == "duplicate_bank_reference" else 1)
                if (attempts_by_order.get(order_id, 0) != expected_attempts
                        or processors_by_index.get(index, 0) != expected_processors
                        or sources_by_index.get(index, 0) != expected_sources
                        or entries_by_index.get(index, 0) != expected_entries
                        or banks_by_index.get(index, 0) != expected_banks):
                    relationship_errors += 1
                if (kind == "wrong_batch") != (batch_id != expected_batch):
                    batch_assignment_errors += 1
            report["checks"]["scenario_relationship_errors"] = relationship_errors
            report["checks"]["wrong_batch_assignment_errors"] = batch_assignment_errors
            if relationship_errors:
                report["errors"].append(f"Scenario relationship/cardinality errors: {relationship_errors}")
            if batch_assignment_errors:
                report["errors"].append(f"Wrong batch assignment expectation errors: {batch_assignment_errors}")

            timeline_rows = db.execute("""
                SELECT sc.kind, s.expected_date, s.settled_at
                FROM scenarios sc JOIN settlements s ON s.batch_id=sc.batch_id
            """)
            for kind, expected_date, settled_at in timeline_rows:
                should_be_missing = kind in {"missing_processor", "incomplete_evidence"}
                if (settled_at is None) != should_be_missing:
                    date_errors += 1
                elif settled_at is not None:
                    actual_day = settled_at[:10]
                    should_be_late = kind == "late_settlement"
                    if (actual_day > expected_date) != should_be_late:
                        date_errors += 1
            report["checks"]["scenario_date_errors"] = date_errors
            if date_errors:
                report["errors"].append(f"Scenario expected/actual date errors: {date_errors}")
            db.close()
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError) as error:
        report["errors"].append(f"{type(error).__name__}: {error}")

    report["duration_seconds"] = round(perf_counter() - started, 6)
    report["passed"] = not report["errors"]
    report_path = run_dir / "validation_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
