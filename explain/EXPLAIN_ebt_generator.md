# EXPLAIN — `ebt_generator.py`

## What this module does

It invents a fake SNAP/EBT card system on a laptop: 2,000 households, 600
store terminals, six months of transactions, and produces a CSV where every
row is either an ordinary purchase or one of the labelled anomaly types
(fraud pattern P2–P8, technical failure N1, or legitimate secondary-user
activity N2). Nothing here touches a real payment network, a real bank, or
real cardholder data — it is a simulation used to test the scoring engine
that gets built in the rest of Phase 0.

It writes two files from the same underlying model, differing only in how
much fraud is mixed in (`config.yaml` → `ebt_generator.prevalence_regimes`):

| File | Households | Fraud rate | Purpose |
|---|---|---|---|
| `data/ebt_synthetic.csv` (**canonical, Day 2 input**) | 2,000 | ~0.40% (elevated ~20×) | Enough fraud rows for stable precision/recall while building and tuning |
| `data/ebt_synthetic_realistic.csv` (538 MB, robustness run only) | 38,000 | ~0.02%, matched to GAO-25-107964's affected-household rate | Confirms conclusions hold outside the power-boosted regime |

**Note on `.gitignore`:** the realistic file is excluded from Git —
`.gitignore` line 10, confirmed with `git check-ignore`. It was missing when
this doc was first written; it exists now, so the 538 MB file cannot be
committed by accident.

## Measured output (this run, `random_seed: 42`)

Read directly from `data/ebt_synthetic.csv`, not from what the code intends:

- **137,080 rows**, 2,000 households, 599 of 600 terminals used
- **547 fraud rows (0.399%)** — P2/P3/P4/P5/P7/P8 ≈77–78 rows each, P6 (terminal-clustering) 82 rows
- **339 N1 rows** (technical failure, `is_fraud=False`), of which **48 cross an issuance boundary** — this is the exact subgroup SPEC.md §4.4 flags for a mandatory confidence interval, so that requirement isn't hypothetical, it's live in the data
- **1,686 N2 rows** (secondary/household-member use, `is_fraud=False`)
- **385 rows** occurred while their terminal was mid-compromise (`terminal_compromised_at_time=True`) — these are ordinary legitimate purchases, not fraud (see P1 note below)
- Date range 2026-01-01 to 2026-07-02 (183 days, six monthly benefit cycles)
- Amounts: median $17.86, mean $27.15, max $708.36; fraud-pattern amounts run higher on average (P4 issuance-day drain averages $273) because drains target a large fraction of remaining balance by design

## Why each significant design choice was made

**Chronological, balance-aware walk, not independent random rows.** Each
household's transactions are generated in time order with a running balance
that actually depletes as it spends, because the spend-baseline feature
(Day 2) needs a real drawdown curve to score against — a feature built on
"% of remaining balance" is meaningless if the generator never tracked a
remaining balance in the first place.

**Front-loaded spending with a late-cycle tail (`late_cycle_trip_probability: 0.15`).**
Originally all primary-user spending followed a Beta(2,5) curve (heavy early,
almost nothing late in the cycle). The author caught that this left only 0.06% of
*normal* transactions in the late-cycle window (day 25+) while 24.4% of N1
failures landed there — a detector could have learned "late in cycle = N1"
purely from a generator artifact, not from any real signal. 15% of normal
trips are now drawn uniformly across the whole cycle instead (modelling
occasional late top-up shops), which is why the N1 false-flag rate this
project reports will mean something rather than being a coin flip the
generator rigged in advance.

**P1 (skimmer harvest) is not written as a fraud row.** The skimmer captures
card data passively during an otherwise completely ordinary purchase — at
the moment it happens there is nothing observably wrong with the
transaction. Labelling it fraud would train/score against information (that
the terminal is secretly compromised) that doesn't exist yet, and every such
row would be a guaranteed, meaningless miss. Instead every row carries
`terminal_compromised_at_time`, ground truth for "was this terminal mid-
compromise right now," independent of `is_fraud` — that's what lets
`evaluate.py` later test whether terminal-reputation *eventually* flags a
bad terminal, without punishing the model for not psychically flagging the
victim's own legitimate purchase.

**Sequential fraud events built from each other's real timestamps, not
resampled independently.** P2 (test-then-drain), P3 (probe-then-drain), and
P8 (PIN attempts-then-drain) each derive the next event's clock time by
adding a `Timedelta` to the previous event's actual timestamp. Early
versions sampled each event's time-of-day independently, which could put a
"drain" before its own "test transaction" in the row order — a data bug that
would have silently taught a temporal feature the wrong thing.

**Amounts as a fraction of remaining balance, not a flat range.** Every
purchase amount (legitimate or fraudulent) is drawn as a fraction of the
household's balance *at that moment in the cycle*, not a fixed dollar range.
This is what makes "percentage of remaining balance × days-since-issuance"
(the spend-baseline feature Day 2 will build) a meaningful signal at all,
and it's why P4 (issuance-day drain) rows average $273 while P8 rows average
$47 — the fraud patterns differ in how much of the balance they take, which
only means something if amounts are balance-relative to begin with.

**Locality-class mix (40/35/25 urban/suburban/rural) is a modelling choice
for statistical power, not a demographic claim.** It's picked so every
`locality_class` band has enough rows (35,866 rural rows, the smallest
group) for the fairness audit in §4.7 to be statistically meaningful — it is
not an assertion about the real geographic distribution of SNAP caseloads.

**Every numeric parameter for P1–P8 is a labelled assumption, not a
measured figure.** The public record (GAO-25-107964) confirms each pattern
*exists* but publishes no operational numbers — no harvest-window length,
no test-transaction amount, no cards-per-terminal count. Every such value in
`config.yaml` under `fraud_patterns` carries a comment saying so explicitly,
per SPEC.md §3.2's sourcing table.

## Key parameters and what happens if you change them

All in `config.yaml` under `ebt_generator`:

- `prevalence_regimes.primary.target_fraud_prevalence` (0.004) — raising this
  gives more fraud rows to train/evaluate against but moves further from
  realistic conditions; lowering it moves toward realism but risks too few
  rows per pattern for stable per-pattern metrics (P4/P5/P7 are already down
  to 77 rows each at the current setting)
- `n1_technical_failure.auto_reversal_fraction` (0.50) — the share of
  technical failures that self-resolve and never become an N1 row. Raise it
  and N1 becomes rarer in the labelled data (fewer, harder-to-generalize-from
  cases); lower it and N1 becomes more common, which would understate how
  rare this really is operationally
- `n1_technical_failure.crossing_issuance_boundary_fraction` (0.15) — controls
  how many of the 339 N1 rows are the store-and-forward-crosses-issuance
  case that mechanically resembles P4. This is the deliberate collision
  SPEC.md §4.2 calls out; raising it makes that confusion more prominent in
  the evaluation
- `late_cycle_trip_probability` (0.15) — lowering this reintroduces the
  generator artifact described above (late-cycle normal activity
  disappearing), which would make the N1 false-flag rate an artifact of the
  generator rather than a real measurement
- `random_seed` (42) — changing it produces a different but equally valid
  dataset; re-running with the same seed reproduces this exact file byte-for-
  byte (CLAUDE.md's "set random seeds everywhere" rule)

**Publishing `remaining_balance_at_transaction` (added 2026-07-27).**
`features.py` computes the point-in-time balance internally to derive the
spend-baseline sub-score, but the column was never written to the CSV. An
outside checker therefore had to *reconstruct* it from the ledger, and could
not always do so: where a household's balance reached zero, or a
store-and-forward row arrived out of ledger order, the reconstruction was
ambiguous and those rows were reported as `undefined` rather than checked.
Publishing the column removes that gap — `src/verify_independent.py` now
recomputes the sub-score exactly, across all 137,080 rows, instead of
approximately across a sample.

The definition matches `features.py::compute_spend_baseline`: benefit minus
this household's own actual prior spend in the same cycle, floored at zero.
Cycle membership uses the issuance-aligned floor division, not the calendar
month — a cycle starting mid-month spans two calendar months, and grouping
by month would silently split it.

It is a pure post-processing step over the assembled frame that draws no
random numbers, so it cannot perturb generation. That was checked rather
than assumed: regenerating both datasets on 2026-07-27 and comparing against
the pre-change files found all 21 original columns byte-identical, on
137,080 primary rows and 2,598,309 realistic rows, with row counts
unchanged. Every downstream metric was likewise unchanged.

## What it does not do, and its limitations

- **No real SNAP data anywhere.** Every household, terminal, and transaction
  is invented. This is stated as a hard boundary in SPEC.md §2 and must stay
  prominent in the eventual README and report, not buried.
- **Benefit amounts are shaped like a typical SNAP allotment (lognormal,
  $50–$900) but are not calibrated to official USDA average-benefit
  statistics.** They're plausible, not authoritative.
- **Three synthetic "state" hubs, not real US geography.** Coordinates are
  chosen only to make Haversine distances between them behaviourally
  sensible (far enough apart that P5 out-of-state drains are unambiguous),
  not to represent any real state.
- **Every P1–P8 numeric parameter is an assumption**, as stated above — the
  patterns' *existence* is sourced to GAO-25-107964, but the specific
  numbers (window lengths, attempt counts, amounts) are not. Anyone citing
  detection-rate results from this dataset needs to know the underlying
  fraud behaviour was invented to a labelled specification, not observed.
- **`detection_lag_days_ebt` is not used by the scorer.** It exists as a
  narrative parameter for the eventual report (how long real EBT fraud takes
  to surface, given no transaction alerting) — scoring happens at
  authorization time regardless of when a human would notice later.
- **The realistic-prevalence file has now been run (2026-07-27).** It was
  scored with the same scorer and the same `config.yaml`, nothing retuned:
  2,598,309 rows, 38,000 households, 518 fraud rows, measured prevalence
  0.0199%. Precision 10.43%, recall 73.17%. Full output in
  `outputs/robustness_realistic_prevalence.md`, reproducible via
  `python src/robustness_realistic.py`. Real output, not assumed output.

## Why the per-pattern row counts differ (P6 = 82, others 77–78)

Asked directly, so recorded here: the spread is deliberate allocation plus
loop granularity, not a rounding artifact.

The budget arithmetic, from `inject_fraud()`:

```
fraud_row_budget    = round(0.004 * 136,533 / (1 - 0.004))  = 548
p6_budget           = round(548 * 0.15)                     =  82   <- fixed 15% share
remaining_budget    = 548 - 82                              = 466
per_pattern_budget  = 466 // 6 single-victim patterns       =  77
```

**P6's 82 is a deliberate fixed 15% of the fraud budget**, set apart because
P6 is a *clustered* pattern — many cloned cards drained through a few
terminals — so it is generated in batches rather than one victim at a time,
and needs its own allocation to produce coherent clusters at all. The other
six patterns split what remains, 77 each.

The 77-versus-78 difference is loop granularity. Each `while` loop runs until
its counter reaches 77, but some patterns emit more than one row per episode,
so the final episode overshoots by exactly one:

| Pattern | Rows | Structure | Why |
|---|---|---|---|
| P4, P5, P7 | 77 | 1 row per episode | counter lands exactly on the budget |
| P2 | 78 | 2 rows per episode (test + drain) | 39 episodes × 2 = 78; 77 is odd, so the last episode overshoots by 1 |
| P3 | 78 | 2 rows per episode (probe + drain), `n_p3 += 2` | same parity effect |
| P8 | 78 | n inquiries + 1 drain per episode | 58 inquiries + 20 drains; the drain is counted after the inner loop breaks |
| P6 | 82 | clustered batches | its own 15% budget, not the per-pattern 77 |

Total 78+78+77+77+82+77+78 = **547** against a budget of 548 — one under,
because P1 is not injected as a fraud row at all (it is the compromise
mechanism, represented via `terminal_compromised_at_time`) and the remainder
of the integer division is not redistributed.

None of this is tuned to a target. Changing `random_seed` produces different
episode contents but the same counts, because the budgets are arithmetic
rather than sampled.
