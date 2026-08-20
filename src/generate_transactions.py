"""
generate_transactions.py

Generates two synthetic transaction sets for a 30-day period:
  - the company's General Ledger (GL) cash account activity
  - the bank's statement activity for the same account

The two sets start from a shared pool of "true" transactions, then
diverge with realistic reconciliation discrepancies planted in on
purpose: outstanding checks, deposits in transit, bank fees not yet
booked, amount typos, and duplicate entries. This mirrors how a real
bank reconciliation actually looks — most items match cleanly, a
handful don't, and reconciliation's job is finding the second group.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

RNG = np.random.default_rng(7)

PERIOD_START = datetime(2026, 7, 1)
PERIOD_END = datetime(2026, 7, 31)
N_DAYS = (PERIOD_END - PERIOD_START).days + 1

VENDORS = [
    "Acme Supply Co", "Meridian Logistics", "Pinnacle Office Solutions",
    "Vertex IT Services", "Crestwood Utilities", "Atlas Insurance Group",
    "Summit Payroll Services", "Riverside Property Mgmt", "NorthStar Bank Fees",
    "Horizon Marketing", "Cascade Equipment Rental", "Beacon Legal Group",
]
CUSTOMERS = [
    "Whitfield Manufacturing", "Delta Retail Group", "Coastal Foods Inc",
    "Granite Construction", "Silverline Technologies", "Maple Grove Clinic",
    "Union Freight Co", "Cedarwood Realty", "Brightline Media",
]


def make_true_transactions(n=420):
    """The underlying set of real transactions both books should agree on."""
    dates = PERIOD_START + pd.to_timedelta(RNG.integers(0, N_DAYS, size=n), unit="D")
    is_deposit = RNG.random(n) < 0.38

    rows = []
    for i in range(n):
        if is_deposit[i]:
            amount = round(RNG.uniform(150, 18000), 2)
            payer = RNG.choice(CUSTOMERS)
            desc = f"Customer payment — {payer}"
        else:
            amount = -round(RNG.uniform(40, 9500), 2)
            payee = RNG.choice(VENDORS)
            desc = f"Payment — {payee}"
        rows.append({
            "txn_id": f"T{10000+i}",
            "txn_date": dates[i],
            "description": desc,
            "amount": amount,
        })
    return pd.DataFrame(rows)


def build_gl_and_bank(true_txns: pd.DataFrame):
    """Split the true set into GL and bank records, planting discrepancies."""
    gl_rows, bank_rows = [], []
    n = len(true_txns)
    idx = RNG.permutation(n)

    outstanding_check_idx = set(idx[:14])        # in GL, not yet cleared bank
    deposit_in_transit_idx = set(idx[14:22])      # in GL, not yet cleared bank
    bank_only_fee_idx = set()                     # bank-only items added below
    amount_typo_idx = set(idx[22:30])             # GL amount doesn't match bank
    duplicate_gl_idx = set(idx[30:34])            # GL double-booked by mistake
    timing_lag_idx = set(idx[34:46])              # clears bank a few days later

    for i, row in true_txns.iterrows():
        gl_row = row.to_dict()
        bank_row = row.to_dict()

        if i in outstanding_check_idx:
            # Recorded in GL, hasn't hit the bank yet (period cutoff)
            gl_rows.append(gl_row)
            continue

        if i in deposit_in_transit_idx:
            gl_rows.append(gl_row)
            continue

        if i in amount_typo_idx:
            typo = round(row["amount"] + RNG.choice([-1, 1]) * RNG.uniform(5, 75), 2)
            gl_row = dict(gl_row, amount=typo)

        if i in timing_lag_idx:
            lag = int(RNG.integers(2, 6))
            bank_row = dict(bank_row, txn_date=row["txn_date"] + timedelta(days=lag))

        gl_rows.append(gl_row)
        bank_rows.append(bank_row)

        if i in duplicate_gl_idx:
            dup = dict(gl_row, txn_id=gl_row["txn_id"] + "-DUP")
            gl_rows.append(dup)

    # Bank-only items: fees, interest, and an NSF the company hasn't booked yet
    bank_only = [
        {"txn_id": "B9001", "txn_date": PERIOD_START + timedelta(days=14), "description": "Monthly service fee", "amount": -32.00},
        {"txn_id": "B9002", "txn_date": PERIOD_START + timedelta(days=14), "description": "Wire transfer fee", "amount": -25.00},
        {"txn_id": "B9003", "txn_date": PERIOD_START + timedelta(days=28), "description": "Interest earned", "amount": 14.63},
        {"txn_id": "B9004", "txn_date": PERIOD_START + timedelta(days=9), "description": "NSF returned check — Coastal Foods Inc", "amount": -1250.00},
        {"txn_id": "B9005", "txn_date": PERIOD_START + timedelta(days=21), "description": "NSF fee", "amount": -30.00},
    ]
    bank_rows.extend(bank_only)

    gl_df = pd.DataFrame(gl_rows).sort_values("txn_date").reset_index(drop=True)
    bank_df = pd.DataFrame(bank_rows).sort_values("txn_date").reset_index(drop=True)
    return gl_df, bank_df


def main():
    Path("data").mkdir(exist_ok=True)
    true_txns = make_true_transactions()
    gl_df, bank_df = build_gl_and_bank(true_txns)

    gl_df.to_csv("data/gl_transactions.csv", index=False)
    bank_df.to_csv("data/bank_statement.csv", index=False)

    print(f"✅ GL transactions: {len(gl_df)} rows -> data/gl_transactions.csv")
    print(f"✅ Bank statement:  {len(bank_df)} rows -> data/bank_statement.csv")
    print(f"   GL total: ${gl_df['amount'].sum():,.2f}")
    print(f"   Bank total: ${bank_df['amount'].sum():,.2f}")


if __name__ == "__main__":
    main()
