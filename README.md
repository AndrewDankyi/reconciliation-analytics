# Transaction Reconciliation Analytics

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![pandas](https://img.shields.io/badge/pandas-2.0-150458?logo=pandas&logoColor=white)

A rule-based bank reconciliation engine: matches a General Ledger cash
account against a bank statement, ages unresolved items, flags amount
discrepancies and duplicate postings, and closes the balance to the
penny with the correcting entries needed to tie out.

**[Live dashboard →](https://andrewdankyi.github.io/reconciliation-analytics/)**

> ⚠️ **Synthetic data only.** All transactions, vendor names, and
> customer names are generated for portfolio demonstration and do not
> represent any real company, bank, or individual.

## Results

| Metric | Value |
|---|---|
| GL transactions | 424 |
| Bank transactions | 403 |
| Match rate | 96.3% (398 matched pairs) |
| Exact matches | 378 |
| Timing differences | 12 |
| Amount variances flagged | 8 ($20.74 net) |
| Outstanding items | 31 (26 GL-only, 5 bank-only) |
| Duplicate GL postings caught | 1 ($2,813.12) |
| **Reconciled after correcting entries** | **✓ Ties to the penny** |

## How the matching works

Three passes, closest to loosest, mirroring how a reconciler actually
works through a statement by hand:

1. **Exact match** — same date, same amount (±$0.02). Auto-clears.
2. **Timing difference** — same amount, date within a 6-day window.
   Catches checks and deposits that post to the bank a few days after
   the GL entry — the single most common reconciling item.
3. **Amount variance** — same date (±1 day), amount within $100.
   Flagged for manual review rather than auto-cleared, since a
   near-match on amount is more likely a data-entry error than a
   coincidence.

Anything left unmatched is a genuine reconciling item: an outstanding
check, a deposit in transit, or a bank-only item (fee, interest, NSF)
the GL hasn't booked yet. Each is aged from its transaction date so
older items surface first — the ones most likely to need escalation.

One of the "outstanding" items in this run is actually a **duplicate
GL posting** (`T10381-DUP`), not a timing difference. The matcher
flags entries with duplicate IDs separately so they don't get
misclassified as a legitimate outstanding check — catching exactly
this kind of processing error is the point of quality control in
reconciliation work.

## Closing the reconciliation

```
  Bank statement balance          $131,254.06
  Less: outstanding checks         -$88,221.79
  Add: deposits in transit         +$60,351.74
  ─────────────────────────────────────────────
  Adjusted bank balance           $103,384.01

  GL book balance                 $101,872.52
  Less: bank fees / NSF not booked  -$1,322.37
  Less: reverse duplicate entry     -$2,813.12
  Correct amount-variance items       +$20.74
  ─────────────────────────────────────────────
  Adjusted GL balance             $103,384.01  ✓
```

The two sides tie exactly once the correcting entries are posted —
reversing the duplicate and booking the net amount-variance
adjustment.

## Tech stack

- **Python** — pandas, numpy
- Rule-based sequential matching (no ML needed here — reconciliation
  is a deterministic matching problem, not a prediction problem)

## Project structure

```
reconciliation-analytics/
├── data/
│   ├── gl_transactions.csv
│   └── bank_statement.csv
├── outputs/
│   ├── matched_transactions.csv
│   ├── outstanding_items.csv
│   └── reconciliation_summary.json
├── src/
│   ├── generate_transactions.py
│   └── reconcile.py
├── index.html
└── README.md
```

## How to run

```bash
pip install pandas numpy
python src/generate_transactions.py   # creates data/gl_transactions.csv + bank_statement.csv
python src/reconcile.py               # matches, ages, and reconciles — writes outputs/
```

Open `index.html` in a browser to view the dashboard.

## Why this design

Reconciliation software in practice (bank feeds, SS&C-style
platforms, etc.) generally does exactly this: sequential rule-based
matching passes from tightest to loosest, with anything left over
routed to a human for review. It's deliberately not framed as a
machine learning problem — the point of a reconciliation is to be
deterministic and auditable, not probabilistic.

---

Built by [Andrew Dankyi Twum](https://andrewdankyi.github.io/Portfolio/) — Data/Financial Analyst.
