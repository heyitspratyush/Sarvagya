# Three-minute SettlementLens demo script

This walkthrough uses the existing, verified `FINAL10K03` artifacts. It does not reload the dataset or rerun reconciliation. The benchmark's report files are local under the ignored `.benchmark-data/` directory. A terminal is the current investigation interface.

## 0:00–0:25 — Problem and boundary

**Say:** “A merchant payment has several stages: payment attempt, processor collection, settlement batch, and bank payout. A reference or amount missing at one stage does not prove that payment failed. SettlementLens keeps those questions separate and preserves ambiguous evidence.”

Show the layer table in `README.md`. Emphasize explicit references and no amount-only identity matching.

## 0:25–0:55 — Benchmark provenance and verified counts

From the repository root:

```bash
cat .benchmark-data/FINAL10K03/manifest.json
cat .benchmark-data/FINAL10K03/validation_report.json
```

**Say:** “This deterministic run has 10,000 orders and 70,500 source rows across seven tables. The offline validator passed before load. Ground truth was generated independently from the reconciliation engine.”

## 0:55–1:25 — Exasol work and measured result

```bash
cat .benchmark-data/FINAL10K03/ingestion_report.json
cat .benchmark-data/FINAL10K03/analytics_report.json
```

**Say:** “The stored ingestion report records all 70,500 rows loaded, matching expected and observed table counts, with no failed batches. Five analytical SQL queries ran inside Exasol in about 2.075 seconds total. The separate `verify` command was also reported as passing with matching counts.”

Do not claim a comparison against another database or general performance superiority.

## 1:25–1:55 — Reconciliation and evaluation

```bash
cat .benchmark-data/FINAL10K03/reconciliation_report.json
cat .benchmark-data/FINAL10K03/evaluation_report.json
```

**Say:** “Reconciliation completed for all 10,000 orders. Primary evaluation reports 4,000 true positives, 6,000 true negatives, no false positives or negatives, with precision and recall of 1.0 under the documented evaluator definitions. Exact Decimal financial comparisons were correct for all 10,000 batches. There are 4,700 unresolved engine findings; unresolved is an explicit outcome, not a hidden failure.”

**Timing qualification:** “The timing evaluator reports a match for each batch if any timing finding has the expected classification. One batch had multiple timing findings, so this is not proven one-to-one timing accuracy.”

## 1:55–2:45 — Human-readable evidence inspection

```bash
python -m scripts.benchmark_pipeline findings --run-id FINAL10K03 --search "multiple bank transactions"
python -m scripts.benchmark_pipeline show --run-id FINAL10K03 --finding-id FND-1e48ffcc32773554cb0a149068bec86d515c85a0
```

The demonstrated local finding preserves two bank candidates for one settlement batch, labels the result ambiguous, shows the expected amount, and does not select a candidate. Point to its evidence references and limitations.

## 2:45–3:00 — Close

**Say:** “The contribution is an inspectable deterministic workflow and measured behavior against independent synthetic truth. It is a prototype: one synthetic INR merchant, no real integrations or FX, and a terminal interface rather than a dashboard. The 100,000-order data is offline-prepared only.”

Do not run `load` or `reconcile` during this walkthrough; the verified run is already present and its loader/reconciliation artifacts are protected against overwriting.
