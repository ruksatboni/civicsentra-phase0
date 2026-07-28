# CivicSentra Phase 0 — EBT fraud detection reference implementation

An open synthetic benchmark for EBT/SNAP benefits-card fraud, together with a
shadow-mode risk scoring engine and measured results on detection,
cost-effectiveness, and latency.

No public dataset of EBT fraud transactions exists. Privacy law and program
rules make one unlikely to ever exist — the U.S. GAO reports that FNS itself
does not collect data on where or how benefits were stolen, because most
recipients do not know (GAO-25-107964, p.3). This repository exists because
that gap makes claims about EBT fraud detection difficult to test, including
the author's own.

**This is a simulation, not a payment system.** No cards, no terminals, no
connection to any real network, no real cardholder or beneficiary data. It
runs in shadow mode: the engine writes a decision into a column and nothing is
ever actually blocked.

---

## Relationship to the white paper

This implements Phase 0 (Shadow Mode) of *CivicSentra: A Sustainable AI-Driven
Model for Securing Transactions Across E-Commerce, Banking, and Public Welfare
Systems* (Ruksat Hossain Boni). The paper is cited here, not included in this
repository.

The paper makes four claims. This build exists to test them and report what
actually happens. **Not one of the four survives intact: two are not supported,
one was never tested, and the fourth holds only as a projection.** This
repository exists partly to say so.

| Claim | Paper says | Measured here |
|---|---|---|
| C1 · Latency | Scoring completes under 30 ms | **Not supported.** p50 640.08 ms; 0% of sampled transactions under 30 ms |
| C2 · Detection | Fraud reduced 60–80% | **Not supported as stated.** Recall measured at 72.94% (17.12% precision), but recall is not fraud reduction: shadow mode blocks nothing, so no reduction was or could be measured. The claim requires a live pilot |
| C3 · Federated learning | Beats siloed models | **Not tested.** `federated.py` was not built. No evidence either way |
| C4 · Cost ratio | Savings vastly exceed cost | **Partially supported, as a projection.** 3.15:1 to 4.52:1, above break-even but below the paper's §4.4 figure — both sides of the ratio are counterfactual |

**On C2, because the distinction is easy to lose.** Recall is the fraction of
labelled fraud a detector flags on a fixed historical dataset. Fraud reduction
is how much less fraud occurs once a system is deployed and starts blocking.
The second requires three things this build does not have: live enforcement,
adversaries who adapt to being blocked, and a before/after comparison against
a period without the system. In shadow mode nothing is ever blocked, no
fraudster ever changes behaviour in response, and there is no baseline period
to compare against. **No fraud reduction figure can be derived from this work
at any level of statistical care** — not because the measurement was
imprecise, but because the quantity was never observable here. Reporting
72.94% recall as though it were 72.94% fraud reduction would be a category
error, and any such figure attributed to this repository is misquoted.

The same discipline applies to C1: a measurement is reported against the claim
it can actually support, and where no such measurement exists, that is stated
rather than filled with the nearest available number.

The paper will be revised to match these measurements rather than the reverse.
Where a claim did not survive, the claim is what changes.

---

## Headline results

All figures produced by executed code, recorded in
[`outputs/evaluate_metrics.md`](outputs/evaluate_metrics.md) and
[`outputs/benchmark_latency.md`](outputs/benchmark_latency.md). Dataset:
137,080 transactions, 2,000 households, 547 labelled fraud rows.

**Detection**

- Precision 17.12%, recall 72.94%, PR-AUC 0.5364 at the configured operating
  point. **Read precision together with limitation 6 below: 99.1% of the
  ordinary-legitimate false positives behind that 17.12% are fraud victims'
  own transactions after their balance was stolen**, not ordinary shoppers
  caught by a loose threshold
- **Block-tier precision 92.86%** (39 true / 3 false) versus 17.12% across all
  alerts — because a block requires stacked corroborating signals, while a
  step-up does not. Most of the false-positive volume is challenges, not denials
- By pattern: P4 issuance-day drain 100%, P5 out-of-state 100%, P6 terminal
  clustering 100%, P7 off-hours 88.31%, P2 test transaction 50.00%, P3 balance
  probe 46.15%, **P8 PIN guessing 25.64%**
- **P8 detection rests entirely on one rule.** Of 78 P8 rows, 20 are detected —
  and those 20 are *exactly* the 20 where the balance-probe policy rule fires,
  an identical set rather than an overlap. Terminal temporal-neighbour fires on
  11 P8 rows, of which 4 are detected, and all 4 also fired balance-probe.
  **Terminal-neighbour therefore contributes no P8 detections of its own:** at
  weight 0.10 its maximum contribution is 10 points against a 20-point alert
  line, so it cannot trigger an alert alone. It is a corroborating signal on
  this dataset, not a detector. Reported rather than re-weighted — tuning a
  feature's weight upward to make it look productive against fraud we injected
  ourselves would be circular
- **Every P8 row the system catches is the drain; it catches none of the
  guessing.** The 78 P8 rows are 58 PIN-guessing balance inquiries followed by
  20 drains. **All 20 detected rows are the drains — 0 of the 58 attempts are
  detected.** The 25.64% pattern-level rate is not partial coverage of P8; it
  is total coverage of P8's last step and zero coverage of everything leading
  to it. The two populations do not even overlap on score: inquiries reach at
  most 15.95, drains start at 29.80, against a 20-point alert line. Nothing
  sits near the threshold, so this is not a tuning gap that a lower line would
  close — the reconnaissance carries no signal this feature set can see. This
  is limitation 5 stated sharply: limitation 5 counts the 11 P8 rows that score
  exactly zero, but the blindness is wider than those 11 — the other 47
  inquiries score above zero and are still never actionable
- Legitimate transactions **challenged** (step-up, proceeds after review):
  1,928 rows, $52,887.85. Legitimate transactions **denied** (block): 3 rows,
  $69.92

**Cost (C4)**

- Fraud value caught $67,464.18; missed $1,438.79; legitimate value wrongly
  blocked $69.92
- Savings-to-cost ratio **3.15:1 to 4.52:1** across the full $6.40–$9.20
  review-cost range. Above break-even throughout, and the conclusion does not
  flip anywhere inside the range

**Both sides of this ratio are counterfactual, and the ratio is a projection
rather than an observation.** Nothing was blocked, so no fraud was actually
prevented and no money was actually saved; equally, no analyst reviewed
anything, so no review cost was actually incurred. The figures are arithmetic
applied to measured decisions — "if every alert had been reviewed at $X, and
if every flagged fraudulent transaction had been stopped, the ratio would have
been Y." That is a weaker claim than a measurement but a stronger one than C2's,
because the decisions underneath it were genuinely produced by the scorer on
every row; only their consequences are hypothetical.

Two assumptions inside it are worth stating. It assumes a flagged fraudulent
transaction would have been stopped in full, which credits the system with the
entire transaction value. And it prices a step-up purely as analyst review
cost — **see limitation 6, which is the more serious problem with this
number.**

**Latency (C1)**

- p50 640.08 ms, p95 1039.34 ms, p99 1088.05 ms, single transaction at a time
  (not vectorized batch). Apple M3, macOS 26.5.2, Python 3.9.6
- **Measured twice, six days apart:** p50 635.69 ms on 2026-07-25 (macOS
  26.5.1) and 640.08 ms on 2026-07-27 (macOS 26.5.2) — **0.7% apart across an
  OS point update.** The benchmark is stable; the figure is a measurement, not
  a one-off reading
- **0% of sampled transactions scored under 30 ms**, in both runs. The cause is
  architectural, not language choice: features are recomputed from full history
  on every call rather than maintained incrementally, and latency correlates
  with history size at r=0.998. A compiled rewrite would not by itself close
  this gap

---

## LIMITATIONS

Read this section before citing anything above.

**1. The data is synthetic, and we specified the fraud in it.** Every fraud
pattern was designed and injected by the author. A detector evaluated on
fraud its own author defined is measuring internal consistency, not
generalization. The card rail in `SPEC.md` §3.4 existed specifically to test
against fraud we did not invent; **it was not built, so this objection
stands.**

**2. Fraud prevalence is elevated roughly 20x — and this was measured, not
assumed.** The primary dataset targets 0.4% transaction-level fraud prevalence
(measured: 547/137,080 = 0.399%) against a realistic-regime estimate of 0.02%
derived from GAO-25-107964. This was done for statistical power. Precision
depends on the ratio of true to false positives, and prevalence is exactly what
moves that ratio, so the elevation had to be tested rather than waved at.

A second dataset was generated at realistic prevalence (2,598,309 rows, 38,000
households, 518 fraud rows, measured prevalence 0.0199%) and scored with the
**same scorer, config, weights and thresholds** — nothing retuned. Results in
[`outputs/robustness_realistic_prevalence.md`](outputs/robustness_realistic_prevalence.md),
reproducible via `python src/robustness_realistic.py`:

| | Primary (0.399%) | Realistic (0.0199%) |
|---|---|---|
| Precision | 17.12% | **10.43%** |
| Recall | 72.94% | **73.17%** |
| Block-tier precision | 92.86%<br>95% CI [80.99%, 97.54%], n=42 | **100%** (32 TP, 0 FP)<br>95% CI [89.28%, 100%], n=32 |
| Alerts per 1,000 | 17.00 | **1.40** |

**Recall is stable across a 20x prevalence change; precision is not.** Precision
falls by roughly a third. It does not collapse, which a naive prevalence
argument would predict — but the comparison is **confounded and should not be
read as a clean prevalence elasticity.** Two things change between the datasets
at once: prevalence, and the share of households touched by fraud at all (18.3%
primary versus 1.0% realistic). Given limitation 6 below, the second matters as
much as the first. This run does not separate them, and the file says so.

**Precision at genuinely realistic prevalence is therefore measured at 10.43%,
not predicted.**

**3. This is not a pilot, a deployment, or a production system.** Shadow mode
only. No real transaction was ever scored, allowed, challenged or blocked. Any
description of this work as a pilot would be false.

**4. Single rail.** EBT only. The card rail (§3.4), CNP rail (§3.5), federated
learning (§4.6) and graph-based ring detection (§4.2) are specified but not
built.

**5. There is a recall ceiling no threshold can move.** 55 of 547 fraud rows
score exactly zero — no feature fires on them at all. They are
indistinguishable from the 102,153 legitimate rows tied with them at zero, so
**no threshold above zero can exceed 89.95% recall.** Those 55 are
concentrated in the reconnaissance patterns (P3 balance probe 21, P2 test
transaction 18, P8 PIN guessing 11, P7 off-hours 5) and none are P4, P5 or P6.
The system sees drains; it is substantially blind to the activity that
precedes them. P8 shows the sharpest version of this: all 20 of its detections
are drains and none of its 58 PIN-guessing inquiries are detected, scoring or
not — see the P8 breakdown under Results.

**6. The system's main false-positive mode is flagging fraud victims for
being robbed.** 96.32% of false positives are ordinary legitimate
transactions, and `SPEND_BASELINE_HIGH_DRAW` fires on 100% of them. The
obvious reading — that the 40–70%-of-remaining-balance band overlaps with
normal large shopping trips — **is wrong, and measurement overturned it.**
Splitting those false positives by household:

| Ordinary legitimate rows | Count | Flagged |
|---|---|---|
| Household never defrauded | 109,936 | **0.01%** |
| Victim household, *before* the fraud | 11,530 | **0.00%** |
| Victim household, *after* the fraud | 13,042 | **14.14%** |

**99.1% of ordinary-legitimate false positives are a victim's own legitimate
transactions occurring after their balance was drained.** Households never
defrauded are almost never flagged. The mechanism is mechanical: once a
fraudster empties the balance, the household's next genuine purchase draws a
large percentage of a now-tiny remainder and trips the rule.

This is the same failure mode already documented for geo-velocity — a victim's
next legitimate transaction scored against the fraudster's location — but
roughly two orders of magnitude larger in volume. The operational consequence
is the part that matters: **the people this system challenges most are the
people who were just robbed**, at the moment they are trying to buy food with
what is left. Reproduced on every run by `evaluate.py`'s
`fp_victim_contamination()`.

It is not a mistuned threshold, and lowering the band would not address it.
Remediation requires the scorer to know that a household's balance history is
itself suspect — see the roadmap.

**This undermines the cost model in C4, and the cost model does not currently
reflect it.** The dollar matrix prices a step-up as analyst review cost and
nothing else — roughly $6.40–$9.20 of somebody's working time. But 1,928
legitimate transactions were challenged, and limitation 6 establishes that
those challenges land overwhelmingly on households whose benefits were just
stolen, at the moment they are trying to buy food with what remains. The cost
of a step-up in that situation is not an analyst's hour. It is a delayed or
abandoned grocery transaction for a household with no second card and, on the
EBT rail, no transaction alerting to explain what happened. **The
savings-to-cost ratio therefore counts the cheap side of the harm and omits
the expensive side**, and it does so precisely for the population least able
to absorb it.

The `$69.92` "legitimate value wrongly blocked" figure invites the same
mistake. It is accurate and it is reassuringly small, but it measures only
outright denials (3 transactions) and says nothing about the 1,928 challenges
sitting beside it, which is where essentially all of the human cost is. A
reader who takes $69.92 as the cost of false positives has been misled by a
correct number. Any future cost model should price challenges to victims
separately rather than folding them into review overhead.

**How much of the 14.14% is real, and how much is a generator artifact?** This
should be raised here rather than left for a reviewer. A real household
discovers the theft: the card declines, they stop transacting, they call the
agency, they file a claim. The generator does none of that — it keeps victim
households shopping on their normal schedule for the remainder of the benefit
cycle, which is how 13,042 post-fraud legitimate transactions exist to be
scored at all. A real population would produce fewer of them, and some of what
remains would be replaced by claim-handling rather than purchases. **The
mechanism is real and the direction is certainly right — a drained balance
makes the next genuine purchase look like a high-percentage draw, and that is
arithmetic, not an artifact. The magnitude is likely inflated.** Treat 14.14%
as an upper bound on the rate, not an estimate of it. Modelling
post-discovery behaviour is a generator change, not a scorer change, and it is
not in this release.

**7. Legitimate-but-anomalous categories are challenged by design.** All 48
store-and-forward transactions that cross an issuance boundary — legitimate
and permitted under 7 CFR 274.12(m) — receive a step-up: 48/48 = 100%, 95% CI
[92.59%, 100%], with 0% blocked. This is the accepted cost of detecting P4,
and it is measured rather than assumed.

The dataset labels two legitimate-but-anomalous categories separately so their
cost is visible rather than buried in an aggregate: **N1** technical failures
(339 rows, false-flag rate 16.22%) and **N2** legitimate third-party use
(1,686 rows, 0.95%), against an ordinary legitimate false-positive rate of
1.38%. N1's rate is the highest of the three, but N1 and N2 together account
for only 3.68% of all false positives — the ordinary population is roughly 397
times larger, so a low rate there dominates the raw count. Conventional
evaluation reports fraud caught and fraud missed, neither of which shows how
often a system flags transactions that were never fraudulent at all.

**8. Fairness auditing is only partly delivered.** Aggregate false-positive
rates by locality are close (rural 1.32%, suburban 1.46%, urban 1.36%), but
the per-feature breakdown `SPEC.md` §4.7 requires — specifically whether
home-location plausibility's locality-scaled radius removed the disparity it
was designed to remove — was not built. That question is open, not settled.

**9. Small subgroups carry wide intervals.** Any subgroup under ~200 cases is
reported with its raw count and a 95% confidence interval. Point estimates on
48 rows should not be read as precise.

---

## Reproducing the results

Requires Python 3.9+, `numpy`, `pandas`, `PyYAML`. No other dependencies —
scikit-learn and scipy are deliberately not used, so PR-AUC and the Wilson
interval are implemented directly and can be read.

```bash
python -m venv .venv && source .venv/bin/activate
pip install numpy pandas pyyaml
```

Run in order. Every parameter lives in `config.yaml`; `random_seed: 42` makes
generation reproducible byte-for-byte.

```bash
python src/ebt_generator.py      # -> data/ebt_synthetic.csv + data dictionary
python src/scorer.py             # -> data/ebt_scored.csv (features + decisions)
python src/evaluate.py           # -> outputs/evaluate_metrics.md
python src/benchmark_latency.py  # -> outputs/benchmark_latency.md
python src/test_leakage.py       # leakage test, must pass before trusting anything
```

`src/report.py` — a single command regenerating everything with charts — is
specified in `SPEC.md` §4.7 but **not built**. The sequence above is the
current reproduction path.

**On the leakage test.** Every feature must be computable from information
available at the moment a transaction arrives. `test_leakage.py` truncates the
dataset to "what existed at or before this transaction's own timestamp" and
recomputes, rather than inspecting the code and trusting it. The first run
found a real bug: terminal reputation was normalising against the whole
dataframe, silently leaking the eventual average fraud rate. It was fixed
before any result in this repository was produced.

---

## What is in here

| Path | What it is |
|---|---|
| `SPEC.md` | Build specification, with a delivery record marking what was and was not built |
| `config.yaml` | Every weight, threshold and breakpoint, each with its sourcing stated |
| `src/` | Generator, features, scorer, evaluation, latency benchmark, leakage test |
| `explain/` | One document per module: what it does, why, and its limitations |
| `outputs/` | Measured results, written by the scripts that computed them |
| `outputs/TRACEABILITY.md` | Every published figure mapped to the script and function that computed it, including the ones no committed script computes |
| `data/ebt_data_dictionary.md` | Column-by-column description of the generated dataset |
| `paper/section9_draft.md` | Draft of the paper section reporting these results |

**Sourcing discipline.** Fraud patterns P1–P8 come from the public record —
primarily GAO-25-107964 — and every parameter is either cited or explicitly
labelled an unsupported assumption. The author has no direct casework on card
or EBT skimming, and none is claimed. What does come from the author's direct
experience is the N1 (technical failure) and N2 (legitimate third-party use)
categories and the feature-family design. `config.yaml` states which kind of
source each number has, because the difference matters.

---

## Roadmap

Ordered by what the measurements above say is most wrong, not by what is
easiest. Nothing here is a promise of a result; each item names what would be
built and what measurement would show whether it worked.

**1. Stop penalising victims for having been robbed (limitation 6).** The
largest single defect. 99.1% of ordinary-legitimate false positives are a
victim's own post-theft purchases, because remaining balance is treated as
ground truth after a fraudster has emptied it. The intended fix is to make the
spend-baseline feature aware that a household's recent balance history may
itself be the product of fraud — for example scoring the draw against the
household's *expected* balance for that point in the benefit cycle rather than
the observed remainder, once a prior transaction on that account has itself
alerted. Success is measured directly: the 14.14% post-fraud flag rate should
fall toward the 0.01% clean-household rate without recall dropping.

**A cheaper partial fix first: an absolute amount floor.** Expected-balance
scoring is the right answer but it is architectural. A small-denominator guard
is a few lines: below some absolute amount, the high-draw rule does not fire
regardless of percentage, because "90% of a $1 balance" is not evidence of
anything. This is standard practice wherever a ratio has an unstable
denominator, and the smallest flagged transaction among these post-fraud rows
is $0.87. (Across all alerts, including N2 rows, the smallest is $0.73 — $0.87
is the floor for the population this fix targets.)

Measured against the 1,844 affected rows, so the trade is visible rather than
assumed:

| Floor | False positives removed | Detected fraud rows lost |
|---|---|---|
| $1 | 2 (0.1%) | 0 |
| $2 | 23 (1.2%) | 0 |
| **$5** | **248 (13.4%)** | **2** (both P2) |
| $10 | 698 (37.9%) | 2 (both P2) |
| $20 | 1,213 (65.8%) | 6 (P2, P5, P6, P7) |

**A $5 floor removes 13.4%, not most of them** — worth having, and nearly free
at a cost of two P2 test-transaction detections, but it does not solve the
problem. The median flagged post-fraud transaction is $13.48, so these are
ordinary grocery purchases against a drained balance, not a tail of trivial
amounts. Removing most of them needs a $20 floor, which starts costing
detections across P5, P6 and P7 — the high-value patterns the system exists to
catch. **The floor is a cheap first cut; expected-balance scoring remains the
actual fix.**

**2. Close the recall ceiling (limitation 5).** 55 of 547 fraud rows score
exactly zero — no feature fires at all — capping recall at 89.95% regardless of
thresholds. They are concentrated in the reconnaissance patterns: balance
probes, test transactions, PIN guessing. These are sequence and velocity
phenomena across several events, and every current feature scores a single
transaction. Addressing it means per-account event-sequence features, not
retuning. Success: fewer than 55 rows scoring zero, reported by pattern.

**3. Build the card rail (limitation 1).** The most consequential gap for
anyone assessing this work, because it is the only item that tests the system
against fraud the author did not invent. Specified in `SPEC.md` §3.4 against
the Sparkov public dataset. Expected to perform worse — merchant-level
reputation smears a signal that clusters at individual terminals — and that
result is worth having either way.

**4. Make latency a real measurement (C1).** Current p50 is 640.08 ms against
a claimed 30 ms, dominated by recomputing every feature from full history on
each call (r=0.998 with history size). An incrementally stateful implementation
maintaining running per-terminal and per-household counters would test whether
the claim is achievable in principle. Until then C1 stands unsupported, and a
compiled rewrite alone would not fix it.

**5. Graph-based ring detection.** P6 terminal-clustering cashouts spread over
48 hours are invisible to the ±15-minute temporal-neighbour feature (0% of P6).
Also the natural home for the terminal-neighbour signal, which currently
contributes no detections of its own at weight 0.10.

**6. Federated learning (C3).** Specified in `SPEC.md` §4.6, never built, so
the paper's federation claim has no evidence behind it in either direction.
Lowest priority of the six: it is the least load-bearing claim and the most
expensive to test properly.

**7. `report.py` and the full fairness audit.** A single reproducing command
(`SPEC.md` §4.7), plus the per-feature `locality_class` breakdown that would
show whether home-location plausibility's locality-scaled radius actually
removed the disparity it was designed to remove. Currently an open question.

**Not on this roadmap: raising the savings-to-cost ratio.** The C4 figure is
measured and diagnosed. Items 1 and 2 would reduce review volume as a
consequence of fixing defects, which may move it, but improving that number is
not itself a goal — targeting it would invite tuning against a dataset whose
fraud we specified.

---

## License

- **Code** (`src/`, `config.yaml`): MIT License — see [LICENSE](LICENSE).
- **Dataset and documentation** (`data/`, `explain/`, `outputs/`, `SPEC.md`,
  this README): Creative Commons Attribution 4.0 International (CC BY 4.0) —
  see [LICENSE-DATA](LICENSE-DATA).

Both permit commercial and non-commercial reuse, including by state agencies
and vendors, provided attribution is retained. The dataset is synthetic and
contains no real cardholder or beneficiary data, so there is no privacy
restriction on redistributing it.

## Citation

If you use the benchmark, the code, or the results, please cite both the
implementation and the paper it tests.

```bibtex
@software{civicsentra_phase0,
  author  = {Boni, Ruksat Hossain},
  title   = {CivicSentra Phase 0: A Synthetic EBT Fraud Detection Benchmark
             and Shadow-Mode Scoring Engine},
  year    = {2026},
  note    = {Repository URL and DOI to be added on release}
}

@misc{civicsentra_paper,
  author = {Boni, Ruksat Hossain},
  title  = {CivicSentra: A Sustainable AI-Driven Model for Securing
            Transactions Across E-Commerce, Banking, and Public Welfare
            Systems},
  year   = {2026}
}
```

If you cite a detection figure from this repository, please cite it as recall
on synthetic data at elevated prevalence, and not as fraud reduction — see the
note on C2 above.

---

## Disclosure

Domain logic, fraud pattern specification, feature design, scoring weights,
thresholds, and all judgment calls were specified by the author. Code
implementation was AI-assisted. All results were verified by the author
against source data.

