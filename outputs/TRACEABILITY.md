# Traceability — where every published number comes from

Answers "where did this figure come from?" without reading git history. Each
published figure is mapped to the script and function that computed it and the
file it lands in. Figures that **no committed script computes** are listed in
§7 rather than omitted.

**This document is hand-compiled by reading the source, not emitted by a
script.** That is a real limitation: unlike the figures it describes, this
mapping is not itself machine-verified and can drift if a script is renamed or
a function is split. What *is* machine-verified is stronger and narrower —
`src/verify_independent.py` recomputes 34 headline metrics from
`data/ebt_scored.csv` without importing `evaluate.py`, `features.py`, or
`scorer.py`, and parses the "reported" side out of `outputs/evaluate_metrics.md`
rather than trusting a transcription. See §5.

Regenerating everything: `ebt_generator.py` → `scorer.py` → `evaluate.py` →
`benchmark_latency.py` → `robustness_realistic.py` → `verify_independent.py`.
There is no single-command reproduction; `report.py` is deferred to v1.1
(SPEC.md §4.7).

---

## 1. `evaluate.py` → `outputs/evaluate_metrics.md`

Reads `data/ebt_scored.csv`. Every figure in the file is written by the run
that computed it.

| Figure | Value | Computed by | Report section |
|---|---|---|---|
| TP / FP / FN | 399 / 1931 / 148 | `build_report()` | §1 |
| Precision | 17.12% | `build_report()` | §1 |
| Recall | 72.94% | `build_report()` | §1 |
| Block-tier precision | 92.86% (TP=39, FP=3) | `precision_by_tier()` → `tier_stats()` | §1 |
| Block-tier 95% CI | 80.99%–97.54% | `wilson_ci()` via `rate_stat()` | §1 |
| FP composition | 96.32% ordinary / 2.85% N1 / 0.83% N2 | `fp_breakdown()` | §1 |
| Victim-contamination split | 109,936 / 11,530 / 13,042 rows | `fp_victim_contamination()` → `rate()` | §1 |
| After-fraud flag rate | 14.14% | `fp_victim_contamination()` | §1 |
| Share of ordinary FPs after own household's fraud | 99.1% | `fp_victim_contamination()` | §1 |
| PR-AUC | 0.5364 | `average_precision()` (step-wise AP) | §2 |
| Recall ceiling | 89.95% | `recall_ceiling()` | §3 |
| Fraud rows scoring exactly 0.00 | 55 (P3 21, P2 18, P8 11, P7 5) | `recall_ceiling()` | §3 |
| Alerts/1,000 at fixed recall | 2.84 … 1000.00 | `alerts_per_1000_at_recall()` | §3 |
| Threshold sensitivity table | 11 rows, thresholds 0–100 | `threshold_sensitivity_table()` | §4 |
| Detection by pattern P2–P8 + CIs | 50.00% … 25.64% | `detection_by_pattern()` | §5 |
| Fraud value caught / missed | $67,464.18 / $1,438.79 | `cost_matrix()` | §6 |
| Legitimate value blocked | $69.92 | `cost_matrix()` | §6 |
| Total alerts | 2,330 | `cost_matrix()` | §6 |
| Savings ratios (low/mid/high) | 4.52 / 3.86 / 3.15 : 1 | `cost_matrix()` | §6 |
| Challenged vs denied | 1,928 rows / 3 rows | `challenged_vs_denied()` | §6 |
| N1 false-flag rate | 16.22% (55/339) | `build_report()` + `rate_stat()` | §7 |
| N1 crossing-boundary subset | 100.00% (48/48), CI 92.59–100.00% | `build_report()` + `wilson_ci()` | §7 |
| N2 false-flag rate | 0.95% (16/1686) | `build_report()` | §8 |
| Ordinary-legitimate FP rate | 1.38% (1860/134508) | `build_report()` | §9 |
| FP rate by locality | rural 1.32 / suburban 1.46 / urban 1.36% | `build_report()` | §10 |

All subgroup rates under n=200 carry a count and a Wilson 95% CI, produced by
`wilson_ci()` → `rate_stat()` → `fmt_rate()`.

## 2. `benchmark_latency.py` → `outputs/benchmark_latency.md`

| Figure | Value | Computed by |
|---|---|---|
| p50 / p95 / p99 | 640.08 / 1039.34 / 1088.05 ms | `run_benchmark()` → `percentile()` |
| mean / min / max | 640.25 / 75.06 / 1097.17 ms | `run_benchmark()` |
| % under 30 ms (claim C1) | 0.0% of 300 samples | `main()` |
| Correlation, history size vs. latency | r = 0.998 | `main()` |
| 20-point percentile distribution | p5–p95 | `percentile()` |
| Hardware / OS / Python | Apple M3, macOS 26.5.2, 3.9.6 | `get_hardware_info()` |
| Sample selection | 300 positions, seeded, from index 50 | `sample_positions()` |

Timing covers feature computation + scoring, one transaction at a time; the CSV
read is excluded. Not vectorized batch (SPEC.md §4.5).

## 3. `robustness_realistic.py` → `outputs/robustness_realistic_prevalence.md`

Flat module-level script — no functions; figures are computed inline and
written by the `open(...)`/`write` at the end of the module.

| Figure | Value |
|---|---|
| Rows / households | 2,598,309 / 38,000 |
| Fraud rows / prevalence | 518 / 0.0199% |
| Precision / recall | 10.43% / 73.17% |
| Block-only precision | 100.00% (TP=32, FP=0), CI 89.28–100.00% |
| FP composition | 70.52% ordinary / 28.10% N1 / 1.38% N2 |
| Alerts per 1,000 | 1.40 |
| Victim split | 2,526,290 / 12,474 / 13,623 |
| Contaminated households | 386 of 38,000 (1.0%) |

Same config, weights and thresholds as the primary run; only the input dataset
changed.

## 4. `scorer.py` → `data/ebt_scored.csv`

Every downstream metric in §1 and §5 is computed off this file.

| Column | Computed by |
|---|---|
| `risk_score`, per-family contributions | `compute_weighted_score()` |
| `decision` (allow / step_up / block) | `compute_decision()` |
| `reason_codes` | `compute_reason_codes()` → `row_codes()` |
| whole-file orchestration | `score_transactions()` |

Feature columns it consumes come from `features.py` `compute_all_features()`,
which dispatches to `compute_geo_velocity()`,
`compute_home_location_plausibility()`, `compute_terminal_temporal_neighbour()`,
`compute_terminal_reputation()`, `compute_spend_baseline()`, and
`compute_ebt_policy_rules()`.

## 5. `verify_independent.py` → `outputs/INDEPENDENT_VERIFICATION.md`

The machine-checked half of this document. Recomputes from
`data/ebt_scored.csv` in pure Python — no pandas, no numpy, no import of
`evaluate.py`/`features.py`/`scorer.py`. The "reported" column is parsed out of
`outputs/evaluate_metrics.md` by `parse_reported()` → `grab()`, so a
transcription error would surface as a MISMATCH rather than passing silently.

**Result: 34 of 34 metrics MATCH, 8 of 8 population identities hold.**

| Independent recomputation | Function |
|---|---|
| TP/FP/FN, precision, recall | `confusion()` |
| PR-AUC (trapezoidal — different estimator by design) | `pr_auc_trapezoid()` |
| Block-tier precision | `tier_precision()` |
| Detection counts P2–P8 | `by_pattern()` |
| N1 / N2 / ordinary / locality rates | `flag_rate()` |
| Victim-contamination split | `victim_split()` |
| Dollar matrix and savings ratios | `cost_matrix()` |
| Sub-score sum identity | `check_subscore_sum()` |
| Decision-rule reconstruction | `check_decision_rule()` |
| Full-sweep feature agreement (137,080/137,080) | `sweep_feature_agreement()`, `independent_home_subscore()`, `independent_spend_subscore()` |

PR-AUC is compared separately and differs by −0.0001 (0.5364 vs 0.5363). That
is the expected sign and magnitude for step-wise AP vs. trapezoidal
integration, not a defect — see the output file for why.

## 6. Figures that are computed by a script but land only on stdout

Reproducible by re-running, but **no file in `outputs/` captures them**, so a
reader cannot check them without executing code.

| Figure | Script | Note |
|---|---|---|
| Dataset shape: 137,080 rows, 2,000 households, 547 fraud, 339 N1, 1,686 N2, pattern counts, drawdown % | `ebt_generator.py` `main()` | Builds a `summary` dict and `print(yaml.dump(...))`s it. Published in README, SPEC and the data dictionary; persisted nowhere. |
| Realistic-regime shape: 2,598,309 rows, 518 fraud | `ebt_generator.py` `main()` | Same. (The subset republished in `robustness_realistic_prevalence.md` *is* persisted.) |
| Five rows beyond 2× home-zone radius: 283.55, 594.55, 690.57, 720.84, 748.41 miles | `features.py` `__main__` self-test | Seeded (`random_state=42`), so reproducible exactly. Cited in EXPLAIN_features.md. |
| Max home distance 760.41 miles (`TXN00062284`, P5) | `features.py` `__main__` self-test | As above. |
| Leakage-test result (sampled transactions, truncated vs. full features) | `test_leakage.py` `run()` | Pass/fail printed only. Cited as verification in several EXPLAIN files; no artifact records the run. |
| Batch scoring runtime ~3.5 s for 137,080 rows | `scorer.py` | Informal timing cited in EXPLAIN_scorer.md; not benchmarked or persisted. |

**Recommended fix (not done here):** have `ebt_generator.py` and
`test_leakage.py` write `outputs/` artifacts the way the other four scripts do.

## 7. Figures no committed script computes — flagged as untraceable

These appear in published files and cannot be traced to code in this
repository. Each was measured during design (2026-07-25) by ad-hoc queries that
were never committed. They are reproducible *in principle* from
`data/ebt_synthetic.csv`, but nothing in the repo recomputes them today, so a
regenerated dataset would not re-derive or re-validate them.

| Figure | Appears in | Status |
|---|---|---|
| 6 of 130,631 legitimate consecutive pairs read as impossible travel without the 5-minute floor | `config.yaml:60`, `EXPLAIN_features.md:42` | No script computes this. Ad-hoc, 2026-07-25. |
| Same-terminal 15-min neighbour distribution: 95.33% zero / 4.48% one / 0.19% two-or-more | `config.yaml:137`, `EXPLAIN_features.md:137` | No script computes this. Ad-hoc, 2026-07-25. Load-bearing: it is the stated justification for the "2 or more" threshold. |
| Fraud rows that would ever trip the impossible-speed rule: 1 (primary) / 3 (realistic), none under 5 min | `EXPLAIN_features.md` §1 | No script computes this. Ad-hoc, 2026-07-25. |
| Run 1 latency: p50 635.69, p95 1057.68, p99 1102.01, mean 639.96, min/max 79.04/1114.07 ms, r=0.999, macOS 26.5.1 | `EXPLAIN_benchmark_latency.md` §"measured twice", README §Latency | The script computed these on 2026-07-25, but run 2 **overwrote** `outputs/benchmark_latency.md`. Run 1 now survives only as prose. The two-run stability claim therefore rests on a figure with no surviving machine artifact. |
| Data-dictionary observed values (amount median 17.86 / mean 27.15 / max 708.36; per-column counts and ranges) | `data/ebt_data_dictionary.md` | Stated as read from the file, which is credible and checkable by hand, but no committed script emits them. |

**The load-bearing one is the 95.33/4.48/0.19 distribution**, because a
threshold was set from it. The run-1 latency figures are the second, because a
reproducibility claim is built on them and the artifact was overwritten rather
than kept — future runs should write to a timestamped file instead of
clobbering.

## 8. Summary

- **Fully traceable, script → function → output file:** everything in
  `outputs/evaluate_metrics.md`, `outputs/benchmark_latency.md`,
  `outputs/robustness_realistic_prevalence.md`,
  `outputs/INDEPENDENT_VERIFICATION.md`, and `data/ebt_scored.csv`.
- **Independently machine-verified:** 34 headline metrics + 8 population
  identities (§5).
- **Computed but not persisted:** 6 figure groups (§6).
- **Not computed by any committed script:** 6 figure groups (§7), two of them
  load-bearing.

SPEC.md's checklist item "Every number in the report traces to executed code"
is marked met on the basis that every figure in `outputs/` is written by the
script that computed it. That remains accurate as written. §6 and §7 above are
the wider claim — every number in every *published* file — and by that
standard the checklist item is met with the twelve exceptions listed.
