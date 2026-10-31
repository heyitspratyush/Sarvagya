# Architecture

## Components and data flow

```text
Synthetic GT01–GT15 fixtures       Scalable benchmark generator
              │                               │
              └──────────────┬────────────────┘
                             ▼
               Existing SARVAGYA source tables
                             │
                    Exasol analytical SQL
                             │
          Central connection helper / source retrieval
                             │
             Deterministic Python reconciliation engine
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
       Findings in Exasol       Local benchmark predictions
       + entity evidence        (ground truth kept separate)
              │                             │
              ▼                             ▼
     Read-only terminal view        Post-run evaluator
```

### Source data

The seven source tables in `SARVAGYA` are `ORDERS`, `PAYMENT_ATTEMPTS`, `PROCESSOR_TRANSACTIONS`, `PROCESSOR_SOURCE_ROWS`, `SETTLEMENT_TRANSACTIONS`, `SETTLEMENTS`, and `BANK_TRANSACTIONS`. Their definitions are under `sql/schema/`. GT01–GT15 are small SQL fixtures under `seed/data/`; each loader script works on dedicated synthetic identifiers. Benchmark runs are isolated through run-specific ID prefixes because the source schemas do not contain a run-ID column. The normal source reader filters those benchmark prefixes.

### Exasol analytical work

Existing merchant-level analytical SQL is under `sql/analytics/`. The benchmark's five SQL queries under `sql/benchmark/` execute in Exasol and cover:

- payment-attempt counts and status profiles;
- processor candidate counts using explicit order/payment references and conflict checks;
- settlement transaction gross aggregation by batch and component/net comparisons;
- exact bank-reference candidate counts and unique payout comparisons;
- settlement expected-date versus actual-date summaries.

The benchmark runner records each query's execution time and returned row count. These queries perform grouped analytical work in Exasol; they are not Python-only analysis over downloaded source tables.

### Deterministic reconciliation

`scripts/reconciliation_data.py` retrieves the source tables using `scripts/analytics_connection.py`. `scripts/reconciliation_engine.py` performs deterministic matching and classification. It requires explicit, non-conflicting order or merchant-payment references for processor identity; amount equality is not a match key. It preserves multiple candidates and distinguishes payment collection, processor settlement, settlement financials, bank payout, and settlement timing. It uses `Decimal` for monetary calculations.

The settlement-header formula in the engine is:

```text
expected net = gross - fees - refunds - chargebacks + signed adjustment
settlement difference = expected net - reported net
```

Bank comparison uses the exact bank reference to the batch, and the signed difference is observed bank amount minus reported settlement net. Timing compares the timestamp's calendar date with the header's explicit expected settlement date. No universal T+2 is assumed. The special dated batch suffix check is limited to the synthetic GT07/GT08-style processor IDs; it is not a general batch-assignment rule.

### Findings, evidence, investigation

`scripts/reconciliation_persistence.py` writes supported findings to `RECONCILIATION_FINDINGS` and evidence references to `FINDING_EVIDENCE`. Findings retain type, classification, resolution status, financial/date fields, `EVIDENCE_SUMMARY`, and limitations. Evidence rows retain the finding ID, entity type and ID, and evidence role. Source-row lineage is included in the structured summary where applicable.

`scripts/finding_presentation.py` maps structured records to user-readable titles, status labels, values, evidence, limitations, and suggested checks. `scripts/inspect_reconciliation_state.py` retrieves persisted findings/evidence through read-only queries and renders a terminal report. Full IDs, aliases, payloads, and references are available in technical detail mode. This is not a graphical UI.

### Benchmark prediction and independent evaluation

`scripts/benchmark_data.py` streams deterministic table CSV shards and an independent `ground_truth.csv`. The ground truth is authored from generator scenario rules and is not passed into the engine. `scripts/benchmark_pipeline.py load` bulk-imports shards; `verify` checks run-prefix counts; `analytics` invokes the five Exasol SQL reports; and `reconcile` fetches 500-order slices and writes predictions/calculations locally without persisting benchmark findings. `evaluate` runs only after reconciliation completes and compares those outputs with local ground truth.

Primary scenario classification, settlement timing, and financial calculations are evaluated separately. The timing evaluator currently treats a batch as correct if any timing finding for that batch has the expected classification. One batch had multiple timing findings in FINAL10K03, so the reported 10,000/10,000 result is not independent one-to-one timing accuracy.

## Authentication and integration boundaries

The repository uses one central Exasol helper and an ignored `config/exasol.env` file, with a secure interactive password prompt when configured blank. PyExasol is the database driver. No MCP component or MCP connection flow is implemented or verified in this repository. There are no live processor/bank connectors, FX service, or LLM matching component.

## Known implementation boundary

The benchmark source tables are the existing schemas; isolation is by IDs, not a new database schema. Benchmark findings remain local prediction JSONL rather than being persisted into the normal findings tables. The existing interface is terminal-based. See [README.md](README.md) for current setup caveats and measured FINAL10K03 results.
