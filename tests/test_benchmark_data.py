import csv
import json
from decimal import Decimal

import pytest

from scripts import benchmark_data
from scripts.reconciliation_engine import reconcile_orders_attempts_processor_and_settlement


def _logical_files(manifest, run_dir):
    paths = [run_dir / "ground_truth.csv"]
    for shards in manifest["files"].values():
        paths.extend(run_dir / item["path"] for item in shards)
    return {path.name: path.read_bytes() for path in paths}


def test_fixed_seed_is_reproducible_and_independent(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    manifest_left = benchmark_data.generate_dataset("REPRO001", 120, 314159, left, chunk_rows=17)
    manifest_right = benchmark_data.generate_dataset("REPRO001", 120, 314159, right, chunk_rows=17)
    assert _logical_files(manifest_left, left / "REPRO001") == _logical_files(manifest_right, right / "REPRO001")
    assert benchmark_data.validate_dataset("REPRO001", left)["passed"]
    assert "reconciliation_engine" not in open(benchmark_data.__file__, encoding="utf-8").read()


def test_references_counts_and_controlled_retry(tmp_path):
    manifest = benchmark_data.generate_dataset("CHECK001", 300, 9, tmp_path)
    assert manifest["table_counts"]["ORDERS"] == 300
    assert manifest["table_counts"]["PAYMENT_ATTEMPTS"] > 300
    assert manifest["scenario_counts"]["payment_retry"] == 15
    report = benchmark_data.validate_dataset("CHECK001", tmp_path)
    assert report["passed"], report["errors"]
    assert report["checks"]["attempts_without_orders"] == 0
    assert report["checks"]["entries_without_processor"] == 0
    assert report["checks"]["entry_gross_or_decimal_errors"] == 0


def test_inr_distribution_and_run_id_safety(tmp_path):
    bad = dict(benchmark_data.DEFAULT_DISTRIBUTION)
    bad["processor_currency_discrepancy"] = "0.01"
    bad["normal"] = "0.56"
    with pytest.raises(ValueError, match="INR-only"):
        benchmark_data.generate_dataset("SAFE001", 10, 1, tmp_path, bad)
    benchmark_data.generate_dataset("SAFE001", 10, 1, tmp_path)
    with pytest.raises(FileExistsError):
        benchmark_data.generate_dataset("SAFE001", 10, 1, tmp_path)


def test_ground_truth_contains_independent_expected_evidence(tmp_path):
    manifest = benchmark_data.generate_dataset("TRUTH001", 250, 42, tmp_path)
    truth_path = tmp_path / "TRUTH001" / "ground_truth.csv"
    with truth_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 250
    assert all(json.loads(row["EXPECTED_EVIDENCE_JSON"]) is not None for row in rows)
    assert all(row["EXPECTED_TIMING_CLASSIFICATION"] for row in rows)
    assert manifest["currency"] == "INR"


def test_small_fixture_predictions_match_independent_primary_truth(tmp_path):
    run_id = "MATCH001"
    benchmark_data.generate_dataset(run_id, 400, 11, tmp_path, chunk_rows=100)
    run_dir = tmp_path / run_id

    def read_table(table):
        rows = []
        for shard in sorted(run_dir.glob(f"{table.lower()}-*.csv")):
            with shard.open(encoding="utf-8", newline="") as stream:
                for raw in csv.DictReader(stream):
                    rows.append({key: (None if value == benchmark_data.CSV_NULL else value)
                                 for key, value in raw.items()})
        return rows

    result = reconcile_orders_attempts_processor_and_settlement(
        read_table("ORDERS"), read_table("PAYMENT_ATTEMPTS"),
        read_table("PROCESSOR_TRANSACTIONS"), read_table("PROCESSOR_SOURCE_ROWS"),
        read_table("SETTLEMENTS"), read_table("SETTLEMENT_TRANSACTIONS"),
        read_table("BANK_TRANSACTIONS"),
    )
    finding_groups = {}
    for finding in result["findings"]:
        finding_groups.setdefault(finding["finding_type"], []).append(finding)
    with (run_dir / "ground_truth.csv").open(encoding="utf-8", newline="") as stream:
        for truth in csv.DictReader(stream):
            ids = set(json.loads(truth["ENTITY_IDS_JSON"]))
            candidates = [finding for finding in finding_groups.get(truth["PRIMARY_FINDING_TYPE"], [])
                          if ids.intersection(benchmark_entity_ids(finding))]
            expected = truth["EXPECTED_CLASSIFICATION"]
            if expected == "NONE":
                assert not candidates, (truth["SCENARIO_ID"], candidates)
            else:
                assert any(finding["classification"] == expected for finding in candidates), (
                    truth["SCENARIO_ID"], expected, candidates
                )


def benchmark_entity_ids(finding):
    result = set()
    for key, value in finding.items():
        if key.endswith("_id") and isinstance(value, str):
            result.add(value)
        elif key.endswith("_ids") and isinstance(value, list):
            result.update(value)
        elif key == "evidence":
            result.update(item.get("entity_id") for item in value if item.get("entity_id"))
    return result

