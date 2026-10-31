import argparse
import csv
import json
from pathlib import Path

import pytest
from pyexasol.formatter import ExaFormatter
from pyexasol.query_builders.csv.builders import ImportBuilder
from pyexasol.query_builders.csv.clause_formatter import ClauseFormatter

from scripts import benchmark_data, benchmark_pipeline


def test_analytics_queries_are_read_only_and_parameterized():
    files = sorted(benchmark_pipeline.SQL_DIR.glob("*.sql"))
    assert len(files) >= 5
    class FormatterConnection:
        options = {"quote_ident": False}

    formatter = ExaFormatter(FormatterConnection())
    params = {"attempt_prefix": "BMK-RUN1-%", "processor_prefix": "SL-GT07-BMK-RUN1-%",
              "batch_prefix": "SL-GT07-BMK-RUN1-%", "bank_prefix": "BMK-RUN1-%"}
    for path in files:
        raw_sql = path.read_text(encoding="utf-8")
        sql = formatter.format(raw_sql, **params).lstrip().upper()
        assert sql.startswith(("SELECT", "WITH"))
        assert not any(token in sql for token in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE ", "CREATE ", "DROP "))
        assert "{" not in sql
        assert "BMK-RUN1-%" in sql


def test_evaluator_metrics_have_explicit_denominators(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark_data, "DATA_ROOT", tmp_path)
    run_id = "EVAL001"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    fields = benchmark_data.SCENARIO_COLUMNS
    truth = {column: "" for column in fields}
    truth.update({
        "RUN_ID": run_id, "SCENARIO_ID": "SCN-000001", "SCENARIO_TYPE": "normal",
        "PRIMARY_FINDING_TYPE": "PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION",
        "EXPECTED_CLASSIFICATION": "NONE", "ENTITY_IDS_JSON": '["ORDER-1"]',
        "ACTUAL_BATCH_ID": "BATCH-1", "EXPECTED_TIMING_CLASSIFICATION": "ON_TIME",
    })
    with (run_dir / "ground_truth.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerow(truth)
    (run_dir / "engine_predictions.jsonl").write_text("", encoding="utf-8")
    (run_dir / "engine_calculations.jsonl").write_text("", encoding="utf-8")
    (run_dir / "reconciliation_report.json").write_text(json.dumps({"complete": True}), encoding="utf-8")
    assert benchmark_pipeline.evaluate(argparse.Namespace(run_id=run_id)) == 0
    report = json.loads((run_dir / "evaluation_report.json").read_text(encoding="utf-8"))
    primary = report["primary_case_evaluation"]
    assert primary["true_negatives"] == 1
    assert primary["precision"] is None
    assert primary["recall"] is None
    assert report["timing_layer"]["cases"] == 1


def test_evaluator_counts_false_positive_and_false_negative(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark_data, "DATA_ROOT", tmp_path)
    run_id = "METR001"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    fields = benchmark_data.SCENARIO_COLUMNS
    truths = []
    for index, (classification, entity_id) in enumerate((
        ("EXPECTED", "POS1"), ("EXPECTED", "POS2"), ("NONE", "NEG1"), ("NONE", "NEG2"),
    ), 1):
        truth = {column: "" for column in fields}
        truth.update({
            "RUN_ID": run_id, "SCENARIO_ID": f"SCN-{index:06d}", "SCENARIO_TYPE": "normal",
            "PRIMARY_FINDING_TYPE": "PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION",
            "EXPECTED_CLASSIFICATION": classification,
            "ENTITY_IDS_JSON": json.dumps([entity_id]),
            "ACTUAL_BATCH_ID": f"BATCH-{index}",
            "EXPECTED_TIMING_CLASSIFICATION": "ON_TIME",
        })
        truths.append(truth)
    with (run_dir / "ground_truth.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(truths)
    predictions = []
    for finding_id, entity_id, classification in (
        ("FND-1", "POS1", "EXPECTED"), ("FND-2", "POS2", "OTHER"),
        ("FND-3", "NEG1", "UNEXPECTED"),
    ):
        predictions.append({
            "finding_id": finding_id,
            "finding_type": "PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION",
            "classification": classification,
            "resolution_status": "UNRESOLVED",
            "evidence": [{"entity_type": "PAYMENT_ATTEMPT", "entity_id": entity_id}],
        })
    predictions.extend({
        "finding_id": f"TIME-{index}",
        "finding_type": "SETTLEMENT_TIMING_RECONCILIATION",
        "classification": "ON_TIME", "batch_id": f"BATCH-{index}",
    } for index in range(1, 5))
    (run_dir / "engine_predictions.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in predictions), encoding="utf-8")
    (run_dir / "engine_calculations.jsonl").write_text("", encoding="utf-8")
    (run_dir / "reconciliation_report.json").write_text(
        json.dumps({"complete": True, "unresolved_findings": 3}), encoding="utf-8")
    benchmark_pipeline.evaluate(argparse.Namespace(run_id=run_id))
    report = json.loads((run_dir / "evaluation_report.json").read_text(encoding="utf-8"))
    primary = report["primary_case_evaluation"]
    assert (primary["true_positives"], primary["true_negatives"],
            primary["false_positives"], primary["false_negatives"]) == (1, 1, 2, 1)
    assert primary["precision"] == pytest.approx(1 / 3)
    assert primary["recall"] == pytest.approx(1 / 2)
    assert report["timing_layer"]["accuracy"] == 1


def test_normal_reconciliation_data_excludes_benchmark_prefixes():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "reconciliation_data.py").read_text(encoding="utf-8")
    assert "ORDER_ID NOT LIKE 'BMK-%'" in source
    assert "BATCH_ID NOT LIKE 'SL-GT07-BMK-%'" in source


class _Cursor:
    def __init__(self, rows=(), columns=()):
        self.rows = rows
        self.columns = columns

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]

    def column_names(self):
        return self.columns


class _FakeConnection:
    def __init__(self, fail_on=None):
        self.imports = []
        self.queries = []
        self.closed = False
        self.fail_on = fail_on
        self.counts = {table: 0 for table in benchmark_data.TABLE_COLUMNS}

    def execute(self, sql, params=None):
        self.queries.append(sql)
        if "EXA_ALL_COLUMNS" in sql:
            return _Cursor([(table, column) for table, columns in benchmark_data.TABLE_COLUMNS.items()
                            for column in columns])
        table = sql.split("SARVAGYA.", 1)[1].split()[0]
        return _Cursor([(self.counts[table],)])

    def import_from_file(self, path, table, params):
        self.imports.append((path, table, params))
        if self.fail_on and len(self.imports) == self.fail_on:
            raise RuntimeError("mocked import failure")
        with open(path, encoding="utf-8", newline="") as stream:
            self.counts[table[1]] += sum(1 for _ in csv.reader(stream)) - 1
        return None

    def close(self):
        self.closed = True


def test_bulk_import_mocked_success_and_rerun_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark_data, "DATA_ROOT", tmp_path)
    benchmark_data.generate_dataset("LOAD001", 8, 4, tmp_path, chunk_rows=2)
    fake = _FakeConnection()
    monkeypatch.setattr("scripts.analytics_connection.get_analytics_connection", lambda: fake)
    benchmark_pipeline.load(argparse.Namespace(run_id="LOAD001"))
    report = json.loads((tmp_path / "LOAD001" / "ingestion_report.json").read_text())
    assert report["complete"] is True
    assert len(fake.imports) == sum(len(items) for items in benchmark_data.load_manifest("LOAD001", tmp_path)["files"].values())
    expected_targets = [
        ("SARVAGYA", table)
        for table, shards in benchmark_data.load_manifest("LOAD001", tmp_path)["files"].items()
        for _ in shards
    ]
    assert [table_id for _, table_id, _ in fake.imports] == expected_targets
    class FormatterConnection:
        options = {"quote_ident": False}

    formatter = ExaFormatter(FormatterConnection())
    for _, table_id, params in fake.imports:
        table = table_id[1]
        assert params == {
            "columns": list(benchmark_data.TABLE_COLUMNS[table]),
            "skip": 1,
            "column_separator": ",",
            "column_delimiter": '"',
            "encoding": "UTF-8",
            "null": benchmark_data.CSV_NULL,
            "row_separator": "LF",
        }
        import_builder = ImportBuilder(
            compression=False, table=table_id, **params,
        )
        row_separator_sql = ClauseFormatter(formatter).row_separator(import_builder.row_separator)
        assert row_separator_sql == "ROW SEPARATOR = 'LF'"
        assert "\n" not in row_separator_sql and "\r" not in row_separator_sql
    assert fake.closed
    assert all("DELETE" not in sql.upper() and "TRUNCATE" not in sql.upper() for sql in fake.queries)
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        benchmark_pipeline.load(argparse.Namespace(run_id="LOAD001"))


def test_bulk_import_partial_failure_is_reported_without_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark_data, "DATA_ROOT", tmp_path)
    benchmark_data.generate_dataset("PART001", 8, 5, tmp_path, chunk_rows=2)
    fake = _FakeConnection(fail_on=2)
    monkeypatch.setattr("scripts.analytics_connection.get_analytics_connection", lambda: fake)
    with pytest.raises(RuntimeError, match="Partial ingestion"):
        benchmark_pipeline.load(argparse.Namespace(run_id="PART001"))
    report_text = (tmp_path / "PART001" / "ingestion_report.json").read_text()
    report = json.loads(report_text)
    assert report["complete"] is False
    assert len(report["failed_batches"]) == 1
    assert sum(table["loaded_rows"] for table in report["tables"].values()) == 2
    assert "password" not in report_text.lower()
    assert fake.closed
    import_calls = len(fake.imports)
    with pytest.raises(FileExistsError, match="Refusing to overwrite existing ingestion report"):
        benchmark_pipeline.load(argparse.Namespace(run_id="PART001"))
    assert len(fake.imports) == import_calls
    assert (tmp_path / "PART001" / "ingestion_report.json").read_text() == report_text


def test_local_finding_list_and_detail_preserve_evidence(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(benchmark_data, "DATA_ROOT", tmp_path)
    run_dir = tmp_path / "SHOW001"
    run_dir.mkdir()
    finding = {
        "finding_id": "FND-1234567890", "finding_type": "PAYMENT_ATTEMPT_PROCESSOR_RECONCILIATION",
        "classification": "MULTIPLE_PROCESSOR_TRANSACTION_CANDIDATES",
        "resolution_status": "UNRESOLVED", "attempt_id": "ATT-EXACT-1",
        "processor_transaction_ids": ["PTX-CANDIDATE-1", "PTX-CANDIDATE-2"],
        "evidence": [{"entity_type": "PAYMENT_ATTEMPT", "entity_id": "ATT-EXACT-1"}],
        "limitation": "All explicit candidates are preserved.",
    }
    (run_dir / "engine_predictions.jsonl").write_text(json.dumps(finding) + "\n", encoding="utf-8")
    benchmark_pipeline.list_findings(argparse.Namespace(run_id="SHOW001", status=None, layer=None, search="candidate"))
    assert "Multiple processor transactions match" in capsys.readouterr().out
    benchmark_pipeline.show_finding(argparse.Namespace(run_id="SHOW001", finding_id="FND-123", technical=False))
    output = capsys.readouterr().out
    assert "FND-1234567890" in output
    assert "PTX-CANDIDATE-2" in output
    assert "All explicit candidates are preserved" in output
