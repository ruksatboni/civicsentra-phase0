#!/usr/bin/env python3
"""Robustness run: does the system hold up at realistic fraud prevalence?

The primary dataset runs at ~20x the realistic transaction-level fraud rate,
for statistical power. That elevation has to be tested rather than waved at,
because precision in particular depends on the ratio of true to false
positives, and that ratio is exactly what prevalence changes.

Scores data/ebt_synthetic_realistic.csv (0.02% prevalence, 38,000 households)
with the *same* scorer, the same config.yaml, the same weights and the same
thresholds as the primary run. Nothing is retuned for this dataset --
retuning would defeat the comparison.

The input file is ~521MB and is gitignored (see .gitignore). Regenerate it
from src/ebt_generator.py with config.yaml's `realistic` dataset block before
running this. Writes outputs/robustness_realistic_prevalence.md.
"""
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import ROOT, load_config          # noqa: E402
from scorer import score_transactions           # noqa: E402
from evaluate import fp_victim_contamination, wilson_ci  # noqa: E402

t0 = time.time()
cfg = load_config()
print("loading realistic dataset...", flush=True)
raw = pd.read_csv(ROOT / "data/ebt_synthetic_realistic.csv", parse_dates=["timestamp"])
print(f"  {len(raw):,} rows loaded in {time.time()-t0:.1f}s", flush=True)

t1 = time.time()
print("scoring...", flush=True)
scored = score_transactions(raw, cfg)
out = pd.concat([raw, scored], axis=1)
print(f"  scored in {time.time()-t1:.1f}s", flush=True)

alerted = out["decision"] != "allow"
is_fraud = out["is_fraud"]
tp = int((alerted & is_fraud).sum())
fp = int((alerted & ~is_fraud).sum())
fn = int((~alerted & is_fraud).sum())
prec = tp / (tp + fp) if (tp + fp) else float("nan")
rec = tp / (tp + fn) if (tp + fn) else float("nan")

n = len(out)
n_fraud = int(is_fraud.sum())
prevalence = n_fraud / n

block = out["decision"] == "block"
btp = int((block & is_fraud).sum())
bfp = int((block & ~is_fraud).sum())

fp_rows = out[alerted & ~is_fraud]
by_cat = {
    "ordinary_legitimate": int(fp_rows["fraud_pattern"].isna().sum()),
    "N1": int((fp_rows["fraud_pattern"] == "N1").sum()),
    "N2": int((fp_rows["fraud_pattern"] == "N2").sum()),
}

lines = []
A = lines.append
A("# CivicSentra Phase 0 -- robustness run at realistic fraud prevalence")
A(f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC from "
  f"data/ebt_synthetic_realistic.csv ({n:,} rows).")
A("")
A("Same scorer, same config.yaml, same weights and thresholds as the primary run. "
  "The only thing that changed is the input dataset. Nothing was retuned for this "
  "run -- retuning would defeat the purpose of the comparison.")
A("")
A("## Dataset")
A(f"Rows: {n:,}   households: {out['household_id'].nunique():,}")
A(f"Fraud rows: {n_fraud:,}   transaction-level prevalence: {prevalence*100:.4f}%")
A("")
A("## Precision / recall at the same operating point")
A(f"TP={tp}  FP={fp}  FN={fn}")
A(f"Precision: {prec*100:.2f}%   Recall: {rec*100:.2f}%")
if btp + bfp:
    # SPEC.md §4.4 small-subgroup rule: the block tier here is 32 cases, far
    # under the 200-case threshold, and 100% on 32 is not the same evidence
    # as 100% on 3,200. The interval is reported alongside the point estimate.
    blo, bhi = wilson_ci(btp, btp + bfp)
    A(f"Block-only: TP={btp} FP={bfp} precision={btp/(btp+bfp)*100:.2f}%"
      f"  [n={btp+bfp}<200: 95% CI {blo*100:.2f}%-{bhi*100:.2f}%]")
else:
    A("Block-only: no blocks")
A("")
A("## False-positive composition")
for k, v in by_cat.items():
    A(f"  {k}: {v} of {fp} ({v/fp*100:.2f}%)" if fp else f"  {k}: 0")
A("")
A("## Alert volume")
A(f"Alerts per 1,000 transactions: {alerted.sum()/n*1000:.2f}")
A("")
A("## Why precision differs -- the comparison is not prevalence alone")
vc = fp_victim_contamination(out)
for key, label in [("clean_household", "household never defrauded          "),
                   ("victim_household_before_fraud", "victim household, BEFORE the fraud "),
                   ("victim_household_after_fraud", "victim household, AFTER the fraud  ")]:
    s = vc[key]
    A(f"  {label}: n={s['n']:>9,}  flagged={s['flagged']:>5,}  rate={s['rate']*100:6.2f}%")
victim_hh = out.loc[is_fraud, "household_id"].nunique()
all_hh = out["household_id"].nunique()
A(f"Households containing at least one fraud row: {victim_hh:,} of {all_hh:,} "
  f"({victim_hh/all_hh*100:.1f}%)")
A("")
A("The dominant false-positive mechanism in both datasets is the same: a victim's "
  "own legitimate transactions after their balance was drained. What changes between "
  "the two runs is how much of the population that mechanism can reach. Spreading a "
  "similar number of fraud episodes over 19x more households leaves a far smaller "
  "share of households contaminated, so the aggregate ordinary false-positive rate "
  "falls. Precision therefore moves for two reasons at once -- lower prevalence and "
  "lower victim-household density -- and this run does not separate them. Read the "
  "precision figure as 'measured at realistic prevalence in this dataset', not as a "
  "clean prevalence-only elasticity.")
A("")

with open(ROOT / "outputs/robustness_realistic_prevalence.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")

print("\n".join(lines))
print(f"\ntotal wall time {time.time()-t0:.1f}s")
