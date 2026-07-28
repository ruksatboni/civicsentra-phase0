"""Recompute the same-terminal temporal-neighbour distribution that justifies
`min_neighbours_flagged: 2` in config.yaml.

Why this exists: the figures "95.33% zero / 4.48% one / 0.19% two-or-more" were
measured once, by hand, on 2026-07-25, and written into a config.yaml comment.
A threshold was then set from them. Nothing in the repository recomputed them,
so a regenerated dataset would not re-derive or invalidate the justification --
flagged as a load-bearing traceability gap in outputs/TRACEABILITY.md. This
script closes that gap.

Two independent computations, deliberately not sharing an implementation:

  1. A pure-Python count (bisect over a per-terminal sorted list) written here,
     importing nothing from features.py.
  2. features.py's own compute_terminal_temporal_neighbour(), which uses a
     different algorithm (numpy searchsorted over grouped arrays).

If those two disagree, one of them is wrong and this script says so rather than
reporting a number. It also parses the claimed percentages back out of
config.yaml's comment and compares -- the same trick verify_independent.py uses
for evaluate.py's output, so a stale comment surfaces as a MISMATCH instead of
sitting there looking authoritative.

Writes outputs/neighbour_distribution.md.
"""
import re
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import ROOT, load_config, compute_terminal_temporal_neighbour  # noqa: E402

CSV = ROOT / "data/ebt_synthetic.csv"
CONFIG_PATH = ROOT / "config.yaml"
OUT_PATH = ROOT / "outputs/neighbour_distribution.md"


def independent_counts(df, window_minutes):
    """Prior same-terminal transactions within `window_minutes`, before-only.

    Deliberately a different implementation from features.py: a plain sorted
    list per terminal with a bisect lower-bound, no numpy. Minute resolution,
    matching features.py's datetime64[m] truncation -- the feature genuinely
    operates at minute granularity, so this must too or the comparison is
    meaningless rather than independent.
    """
    minutes = (df["timestamp"].values.astype("datetime64[m]")
               .astype("int64").tolist())
    terminals = df["terminal_id"].tolist()

    by_terminal = defaultdict(list)
    for row_pos, terminal in enumerate(terminals):
        by_terminal[terminal].append(row_pos)

    counts = [0] * len(df)
    for terminal, row_positions in by_terminal.items():
        # stable sort by minute, mirroring features.py's kind="stable"
        ordered = sorted(row_positions, key=lambda p: minutes[p])
        seen = []
        for pos in ordered:
            t = minutes[pos]
            lo = bisect_left(seen, t - window_minutes)
            counts[pos] = len(seen) - lo
            seen.append(t)
    return counts


def parse_claimed_from_config(text):
    """Pull the percentages out of config.yaml's own comment.

    Returns (zero, one, two_plus, window) or None if the comment has changed
    shape. Returning None is not an error -- it means the comment can no longer
    be machine-checked, which is itself worth reporting.
    """
    stripped = re.sub(r"^\s*#\s?", "", text, flags=re.MULTILINE)
    flat = re.sub(r"\s+", " ", stripped)
    m = re.search(
        r"([\d.]+)% of rows have zero prior same-terminal neighbours within (\d+) min, "
        r"([\d.]+)% have one, ([\d.]+)% have two or more",
        flat,
    )
    if not m:
        return None
    return float(m.group(1)), float(m.group(3)), float(m.group(4)), int(m.group(2))


def main():
    cfg = load_config()
    ncfg = cfg["features"]["terminal_temporal_neighbour"]
    window = ncfg["window_minutes"]
    min_flagged = ncfg["min_neighbours_flagged"]

    df = pd.read_csv(CSV, parse_dates=["timestamp"])
    n = len(df)
    print(f"Recomputing neighbour distribution over {n:,} rows "
          f"(window={window} min, before-only)...")

    mine = independent_counts(df, window)
    theirs = compute_terminal_temporal_neighbour(df, cfg)["terminal_neighbour_count_before"].tolist()

    disagreements = [i for i in range(n) if mine[i] != theirs[i]]
    agree = n - len(disagreements)

    zero = sum(1 for c in mine if c == 0)
    one = sum(1 for c in mine if c == 1)
    two_plus = sum(1 for c in mine if c >= 2)
    at_or_above = sum(1 for c in mine if c >= min_flagged)

    pct = lambda k: 100.0 * k / n  # noqa: E731

    claimed = parse_claimed_from_config(CONFIG_PATH.read_text())

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    L = []
    L.append("# CivicSentra Phase 0 -- same-terminal temporal-neighbour distribution")
    L.append(f"Generated {ts} by `src/neighbour_distribution.py` from "
             f"`data/ebt_synthetic.csv` ({n:,} rows).")
    L.append("")
    L.append("This is the measurement that justifies `min_neighbours_flagged` in "
             "config.yaml. It was previously a hand-measured figure in a comment with "
             "no script behind it (outputs/TRACEABILITY.md §7). It is now recomputed "
             "here, by two independent implementations, and the config comment's own "
             "numbers are parsed back out and checked against them.")
    L.append("")
    L.append(f"Definition: for each transaction, the number of OTHER transactions at the "
             f"same `terminal_id` in the {window} minutes immediately BEFORE it. Never "
             f"after -- an 'after' count needs a future transaction and would be leakage "
             f"(config.yaml, features.py). Minute resolution.")
    L.append("")

    L.append("## Two implementations, compared")
    L.append(f"- `neighbour_distribution.py` `independent_counts()` -- pure Python, "
             f"bisect over a per-terminal sorted list, imports nothing from features.py")
    L.append(f"- `features.py` `compute_terminal_temporal_neighbour()` -- numpy "
             f"searchsorted over grouped arrays")
    L.append("")
    if disagreements:
        L.append(f"**{len(disagreements):,} of {n:,} rows DISAGREE.** The distribution "
                 f"below is not trustworthy until this is resolved. First disagreeing "
                 f"rows: {disagreements[:10]}")
    else:
        L.append(f"**{agree:,} of {n:,} rows agree exactly.** The two implementations "
                 f"produce identical counts, so the distribution below is not an "
                 f"artifact of either one.")
    L.append("")

    L.append("## Distribution")
    L.append("")
    L.append("| Prior same-terminal neighbours in window | Rows | Share |")
    L.append("|---|---|---|")
    L.append(f"| 0 | {zero:,} | {pct(zero):.2f}% |")
    L.append(f"| 1 | {one:,} | {pct(one):.2f}% |")
    L.append(f"| 2 or more | {two_plus:,} | {pct(two_plus):.2f}% |")
    L.append("")
    L.append(f"Rows at or above the configured `min_neighbours_flagged` "
             f"({min_flagged}): {at_or_above:,} ({pct(at_or_above):.2f}%).")
    L.append("")

    L.append("## Against the figures in config.yaml's comment")
    L.append("")
    if claimed is None:
        L.append("The comment no longer matches the expected shape, so its figures could "
                 "not be parsed and machine-checked. Fix the comment or this parser -- "
                 "an unparseable justification is the gap this script exists to close.")
        mismatched = True
    else:
        c_zero, c_one, c_two, c_window = claimed
        rows = [("zero neighbours (%)", c_zero, pct(zero)),
                ("exactly one (%)", c_one, pct(one)),
                ("two or more (%)", c_two, pct(two_plus)),
                ("window (minutes)", float(c_window), float(window))]
        L.append("| Quantity | config.yaml comment | recomputed | |")
        L.append("|---|---|---|---|")
        mismatched = False
        for label, claimed_v, actual_v in rows:
            ok = abs(claimed_v - actual_v) <= 0.005
            mismatched = mismatched or not ok
            L.append(f"| {label} | {claimed_v:.2f} | {actual_v:.2f} | "
                     f"{'MATCH' if ok else 'MISMATCH'} |")
        L.append("")
        if mismatched:
            L.append("**MISMATCH.** The comment and the data disagree. The threshold set "
                     "from these figures should be re-examined before the comment is "
                     "edited to agree -- the comment is the claim under test here, not "
                     "the authority.")
        else:
            L.append("**All match.** The hand-measured figures from 2026-07-25 are "
                     "confirmed against the current dataset, and the justification for "
                     "`min_neighbours_flagged` is now reproducible rather than asserted.")

    report = "\n".join(L) + "\n"
    print(report)
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(report)
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}")

    if disagreements or mismatched:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
