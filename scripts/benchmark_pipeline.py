"""Offline-first synthetic benchmark orchestration for SettlementLens.

The ground-truth file is never passed to the reconciliation engine. All Exasol
operations are explicit subcommands and use the central connection helper.
"""

import argparse
import csv
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import sys
from time import perf_counter

from scripts import benchmark_data
from scripts.finding_presentation import present_finding


ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql" / "benchmark"
SLICE_SIZE = 500


def _json_default(value):
    if isinstance(value, Decimal):
        return format(value, ".2f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def generate(args):
    manifest = benchmark_data.generate_dataset(
        args.run_id, args.orders, args.seed, distribution=_read_distribution(args.distribution),
    )
    print(json.dumps({k: manifest[k] for k in (
        "run_id", "seed", "order_count", "scenario_counts", "table_counts",
        "total_source_records", "total_files_bytes", "generation_seconds",
    )}, indent=2))


def _read_distribution(path):
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_float=Decimal)


def validate(args):
    report = benchmark_data.validate_dataset(args.run_id, benchmark_data.DATA_ROOT)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


def _prefixes(run_id):
    return {
        "ORDERS": ("ORDER_ID", f"BMK-{run_id}-ORD-"),
        "PAYMENT_ATTEMPTS": ("ATTEMPT_ID", f"BMK-{run_id}-ATT-"),
        "PROCESSOR_TRANSACTIONS": ("PROCESSOR_TXN_ID", f"SL-GT07-BMK-{run_id}-PTX-"),
        "PROCESSOR_SOURCE_ROWS": ("SOURCE_ROW_ID", f"BMK-{run_id}-SRC-"),
        "SETTLEMENT_TRANSACTIONS": ("BATCH_ID", f"SL-GT07-BMK-{run_id}-BAT-"),
        "SETTLEMENTS": ("BATCH_ID", f"SL-GT07-BMK-{run_id}-BAT-"),
        "BANK_TRANSACTIONS": ("BANK_TXN_ID", f"BMK-{run_id}-BNK-"),
    }


def _read_counts(connection, run_id):
    counts = {}
    for table, (column, prefix) in _prefixes(run_id).items():
        result = connection.execute(
            f"SELECT COUNT(*) FROM SARVAGYA.{table} WHERE {column} LIKE {{prefix}}",
            {"prefix": prefix + "%"},
        )
        counts[table] = result.fetchone()[0]
    return counts


def load(args):
    manifest = benchmark_data.load_manifest(args.run_id, benchmark_data.DATA_ROOT)
    report_path = Path(benchmark_data.DATA_ROOT) / args.run_id / "ingestion_report.json"
    if report_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing ingestion report: {report_path}")
    validation = benchmark_data.validate_dataset(args.run_id, benchmark_data.DATA_ROOT)
    if not validation["passed"]:
        raise RuntimeError("Offline validation failed; see validation_report.json")
    from scripts.analytics_connection import get_analytics_connection

    connection = None
    report = {"run_id": args.run_id, "tables": {}, "failed_batches": [], "complete": False}
    started = perf_counter()
    try:
        connection = get_analytics_connection()
        schema_rows = connection.execute("""
            SELECT COLUMN_TABLE, COLUMN_NAME
            FROM EXA_ALL_COLUMNS
            WHERE COLUMN_SCHEMA = 'SARVAGYA'
        """).fetchall()
        schema = {}
        for table_name, column_name in schema_rows:
            schema.setdefault(table_name, set()).add(column_name)
        missing = {
            table: sorted(set(columns) - schema.get(table, set()))
            for table, columns in benchmark_data.TABLE_COLUMNS.items()
            if set(columns) - schema.get(table, set())
        }
        if missing:
            raise RuntimeError(f"Target schema is missing required columns: {missing}")
        existing = _read_counts(connection, args.run_id)
        if any(existing.values()):
            raise RuntimeError(
                f"Run ID already has records in Exasol ({existing}); use a new run ID. No rows changed."
            )
        for table, files in manifest["files"].items():
            table_started = perf_counter()
            report["tables"][table] = {"loaded_rows": 0, "successful_batches": [], "failed_batch": None}
            for info in files:
                path = Path(benchmark_data.DATA_ROOT) / args.run_id / info["path"]
                try:
                    response = connection.import_from_file(
                        str(path), ("SARVAGYA", table),
                        {"columns": list(benchmark_data.TABLE_COLUMNS[table]), "skip": 1,
                         "column_separator": ",", "column_delimiter": '"', "encoding": "UTF-8",
                         "null": benchmark_data.CSV_NULL, "row_separator": "LF"},
                    )
                    # Exasol returns the imported row count as import_rows when available.
                    imported = info["rows"]
                    if isinstance(response, dict):
                        imported = response.get("import_rows", imported)
                    report["tables"][table]["loaded_rows"] += imported
                    report["tables"][table]["successful_batches"].append(
                        {"file": info["path"], "rows": imported}
                    )
                except Exception as error:
                    failure = {"table": table, "file": info["path"], "error": f"{type(error).__name__}: {error}"}
                    report["tables"][table]["failed_batch"] = failure
                    report["tables"][table]["duration_seconds"] = round(perf_counter() - table_started, 6)
                    report["failed_batches"].append(failure)
                    raise RuntimeError(f"Partial ingestion; see ingestion_report.json: {failure}") from error
            report["tables"][table]["duration_seconds"] = round(perf_counter() - table_started, 6)
        observed = _read_counts(connection, args.run_id)
        expected = manifest["table_counts"]
        report["verified_counts"] = observed
        report["expected_counts"] = expected
        if observed != expected:
            raise RuntimeError(f"Import finished but observed counts differ: expected={expected}, observed={observed}")
        report["complete"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if connection is not None:
            try:
                report["observed_counts_at_exit"] = _read_counts(connection, args.run_id)
            except Exception as error:
                report["count_verification_error"] = f"{type(error).__name__}: {error}"
        report["duration_seconds"] = round(perf_counter() - started, 6)
        report["total_loaded_rows"] = sum(report.get("observed_counts_at_exit", {}).values())
        report["rows_per_second"] = (
            report["total_loaded_rows"] / report["duration_seconds"]
            if report["duration_seconds"] else None
        )
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if connection is not None:
            connection.close()
    print(json.dumps(report, indent=2))


def verify(args):
    from scripts.analytics_connection import get_analytics_connection
    connection = get_analytics_connection()
    try:
        counts = _read_counts(connection, args.run_id)
    finally:
        connection.close()
    expected = benchmark_data.load_manifest(args.run_id, benchmark_data.DATA_ROOT)["table_counts"]
    output = {"run_id": args.run_id, "expected": expected, "observed": counts,
              "passed": counts == expected}
    print(json.dumps(output, indent=2))
    return 0 if output["passed"] else 1


def run_analytics(args):
    from scripts.analytics_connection import get_analytics_connection
    connection = get_analytics_connection()
    prefix = f"BMK-{args.run_id}-%"
    settlement_prefix = f"SL-GT07-BMK-{args.run_id}-%"
    output, total = [], 0.0
    try:
        for path in sorted(SQL_DIR.glob("*.sql")):
            query = path.read_text(encoding="utf-8")
            params = {"order_prefix": prefix, "attempt_prefix": prefix,
                      "processor_prefix": f"SL-GT07-BMK-{args.run_id}-%",
                      "batch_prefix": settlement_prefix, "bank_prefix": prefix}
            start = perf_counter()
            cursor = connection.execute(query, params)
            rows = cursor.fetchall()
            duration = perf_counter() - start
            total += duration
            output.append({"query": path.name, "seconds": round(duration, 6), "rows": len(rows),
                           "sample": rows[:10]})
    finally:
        connection.close()
    report = {"run_id": args.run_id, "queries": output, "total_seconds": round(total, 6)}
    (Path(benchmark_data.DATA_ROOT) / args.run_id / "analytics_report.json").write_text(
        json.dumps(report, default=_json_default, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, default=_json_default, indent=2))


def run_reconciliation(args):
    from scripts.analytics_connection import get_analytics_connection
    from scripts.reconciliation_engine import reconcile_orders_attempts_processor_and_settlement

    run_dir = Path(benchmark_data.DATA_ROOT) / args.run_id
    predictions_path = run_dir / "engine_predictions.jsonl"
    calculations_path = run_dir / "engine_calculations.jsonl"
    if predictions_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing {predictions_path}")
    if calculations_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing {calculations_path}")
    manifest = benchmark_data.load_manifest(args.run_id, benchmark_data.DATA_ROOT)
    connection = get_analytics_connection()
    started = perf_counter()
    counts, findings_by_type, findings_by_classification, findings_by_layer_classification, findings_by_status = 0, {}, {}, {}, {}
    completed_ranges, run_error = [], None
    financial_signed_total = Decimal("0.00")
    financial_absolute_total = Decimal("0.00")
    financial_discrepancy_batches = 0
    try:
        with predictions_path.open("w", encoding="utf-8") as out, calculations_path.open("w", encoding="utf-8") as calculations_out:
            for first in range(1, manifest["order_count"] + 1, SLICE_SIZE):
                last = min(first + SLICE_SIZE, manifest["order_count"] + 1)
                low = f"{first:06d}"
                high = f"{last:06d}"
                def get(table, columns, id_column, prefix):
                    low_id = prefix + low
                    high_id = prefix + high
                    if table == "SETTLEMENTS":
                        # Batch IDs include the index then a date suffix.
                        low_id, high_id = prefix + low + "-", prefix + high + "-"
                    sql = (f"SELECT {columns} FROM SARVAGYA.{table} "
                           f"WHERE {id_column} >= {{lo}} AND {id_column} < {{hi}} "
                           f"AND {id_column} LIKE {{scope}}")
                    cursor = connection.execute(sql, {
                        "lo": low_id, "hi": high_id, "scope": prefix + "%",
                    })
                    names = cursor.column_names()
                    return [dict(zip(names, row)) for row in cursor.fetchall()]

                orders = get("ORDERS", "ORDER_ID, ORDER_AMOUNT, CURRENCY", "ORDER_ID", f"BMK-{args.run_id}-ORD-")
                attempts = get("PAYMENT_ATTEMPTS", "ATTEMPT_ID, ORDER_ID, MERCHANT_PAYMENT_REF, ATTEMPT_AMOUNT, ATTEMPT_STATUS", "ATTEMPT_ID", f"BMK-{args.run_id}-ATT-")
                processors = get("PROCESSOR_TRANSACTIONS", "PROCESSOR_TXN_ID, PROCESSOR_NAME, ORDER_ID, MERCHANT_PAYMENT_REF, TRANSACTION_AMOUNT, CURRENCY, TRANSACTION_STATUS, TRANSACTION_AT", "PROCESSOR_TXN_ID", f"SL-GT07-BMK-{args.run_id}-PTX-")
                sources = get("PROCESSOR_SOURCE_ROWS", "SOURCE_ROW_ID, PROCESSOR_TXN_ID, SOURCE_FILE, SOURCE_ROW_NUMBER, IMPORTED_AT", "SOURCE_ROW_ID", f"BMK-{args.run_id}-SRC-")
                settlements = get("SETTLEMENTS", "BATCH_ID, GROSS_AMOUNT, FEE_AMOUNT, REFUND_AMOUNT, CHARGEBACK_AMOUNT, ADJUSTMENT_AMOUNT, REPORTED_NET_AMOUNT, CURRENCY, EXPECTED_SETTLEMENT_DATE, SETTLED_AT, SETTLEMENT_STATUS", "BATCH_ID", f"SL-GT07-BMK-{args.run_id}-BAT-")
                entries = get("SETTLEMENT_TRANSACTIONS", "BATCH_ID, PROCESSOR_TXN_ID", "BATCH_ID", f"SL-GT07-BMK-{args.run_id}-BAT-")
                banks = get("BANK_TRANSACTIONS", "BANK_TXN_ID, BANK_REFERENCE, AMOUNT, CURRENCY, TRANSACTION_AT, DESCRIPTION, SOURCE_FILE", "BANK_TXN_ID", f"BMK-{args.run_id}-BNK-")
                result = reconcile_orders_attempts_processor_and_settlement(
                    orders, attempts, processors, sources, settlements, entries, banks)
                for finding in result["findings"]:
                    out.write(json.dumps(finding, default=_json_default, sort_keys=True) + "\n")
                    findings_by_type[finding.get("FINDING_TYPE", finding.get("finding_type", "UNKNOWN"))] = findings_by_type.get(finding.get("FINDING_TYPE", finding.get("finding_type", "UNKNOWN")), 0) + 1
                    key = f"{finding.get('finding_type', 'UNKNOWN')}|{finding.get('classification', 'UNKNOWN')}"
                    findings_by_classification[key] = findings_by_classification.get(key, 0) + 1
                    layer_key = f"{finding.get('layer', finding.get('finding_type', 'UNKNOWN'))}|{finding.get('classification', 'UNKNOWN')}"
                    findings_by_layer_classification[layer_key] = findings_by_layer_classification.get(layer_key, 0) + 1
                    status = finding.get("resolution_status", "UNKNOWN")
                    findings_by_status[status] = findings_by_status.get(status, 0) + 1
                counts += len(orders)
                for batch_id, calculation in result["settlement_financial_calculations"].items():
                    discrepancy = Decimal(str(calculation["discrepancy"]))
                    financial_signed_total += discrepancy
                    financial_absolute_total += abs(discrepancy)
                    if discrepancy != 0:
                        financial_discrepancy_batches += 1
                    calculations_out.write(json.dumps(
                        {"batch_id": batch_id, **calculation}, default=_json_default, sort_keys=True
                    ) + "\n")
                completed_ranges.append({"first_order_index": first, "last_order_index": last - 1})
    except Exception as error:
        run_error = f"{type(error).__name__}: {error}"
    finally:
        connection.close()
    report = {"run_id": args.run_id, "orders_reconciled": counts,
              "finding_counts_by_type": findings_by_type,
              "finding_counts_by_type_and_classification": findings_by_classification,
              "finding_counts_by_layer_and_classification": findings_by_layer_classification,
              "financial_discrepancies": {
                  "batches_with_nonzero_difference": financial_discrepancy_batches,
                  "signed_difference_total_expected_minus_reported": format(financial_signed_total, ".2f"),
                  "sum_of_absolute_differences": format(financial_absolute_total, ".2f"),
              },
              "finding_counts_by_resolution_status": findings_by_status,
              "unresolved_findings": findings_by_status.get("UNRESOLVED", 0),
              "completed_ranges": completed_ranges, "error": run_error,
              "complete": run_error is None and counts == manifest["order_count"],
              "duration_seconds": round(perf_counter() - started, 6),
              "ground_truth_used_for_prediction": False}
    (run_dir / "reconciliation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if run_error:
        raise RuntimeError("Partial reconciliation; see reconciliation_report.json")


def evaluate(args):
    started = perf_counter()
    run_dir = Path(benchmark_data.DATA_ROOT) / args.run_id
    reconciliation_report_path = run_dir / "reconciliation_report.json"
    if not reconciliation_report_path.is_file():
        raise FileNotFoundError("Run benchmark reconciliation first.")
    reconciliation_report = json.loads(reconciliation_report_path.read_text(encoding="utf-8"))
    if not reconciliation_report.get("complete"):
        raise RuntimeError("Refusing evaluation of incomplete reconciliation output.")
    predictions = run_dir / "engine_predictions.jsonl"
    if not predictions.is_file():
        raise FileNotFoundError("Run benchmark reconciliation first.")
    by_type = {}
    by_timing_batch = {}
    with predictions.open(encoding="utf-8") as stream:
        for line in stream:
            finding = json.loads(line)
            finding_type = finding.get("finding_type")
            if finding_type == "SETTLEMENT_TIMING_RECONCILIATION":
                by_timing_batch.setdefault(finding.get("batch_id"), []).append(finding)
            for entity_id in _finding_entity_ids(finding):
                by_type.setdefault((finding_type, entity_id), []).append(finding)

    predicted_calculations = {}
    calc_path = run_dir / "engine_calculations.jsonl"
    if calc_path.is_file():
        with calc_path.open(encoding="utf-8") as stream:
            for line in stream:
                calculation = json.loads(line)
                predicted_calculations[calculation["batch_id"]] = calculation

    tp = fp = fn = tn = 0
    timing_correct = timing_total = 0
    financial_count = financial_correct = case_count = 0
    predicted_case_count = predicted_primary_finding_count = 0
    case_results_path = run_dir / "evaluation_cases.jsonl"
    with case_results_path.open("w", encoding="utf-8") as cases_out:
        with (run_dir / "ground_truth.csv").open(encoding="utf-8", newline="") as stream:
            for truth in csv.DictReader(stream):
                case_count += 1
                entity_ids = set(json.loads(truth["ENTITY_IDS_JSON"]))
                candidates_by_id = {}
                for entity_id in entity_ids:
                    for finding in by_type.get((truth["PRIMARY_FINDING_TYPE"], entity_id), ()):
                        candidates_by_id[finding.get("finding_id")] = finding
                candidates = list(candidates_by_id.values())
                if candidates:
                    predicted_case_count += 1
                    predicted_primary_finding_count += len(candidates)
                expected = truth["EXPECTED_CLASSIFICATION"]
                exact = [f for f in candidates if f.get("classification") == expected]
                if expected == "NONE":
                    if candidates:
                        fp += len(candidates)
                        outcome = "false_positive"
                    else:
                        tn += 1
                        outcome = "true_negative"
                elif exact:
                    tp += 1
                    fp += max(0, len(candidates) - 1)
                    outcome = "true_positive"
                else:
                    fn += 1
                    fp += len(candidates)
                    outcome = "false_negative"
                cases_out.write(json.dumps({
                    "scenario_id": truth["SCENARIO_ID"], "outcome": outcome,
                    "expected": expected,
                    "predicted": [f.get("classification") for f in candidates],
                }) + "\n")

                timing_total += 1
                timing = by_timing_batch.get(truth["ACTUAL_BATCH_ID"], ())
                if any(f.get("classification") == truth["EXPECTED_TIMING_CLASSIFICATION"] for f in timing):
                    timing_correct += 1

                prediction = predicted_calculations.get(truth["ACTUAL_BATCH_ID"])
                if prediction is not None:
                    financial_count += 1
                    financial_correct += int(
                        Decimal(str(prediction["expected_net_amount"])) == Decimal(truth["EXPECTED_AMOUNT"])
                        and Decimal(str(prediction["reported_net_amount"])) == Decimal(truth["OBSERVED_AMOUNT"])
                        and Decimal(str(prediction["discrepancy"])) == Decimal(truth["DIFFERENCE_AMOUNT"])
                    )

    denominator = tp + fp
    expected_positive = tp + fn
    report = {
        "run_id": args.run_id,
        "duration_seconds": round(perf_counter() - started, 6),
        "primary_case_evaluation": {
            "cases": case_count, "true_positives": tp, "true_negatives": tn,
            "false_positives": fp, "false_negatives": fn,
            "predicted_positive_cases": predicted_case_count,
            "predicted_primary_findings": predicted_primary_finding_count,
            "precision": tp / denominator if denominator else None,
            "recall": tp / expected_positive if expected_positive else None,
            "denominators": {
                "precision": "TP / (TP + FP), where each extra or wrong finding of the expected primary layer is an FP",
                "recall": "TP / expected positive cases (TP + FN); NONE control cases are excluded",
                "true_negatives": "NONE control cases with no finding of the primary layer",
            },
            "false_matches": fp, "missed_matches": fn,
            "case_outcomes_file": case_results_path.name,
        },
        "timing_layer": {"cases": timing_total, "correct_classification": timing_correct,
                         "accuracy": timing_correct / timing_total if timing_total else None,
                         "denominator": "one timing classification comparison per generated case"},
        "financial_calculations": {
            "compared_batches": financial_count, "correct_calculations": financial_correct,
            "accuracy": financial_correct / financial_count if financial_count else None,
            "definition": "Exact Decimal equality for expected net, reported net, and the engine's expected-minus-reported discrepancy; missing calculation rows are excluded and counted by the denominator.",
        },
        "unresolved_engine_findings": reconciliation_report.get("unresolved_findings"),
        "evaluation_scope": "Transaction/scenario primary layer and settlement batch financial/timing layers are evaluated separately.",
        "ground_truth_used_for_prediction": False,
        "limitations": [
            "Primary evaluation counts only findings of each case's declared primary finding type; other independently modeled layers are reported by reconciliation, not treated as primary false positives.",
            "Financial accuracy is evaluated from Exasol engine calculations in analytics output, and is not claimed by this offline finding evaluator.",
        ],
    }
    path = run_dir / "evaluation_report.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # Keep the saved report complete while making the console summary concise.
    print(json.dumps(report, indent=2))
    return 0


def _safe_terminal(value):
    return "".join(character if character.isprintable() else " " for character in str(value))


def _local_findings(run_id):
    path = Path(benchmark_data.DATA_ROOT) / run_id / "engine_predictions.jsonl"
    if not path.is_file():
        raise FileNotFoundError("Run benchmark reconciliation first.")
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            yield record, present_finding(record)


def list_findings(args):
    search = args.search.casefold() if args.search else None
    shown = 0
    for record, item in _local_findings(args.run_id):
        if args.status and args.status.casefold() != item["status"].casefold():
            continue
        if args.layer and args.layer.casefold() not in item["layer"].casefold():
            continue
        if search and search not in " ".join((
            item["title"], item["explanation"], item["layer"],
            str(record.get("finding_id", "")),
            " ".join(str(ref["value"]) for ref in item["references"]),
        )).casefold():
            continue
        refs = ", ".join(f"{ref['label']}: {_safe_terminal(ref['value'])}"
                          for ref in item["references"][:3]) or "Reference not available"
        amounts = ""
        if item["expected_amount"] is not None or item["observed_amount"] is not None:
            amounts = (f" | expected {item['expected_amount_display']}"
                       f" | observed {item['observed_amount_display']}"
                       f" | difference {item['difference_display']}")
        print(f"{item['title']} [{item['status']}] | {item['layer']} | {refs}"
              f"{amounts} | ID {record.get('finding_id')}")
        shown += 1
    if shown == 0:
        print("No benchmark findings match the requested filters.")
    print(f"Findings shown: {shown}")


def show_finding(args):
    matches = []
    for record, item in _local_findings(args.run_id):
        finding_id = str(record.get("finding_id", ""))
        if finding_id == args.finding_id:
            matches = [(record, item)]
            break
        if finding_id.startswith(args.finding_id):
            matches.append((record, item))
    if not matches:
        raise LookupError(f"No finding matches ID or prefix {args.finding_id}")
    if len(matches) != 1:
        raise LookupError("Finding reference prefix is ambiguous; provide a longer or full ID.")
    record, item = matches[0]
    print(_safe_terminal(item["title"]))
    print(f"Status: {_safe_terminal(item['status'])}")
    print(f"Layer: {_safe_terminal(item['layer'])}")
    print(f"Finding ID: {_safe_terminal(record.get('finding_id'))}")
    print(f"Classification: {_safe_terminal(item['classification'])}")
    print(f"\nWhat happened: {_safe_terminal(item['explanation'])}")
    print("\nAffected references:")
    for ref in item["references"]:
        print(f"  {_safe_terminal(ref['label'])}: {_safe_terminal(ref['value'])}")
    print("\nAmounts:")
    print(f"  Expected: {item['expected_amount_display']}")
    print(f"  Observed: {item['observed_amount_display']}")
    print(f"  Difference: {item['difference_display']}")
    if item["difference_convention"]:
        print(f"  Sign convention: {_safe_terminal(item['difference_convention'])}")
    for component in item["financial_components"]:
        print(f"  {component['label']}: {component['display']}")
    print("\nDates:")
    print(f"  Expected: {item['expected_date_display']}")
    print(f"  Actual: {item['actual_date_display']}")
    if item["delay_days"] is not None:
        print(f"  Delay: {_safe_terminal(item['delay_days'])} calendar days")
    elif item["delay_minutes"] is not None:
        print(f"  Delay: {_safe_terminal(item['delay_minutes'])} minutes")
    print("\nEvidence:")
    if item["evidence"]:
        for evidence in item["evidence"]:
            print("  " + _safe_terminal(json.dumps(evidence, ensure_ascii=False, default=str)))
    else:
        print("  No evidence references are available.")
    print("\nSource-row lineage:")
    for lineage in item["source_row_lineage"]:
        print("  " + _safe_terminal(json.dumps(lineage, ensure_ascii=False, default=str)))
    if not item["source_row_lineage"]:
        print("  Not available")
    if item["candidates"]:
        print("\nPreserved candidates:")
        for number, candidate in enumerate(item["candidates"], 1):
            rendered = json.dumps(candidate, ensure_ascii=False, default=str)
            print(f"  Candidate {number}: {_safe_terminal(rendered)}")
    print("\nLimitations and unresolved questions:")
    for limitation in item["limitations"]:
        print("  " + _safe_terminal(limitation))
    for check in item["suggested_checks"]:
        print("Suggested check: " + _safe_terminal(check))
    if args.technical:
        print("\nTechnical details:")
        print(json.dumps(record, indent=2, ensure_ascii=False, default=str))


def _finding_entity_ids(finding):
    ids = set()
    for key, value in finding.items():
        if key.endswith("_id") and isinstance(value, str):
            ids.add(value)
        elif key.endswith("_ids") and isinstance(value, (list, tuple)):
            ids.update(item for item in value if isinstance(item, str))
        elif key == "evidence" and isinstance(value, list):
            ids.update(item.get("entity_id") for item in value if isinstance(item, dict))
    return ids


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("generate", help="Generate CSV shards and independent truth offline")
    p.add_argument("--run-id", required=True)
    p.add_argument("--orders", type=int, choices=(10_000, 100_000), required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--distribution")
    p.set_defaults(func=generate)
    p = sub.add_parser("validate", help="Validate generated dataset offline")
    p.add_argument("--run-id", required=True); p.set_defaults(func=validate)
    p = sub.add_parser("load", help="Safely bulk-import prepared CSV shards into Exasol")
    p.add_argument("--run-id", required=True); p.set_defaults(func=load)
    p = sub.add_parser("verify", help="Read-only per-table count check in Exasol")
    p.add_argument("--run-id", required=True); p.set_defaults(func=verify)
    p = sub.add_parser("analytics", help="Run benchmark SQL inside Exasol")
    p.add_argument("--run-id", required=True); p.set_defaults(func=run_analytics)
    p = sub.add_parser("reconcile", help="Reconcile only one benchmark run in bounded slices")
    p.add_argument("--run-id", required=True); p.set_defaults(func=run_reconciliation)
    p = sub.add_parser("evaluate", help="Compare predictions against local independent truth")
    p.add_argument("--run-id", required=True); p.set_defaults(func=evaluate)
    p = sub.add_parser("findings", help="List local benchmark predictions in readable form")
    p.add_argument("--run-id", required=True)
    p.add_argument("--status")
    p.add_argument("--layer")
    p.add_argument("--search")
    p.set_defaults(func=list_findings)
    p = sub.add_parser("show", help="Show one local benchmark finding and its evidence")
    p.add_argument("--run-id", required=True)
    p.add_argument("--finding-id", required=True)
    p.add_argument("--technical", action="store_true")
    p.set_defaults(func=show_finding)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
        return result if isinstance(result, int) else 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
