# EXPLAIN — `scorer.py`

## What this module does

Takes every transaction, runs `features.py`'s six sub-scores, and produces
three things per row: a **risk score** (0–100), a **decision**
(`allow` / `step_up` / `block`), and one or more **reason codes** naming
every signal that fired. In shadow mode nothing is actually blocked — the
decision is a label `evaluate.py` (next) compares against ground truth
`is_fraud`. Output: `data/ebt_scored.csv`.

Every number below came from running `python src/scorer.py` against
`data/ebt_synthetic.csv`, not assumed.

## Why this isn't a plain weighted sum

SPEC.md §4.3 describes a pure linear-weighted-sum design: six sub-scores,
weights summing to 1.0, final score = weighted sum × 100. The author's core design
principle (2026-07-25, PROGRESS.md) is that **only geo-velocity's
impossible-travel case may ever block a transaction on its own** — every
other signal must stack with at least one other signal to reach block,
because a false block on EBT means a person can't buy food that day, often
with no second card, so the one rule allowed to act alone has to be one
where being wrong is close to physically impossible.

A pure weighted sum can't do both things at once: if any single feature's
weight is high enough to reach the block line alone, it isn't actually
requiring stacking; if no feature's weight is high enough, geo-velocity
can't block alone either. The author accepted the fix: the weighted score drives
`allow`/`step_up` only. Block is reached by **either** of two independent
paths, checked every time, not one falling back to the other:

1. The weighted score crosses `step_up_to_block` (50) through **stacked**
   features, or
2. Geo-velocity's hard override fires **alone** (impossible travel, ≥621.4
   mph — see `EXPLAIN_features.md` family 1).

## Weights and thresholds

All from `config.yaml`, the author's numbers (2026-07-25), not optimized:

| Feature | Weight |
|---|---|
| geo_velocity | 0.15 |
| home_location_plausibility | 0.25 |
| spend_baseline | 0.25 |
| terminal_reputation | 0.15 |
| terminal_temporal_neighbour | 0.10 |
| ebt_policy_rules | 0.10 |

Thresholds: `allow_to_step_up = 20`, `step_up_to_block = 50`. Chosen so that
any single non-geo feature maxed out (≤25 points) clears step-up but never
reaches block alone, while home-location + spend-baseline both maxed
(25+25=50) exactly reaches block — matching the author's own "distance + large
draw stacks to block" example. A lone geo-velocity contribution through the
weighted score alone maxes at 15 points (0.15×100) and never reaches block
that way — geo-velocity only blocks through the hard override, never
through score accumulation.

## Verification case (run before trusting this against real data)

A transaction that trips **only** spend-baseline, at exactly 75% of
remaining balance, with nothing else firing:

```
risk_score=25.00  decision=step_up  reason_codes=SPEND_BASELINE_HIGH_DRAW
```

25.00 = 0.25 (weight) × 1.0 (saturated sub-score) × 100 — exactly the
step-up/block boundary is 50, so 25 is comfortably `step_up`, not `block`.
This is the case that protects the 48 legitimate crossing-issuance-boundary
N1 cases (`EXPLAIN_features.md` family 5, and family 6's issuance-day
fast-drain rule) from being denied outright — they get challenged, not
refused.

## Reason codes

SPEC.md §4.3: "every decision returns reason codes naming the contributing
factors." A factor counts as contributing if its sub-score is **above
zero**, independent of whether it was large enough to change the decision —
so a `step_up` row's reason codes show everything that fed it, not just the
one signal that happened to push it over the line.

Ten possible codes:

- `GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK` — the hard override fired. When this is
  present, `GEO_VELOCITY_ELEVATED_SPEED` is suppressed (it would be
  redundant — the override already implies elevated speed).
- `GEO_VELOCITY_ELEVATED_SPEED` — geo-velocity sub-score > 0, override not
  triggered.
- `HOME_LOCATION_OUT_OF_ZONE`, plus `HOME_LOCATION_NIGHT_AMPLIFIED` as an
  additional code when the transaction is also in the night window — kept
  as two codes rather than folding the interaction into one label, so an
  investigator reading reason codes can see *why* the sub-score is as high
  as it is, not just that it's elevated.
- `SPEND_BASELINE_HIGH_DRAW`
- `TERMINAL_REPUTATION_ELEVATED`
- `TERMINAL_NEIGHBOUR_CLUSTER`
- `POLICY_OUT_OF_STATE`, `POLICY_ISSUANCE_DAY_FAST_DRAIN`,
  `POLICY_BALANCE_PROBE_THEN_PURCHASE` — all three are reported
  independently even though `features.py` collapses them into a single
  MAX'd sub-score for scoring purposes. Which specific policy rule fired
  matters to an investigator even when only one of the three actually drove
  the number.
- `NO_RISK_SIGNALS_DETECTED` — fallback when nothing fired at all (the
  large majority of rows).

## Real check against the full primary dataset (137,080 rows)

```
decision counts, all rows:        allow 134,750 | step_up 2,288 | block 42
decision counts, is_fraud=True:   step_up 360    | allow 148    | block 39
decision counts, fraud_pattern=N1: allow 284      | step_up 55   | block 0
```

Read carefully — these are description, not a claimed performance figure;
`evaluate.py` (not yet built) is what computes precision/recall/PR-AUC
properly:

- **Zero N1 rows reach `block`.** Consistent with the design: the only rule
  that can fire on N1 crossing cases (issuance-day fast-drain, weight 0.10,
  sub-score 0.8 → 8 points alone) cannot reach the 50-point block line
  without stacking, and ordinary legitimate N1 rows don't carry the other
  signals (out-of-state, impossible travel, terminal clustering) that real
  fraud stacks with. This is the trade-off `config.yaml`'s
  `ebt_policy_rules` comment documents as deliberately accepted, not a
  side-effect discovered after the fact.
- **148 of 547 fraud rows land on `allow`** — the detector misses these
  entirely under shadow-mode scoring. This is a real, measured miss rate,
  not tuned; `evaluate.py` will report it properly broken down by pattern
  (P1–P8) per SPEC.md §4.4. Not investigated further here — that's
  `evaluate.py`'s job, not this module's.
- **39 fraud rows reach `block`.** A mix of stacked-feature blocks and
  geo-velocity hard-override blocks; `evaluate.py` should eventually
  separate the two paths if that distinction turns out to matter for the
  report (not done here — out of scope for this module).

## What this module does *not* do

- Does not decide detection quality — that's `evaluate.py`. This module
  only produces the label; it does not compute precision, recall, PR-AUC,
  or the dollar cost matrix.
- Does not report the step-up rate on the 48 legitimate crossing-boundary
  N1 cases specifically, even though `config.yaml`'s `ebt_policy_rules`
  comment requires it — that is `evaluate.py`'s job (not yet built) and is
  flagged in `PROGRESS.md` so it isn't lost before that module exists.
- Does not distinguish, in the decision column itself, *which* of the two
  block paths (stacked score vs. hard override) produced a given `block` —
  that distinction is recoverable from `geo_hard_override` and
  `risk_score` together in the output CSV, but isn't surfaced as a
  separate label.
- Does not batch-optimize for speed. `score_transactions()` runs the full
  137,080-row dataset in ~3.5 seconds via vectorized pandas operations
  (except the reason-code assembly, which is a row-wise `apply` over 10
  boolean columns) — fine for this batch use, but this is not the
  per-transaction authorization-path timing `benchmark_latency.py` (not yet
  built) will measure; that module must score one transaction at a time,
  not reuse this batch path, per SPEC.md §4.5.
