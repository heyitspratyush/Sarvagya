# ExaThon 2026 Submission Deliverables

This directory organizes the final submission materials for **SettlementLens (Sarvagya)** for ExaThon India 2026.

---

## Deliverables Checklist

| Deliverable | Status | Location / Details |
|---|---|---|
| **Demonstration Video** | ✅ Completed | [`submission/demo.mp4`](demo.mp4) (40.83 MB, 3m 01s) |
| **Merchant Graphical Interface** | ✅ Completed | [`gui/`](../gui) (Flask web application running on port 5000) |
| **Deterministic Reconciliation Engine** | ✅ Completed | [`scripts/reconciliation_engine.py`](../scripts/reconciliation_engine.py) |
| **Exasol Analytical Queries** | ✅ Completed | [`sql/analytics/`](../sql/analytics/) & [`sql/benchmark/`](../sql/benchmark/) |
| **Problem Statement** | ✅ Present | [`PROBLEM_STATEMENT.md`](../PROBLEM_STATEMENT.md) |
| **System Architecture** | ✅ Present | [`ARCHITECTURE.md`](../ARCHITECTURE.md) |
| **Comprehensive Run Guide** | ✅ Present | [`README.md`](../README.md) |
| **Open Source License** | ✅ Present | [`LICENSE`](../LICENSE) (MIT License) |
| **Presentation Pitch Deck** | ⚠️ Pending Upload | Place final PDF/PPTX here as `submission/pitch_deck.pdf` |

---

## 1. Demonstration Video

- **File**: [`submission/demo.mp4`](demo.mp4)
- **File Size**: 42,810,031 bytes (40.83 MB)
- **Duration**: 3 minutes 01 seconds (181.83 seconds)
- **Format**: MP4 (H.264 / AAC)
- **Contents**:
  1. Overview of the merchant settlement reconciliation problem across disparate commerce, processor, and banking feeds.
  2. Execution of the deterministic reconciliation engine.
  3. Demonstration of the merchant-friendly graphical dashboard navigating ground-truth scenarios (normal captures, amount mismatches, delayed settlements, and component discrepancies).
  4. Traceability across the 5-stage lifecycle funnel (`Orders` ➔ `Payment Attempts` ➔ `Processor Captures` ➔ `Settlement Batches` ➔ `Bank Deposits`).
  5. Actionable merchant investigation drawer with suggested operational checks.

> [!TIP]
> **Git File Size Note**: At 40.83 MB, this video is within GitHub's standard per-file limit (< 50 MB) and can be committed directly. If external hosting or embedding is preferred for hackathon reviewers, place the public video streaming link (e.g. YouTube, Loom, or Google Drive) in this section.

---

## 2. Presentation Pitch Deck

- **Target Location**: `submission/pitch_deck.pdf` (or `.pptx`)
- **Status**: Awaiting file placement by the author prior to final form submission.
