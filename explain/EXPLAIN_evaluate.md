# EXPLAIN — `evaluate.py`

## What this module does

Reads `data/ebt_scored.csv` (scorer.py's decisions) and compares them
against ground truth (`is_fraud`, `fraud_pattern`) to produce every metric
SPEC.md §4.4 requires, plus the two additions the author asked for directly
(2026-07-25): the N1 crossing-issuance-boundary step-up rate, and detection
broken down by pattern with enough detail to see *why* missed fraud rows
were missed. Writes `outputs/evaluate_metrics.md`. This is not the final
`outputs/PHASE0_REPORT.md` — that polished, charted report is `report.py`'s
job (SPEC.md §4.7, not yet built); this module's job is to compute and
record the real numbers.

Every number in `outputs/evaluate_metrics.md` came from running
`python src/evaluate.py` against `data/ebt_scored.csv`, not assumed
(CLAUDE.md Rule 1).

## Ten sections, what each answers

1. **Precision/recall at the operating point.** "Alerted" = `decision !=
   allow` (step_up or block both count — both mean the transaction didn't
   sail through untouched). At the current scorer.py thresholds: 399 true
   positives, 1,931 false positives, 148 false negatives → 17.12% precision,
   72.94% recall.

   **False-positive decomposition (added 2026-07-25, the author pressure-testing
   precision before accepting it).** The hypothesis going in: low precision
   might be *by design* — the deliberate N1/N2 challenge trade-off
   (`EXPLAIN_features.md` family 6) rather than a threshold set too loose.
   Measured breakdown of the 1,931 false positives: **96.32% (1,860) are
   ordinary-legitimate, 2.85% (55) are N1, 0.83% (16) are N2.** The
   hypothesis does not hold up against the count — N1/N2 combined explain
   under 4% of false positives, not the majority. The reason the intuition
   still felt right: N1 has a genuinely high 16.22% flag rate *within its
   own 339-row population* (§7), but that population is ~400x smaller than
   the 134,508-row ordinary-legitimate population, whose own flag rate is
   only 1.38% — a low rate on a huge population outnumbers a high rate on a
   tiny one in raw count. The actual driver: `SPEND_BASELINE_HIGH_DRAW`
   fires on **100%** of the 1,860 ordinary-legitimate false positives (often
   paired with `TERMINAL_REPUTATION_ELEVATED`, 39.7% of them). This
   decomposition is now a permanent section of `evaluate.py`'s output
   (`fp_breakdown()`), not a one-off answer — reproducible on every run, not
   just recorded in conversation.

   **Superseded 2026-07-27 — the explanation above was wrong, and measuring
   it fixed it.** This document previously read the 100% figure as a design
   tension: the 40–70%-of-remaining-balance band supposedly overlapping with
   ordinary large SNAP shopping trips early in the benefit cycle. That is not
   what is happening. Splitting the ordinary-legitimate rows by household
   (`fp_victim_contamination()`, section 1 of the output):

   | Ordinary legitimate rows | n | flagged |
   |---|---|---|
   | household never defrauded | 109,936 | **0.01%** |
   | victim household, *before* the fraud | 11,530 | **0.00%** |
   | victim household, *after* the fraud | 13,042 | **14.14%** |

   **99.1% of ordinary-legitimate false positives fall after their own
   household's fraud.** Households never defrauded are essentially never
   flagged, and no victim household is flagged before its fraud occurs. The
   mechanism is mechanical rather than a judgment call about band width: once
   a fraudster drains the balance, the household's own next legitimate
   purchase necessarily draws a large percentage of a now-tiny remainder.
   The feature is not confusing big shoppers with fraudsters; it is
   confusing *robbed people* with fraudsters.

   This is the same failure mode documented for geo-velocity in
   `EXPLAIN_features.md` family 1 — a victim's next legitimate transaction
   scored against the fraudster's location — about two orders of magnitude
   larger. It also explains why precision differs between the primary and
   realistic-prevalence datasets (`outputs/robustness_realistic_prevalence.md`):
   what changes is not only prevalence but the share of households the
   mechanism can reach at all (18.3% versus 1.0%).

   **Named feature-design limitation, for §9 of the paper (restated
   2026-07-27 in light of the measurement above):** the spend-baseline
   feature (`EXPLAIN_features.md` family 5) is built on the correct
   structural insight that EBT spending is fixed-benefit, not open-ended.
   Its defect is narrower and worse than "the band is too wide": it treats
   the observed remaining balance as ground truth, when that balance may
   itself be the product of a theft the system has already seen. From
   amount and cycle-position alone it cannot distinguish a household
   drawing down a genuinely low balance from one drawing down a
   fraudulently emptied one — and empirically the second case is where
   essentially all of its false positives come from. This is not a
   mistuned breakpoint, and narrowing the band would not address it; the
   feature needs to know that the balance history is suspect (README
   roadmap, item 1). It is **contained, not eliminated**, by the block-alone-
   asymmetry design principle (`EXPLAIN_scorer.md`): this feature alone can
   only reach `step_up` (weight 0.25 × sub-score 1.0 × 100 = 25, below the
   50-point block line), so the false positives it drives are challenges,
   not denials — see the block-vs-alert precision split and the
   challenged-vs-denied contrast below, both of which exist specifically to
   demonstrate that containment with numbers rather than assert it.

   **Precision by decision tier (added 2026-07-25, the author: "show me the
   number that makes 17% defensible").** All-alert precision (17.12%) and
   block-only precision are reported as two separate numbers
   (`precision_by_tier()`), because they answer different questions: block
   requires either stacked features crossing the 50-point line or the
   geo-velocity hard override firing alone, so it should look nothing like
   the step_up-dominated all-alert figure if the design is working.
   Measured: **block-only precision = 92.86%** (39 TP, 3 FP) against
   17.12% all-alert precision (399 TP, 1,931 FP). This is the number that
   makes the low all-alert figure defensible — almost all the false-positive
   volume behind 17% is step_up (a challenge), and the tier that actually
   denies a transaction is precise.
2. **PR-AUC**, not ROC-AUC (SPEC.md §4.4 explicitly rules out ROC-AUC — it
   flatters classifiers on imbalanced data, and fraud detection is exactly
   that: 547 fraud rows out of 137,080). Computed as the standard step-wise
   average-precision definition, hand-implemented rather than pulled from
   scikit-learn — scikit-learn is not an installed dependency
   (`CLAUDE.md`: keep dependencies minimal) and this is a ~10-line
   computation, not worth a new install for.
3. **Alerts per 1,000 transactions at fixed recall levels.** This is how
   review capacity is actually planned in a real fraud operation: "if we
   need to catch 80% of fraud, how many transactions per 1,000 does an
   analyst have to look at?" Answer, measured: 16.95 per 1,000 at 70%
   recall, 52.49 at 80%, 96.48 at 85% — the curve gets steep fast past
   ~80%, a real operational finding.

   **Corrected 2026-07-27 — this section previously disagreed with section
   4 on the same data.** The original implementation cut the score-sorted
   ranking at the top-N rows reaching each target, then printed the score of
   the last included row as if it were a threshold. Wherever that cut landed
   inside a block of tied scores it named a rule it could not deliver: it
   reported "threshold >= 0.00, 260.37 alerts/1000" for 90% recall, but
   `risk_score >= 0.00` alerts on all 137,080 rows, which is what section 4
   correctly showed. 102,208 rows tie at exactly 0.00. Section 3 now applies
   genuine `risk_score >= t` rules, so the two sections agree.

   **What the correction exposed, and it matters more than the bug.** 55
   fraud rows score exactly 0.00 — every sub-score zero, reason code
   `NO_RISK_SIGNALS_DETECTED`, no feature firing at all. They are
   indistinguishable from the 102,153 legitimate rows tied with them.
   **No threshold above zero can therefore exceed 89.95% recall**, and the
   90%/95% targets are now marked degenerate: reachable only by alerting on
   every transaction. The 55 break down as P3 21, P2 18, P8 11, P7 5 — the
   reconnaissance patterns (balance probes, test transactions, PIN
   guessing), not the high-value drains. P4, P5 and P6 have no invisible
   rows at all. This is a feature-coverage ceiling, not a threshold-tuning
   problem, and no choice of thresholds can move it.
4. **Threshold sensitivity.** Shows precision/recall/alert-volume at score
   thresholds from 0 to 100 in steps of 10, so the current configured
   threshold (20) can be seen in context rather than in isolation.
5. **Detection by pattern (P2–P8).** For each pattern, not just the
   detection rate but — for whichever rows were missed — the mean
   risk_score and the three most common reason codes that DID fire but
   weren't enough to cross `allow_to_step_up`. This directly answers the author's
   question ("which of the 148 missed fraud rows are missed and why"), not
   just how many were missed.
   - **P1 is deliberately excluded.** It's the compromise mechanism
     underlying P2–P8 (a victim's card gets skimmed while transacting
     normally), not itself a labelled fraud row — see
     `explain/EXPLAIN_ebt_generator.md`, "P1 is not written as a fraud row."
     There is nothing to compute a detection rate against.
6. **Dollar cost matrix and the C4 savings-to-cost ratio** — see its own
   section below, the methodology choices here matter.
7. **N1 false-flag rate**, split into the overall N1 rate (55/339 = 16.22%)
   and the crossing-issuance-boundary subset specifically (48/48 = **100%**,
   95% CI 92.59%–100% since n=48 < the 200-case small-n threshold, SPEC.md
   §4.4). This is the measured cost of the issuance-day-fast-drain policy
   rule's accepted 0.8 sub-score (`config.yaml`, `explain/EXPLAIN_
   features.md` family 6): every one of the 48 legitimate crossing cases
   gets step-up, none gets block — the design worked exactly as intended
   (challenge, not denial), but the trade-off is real and now measured, not
   assumed.
8. **N2 false-flag rate** (16/1,686 = 0.95%), reported separately from N1
   per SPEC.md §4.4.
9. **Ordinary legitimate-transaction false-positive rate** (1,860/134,508 =
   1.38%) — explicitly excluding N1 and N2 rows, so this number isn't
   diluted or inflated by the two special categories that are reported on
   their own.
10. **False-positive rate by `locality_class`**, on ordinary legitimate
    rows only (same exclusion as #9, to keep this a clean read on the
    geographic fairness question rather than mixing in N1/N2 dynamics):
    rural 1.32%, suburban 1.46%, urban 1.36% — close together, no large
    disparity in the *overall* decision-based FP rate. This is the
    `evaluate.py`-level (SPEC.md §4.4) version of the check; the deeper,
    feature-specific fairness audit SPEC.md §4.7 describes (isolating
    geo-velocity's FP rate by locality vs. home-location-plausibility's,
    to confirm the zone-radius scaling actually worked) is `report.py`'s
    job, not built here.

## Small-n confidence intervals

Implemented as a Wilson score interval, not a normal approximation — Wilson
behaves better than normal approximation for small n or rates near 0%/100%,
both of which apply here (n=48 for the crossing subset; the crossing rate
itself is 100%, where a normal approximation would produce a nonsensical
interval). The 95% critical value (z=1.959963984540054) is hardcoded rather
than computed via `scipy.stats.norm.ppf(0.975)` — scipy is not an installed
dependency and this constant never changes.

Applied per SPEC.md §4.4/the author's 2026-07-24 rule: any subgroup metric on
fewer than ~200 cases gets its raw count and 95% CI stated alongside the
rate. Only the N1 crossing-boundary subset (n=48) triggers this in the
current report; every other subgroup here exceeds 200 cases.

## The dollar cost matrix — methodology choices, not domain figures

SPEC.md §4.4 specifies four line items (fraud value caught, fraud value
missed, legitimate value wrongly blocked, review cost per alert) and says
this "produces the real savings-to-cost ratio for C4." It does not specify
the exact formula, so three definitional choices were made here — these are
evaluation-methodology decisions, not fraud domain judgments (Rule 6 is
about fraud patterns/thresholds/risk weights), but they're flagged
explicitly so the author can react to them:

1. **"Alerted" (consumes review cost) = `decision != allow`.** Both step_up
   and block require a human/compliance review in a real EBT system —
   including an automatic block, which still needs to be logged and
   reviewable, not just step_up.
2. **"Fraud value caught" = the dollar amount of fraud rows where `decision
   != allow`.** In shadow mode nothing is actually stopped, so this is the
   value that *would* have been prevented had the decision been acted on
   live — a hypothetical built on a real decision label, not a measured
   prevention.
3. **"Legitimate value wrongly blocked" = the dollar amount of legitimate
   rows with `decision == block` specifically** (an actual denial), not
   `step_up` (a challenge that still proceeds). This matches SPEC's
   "wrongly *blocked*" wording — a step-up isn't a block.
4. **The headline ratio = fraud value caught ÷ total review cost**,
   matching the paper's "spend 1, save 99" framing literally: money spent
   running the review process vs. money saved. `legit_value_wrongly_
   blocked_usd` is reported as its own line item, **not folded into the
   ratio's cost side** — combining a denied-benefit dollar amount with an
   operational-cost denominator is a framing choice with real consequences
   for how the number reads, and it's left visible rather than pre-decided
   here.

## Real result, measured 2026-07-25

```
Fraud value caught:              $67,464.18
Fraud value missed:               $1,438.79
Legitimate value wrongly blocked:    $69.92
Total alerts:                       2,330

low  ($6.40/alert): total review cost=$14,912.00   ratio=4.52:1
mid  ($7.50/alert): total review cost=$17,475.00   ratio=3.86:1
high ($9.20/alert): total review cost=$21,436.00   ratio=3.15:1
```

**Why $69.92 is so small (verified 2026-07-25, the author asked directly because it
"looks almost too clean"):** only 3 of 136,533 legitimate rows in the entire
dataset ever reach `block` at all — everything else that gets flagged lands
on `step_up` (1,928 legitimate rows, $52,887.85 in transaction value
challenged but not denied — captured in the review-cost side of the ratio,
not here). All 3 of those blocked legitimate rows fired
`GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK`, and geo-velocity's hard override fires
on exactly 3 legitimate rows total in this dataset — the same count as the
"victim's own next legitimate transaction" collateral-trigger limitation
already documented in `EXPLAIN_features.md` family 1. The small, clean
number is a direct, traceable consequence of a design decision already on
record, not an artifact of how "wrongly blocked" was defined.

**Challenged vs. denied (added 2026-07-25, `challenged_vs_denied()`), now a
permanent report section rather than a chat answer.** Makes the contrast
between the two tiers explicit as its own line: 1,928 legitimate rows
CHALLENGED (step_up, $52,887.85 in value, proceeds after review) vs. 3
legitimate rows DENIED (block, $69.92, does not proceed) — and asserts in
code, not just prose, that all 3 denials carry
`GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK`. This is the block-alone-asymmetry design
principle's headline number: almost nothing legitimate is ever actually
denied, only challenged.

The measured ratio (3.15:1–4.52:1) sits below both figures the paper
currently states (20–80× in §4.4, 4–5× in §6) — near the bottom of the §6
range at the low end of the review-cost band, and below it entirely at the
high end. **This does not flip sign anywhere in the range (ratio stays
above 1:1 throughout)**, so C4's qualitative claim ("savings exceed cost")
holds, but the multiple the paper currently states is not supported by this
measurement. Per SPEC.md's own instruction (§1: "we are not trying to reach
99, we are trying to find out what the real figure is") and CLAUDE.md Rule
1, this is reported as the headline number it is, not softened.

## What this module does *not* do

- Does not build `outputs/PHASE0_REPORT.md` — that's `report.py` (SPEC.md
  §4.7), with charts, full run configuration, and the fairness audit that
  goes beyond the locality_class FP-rate check here.
- Does not separately attribute `block` decisions to "hard override" vs.
  "stacked weighted score" — that distinction is recoverable from
  `data/ebt_scored.csv`'s `geo_hard_override` and `risk_score` columns
  together, but isn't broken out as its own report section here; left for
  `report.py` if that distinction turns out to matter for the write-up.
- Does not compute the §4.7 fairness audit's feature-specific breakdowns
  (geo-velocity FP rate by locality vs. home-location-plausibility FP rate
  by locality, to check whether the zone-radius scaling actually closed the
  disparity it was built to close) — only the aggregate decision-level FP
  rate by locality_class, which is what SPEC.md §4.4 (not §4.7) asks for.
