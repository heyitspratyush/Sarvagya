# SettlementLens

**Evidence-backed merchant settlement reconciliation for ExaThon India 2026**

SettlementLens is a prototype for tracing a merchant order through payment attempts, processor transactions, processor settlement batches, and bank payout evidence. It turns incomplete or conflicting source records into deterministic findings with preserved references and limitations.

Reconciliation is an established problem with existing commercial products. SettlementLens demonstrates a transparent, deterministic approach whose matching decisions and evidence can be inspected, and whose correctness can be measured on synthetic cases.

## What it does

- Reconciles orders and multiple payment attempts to processor transactions using explicit order or merchant-payment references.
- Distinguishes processor collection evidence from a payment-attempt `SUCCESS` status. The engine treats `CAPTURED` processor status as the synthetic collection evidence.
- Checks processor transaction IDs against settlement transaction entries and preserves ambiguous or missing links.
- Calculates settlement header net as gross minus fees, refunds, and chargebacks, plus the signed adjustment, using `Decimal`; the difference is expected net minus reported net.
- Compares a settlement batch to bank rows by exact batch reference. It preserves multiple bank candidates and does not choose by amount.
- Compares a settlement timestamp with the explicit expected settlement date in its header. It does not assume universal T+2 or infer a cause for lateness.
- Persists findings and source evidence in Exasol and provides both a **merchant-friendly graphical dashboard** (`gui/`) and a **terminal-based** investigation report (`scripts/inspect_reconciliation_state.py`).
- Generates an isolated, reproducible benchmark with local independent ground truth and read-only Exasol analytics.

Missing evidence is unverified or unresolved; it is not automatically treated as failure. Equal amounts do not prove identity. Duplicate source rows do not, by themselves, prove duplicate collections.

## Submission deliverables

| Item | Details | Link |
|---|---|---|
| **Demonstration Video** | 3-minute video walkthrough (40.83 MB) | [`submission/demo.mp4`](submission/demo.mp4) |
| **Submission Guide** | Video specs, pitch deck checklist, and delivery notes | [`submission/README.md`](submission/README.md) |
| **Merchant Graphical Interface** | Interactive Flask dashboard with 5-stage lifecycle flow | [`gui/`](gui/) |
| **Deterministic Engine** | Multi-layer reconciliation with Decimal arithmetic | [`scripts/reconciliation_engine.py`](scripts/reconciliation_engine.py) |
| **Exasol Benchmark** | Verified FINAL10K03 10,000-order pipeline | [`scripts/benchmark_pipeline.py`](scripts/benchmark_pipeline.py) |

## Reconciliation layers

| Layer | Main question | Examples of outcomes |
|---|---|---|
| Order and payment attempt | Does an attempt reference an available order? | Unlinked or multiple attempts |
| Payment attempt and processor | Is there a non-conflicting explicit identity link, and does processor evidence confirm collection? | No candidate, ambiguous candidates, amount or currency discrepancy |
| Processor and settlement | Does a settlement entry reference the processor transaction? | Missing entry, ambiguous entry, synthetic dated-batch mismatch |
| Settlement financials | Do settlement header components calculate to its reported net? | Amount mismatch or invalid header evidence |
| Settlement and bank payout | Does exactly one bank transaction reference the settlement batch? | Unverified, ambiguous, currency or amount mismatch |
| Settlement timing | Is the actual settlement date on or before the stored expected date? | On time, confirmed late, unresolved |

Financial and timing outcomes are separate. A late settlement can be financially correct. A synthetic batch-date suffix check is limited to the existing GT07/GT08-style fixture IDs; it is not an assertion about universal processor business-date rules.

## Architecture and data flow

1. Source rows are stored in the existing `SARVAGYA` Exasol schema: `ORDERS`, `PAYMENT_ATTEMPTS`, `PROCESSOR_TRANSACTIONS`, `PROCESSOR_SOURCE_ROWS`, `SETTLEMENT_TRANSACTIONS`, `SETTLEMENTS`, and `BANK_TRANSACTIONS`.
2. The GT01–GT15 SQL fixtures create small, explainable correctness and adversarial cases. The scalable benchmark is separate and uses run-specific ID prefixes.
3. Exasol SQL performs analytical joins and aggregation. Existing queries are under `sql/analytics/`; the benchmark has five grouped queries under `sql/benchmark/` for attempt profiles, explicit-reference identity candidates, settlement components, bank references, and timing.
4. `scripts/reconciliation_data.py` reads source rows over one central connection and excludes benchmark-prefixed rows from the ordinary reconciliation scan. `scripts/reconciliation_engine.py` applies deterministic Python rules without fuzzy or amount-only identity matching.
5. `scripts/reconciliation_persistence.py` stores supported findings in `RECONCILIATION_FINDINGS` and entity evidence in `FINDING_EVIDENCE`. Serialized `EVIDENCE_SUMMARY` retains finding details, evidence and limitations; source-row lineage is kept in the finding payload where applicable.
6. `scripts/inspect_reconciliation_state.py` retrieves persisted findings and evidence and renders them in a terminal report. The **merchant-friendly graphical dashboard** (`gui/`) provides an interactive web interface atop `scripts/finding_presentation.py` and `scripts/reconciliation_engine.py`, offering executive financial metrics, a 5-stage lifecycle flow, and actionable investigation drawers.
7. Benchmark predictions are written locally as JSONL; independent ground truth remains local and is read only by the evaluator after prediction. Benchmark findings are not persisted into the normal findings tables.

The benchmark SQL aggregates inside Exasol; it does not move all source rows to Python for those five reports. Benchmark reconciliation retrieves at most 500 order indices per slice. No MCP integration is implemented or verified.

## Technology and repository map

- Python 3.10 or newer; the checked environment uses Python 3.14.
- Exasol with PyExasol 3.0.0 (`requirements.txt`).
- Flask web framework (`requirements.txt`) for the merchant graphical interface.
- SQL for source tables, synthetic scenarios, and analytics.
- `Decimal` monetary arithmetic; SQLite is used only as a temporary offline validator.
- Pytest test suite (both offline engine/GUI tests and live schema tests).

```text
gui/                         Merchant graphical interface (Flask app, templates, static assets)
gui/scenario_fixtures.py     Offline GT01–GT15 scenario parser and CSV ingestion
submission/                  ExaThon deliverables (demonstration video, submission guide)
sql/schema/                  Exasol source and findings table definitions
sql/analytics/               Existing analytical queries
sql/benchmark/               Five benchmark analytical queries
seed/data/                   GT01–GT15 synthetic scenario SQL
seed/load_seed.py            Loads one named scenario
scripts/analytics_connection.py  Central Exasol config and connection helper
scripts/reconciliation_data.py   Source retrieval and benchmark isolation
scripts/reconciliation_engine.py Deterministic reconciliation decisions
scripts/reconciliation_persistence.py Finding/evidence persistence
scripts/inspect_reconciliation_state.py Read-only terminal investigation view
scripts/finding_presentation.py Human-readable finding formatter
scripts/benchmark_data.py    Offline generator and independent validator
scripts/benchmark_pipeline.py Benchmark load, analytics, reconcile, evaluate, show
tests/                       Offline tests and live schema tests
```

## Setup

From the repository root in WSL/Linux, create and activate a virtual environment, then install the declared dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Exasol credentials

Copy the example to the ignored local configuration file:

```bash
cp config/exasol.env.example config/exasol.env
chmod 600 config/exasol.env
```

Set `EXASOL_HOST`, `EXASOL_PORT`, and `EXASOL_USER` in that file. Leave `EXASOL_PASSWORD` blank for a secure `getpass` prompt in an interactive terminal, or set it only in the ignored file. Do not paste credentials into chat or put them in command arguments. The central helper does not silently fall back to environment variables. The example targets a local development endpoint; its TLS certificate verification setting is not suitable as a production TLS configuration.

### Schema setup status

The current schema bootstrap is not completely automated. `create_schema.py` creates the non-`ORDERS` tables and assumes `SARVAGYA.ORDERS` already exists. `create_orders.py` currently refers to `sql/create_schema.sql`, which is absent from this repository. For a fresh local database, use an Exasol SQL client to create the schema and `ORDERS` table with explicit qualification, then run:

```sql
CREATE SCHEMA IF NOT EXISTS SARVAGYA;

CREATE TABLE IF NOT EXISTS SARVAGYA.ORDERS (
    ORDER_ID VARCHAR(50) NOT NULL,
    ORDER_AMOUNT DECIMAL(12,2) NOT NULL,
    CURRENCY CHAR(3) NOT NULL,
    CREATED_AT TIMESTAMP NOT NULL,
    MERCHANT_ID VARCHAR(50) NOT NULL
);
```

This is equivalent to the required columns in `sql/schema/orders.sql`, with schema qualification made explicit. Then run:

```bash
python create_schema.py
python inspect_schema.py
```

The required `ORDERS` columns are `ORDER_ID`, `ORDER_AMOUNT`, `CURRENCY`, `CREATED_AT`, and `MERCHANT_ID`; use the `SARVAGYA` schema. The other table definitions are in `sql/schema/`. `PAYMENT_ATTEMPTS` already includes `MERCHANT_PAYMENT_REF`; `migrate_payment_attempts.py` is for an older table missing that column and checks before altering it. Do not run setup scripts against production without reviewing their SQL and target schema.

Connection and schema checks, when Exasol is available:

```bash
python test_exasol.py
python inspect_schema.py
```

## Correctness scenarios and reconciliation

Scenario files are named by stem under `seed/data/`. Load one in the configured Exasol database with:

```bash
python seed/load_seed.py gt01_normal_payment
python seed/load_seed.py gt08_late_settlement
python seed/load_seed.py gt13_duplicate_bank_reference
```

The other available scenario stems are `gt02_amount_mismatch`, `gt03_payment_retry`, `gt04_duplicate_collection`, `gt05_duplicate_source_row`, `gt06_unmatched_processor`, `gt07_wrong_batch`, `gt09_missing_bank_payout`, `gt10_settlement_component_discrepancy`, `gt11_gt12_bank_mismatches`, `gt14_collection_currency_mismatch`, and `gt15_missing_processor_transaction`. These scripts delete and recreate only their dedicated synthetic IDs; use them only in the intended test database.

Run the deterministic engine and persist supported findings/evidence with:

```bash
python -m scripts.run_reconciliation
```

This command reads source tables and writes findings and evidence to Exasol. It is not a read-only inspection command. The persistence layer recognizes existing finding IDs and handles evidence idempotently; inspect its output for persistence errors.

Run one of the existing analytical queries (valid names are file stems in `sql/analytics/`):

```bash
python scripts/run_analytics.py 01_confirmed_collections
python scripts/run_analytics.py 02_settlement_components
python scripts/run_analytics.py 03_settlement_bank_comparison
python scripts/run_analytics.py 04_inspect_bank_transactions
```

Inspect persisted state or findings without database writes:

```bash
python -m scripts.inspect_reconciliation_state state
python -m scripts.inspect_reconciliation_state findings --status Unresolved
python -m scripts.inspect_reconciliation_state findings --search GT13
python -m scripts.inspect_reconciliation_state findings --show FINDING-ID-PREFIX --technical
```

Replace `FINDING-ID-PREFIX` with the full finding ID or a unique prefix returned by the findings list. The inspector is a terminal report, while the graphical interface provides an interactive browser-based dashboard. The technical option preserves access to full IDs and stored evidence payloads.

## Merchant graphical interface

SettlementLens includes a modern, merchant-friendly web interface designed for finance, operations, and audit teams to visualize reconciliation lifecycles, monitor financial variances, and resolve discrepancies without running terminal commands or raw SQL.

### Features

- **Executive KPI Ribbon**: Real-time totals for Gross Order Volume (₹), Net Discrepancies, Delayed Settlements, and Verified Bank Credits.
- **5-Stage Lifecycle Funnel**: Interactive visual trace across `1. Orders` ➔ `2. Payment Attempts` ➔ `3. Processor Captures` ➔ `4. Settlement Batches` ➔ `5. Bank Deposits`. Clicking any stage filters findings directly to that reconciliation layer.
- **Interactive Findings Explorer**: Real-time multi-layer filtering, status filtering (*Action Required* vs. *Resolved*), live search across Order and Batch IDs, and direct CSV export.
- **Merchant Investigation Drawer**: Plain-English explanations translated from technical classifications, exact financial delta breakdowns formatted in Indian number groupings (₹), settlement timeline comparisons, click-to-copy entity evidence badges, and a collapsible developer audit trail.
- **Zero-Setup Scenario Runner**: 1-click loading and execution for all synthetic scenarios (`GT01`–`GT15`) or a combined benchmark test suite offline.
- **CSV Statement Ingestion**: Upload custom merchant commerce, gateway, settlement, or bank CSV statement feeds with downloadable template formats.

### How to start the graphical interface

Start the interface locally using any of the following methods:

**Cross-platform / Linux / macOS / WSL**:
```bash
python -m gui.app
```

**Windows (1-Click Launchers)**:
- Double-click `gui/run_gui.bat`
- Or run `.\gui\run_gui.ps1` in PowerShell.

Once started, open your web browser and navigate to:
```
http://127.0.0.1:5000
```
*(The listening port can be customized by setting the `PORT` environment variable).*

## Running tests

The test suite covers the deterministic reconciliation engine, presentation formatters, offline benchmark generators, and the merchant graphical interface:

```bash
# Run all offline unit tests (engine, presentation, benchmarks, and GUI)
pytest tests/test_gui.py tests/test_reconciliation_engine.py tests/test_finding_presentation.py -v

# Run full test suite excluding live database dependencies
pytest -k "not live"

# Run all tests including live Exasol schema tests (requires active Exasol instance)
pytest
```

## Scalable synthetic benchmark

`scripts/benchmark_data.py` creates deterministic CSV shards and a separate `ground_truth.csv`; it does not call the reconciliation engine. The CLI supports 10,000 and 100,000 orders, with a fixed seed and an optional JSON scenario distribution. It generates one synthetic INR merchant, retries, explicit references, settlement batches, bank rows, and controlled missing, ambiguous, or mismatched evidence. The INR currency-mismatch scenario has a zero default weight and nonzero weight is rejected.

The validator checks file checksums, row counts, keys and references, scenario relationships, batch/date expectations, INR/single-merchant constraints, and settlement arithmetic using `Decimal`. Generated files and reports are stored under ignored `.benchmark-data/`. IDs are prefixed with a run ID because the existing source schemas have no benchmark run-ID columns. A normal reconciliation run excludes those benchmark prefixes.

Generate and validate a fresh benchmark run offline:

```bash
python -m scripts.benchmark_pipeline generate --run-id DOCS10K01 --orders 10000 --seed 20261031
python -m scripts.benchmark_pipeline validate --run-id DOCS10K01
```

The 100,000-order option is offline-prepared only; it has not been loaded into Exasol:

```bash
python -m scripts.benchmark_pipeline generate --run-id DOCS100K1 --orders 100000 --seed 20261031
python -m scripts.benchmark_pipeline validate --run-id DOCS100K1
```

The optional Exasol stages use the central helper and an interactive password prompt when needed. Use a fresh run ID: the loader refuses a run that already has an ingestion report or records under its ID prefix, and does not reset data.

```bash
python -m scripts.benchmark_pipeline load --run-id DOCS10K01
python -m scripts.benchmark_pipeline verify --run-id DOCS10K01
python -m scripts.benchmark_pipeline analytics --run-id DOCS10K01
python -m scripts.benchmark_pipeline reconcile --run-id DOCS10K01
python -m scripts.benchmark_pipeline evaluate --run-id DOCS10K01
python -m scripts.benchmark_pipeline findings --run-id DOCS10K01 --search settlement
python -m scripts.benchmark_pipeline show --run-id DOCS10K01 --finding-id FINDING-ID-FROM-LIST --technical
```

`load` uses PyExasol CSV bulk import in manifest shards, checks target columns and run-prefix counts, and writes an ingestion report with successful/failed batches. `verify` compares each table's observed run-prefix count with the manifest. `analytics` runs the five SQL queries inside Exasol and records per-query time and returned row count. `reconcile` processes 500-order slices using the existing engine and writes local prediction/calculation JSONL without persisting benchmark findings. `evaluate` runs only after complete reconciliation, against local ground truth.

For `show`, replace `FINDING-ID-FROM-LIST` with the full ID printed by the preceding `findings` command.

The primary evaluator defines precision as TP/(TP+FP) and recall as TP/(TP+FN) over expected positive primary cases; `NONE` control cases contribute true negatives but not to recall. Financial evaluation compares expected net, reported net, and the signed expected-minus-reported difference using exact `Decimal` equality. The timing evaluator currently counts a batch as correct when **any** timing finding for that batch has the expected classification. Multiple timing findings can therefore inflate apparent timing correctness; its reported score must not be described as independent one-to-one timing accuracy.

### Verified FINAL10K03 result

The stored `.benchmark-data/FINAL10K03/` manifest and run reports show:

- 10,000 orders and 70,500 source records across seven tables; offline generation and validation passed.
- All 70,500 records loaded; the ingestion report shows no failed batches and matching expected/verified table counts. The separate `verify` command was also reported as passed with matching counts.
- Five Exasol analytical SQL queries executed; total query execution time was 2.075 seconds.
- Reconciliation completed for 10,000 orders. The evaluator reports 4,000 TP, 6,000 TN, 0 FP, 0 FN, precision 1.0 and recall 1.0 under the definitions above.
- Financial evaluation compared 10,000 batches and found 10,000 correct using exact `Decimal` comparisons.
- 4,700 engine findings remained unresolved.
- Ground truth was not supplied to the prediction engine.
- Timing reports 10,000/10,000 classification matches, but this does **not** establish one-to-one timing accuracy because the evaluator accepts any expected-classification timing finding per batch and one batch had multiple timing findings.

These are synthetic benchmark results, not a comparison with another database or a claim that Exasol is faster than competing systems. The 100,000-order dataset is present as offline-prepared data only; it was not loaded into Exasol.

## Implemented, verified, and deferred

**Implemented:** existing GT01–GT15 fixture SQL; deterministic reconciliation and evidence persistence; read-only terminal inspection; merchant graphical web interface (`gui/`) with offline scenario runner and CSV statement ingestion; offline 10k/100k generator and validator; isolated bulk-loader, SQL analytics, bounded benchmark reconciliation, local evaluator, and readable local prediction commands.

**Verified:** 10k `FINAL10K03` generation, validation, load counts, separate count verification, five Exasol analytics queries, 10k reconciliation, and primary/financial evaluation as reported above. Automated offline tests cover the merchant GUI (`tests/test_gui.py`), reconciliation engine (`tests/test_reconciliation_engine.py`), formatter (`tests/test_finding_presentation.py`), generator, loader mocks, and evaluator. The live schema test suite requires an Exasol connection.

**Not verified or deferred:** 100k live ingestion or Exasol execution; real processor/bank integrations; FX or additional currencies; LLM/fuzzy matching; MCP integration; and deployment/production hardening. No MCP integration is demonstrated in the repository.

## Limitations and future work

- One synthetic merchant and INR only; no real-world feeds or FX.
- The web interface is a local dashboard for exploration, audit, and offline CSV reconciliation; enterprise auth and cloud multi-tenancy are deferred.
- Incomplete evidence remains unresolved/unverified. Findings explain available evidence and do not invent causes.
- Current schema bootstrap requires manual care for `ORDERS`; `create_orders.py` references a missing SQL file.
- Benchmark run isolation relies on ID prefixes because source tables have no run-ID column.
- Timing evaluator matching needs a one-to-one finding-to-case association before timing accuracy can be asserted independently.
- 100,000-order Exasol ingestion and analytics remain unverified.
- Production TLS configuration, deployment, access control, and operational retention are outside this prototype.

## License

This project is licensed under the [MIT License](LICENSE).
