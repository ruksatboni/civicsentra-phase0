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

## 2. `benchmark_latency.py` → `outputs/benchmark_runs/<date>.md` + `outputs/benchmark_latency.md`

Values below are run 4 (2026-07-28), the current run.

| Figure | Value | Computed by |
|---|---|---|
| p50 / p95 / p99 | 637.16 / 1037.45 / 1083.36 ms | `run_benchmark()` → `percentile()` |
| mean / min / max | 639.55 / 76.43 / 1100.05 ms | `run_benchmark()` |
| % under 30 ms (claim C1) | 0.0% of 300 samples | `main()` |
| Correlation, history size vs. latency | r = 0.997 | `main()` |
| 20-point percentile distribution | p5–p95 | `percentile()` |
| Hardware / OS / Python | Apple M3, macOS 26.5.2, 3.9.6 | `get_hardware_info()` |
| Sample selection | 300 positions, seeded, from index 50 | `sample_positions()` |

Timing covers feature computation + scoring, one transaction at a time; the CSV
read is excluded. Not vectorized batch (SPEC.md §4.5).

**Write-once archiving.** `main()` writes a dated archive to
`outputs/benchmark_runs/` *before* touching the stable path, falls back to a
second-resolution filename if the dated one exists, and raises rather than
overwrite. `outputs/benchmark_latency.md` is a copy of the latest run kept at a
stable path for citation. Surviving machine records:

| Run | Date | p50 | Archive |
|---|---|---|---|
| 1 | 2026-07-25 | 635.69 ms | **none — overwritten by run 2** |
| 2 | 2026-07-27 | 640.08 ms | `benchmark_runs/benchmark_latency_2026-07-27.md` |
| 3 | 2026-07-28 | 636.79 ms | `benchmark_runs/benchmark_latency_2026-07-28.md` |
| 4 | 2026-07-28 | 637.16 ms | `benchmark_runs/benchmark_latency_2026-07-28T02-26-36Z.md` |

The four-run stability claim in `explain/EXPLAIN_benchmark_latency.md` rests on
runs 2, 3 and 4, all archived. Run 1 is cited as historical prose and labelled
as such. Run 4 took a second-resolution filename because run 3 already held the
dated one — the write-once fallback working as intended.

**Two archived runs still contain the phrase "per CLAUDE.md Rule 1"** in their
generated caveat text. `CLAUDE.md` is a private file and every other reference
to it was replaced on 2026-07-28; these two were not, because they are
write-once records of what the script actually printed on those dates. Editing
them would make them no longer that. The wording is fixed at source, so every
run from 4 onward is clean.

## 2b. `neighbour_distribution.py` → `outputs/neighbour_distribution.md`

Recomputes the distribution that justifies `min_neighbours_flagged: 2`.

| Figure | Value | Computed by |
|---|---|---|
| Zero prior same-terminal neighbours in 15 min | 130,678 rows (95.33%) | `independent_counts()` |
| Exactly one | 6,145 rows (4.48%) | `independent_counts()` |
| Two or more | 257 rows (0.19%) | `independent_counts()` |
| Cross-check vs. `features.py` | 137,080 / 137,080 rows agree | `compute_terminal_temporal_neighbour()` |
| Config comment vs. recomputed | 4 of 4 MATCH | `parse_claimed_from_config()` |

Two independent implementations (pure-Python bisect here, numpy searchsorted in
`features.py`), plus the claimed percentages parsed back out of `config.yaml`'s
own comment and compared — so a stale comment surfaces as a MISMATCH and the
script exits non-zero.

## 2c. `geo_floor_justification.py` → `outputs/GEO_FLOOR_JUSTIFICATION.md`

Recomputes every figure justifying `min_elapsed_minutes_to_score: 5`, over both
datasets. Both halves of the argument in one script, deliberately: the floor
being *needed* and the floor being *free* are separate claims, and a floor
justified only by the first could be suppressing real detections.

| Figure | Value | Computed by |
|---|---|---|
| Legitimate consecutive pairs, primary | 130,631 | `analyse()` |
| Read as impossible travel with no floor | 6 (0.0046%) | `analyse()` |
| Largest elapsed gap among those 6 | 1.0 min | `analyse()` |
| Legitimate pairs the floor declines to score | 447 (0.34%) | `analyse()` |
| Fraud rows tripping impossible-speed, no floor | 1 primary (P5) / 3 realistic (P5×2, P6) | `analyse()` |
| **Of those, under the 5-minute floor** | **0 of 4** — gaps are 15, 20, 28, 46 min | `analyse()` |
| Same-timestamp diff-terminal pairs | 36 primary / 725 realistic | `analyse()` |
| Of those, both endpoints ordinary legitimate | 35 / 705 | `analyse()` |
| Of those, involving a fraud row | 0 / 0 | `analyse()` |
| Config comment vs. recomputed | 11 of 11 MATCH | `parse_claimed()` |

## 2d. `test_leakage.py` → `outputs/LEAKAGE_TEST.md`

| Figure | Value | Computed by |
|---|---|---|
| Sampled transactions | 34, seeded `default_rng(42)` | `pick_sample()` |
| Selection reason per row | fraud pattern / override / first-per-household / clustered / random | `pick_sample()` |
| Feature columns compared per row | 17, across all six families | `run()` |
| Result | 34 of 34 PASS, 0 leaks | `run()` |
| Report | written on pass *and* fail | `write_report()` |

Truncates the dataset to each sampled transaction's own timestamp and compares
every feature against the full-dataset value, so a feature consulting a future
row fails rather than merely looking correct. Sampled, not exhaustive — stated
as such in the report.

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

**Load-bearing** below means a published claim would weaken or change if the
figure were wrong. Where it says no, the figure appears in prose and nothing
depends on it — documented as an exception, deliberately not chased.

| Figure | Script | Load-bearing? |
|---|---|---|
| Dataset shape: 137,080 rows, 2,000 households, 547 fraud, 339 N1, 1,686 N2, pattern counts | `ebt_generator.py` `main()` | **Partly.** These are denominators for precision/recall. But `verify_independent.py` re-derives them from the CSV and its 8 population identities (547 + 136,533 = 137,080) hold, so the published figures *are* machine-checked downstream — just not by the script that produced them. The generator's drawdown-% and dsi figures are stdout-only but appear in no published file. |
| Realistic-regime shape: 2,598,309 rows, 518 fraud | `ebt_generator.py` `main()` | **No.** The published subset is re-derived and persisted by `robustness_realistic.py` into `robustness_realistic_prevalence.md`. |
| Five rows beyond 2× home-zone radius: 283.55, 594.55, 690.57, 720.84, 748.41 miles | `features.py` `__main__` self-test | **No.** Illustrative sample in EXPLAIN_features.md, explicitly labelled as not the five farthest. Seeded (`random_state=42`), so exactly reproducible on demand. |
| Max home distance 760.41 miles (`TXN00062284`, P5) | `features.py` `__main__` self-test | **No.** Same self-test, same seed; a descriptive aside. |
| Batch scoring runtime ~3.5 s for 137,080 rows | `scorer.py` | **No.** An informal aside in EXPLAIN_scorer.md, explicitly contrasted with the real per-transaction benchmark. Nothing rests on it. |

**Closed:** `test_leakage.py` now writes `outputs/LEAKAGE_TEST.md` — see §2d.
The five entries above are all non-load-bearing and are left as documented
exceptions.

## 7. Figures no committed script computes — flagged as untraceable

These appear in published files and cannot be traced to code in this
repository. Each was measured during design (2026-07-25) by ad-hoc queries that
were never committed. They are reproducible *in principle* from
`data/ebt_synthetic.csv`, but nothing in the repo recomputes them today, so a
regenerated dataset would not re-derive or re-validate them.

| Figure | Appears in | Load-bearing? |
|---|---|---|
| Run 1 latency: p50 635.69, p95 1057.68, p99 1102.01, mean 639.96, min/max 79.04/1114.07 ms, r=0.999, macOS 26.5.1 | `EXPLAIN_benchmark_latency.md` §"measured four times", README §Latency | **No longer.** Run 2 overwrote it and the artifact is unrecoverable, but runs 3 and 4 (both 2026-07-28) supply two further archived measurements, so the stability claim now rests on runs 2, 3 and 4 — all with machine records. Run 1 stays in the table as historical prose, labelled as having no artifact. The clobbering cause is fixed (§2). |
| Data-dictionary observed values (amount median 17.86 / mean 27.15 / max 708.36; per-column counts and ranges) | `data/ebt_data_dictionary.md` | **No.** Descriptive column documentation, checkable by hand against the CSV; no result depends on it. |

**Closed since the first version of this document:**

| Figure | How it was closed |
|---|---|
| Same-terminal 15-min neighbour distribution: 95.33% / 4.48% / 0.19% | `src/neighbour_distribution.py` now recomputes it into `outputs/neighbour_distribution.md`, by two independent implementations that agree on all 137,080 rows, and parses the claimed figures back out of `config.yaml`'s comment to check them. All four match the hand-measured 2026-07-25 values exactly — the threshold's justification stands and is now reproducible. See §2b. |
| Run 1 latency being the sole basis of a reproducibility claim | Run 3 executed 2026-07-28 with a write-once archive; the claim now rests on two surviving machine records. Reclassified above rather than deleted. |
| Geo-velocity 5-minute floor: 6 of 130,631 pairs, and the 1/3 fraud rows that would trip impossible-speed | `src/geo_floor_justification.py` recomputes **all 11** figures in the config comment over both datasets — both halves of the argument together, since a floor justified only by "it removes artifacts" could be silently destroying detections. All 11 match; 0 of the 4 tripping fraud rows sit under the floor. See §2c. |
| Leakage-test result | `test_leakage.py` now writes `outputs/LEAKAGE_TEST.md` on every run, pass or fail — all 34 sampled rows, what each was chosen to exercise, per-row result, and the 2026-07-25 bug it caught. Current run 34/34 PASS. See §2d. |

**No load-bearing figure is now untraced.** The two entries remaining above
are a lost artifact that has been superseded and a set of descriptive column
values; nothing depends on either.

## 8. Summary

- **Fully traceable, script → function → output file:** everything in
  `outputs/evaluate_metrics.md`, `outputs/benchmark_latency.md`,
  `outputs/benchmark_runs/`, `outputs/neighbour_distribution.md`,
  `outputs/robustness_realistic_prevalence.md`,
  `outputs/INDEPENDENT_VERIFICATION.md`, and `data/ebt_scored.csv`.
- **Independently machine-verified:** 34 headline metrics + 8 population
  identities (§5), plus the neighbour distribution's two-implementation
  agreement across all 137,080 rows (§2b).
- **Computed but not persisted:** 5 figure groups (§6) — one partly
  load-bearing but machine-checked downstream, four not load-bearing.
- **Not computed by any committed script:** 2 figure groups (§7) — neither
  load-bearing.

**No load-bearing published figure is untraced.** That was not true when this
document was first written; it is now.

**Correction to the first version of this document:** it said "twelve
exceptions … six and six". The count was wrong — §7 listed five groups, not
six, so the total was eleven. Individual entries were correct; only the tally
was off. The count has since gone eleven → ten (neighbour distribution closed,
run-1 latency reclassified) → **seven** (5-minute floor, the fraud rows that
would trip impossible-speed, and the leakage-test result all closed).

SPEC.md's checklist item "Every number in the report traces to executed code"
is marked met on the basis that every figure in `outputs/` is written by the
script that computed it. That remains accurate as written. §6 and §7 above are
the wider claim — every number in every *published* file — and by that
standard the checklist item is met with the seven exceptions listed, none of
them load-bearing.
