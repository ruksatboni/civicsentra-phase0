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

No new dependency: plain assertions, not pytest (this project keeps
dependencies minimal).
"""
import sys
from collections import defaultdict
from datetime import datetime, timezone
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
    """Return {row_index: [reasons it was chosen]}.

    The reasons are carried through to outputs/LEAKAGE_TEST.md rather than
    being implicit in the selection code: a leakage test is only as good as
    what it sampled, so a reader has to be able to see that the sample
    deliberately covers each fraud pattern, the geo-velocity override rows,
    first-per-household edge cases and clustered rows -- not just 34 random
    transactions that might all be easy ones. A row picked by two rules keeps
    both reasons.
    """
    rng = np.random.default_rng(42)
    reasons = defaultdict(list)

    # one of each fraud pattern, where it exists
    for pattern in df["fraud_pattern"].dropna().unique():
        if pattern == "":
            continue
        rows = df.index[df["fraud_pattern"] == pattern]
        if len(rows):
            reasons[int(rng.choice(rows))].append(f"fraud pattern {pattern}")

    # the known geo-velocity impossible-override rows (both the correctly-caught
    # fraud row and the collateral-victim rows -- the victim's own next
    # legitimate transaction, hard-blocked because velocity is measured against
    # the fraudster's location rather than the victim's prior movement; see
    # explain/EXPLAIN_features.md §1 item 3, "shadow-mode collateral trigger")
    for i in full_feats.index[full_feats["geo_velocity_impossible_override"]].tolist():
        reasons[int(i)].append("geo-velocity impossible-travel hard override")

    # known first-transaction-per-household edge cases (not scoreable for geo-velocity)
    first_txn = df.sort_values(["household_id", "timestamp"]).groupby("household_id").head(1).index
    for i in rng.choice(first_txn, size=3, replace=False):
        reasons[int(i)].append("first transaction for its household (no geo-velocity history)")

    # terminal-neighbour clustered rows
    clustered = full_feats.index[full_feats["terminal_neighbour_count_before"] >= 2]
    if len(clustered):
        for i in rng.choice(clustered, size=min(3, len(clustered)), replace=False):
            reasons[int(i)].append("2+ prior same-terminal neighbours in window")

    # plain random rows for general coverage
    for i in rng.choice(df.index, size=n_random, replace=False):
        reasons[int(i)].append("random, general coverage")

    return dict(sorted(reasons.items()))


def run():
    cfg = load_config()
    df = pd.read_csv(ROOT / "data/ebt_synthetic.csv", parse_dates=["timestamp"])

    print("Computing full-dataset features (reference)...")
    full_feats = compute_all_features(df, cfg)

    sample = pick_sample(df, full_feats)
    sample_idx = list(sample.keys())
    print(f"Testing {len(sample_idx)} sampled transactions "
          f"(fraud patterns, geo-velocity overrides, first-per-household, clustered, random)\n")

    n_pass, n_fail = 0, 0
    failures = []
    rows_out = []

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
        rows_out.append({
            "transaction_id": row["transaction_id"],
            "pattern": row["fraud_pattern"] if isinstance(row["fraud_pattern"], str) and row["fraud_pattern"] else "ordinary",
            "reasons": "; ".join(sample[i]),
            "n_visible": len(truncated),
            "status": status,
            "mismatches": mismatches,
        })
        if not row_ok:
            n_fail += 1
            failures.append((row["transaction_id"], mismatches))
            for col, a, b in mismatches:
                print(f"    LEAK: {col}  truncated={a}  full_dataset={b}")
        else:
            n_pass += 1

    print(f"\n{n_pass} passed, {n_fail} failed, out of {len(sample_idx)} sampled transactions.")
    write_report(rows_out, n_pass, n_fail, len(df))
    if n_fail:
        raise AssertionError(f"Leakage detected in {n_fail} feature computation(s) -- see LEAK lines above.")
    print("No leakage detected: every sampled transaction's features are unchanged when the "
          "dataset is truncated to only what existed at or before its own timestamp.")


def write_report(rows_out, n_pass, n_fail, n_dataset):
    """Write outputs/LEAKAGE_TEST.md.

    This test is cited in README as "must pass before trusting anything" and
    EXPLAIN_features.md devotes a section to it, but until now it only printed
    to the console -- so the check the credibility of every published result
    rests on had no artifact anyone could read without re-running it. Written
    on both outcomes, pass and fail, so a failure leaves evidence too.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    L = []
    L.append("# CivicSentra Phase 0 -- leakage test")
    L.append(f"Generated {ts} by `src/test_leakage.py` from `data/ebt_synthetic.csv` "
             f"({n_dataset:,} rows).")
    L.append("")
    if n_fail:
        L.append(f"**RESULT: {n_fail} of {len(rows_out)} sampled transactions FAILED. "
                 f"Leakage is present. No result computed from these features should be "
                 f"published until this is fixed.**")
    else:
        L.append(f"**RESULT: {n_pass} of {len(rows_out)} sampled transactions PASS. "
                 f"No leakage detected.**")
    L.append("")
    L.append("## What this proves, and what it does not")
    L.append("")
    L.append("For each sampled transaction, every feature is recomputed against a dataset "
             "truncated to only the rows existing at or before that transaction's own "
             "timestamp, and compared to the value the same functions produce over the full "
             "137,080 rows. If any feature secretly consulted a later row -- a terminal's "
             "eventual fraud rate, a subsequent neighbour -- the truncated value would "
             "differ and the row fails.")
    L.append("")
    L.append("This is a **sampled** test, not a proof over the whole dataset. It "
             "demonstrates by direct comparison rather than by reading the code and "
             "reasoning that it looks correct -- which is the point, since the bug it "
             "caught (below) was invisible to exactly that kind of reasoning. A clean run "
             "means no leakage in these rows against these feature families, not a "
             "guarantee for every row.")
    L.append("")
    L.append("## The sample, and why each row is in it")
    L.append("")
    L.append("The sample is seeded (`np.random.default_rng(42)`), so it is the same every "
             "run. It deliberately covers each fraud pattern, every geo-velocity "
             "hard-override row, first-per-household rows with no prior history, and "
             "terminal-clustered rows -- not 34 random transactions that might all be easy "
             "cases. A row selected by more than one rule lists every reason.")
    L.append("")
    L.append("| # | Transaction | Pattern | Chosen to exercise | Rows visible at cutoff | Result |")
    L.append("|---|---|---|---|---|---|")
    for n, r in enumerate(rows_out, 1):
        L.append(f"| {n} | `{r['transaction_id']}` | {r['pattern']} | {r['reasons']} | "
                 f"{r['n_visible']:,} | {r['status']} |")
    L.append("")
    if n_fail:
        L.append("## Failures")
        L.append("")
        for r in rows_out:
            if r["status"] == "FAIL":
                L.append(f"**`{r['transaction_id']}`**")
                for col, a, b in r["mismatches"]:
                    L.append(f"- `{col}`: truncated={a}  full_dataset={b}")
                L.append("")
    L.append("## Features compared, per row")
    L.append("")
    L.append("All " + str(len(FEATURE_COLS)) + " feature columns across the six families: "
             + ", ".join(f"`{c}`" for c in FEATURE_COLS) + ".")
    L.append("")
    L.append("## Historical note: the bug this test caught (2026-07-25)")
    L.append("")
    L.append("**The first run of this test failed on 11 of 34 sampled rows**, and finding "
             "that is the most valuable thing it has done.")
    L.append("")
    L.append("Terminal reputation's *raw* shrunk rate was correctly point-in-time, built "
             "from an expanding cumulative sum over strictly-prior rows only. But the "
             "sub-score's normalization baseline used `df[\"is_fraud\"].mean()` -- the mean "
             "of whichever dataframe was passed in. Over the full 137,080 rows that is one "
             "number; over any earlier prefix of the data it is a different one. So every "
             "transaction's sub-score silently depended on the dataset's *eventual* average "
             "fraud rate, which had not happened yet at the moment that transaction was "
             "scored.")
    L.append("")
    L.append("The raw feature looked correct under inspection, and the leak sat in the "
             "normalization step rather than the feature logic -- which is why it survived "
             "code review and was caught only by recomputing against a truncated dataset.")
    L.append("")
    L.append("**Fixed** by using each row's own point-in-time expanding global rate as the "
             "baseline instead of a dataset-wide constant. All 34 rows passed after the "
             "fix, and the fix landed before any result in this repository was produced -- "
             "no published figure was ever computed with the leaking version. See "
             "`explain/EXPLAIN_features.md` family 4.")

    out = ROOT / "outputs" / "LEAKAGE_TEST.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(L) + "\n")
    print(f"Wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    run()
