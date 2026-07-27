"""Leakage test for features.py (SPEC.md §4.2 leakage warning).

Proves, by direct comparison rather than by reasoning about the code, that
every feature's value for a given transaction depends only on transactions
that occurred at or before that transaction's own timestamp: for a sample of
real transactions, recompute every feature using ONLY the rows that existed
in the dataset up to and including that transaction's timestamp, and check
the sampled transaction's own feature values are identical to what the same
feature functions produce over the full dataset.

If any feature secretly used a later row (a future terminal's eventual fraud
rate, a later neighbour, etc.), truncating the dataset to "the world as it
looked at that moment" would change that transaction's own values -- this
test would then fail, not just look plausible.

No new dependency: plain assertions, not pytest (CLAUDE.md: keep
dependencies minimal).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import ROOT, compute_all_features, load_config  # noqa: E402

FEATURE_COLS = [
    "geo_velocity_mph", "geo_velocity_subscore", "geo_velocity_impossible_override",
    "home_dist_miles", "home_location_subscore",
    "terminal_neighbour_count_before", "terminal_neighbour_subscore",
    "terminal_reputation_prior_n", "terminal_reputation_shrunk_rate", "terminal_reputation_subscore",
    "remaining_balance_before", "pct_of_remaining_balance", "spend_baseline_subscore",
    "policy_out_of_state_flag", "policy_fast_drain_flag", "policy_balance_probe_flag",
    "ebt_policy_rules_subscore",
]


def pick_sample(df, full_feats, n_random=15):
    rng = np.random.default_rng(42)
    ids = set()

    # one of each fraud pattern, where it exists
    for pattern in df["fraud_pattern"].dropna().unique():
        if pattern == "":
            continue
        rows = df.index[df["fraud_pattern"] == pattern]
        if len(rows):
            ids.add(rng.choice(rows))

    # the known geo-velocity impossible-override rows (both the correctly-caught
    # fraud row and the collateral-victim rows -- PROGRESS.md 2026-07-25)
    ids.update(full_feats.index[full_feats["geo_velocity_impossible_override"]].tolist())

    # known first-transaction-per-household edge cases (not scoreable for geo-velocity)
    first_txn = df.sort_values(["household_id", "timestamp"]).groupby("household_id").head(1).index
    ids.update(rng.choice(first_txn, size=3, replace=False))

    # terminal-neighbour clustered rows
    clustered = full_feats.index[full_feats["terminal_neighbour_count_before"] >= 2]
    if len(clustered):
        ids.update(rng.choice(clustered, size=min(3, len(clustered)), replace=False))

    # plain random rows for general coverage
    ids.update(rng.choice(df.index, size=n_random, replace=False))

    return sorted(ids)


def run():
    cfg = load_config()
    df = pd.read_csv(ROOT / "data/ebt_synthetic.csv", parse_dates=["timestamp"])

    print("Computing full-dataset features (reference)...")
    full_feats = compute_all_features(df, cfg)

    sample_idx = pick_sample(df, full_feats)
    print(f"Testing {len(sample_idx)} sampled transactions "
          f"(fraud patterns, geo-velocity overrides, first-per-household, clustered, random)\n")

    n_pass, n_fail = 0, 0
    failures = []

    for i in sample_idx:
        row = df.loc[i]
        cutoff = row["timestamp"]
        truncated = df[df["timestamp"] <= cutoff].copy()
        assert i in truncated.index, "sampled row must survive its own truncation"

        trunc_feats = compute_all_features(truncated, cfg)
        trunc_row = trunc_feats.loc[i]
        full_row = full_feats.loc[i]

        row_ok = True
        mismatches = []
        for col in FEATURE_COLS:
            a, b = trunc_row[col], full_row[col]
            if isinstance(a, (bool, np.bool_)) or isinstance(b, (bool, np.bool_)):
                same = bool(a) == bool(b)
            elif pd.isna(a) and pd.isna(b):
                same = True
            else:
                same = np.isclose(float(a), float(b), rtol=1e-9, atol=1e-9)
            if not same:
                row_ok = False
                mismatches.append((col, a, b))

        status = "PASS" if row_ok else "FAIL"
        print(f"[{status}] {row['transaction_id']} (pattern={row['fraud_pattern'] or 'ordinary'}, "
              f"n_rows_visible_at_cutoff={len(truncated)})")
        if not row_ok:
            n_fail += 1
            failures.append((row["transaction_id"], mismatches))
            for col, a, b in mismatches:
                print(f"    LEAK: {col}  truncated={a}  full_dataset={b}")
        else:
            n_pass += 1

    print(f"\n{n_pass} passed, {n_fail} failed, out of {len(sample_idx)} sampled transactions.")
    if n_fail:
        raise AssertionError(f"Leakage detected in {n_fail} feature computation(s) -- see LEAK lines above.")
    print("No leakage detected: every sampled transaction's features are unchanged when the "
          "dataset is truncated to only what existed at or before its own timestamp.")


if __name__ == "__main__":
    run()
