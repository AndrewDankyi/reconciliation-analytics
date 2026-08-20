"""
reconcile.py

A bank reconciliation engine: matches General Ledger transactions
against the bank statement, classifies discrepancies, and produces
the outputs a reconciliation dashboard needs.

Matching strategy (mirrors how this is actually done by hand):
  1. Exact match — same amount, same date. Auto-cleared.
  2. Near match — same amount, date within a tolerance window.
     Flagged as a timing difference (e.g. check clears a few days later).
  3. Amount-typo match — same date (+/- 1 day), amount within a small
     dollar tolerance. Flagged for review — likely a data entry error.
  4. Anything left unmatched on either side is a genuine reconciling
     item: outstanding check, deposit in transit, or a bank-only item
     (fee, interest, NSF) not yet booked to the GL.

Usage:
    python generate_transactions.py
    python reconcile.py
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

DATE_TOLERANCE_DAYS = 6      # near-match window for timing differences
AMOUNT_TOLERANCE = 0.02      # exact-match rounding tolerance ($)
TYPO_TOLERANCE = 100.00      # max $ difference still considered a likely typo


def load_data():
    gl = pd.read_csv("data/gl_transactions.csv", parse_dates=["txn_date"])
    bank = pd.read_csv("data/bank_statement.csv", parse_dates=["txn_date"])
    return gl, bank


def reconcile(gl: pd.DataFrame, bank: pd.DataFrame):
    gl = gl.copy().reset_index(drop=True)
    bank = bank.copy().reset_index(drop=True)
    gl["matched"] = False
    bank["matched"] = False

    matches = []

    # Pass 1: exact match on amount + exact date
    for gi, g in gl[~gl["matched"]].iterrows():
        candidates = bank[
            (~bank["matched"])
            & (bank["txn_date"] == g["txn_date"])
            & ((bank["amount"] - g["amount"]).abs() <= AMOUNT_TOLERANCE)
        ]
        if len(candidates):
            bi = candidates.index[0]
            gl.at[gi, "matched"] = True
            bank.at[bi, "matched"] = True
            matches.append({"gl_txn_id": g["txn_id"], "bank_txn_id": bank.at[bi, "txn_id"],
                             "match_type": "exact", "amount": g["amount"],
                             "gl_date": g["txn_date"], "bank_date": bank.at[bi, "txn_date"]})

    # Pass 2: near match — same amount, date within tolerance (timing differences)
    for gi, g in gl[~gl["matched"]].iterrows():
        window = bank[
            (~bank["matched"])
            & ((bank["amount"] - g["amount"]).abs() <= AMOUNT_TOLERANCE)
            & ((bank["txn_date"] - g["txn_date"]).abs() <= pd.Timedelta(days=DATE_TOLERANCE_DAYS))
        ]
        if len(window):
            bi = window.index[0]
            gl.at[gi, "matched"] = True
            bank.at[bi, "matched"] = True
            matches.append({"gl_txn_id": g["txn_id"], "bank_txn_id": bank.at[bi, "txn_id"],
                             "match_type": "timing_difference", "amount": g["amount"],
                             "gl_date": g["txn_date"], "bank_date": bank.at[bi, "txn_date"]})

    # Pass 3: likely amount typo — same date (+/-1 day), amount close but not exact
    for gi, g in gl[~gl["matched"]].iterrows():
        window = bank[
            (~bank["matched"])
            & ((bank["txn_date"] - g["txn_date"]).abs() <= pd.Timedelta(days=1))
            & ((bank["amount"] - g["amount"]).abs() <= TYPO_TOLERANCE)
            & (np.sign(bank["amount"]) == np.sign(g["amount"]))
        ]
        if len(window):
            bi = window.index[0]
            gl.at[gi, "matched"] = True
            bank.at[bi, "matched"] = True
            variance = round(bank.at[bi, "amount"] - g["amount"], 2)
            matches.append({"gl_txn_id": g["txn_id"], "bank_txn_id": bank.at[bi, "txn_id"],
                             "match_type": "amount_variance", "amount": g["amount"],
                             "gl_date": g["txn_date"], "bank_date": bank.at[bi, "txn_date"],
                             "variance": variance})

    matches_df = pd.DataFrame(matches)
    unmatched_gl = gl[~gl["matched"]].drop(columns=["matched"])
    unmatched_bank = bank[~bank["matched"]].drop(columns=["matched"])
    return matches_df, unmatched_gl, unmatched_bank


def classify_unmatched(unmatched_gl, unmatched_bank, as_of):
    """Label each unresolved item with a reconciling-item type and age."""
    gl_items = unmatched_gl.copy()
    gl_items["item_type"] = np.where(
        gl_items["txn_id"].str.endswith("-DUP"), "Duplicate GL entry (error)",
        np.where(gl_items["amount"] < 0, "Outstanding check", "Deposit in transit")
    )
    gl_items["side"] = "GL only"

    bank_items = unmatched_bank.copy()
    bank_items["item_type"] = bank_items["description"].apply(
        lambda d: "Bank fee" if "fee" in d.lower()
        else "Interest income" if "interest" in d.lower()
        else "NSF item" if "nsf" in d.lower()
        else "Unrecorded bank item"
    )
    bank_items["side"] = "Bank only"

    combined = pd.concat([gl_items, bank_items], ignore_index=True)
    combined["age_days"] = (as_of - combined["txn_date"]).dt.days
    combined["aging_bucket"] = pd.cut(
        combined["age_days"], bins=[-1, 5, 10, 20, 999],
        labels=["0-5 days", "6-10 days", "11-20 days", "20+ days"]
    )
    return combined.sort_values("age_days", ascending=False)


def main():
    gl, bank = load_data()
    as_of = max(gl["txn_date"].max(), bank["txn_date"].max())

    logger.info("Reconciling %d GL transactions against %d bank transactions...", len(gl), len(bank))
    matches_df, unmatched_gl, unmatched_bank = reconcile(gl, bank)

    outstanding = classify_unmatched(unmatched_gl, unmatched_bank, as_of)

    Path("outputs").mkdir(exist_ok=True)
    matches_df.to_csv("outputs/matched_transactions.csv", index=False)
    outstanding.to_csv("outputs/outstanding_items.csv", index=False)

    match_counts = matches_df["match_type"].value_counts().to_dict() if len(matches_df) else {}
    gl_book_balance = gl["amount"].sum()
    bank_stmt_balance = bank["amount"].sum()

    # Adjusted (reconciled) balance: bank balance +/- items only GL knows about yet.
    # Duplicate GL postings are excluded from "outstanding checks" — they're a
    # data-entry error requiring a reversing entry, not a legitimate timing item.
    outstanding_checks_total = outstanding.loc[outstanding["item_type"] == "Outstanding check", "amount"].sum()
    deposits_in_transit_total = outstanding.loc[outstanding["item_type"] == "Deposit in transit", "amount"].sum()
    bank_only_total = outstanding.loc[outstanding["side"] == "Bank only", "amount"].sum()
    duplicate_entries_total = outstanding.loc[outstanding["item_type"] == "Duplicate GL entry (error)", "amount"].sum()

    adjusted_bank_balance = bank_stmt_balance + outstanding_checks_total + deposits_in_transit_total
    adjusted_gl_balance = gl_book_balance + bank_only_total
    total_variance = round(float(matches_df.loc[matches_df["match_type"] == "amount_variance", "variance"].sum()), 2) if len(matches_df) and "variance" in matches_df else 0.0
    # Two correcting entries close the gap: (1) reverse the duplicate posting,
    # (2) true up the flagged amount-variance items to what the bank actually cleared.
    adjusted_gl_balance_post_correction = round(adjusted_gl_balance + total_variance - duplicate_entries_total, 2)

    summary = {
        "as_of_date": str(as_of.date()),
        "gl_transaction_count": int(len(gl)),
        "bank_transaction_count": int(len(bank)),
        "matched_count": int(len(matches_df)),
        "match_rate_pct": round(len(matches_df) * 2 / (len(gl) + len(bank)) * 100, 1),
        "match_breakdown": match_counts,
        "unmatched_gl_count": int(len(unmatched_gl)),
        "unmatched_bank_count": int(len(unmatched_bank)),
        "gl_book_balance": round(float(gl_book_balance), 2),
        "bank_statement_balance": round(float(bank_stmt_balance), 2),
        "outstanding_checks_total": round(float(outstanding_checks_total), 2),
        "deposits_in_transit_total": round(float(deposits_in_transit_total), 2),
        "bank_only_items_total": round(float(bank_only_total), 2),
        "duplicate_gl_entries_count": int((outstanding["item_type"] == "Duplicate GL entry (error)").sum()),
        "duplicate_gl_entries_total": round(float(duplicate_entries_total), 2),
        "adjusted_bank_balance": round(float(adjusted_bank_balance), 2),
        "adjusted_gl_balance": round(float(adjusted_gl_balance), 2),
        "reconciled": bool(round(float(adjusted_bank_balance), 2) == round(float(adjusted_gl_balance), 2)),
        "amount_variance_flags": int((matches_df["match_type"] == "amount_variance").sum()) if len(matches_df) else 0,
        "total_variance_dollars": total_variance,
        "adjusted_gl_balance_post_correction": adjusted_gl_balance_post_correction,
        "fully_reconciled_after_adjustment": bool(round(float(adjusted_bank_balance), 2) == adjusted_gl_balance_post_correction),
    }

    with open("outputs/reconciliation_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    logger.info("Match rate: %.1f%% (%d matched pairs)", summary["match_rate_pct"], summary["matched_count"])
    logger.info("Unmatched: %d GL items, %d bank items", summary["unmatched_gl_count"], summary["unmatched_bank_count"])
    logger.info("Adjusted bank balance: $%.2f | Adjusted GL balance: $%.2f | Reconciled: %s",
                summary["adjusted_bank_balance"], summary["adjusted_gl_balance"], summary["reconciled"])

    print("\n" + "=" * 60)
    print(json.dumps(summary, indent=2))
    print("=" * 60)
    print("\nOutputs written to outputs/")


if __name__ == "__main__":
    main()
