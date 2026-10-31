# Problem statement

## The reconciliation problem

A merchant may receive order and payment-attempt records from its commerce system, transaction records from a payment processor, settlement batch headers and entries from a processor settlement feed, and payout records from its bank. Those records describe related stages of a financial lifecycle, but they are produced by different systems and may arrive with different identifiers, levels of detail, or timing.

An accountant trying to reconcile them must answer separate questions:

1. Was an order associated with one or more payment attempts?
2. Does a processor transaction share an explicit, non-conflicting reference with an attempt, and is collection supported by the available processor evidence?
3. Does a settlement entry link that processor transaction to a batch?
4. Do the settlement components agree with the reported net amount?
5. Does bank evidence reference the settlement batch, and is it unique and amount-compatible?
6. Did the settlement occur on or before the expected date recorded in the available evidence?

These are distinct reconciliation layers. A confirmed processor collection is not proof of a processor settlement, and processor settlement is not proof of a bank payout.

## Evidence gaps and ambiguity

Cross-system references can be missing, contradictory, duplicated, or ambiguous. A processor row may share a reference with several payment attempts. A settlement entry may be absent even though the processor transaction exists. Multiple bank rows may reference a batch. Source rows can be duplicated without representing multiple collections. An amount can match by coincidence and does not establish identity.

When evidence is missing, the outcome is unverified or unresolved. It is not automatically a failed payment or failed payout. When several candidates satisfy the available references, all are preserved; the system does not choose one arbitrarily. A detected discrepancy describes the observed records but does not establish its cause.

## Intended contribution

SettlementLens is a prototype for transparent, deterministic reconciliation. It uses explicit references for identity, keeps financial comparisons separate from timing classifications, retains evidence and limitations with findings, and exposes those details in a readable terminal investigation report.

The project does not claim that settlement reconciliation is novel or that existing commercial products lack these capabilities. Its intended contribution is a small, inspectable implementation whose decisions can be traced to evidence and whose behavior can be measured against independent synthetic ground truth.

## Scope

- One synthetic merchant and INR only.
- No live processor or bank integrations and no foreign-exchange conversion.
- No fuzzy or LLM-based matching.
- Deterministic Python engine and Exasol analytical processing.
- Explainable GT01–GT15 correctness scenarios, kept separate from scalable benchmark runs.
- A terminal interface, not a graphical dashboard.

See [README.md](README.md) for setup, commands, benchmark results, current status, and limitations.
