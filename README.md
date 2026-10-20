# SettlementLens

**Evidence-Backed Merchant Settlement Reconciliation**

SettlementLens is an Exasol-powered reconciliation project designed to identify and explain discrepancies between merchant payment attempts, processor transactions, settlement batches, and bank transactions.

## Project goals

- Match transactions using reliable identifiers rather than amount alone.
- Distinguish payment retries, duplicate source rows, and multiple confirmed collections.
- Calculate expected settlement amounts from gross collections, fees, refunds, chargebacks, and signed adjustments.
- Identify settlement discrepancies and late settlements using explicit project rules.
- Preserve evidence and limitations so a discrepancy is not mistaken for a proven cause.

## Technology

- Python
- Exasol
- `pyexasol`
- SQL
- `pytest`

## Repository structure

```text
Sarvagya/
├── sql/                         # Exasol table definitions
├── tests/                       # Automated tests
├── create_orders.py             # Original ORDERS setup script
├── create_schema.py             # Creates the remaining tables
├── inspect_schema.py            # Checks required table columns
├── migrate_payment_attempts.py  # Adds MERCHANT_PAYMENT_REF if missing
├── test_exasol.py               # Connection smoke test
├── requirements.txt
└── README.md
```

## Prerequisites

- Python and a virtual environment
- A running Exasol instance accessible at `127.0.0.1:8563`
- The Exasol `sys` credentials for local development

The connection scripts disable certificate verification for the local development endpoint. Do not reuse that setting for a production connection without an appropriate TLS configuration.

## Setup

Activate your virtual environment, then install dependencies:

```bash
python -m pip install -r requirements.txt
```

Ensure Exasol is running and the `SARVAGYA` schema exists before running the schema scripts.

### Verify the Exasol connection

```bash
python test_exasol.py
```

### Inspect the database schema

```bash
python inspect_schema.py
```

### Create the remaining tables

```bash
python create_schema.py
```

The schema-creation script skips `ORDERS`, which was created separately. The payment-attempt migration can be run with:

```bash
python migrate_payment_attempts.py
```

The migration checks for `MERCHANT_PAYMENT_REF` before adding it.

**Important:** These scripts describe the current development workflow. A fully reproducible fresh-database setup and automated reconciliation test suite are still to be completed.

## Financial correctness principles

- Use decimal-safe monetary calculations.
- Treat identity matching separately from amount consistency.
- Do not count failed attempts as confirmed collections under the project's synthetic rules.
- Do not treat duplicate source rows as separate logical transactions.
- Treat missing evidence as unverified or unresolved rather than automatically failed.
- Keep processor settlement reconciliation separate from bank payout reconciliation.

## Status

The initial Exasol table definitions have been created and their required column names verified. Synthetic ground-truth data, analytical reconciliation queries, and behavioral regression tests remain part of the implementation work.

## License

To be selected before public hackathon submission. The final submission must include the chosen license file.
