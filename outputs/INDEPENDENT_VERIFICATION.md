# Independent verification

Generated 2026-07-28 06:56:32 by `src/verify_independent.py`, which recomputes every headline metric from `data/ebt_scored.csv` (137,080 rows) without importing anything from `evaluate.py`, `features.py` or `scorer.py`, and without using pandas or numpy. The 'reported' column is parsed from `outputs/evaluate_metrics.md` — what evaluate.py actually wrote, not what it was expected to write.

**Result: 34 of 34 metrics MATCH, 0 MISMATCH. 8 of 8 population identities hold.**

## Metric comparison

| Metric | evaluate.py | independent | |
|---|---|---|---|
| True positives (TP) | 399 | 399 | MATCH |
| False positives (FP) | 1931 | 1931 | MATCH |
| False negatives (FN) | 148 | 148 | MATCH |
| Precision (%) | 17.12 | 17.12 | MATCH |
| Recall (%) | 72.94 | 72.94 | MATCH |
| Block-tier TP | 39 | 39 | MATCH |
| Block-tier FP | 3 | 3 | MATCH |
| Block-tier precision (%) | 92.86 | 92.86 | MATCH |
| P2 detected (count) | 39 | 39 | MATCH |
| P3 detected (count) | 36 | 36 | MATCH |
| P4 detected (count) | 77 | 77 | MATCH |
| P5 detected (count) | 77 | 77 | MATCH |
| P6 detected (count) | 82 | 82 | MATCH |
| P7 detected (count) | 68 | 68 | MATCH |
| P8 detected (count) | 20 | 20 | MATCH |
| N1 false-flag rate (%) | 16.22 | 16.22 | MATCH |
| N2 false-flag rate (%) | 0.95 | 0.95 | MATCH |
| N1 crossing-subset rate (%) | 100.00 | 100.00 | MATCH |
| Ordinary-legitimate FP rate (%) | 1.38 | 1.38 | MATCH |
| FP rate, rural (%) | 1.32 | 1.32 | MATCH |
| FP rate, suburban (%) | 1.46 | 1.46 | MATCH |
| FP rate, urban (%) | 1.36 | 1.36 | MATCH |
| Fraud value caught ($) | 67464.18 | 67464.18 | MATCH |
| Fraud value missed ($) | 1438.79 | 1438.79 | MATCH |
| Legitimate value blocked ($) | 69.92 | 69.92 | MATCH |
| Total alerts | 2330 | 2330 | MATCH |
| Savings ratio, low ($6.40) | 4.52 | 4.52 | MATCH |
| Savings ratio, mid ($7.50) | 3.86 | 3.86 | MATCH |
| Savings ratio, high ($9.20) | 3.15 | 3.15 | MATCH |
| Fraud rows scoring exactly 0 | 55 | 55 | MATCH |
| Victim split: clean households (n) | 109936 | 109936 | MATCH |
| Victim split: before fraud (n) | 11530 | 11530 | MATCH |
| Victim split: after fraud (n) | 13042 | 13042 | MATCH |
| Victim split: after-fraud flag rate (%) | 14.14 | 14.14 | MATCH |

## PR-AUC — compared separately, different estimator by design

| | Value |
|---|---|
| evaluate.py, step-wise average precision | 0.5364 |
| independent, trapezoidal PR integration | 0.5363 |
| difference | -0.0001 |

These are two different estimators of the same quantity and are expected to differ slightly. Step-wise average precision credits each recall step with the precision at the end of the step; trapezoidal integration averages precision across the step. Recall only advances when a true positive is found, and finding one raises precision -- so average precision samples at a local maximum, while the trapezoid averages that maximum with the local minimum just before it. **A small negative difference is therefore the correct outcome here**, and the observed -0.0001 is about 0.01% of the value. It is not evidence that either implementation is wrong; a large difference in either direction would be.

## Population arithmetic

| Identity | Computed | Expected | |
|---|---|---|---|
| fraud + legitimate = total rows | 547 + 136533 = 137,080 | 137,080 | OK |
| ordinary + N1 + N2 = legitimate | 134508 + 339 + 1686 = 136,533 | 136,533 | OK |
| victim-split groups = ordinary legitimate | clean+before+after = 134,508 | 134,508 | OK |
| TP + FN = fraud rows | 399 + 148 = 547 | 547 | OK |
| TP + FP = total alerts | 399 + 1931 = 2,330 | 2,330 | OK |
| allow + step_up + block = total rows | 134750 + 2288 + 42 = 137,080 | 137,080 | OK |
| block TP + block FP = block decisions | 39 + 3 = 42 | 42 | OK |
| alert-tier TP + FP = TP + FP | 399 + 1931 = 2,330 | 2,330 | OK |

## Scorer stage — sub-score arithmetic

The metric comparison above cannot catch a scoring error: both implementations read `risk_score`, so a mis-applied weight would produce the same wrong number in each. This recomputes the total from its published parts on **every row**.

- Rows checked: **137,080** (all of them)
- Identity tested: sum of the six `*_subscore_points` columns == `risk_score`
- Rows failing at tolerance 1e-9: **0**
- Largest absolute difference observed: **0.000e+00**

**No row fails.** The weighted combination in `scorer.py` is internally consistent with the components it published.

## Scorer stage — decision rule

Thresholds read from `config.yaml`: allow→step_up at **20**, step_up→block at **50**. Rule re-derived independently: block if `geo_hard_override` fired **or** score reached the block line; step_up if the score reached the alert line; otherwise allow.

- Rows checked: **137,080** (all of them)
- Disagreements with the stored `decision` column: **0**

**No disagreement on any row.** Every decision in the dataset follows from the score, the override flag and the configured thresholds alone — no decision was set by anything else.

## Feature stage — 20-row spot check

Recomputes two feature families from the raw columns and compares against the stored sub-scores. Rows are chosen to span the bands rather than sampled uniformly — a uniform sample is almost all zeros and would demonstrate nothing.

### Home-location plausibility

Zone radii from `config.yaml`: urban 3 mi, suburban 5 mi, rural 9 mi. Inside the zone → 0; out to 2× → 0.35; beyond 2× → 0.75; ×1.5 at hours 00–04, capped at 1.0. Distance computed by haversine written out in this file.

This feature can only produce five distinct sub-scores (0, 0.35, 0.525, 0.75, 1.0), so the five rows below are not a sample — they are every band the feature is capable of emitting, one row each. The spend-baseline table that follows carries the remaining 15 rows.

| transaction_id | locality | zone (mi) | computed dist (mi) | hour | computed sub-score | stored sub-score | |
|---|---|---|---|---|---|---|---|
| TXN00045701 | urban | 3 | 2.595 | 14 | 0.0000 | 0.0000 | MATCH |
| TXN00045304 | urban | 3 | 3.568 | 07 | 0.3500 | 0.3500 | MATCH |
| TXN00044538 | suburban | 5 | 5.157 | 01 | 0.5250 | 0.5250 | MATCH |
| TXN00051473 | suburban | 5 | 563.658 | 11 | 0.7500 | 0.7500 | MATCH |
| TXN00047467 | suburban | 5 | 261.227 | 04 | 1.0000 | 1.0000 | MATCH |

### Spend baseline

Bands from `config.yaml`: under 40% of remaining balance → 0; 40–70% → ramp to 0.6 scaled by a day-in-cycle factor (0.7→1); at or above 70% → 1.0. Remaining balance is read from the published `remaining_balance_at_transaction` column; day-in-cycle is derived from `timestamp` and `issuance_day`.

| transaction_id | amount | published remaining | % of remaining | day in cycle | computed sub-score | stored sub-score | |
|---|---|---|---|---|---|---|---|
| TXN00045516 | 9.14 | 48.95 | 18.67% | 20.48 | 0.0000 | 0.0000 | MATCH |
| TXN00103993 | 14.69 | 36.48 | 40.27% | 18.73 | 0.0048 | 0.0048 | MATCH |
| TXN00058851 | 26.49 | 65.20 | 40.63% | 10.61 | 0.0101 | 0.0101 | MATCH |
| TXN00135166 | 90.16 | 218.55 | 41.25% | 0.51 | 0.0177 | 0.0177 | MATCH |
| TXN00022017 | 48.94 | 117.35 | 41.70% | 2.88 | 0.0248 | 0.0248 | MATCH |
| TXN00000429 | 27.88 | 66.06 | 42.20% | 4.59 | 0.0329 | 0.0329 | MATCH |
| TXN00013396 | 39.82 | 93.02 | 42.81% | 4.70 | 0.0420 | 0.0420 | MATCH |
| TXN00049536 | 94.67 | 217.90 | 43.45% | 5.67 | 0.0522 | 0.0522 | MATCH |
| TXN00135885 | 26.46 | 59.19 | 44.70% | 0.95 | 0.0667 | 0.0667 | MATCH |
| TXN00132566 | 73.35 | 160.05 | 45.83% | 1.54 | 0.0834 | 0.0834 | MATCH |
| TXN00131258 | 55.92 | 118.12 | 47.34% | 4.49 | 0.1094 | 0.1094 | MATCH |
| TXN00133011 | 21.84 | 43.89 | 49.76% | 2.80 | 0.1421 | 0.1421 | MATCH |
| TXN00137014 | 104.41 | 194.05 | 53.81% | 0.82 | 0.1955 | 0.1955 | MATCH |
| TXN00134592 | 34.08 | 55.17 | 61.77% | 0.78 | 0.3082 | 0.3082 | MATCH |
| TXN00049924 | 7.30 | 0.00 | 730.00% | 7.45 | 1.0000 | 1.0000 | MATCH |

**Scope of this check, stated plainly.** Both families are now exact reproductions from published columns, and both are swept across every row in the dataset rather than sampled — the counts below are computed by this script, not quoted from a previous run.

- Home-location: **137,080 of 137,080** rows agree (tolerance 1e-06); largest gap 1.11e-16 at `TXN00000763`.
- Spend baseline: **137,080 of 137,080** rows agree (tolerance 1e-06); largest gap 5.00e-07 at `TXN00133967`.

Spend baseline was previously *approximate*. Remaining balance was not a published column, so this check rebuilt it from the ledger and could not resolve two situations: rows where the rebuilt balance reached zero or arrived out of ledger order, reported as `undefined` and left unscored; and a sub-day gap in the day-in-cycle input, which shifted four rows by ≤0.002 of sub-score. Publishing `remaining_balance_at_transaction` removes the first, and deriving day-in-cycle from `timestamp` and `issuance_day` — both published — removes the second. The feature stage is now verifiable from the CSV exactly, with no tolerance band standing in for a modelling gap.

## Disagreements

None. Every parsed metric agrees and every population identity holds.

