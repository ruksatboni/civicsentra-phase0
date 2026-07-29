# CivicSentra Phase 0 -- evaluate.py output
Generated 2026-07-29 02:16:01 UTC from data/ebt_scored.csv (137,080 rows).
Every number below is computed by this script's own execution, not assumed or carried over from a previous run.

## 1. Precision / recall at the current operating point (scorer.py's configured thresholds)
Alerted = decision != allow. TP=399  FP=1931  FN=148
Precision: 17.12%   Recall: 72.94%

### Precision by decision tier -- block vs. all alerts
Block requires either stacked features crossing the 50-point line or the geo-velocity hard override firing alone (explain/EXPLAIN_scorer.md); step_up requires neither. These are different tiers and one precision number hides that:
  ALL ALERTS (step_up or block): TP=399 FP=1931  precision=17.12%
  BLOCK ONLY:                    TP=39 FP=3  precision=92.86%  [n=42<200: 95% CI 80.99%-97.54%]
Block-tier precision is far above the all-alert figure, consistent with block requiring stacked corroborating signals rather than one feature alone -- this is what makes the 17% all-alert figure defensible: most of the volume behind it is step_up (a challenge, not a denial), not block.

### False-positive composition -- pressure-testing precision
Is low precision explained by the deliberate N1/N2 challenge trade-off, or by something else? Decomposed by category, not asserted either way (the author, 2026-07-25):
  ordinary_legitimate: 1860 of 1931 false positives (96.32%)
  N1: 55 of 1931 false positives (2.85%)
  N2: 16 of 1931 false positives (0.83%)

Ordinary-legitimate FPs -- mean risk_score=26.09, reason codes behind them: {'SPEND_BASELINE_HIGH_DRAW': 1860, 'TERMINAL_REPUTATION_ELEVATED': 738, 'HOME_LOCATION_OUT_OF_ZONE': 54, 'GEO_VELOCITY_ELEVATED_SPEED': 6, 'TERMINAL_NEIGHBOUR_CLUSTER': 4, 'GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK': 3, 'HOME_LOCATION_NIGHT_AMPLIFIED': 1, 'POLICY_BALANCE_PROBE_THEN_PURCHASE': 1, 'POLICY_ISSUANCE_DAY_FAST_DRAIN': 1}
N1 and N2 combined explain only a small minority of false positives by count (see percentages above) despite N1's comparatively high 16% false-flag rate on its own small population (see section 7) -- the ordinary-legitimate population is ~400x larger than N1 and ~80x larger than N2, so even a low per-category alert rate there dominates the raw false-positive count. Read together with section 7's N1/N2 rates, not in isolation from them.

### Where the ordinary-legitimate false positives actually come from
Ordinary legitimate rows split by whether their household was also defrauded, and by whether the row falls before or after that fraud:
  household never defrauded          : n=109,936  flagged=   16  rate=  0.01%
  victim household, BEFORE the fraud : n= 11,530  flagged=    0  rate=  0.00%
  victim household, AFTER the fraud  : n= 13,042  flagged=1,844  rate= 14.14%
Share of all ordinary-legitimate false positives that fall after their own household's fraud: 99.1%
This is the dominant false-positive mechanism, and it is not what the aggregate rate suggests. A household whose balance a fraudster has just drained will have its own next legitimate purchases read as drawing a large percentage of a now-tiny remaining balance, tripping SPEND_BASELINE_HIGH_DRAW. Households never defrauded almost never false-positive. The operational consequence belongs in the report: the people most likely to be repeatedly challenged by this system are the people who were just robbed. Same failure mode as the geo-velocity collateral trigger (EXPLAIN_features.md family 1), roughly two orders of magnitude larger.

## 2. PR-AUC (threshold-independent, average precision over risk_score)
PR-AUC = 0.5364  (not ROC-AUC -- SPEC.md §4.4: ROC-AUC flatters classifiers on imbalanced data)

## 3. Alerts per 1,000 transactions at fixed recall levels
(How many of every 1,000 transactions would need review to catch this much fraud, if the score threshold were moved to hit each recall target.)
Recall ceiling: no threshold above zero can exceed 89.95% recall. 55 of 547 fraud rows score exactly 0.00 with no feature firing at all ({'P3': 21, 'P2': 18, 'P8': 11, 'P7': 5}), so they are indistinguishable from the legitimate rows tied with them at 0.00. Targets above the ceiling are reachable only by alerting on every transaction, and are marked below.
  recall=50%: score_threshold>=31.01, alerts/1000=2.84, precision at this point=70.44%
  recall=60%: score_threshold>=25.26, alerts/1000=7.17, precision at this point=33.47%
  recall=70%: score_threshold>=25.00, alerts/1000=16.95, precision at this point=16.91%
  recall=75%: score_threshold>=11.79, alerts/1000=18.56, precision at this point=16.16%
  recall=80%: score_threshold>=5.14, alerts/1000=52.49, precision at this point=6.09%
  recall=85%: score_threshold>=1.57, alerts/1000=96.48, precision at this point=3.52%
  recall=90%: score_threshold>=0.00, alerts/1000=1000.00, precision at this point=0.40%   <-- DEGENERATE: only reachable by alerting on every transaction; not an operating point
  recall=95%: score_threshold>=0.00, alerts/1000=1000.00, precision at this point=0.40%   <-- DEGENERATE: only reachable by alerting on every transaction; not an operating point

Thresholds here are genuine `risk_score >= t` rules, matching section 4. An earlier version of this section cut the score-sorted ranking at the top-N rows instead, which understated alert volume wherever the cut fell inside a block of tied scores -- see alerts_per_1000_at_recall()'s docstring for what that produced and why it disagreed with section 4.

## 4. Threshold sensitivity
(How the alert threshold on risk_score would move precision/recall/volume if allow_to_step_up were set differently. Current config value: 20.)
 score_threshold  n_alerts  alerts_per_1000  precision  recall
               0    137080        1000.0000     0.0040  1.0000
              10      2815          20.5355     0.1488  0.7660
              20      2330          16.9974     0.1712  0.7294
              30       431           3.1441     0.6682  0.5265
              40       161           1.1745     0.9193  0.2706
              50        42           0.3064     0.9286  0.0713
              60         9           0.0657     0.6667  0.0110
              70         4           0.0292     0.2500  0.0018
              80         4           0.0292     0.2500  0.0018
              90         4           0.0292     0.2500  0.0018
             100         4           0.0292     0.2500  0.0018

## 5. Detection rate by fraud pattern
(P1, skimmer harvest, has no labelled fraud rows by design -- it is the compromise mechanism underlying P2-P8, not itself a fraud transaction; see explain/EXPLAIN_ebt_generator.md.)
  P2: 39/78 detected (50.00%), 39 missed  [n<200: 95% CI 39.17%-60.83%]
    missed rows -- mean risk_score=2.99, top reason codes among missed: {'TERMINAL_REPUTATION_ELEVATED': 19, 'NO_RISK_SIGNALS_DETECTED': 18, 'HOME_LOCATION_OUT_OF_ZONE': 4}
  P3: 36/78 detected (46.15%), 42 missed  [n<200: 95% CI 35.53%-57.14%]
    missed rows -- mean risk_score=2.26, top reason codes among missed: {'NO_RISK_SIGNALS_DETECTED': 21, 'TERMINAL_REPUTATION_ELEVATED': 19, 'POLICY_BALANCE_PROBE_THEN_PURCHASE': 3}
  P4: 77/77 detected (100.00%), 0 missed  [n<200: 95% CI 95.25%-100.00%]
  P5: 77/77 detected (100.00%), 0 missed  [n<200: 95% CI 95.25%-100.00%]
  P6: 82/82 detected (100.00%), 0 missed  [n<200: 95% CI 95.52%-100.00%]
  P7: 68/77 detected (88.31%), 9 missed  [n<200: 95% CI 79.25%-93.73%]
    missed rows -- mean risk_score=4.84, top reason codes among missed: {'NO_RISK_SIGNALS_DETECTED': 5, 'SPEND_BASELINE_HIGH_DRAW': 4, 'TERMINAL_REPUTATION_ELEVATED': 2}
  P8: 20/78 detected (25.64%), 58 missed  [n<200: 95% CI 17.26%-36.31%]
    missed rows -- mean risk_score=4.50, top reason codes among missed: {'TERMINAL_REPUTATION_ELEVATED': 47, 'NO_RISK_SIGNALS_DETECTED': 11, 'HOME_LOCATION_OUT_OF_ZONE': 11}

## 6. Dollar cost matrix and savings-to-cost ratio (C4)
Fraud value caught (decision != allow): $67,464.18
Fraud value missed (decision == allow):  $1,438.79
Legitimate value wrongly BLOCKED (decision == block, is_fraud=False): $69.92
Total alerts (review-cost-consuming, decision != allow): 2,330

### Legitimate transactions: challenged vs. denied
CHALLENGED (step_up -- proceeds after review): 1,928 rows, $52,887.85 in transaction value
DENIED (block -- does not proceed):            3 rows, $69.92 in transaction value
All 3 denials carry GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK -- these are the documented geo-velocity collateral-trigger cases (explain/EXPLAIN_features.md family 1: a fraud victim's own next legitimate transaction, scored against the fraudster's out-of-state location), not a general pattern of denying ordinary legitimate purchases. This is the block-alone-asymmetry design principle (explain/EXPLAIN_scorer.md) working as intended: almost nothing legitimate is ever actually denied.

Savings-to-cost ratio = fraud value caught / total review cost, across the full $6.40-$9.20 review-cost range (SPEC.md §4.4: run the full range, not just the midpoint):
   low ($6.40/alert): total review cost=$14,912.00   ratio=4.52:1
   mid ($7.50/alert): total review cost=$17,475.00   ratio=3.86:1
  high ($9.20/alert): total review cost=$21,436.00   ratio=3.15:1

Paper claims 20-80x (§4.4) / 4-5x (§6), never 99x. Measured ratio here ranges 3.15:1 to 4.52:1 across the review-cost range -- read together with the report's C4 discussion, not in isolation.

## 7. N1 false-flag rate (technical failure, legitimate -- is_fraud=False)
  All N1 rows flagged (step_up or block): 55/339 = 16.22%
  N1 decision breakdown: {'allow': 284, 'step_up': 55}
  Crossing-issuance-boundary N1 subset flagged (step_up or block) -- the accepted trade-off from config.yaml's ebt_policy_rules 0.8 value: 48/48 = 100.00%  [n<200: 95% CI 92.59%-100.00%]
  Crossing-subset decision breakdown: {'step_up': 48}

## 8. N2 false-flag rate (legitimate third-party use -- is_fraud=False)
  All N2 rows flagged (step_up or block): 16/1686 = 0.95%

## 9. Ordinary legitimate-transaction false-positive rate
(is_fraud=False, fraud_pattern is null -- i.e. excluding N1 and N2, which are reported separately above per SPEC.md §4.4.)
  Ordinary legitimate rows flagged: 1860/134508 = 1.38%

## 10. False-positive rate by locality_class (ordinary legitimate rows)
  locality_class=rural: 464/35225 = 1.32%
  locality_class=suburban: 674/46119 = 1.46%
  locality_class=urban: 722/53164 = 1.36%

## 11. TERMINAL_NEIGHBOUR_CLUSTER -- whole-run firing census
The terminal_temporal_neighbour family carries 0.10 of the risk score (10.0 of 100 points at saturation) but is nearly invisible in the sections above: it appears in no per-pattern missed-reason list in section 5, and only a handful of times in section 1's false-positive reason codes. Those sections only surface it where it happens to accompany an alert or a miss, so neither answers whether it fires on fraud rows at all. This section counts every firing in the run.
'Fires' = terminal_neighbour_subscore_points > 0, the same condition scorer.py uses to emit TERMINAL_NEIGHBOUR_CLUSTER. Points column and reason code agree on every row: True.

Total firings across all 137,080 rows: 257
  on FRAUD rows      :    12 of     547 = 2.19%  [95% CI 1.26%-3.80%]
  on LEGITIMATE rows :   245 of 136,533 = 0.18%  [95% CI 0.16%-0.20%]

Fraud side, by pattern (every pattern listed, including those with zero firings -- a zero is the finding here, and a counts-only table would omit it):
  P2: fired on   0 of  78 rows (  0.00%); of those firings, 0 are on rows that alerted
  P3: fired on   1 of  78 rows (  1.28%); of those firings, 1 are on rows that alerted
  P4: fired on   0 of  77 rows (  0.00%); of those firings, 0 are on rows that alerted
  P5: fired on   0 of  77 rows (  0.00%); of those firings, 0 are on rows that alerted
  P6: fired on   0 of  82 rows (  0.00%); of those firings, 0 are on rows that alerted
  P7: fired on   0 of  77 rows (  0.00%); of those firings, 0 are on rows that alerted
  P8: fired on  11 of  78 rows ( 14.10%); of those firings, 4 are on rows that alerted

Legitimate side, by category (same split as section 1's false-positive decomposition):
  ordinary_legitimate: fired on   243 of 134,508 rows (0.18%)
                   N1: fired on     0 of     339 rows (0.00%)
                   N2: fired on     2 of   1,686 rows (0.12%)

It DOES fire on fraud: 12 times, concentrated in P3 (1), P8 (11). The fraud-side firing rate (2.19%) is 12.2x the legitimate-side rate (0.18%), so the feature is not firing at random with respect to the label -- the correct statement is that it discriminates weakly but non-trivially, NOT that it has no supporting evidence in the evaluation.
The two 95% intervals do not overlap (1.26%-3.80% against 0.16%-0.20%), so the enrichment is not an artefact of the small fraud population. It still rests on 12 fraud rows, which is the caveat that belongs next to the lift figure whenever it is quoted.

Magnitude: the largest contribution this family makes anywhere in the run is 7.50 points of a possible 10.0; on fraud rows specifically it never exceeds 2.50 points.
Counterfactual -- the run re-decided with this family's points subtracted from every score (allow/step_up/block recomputed by the same two-path rule scorer.py uses): 0 decisions change (0 on fraud rows, 0 on legitimate rows).
Deleting the feature outright would leave every decision in this evaluation exactly as it stands. That is the finding section 9 should carry, and it is sharper than a firing count either way: the family fires, it fires preferentially on fraud, and it is still decisive nowhere -- its contribution is always too small to move a row across a threshold on its own, and it never arrives as the marginal point on a row sitting at the line. A weight of 0.10 is doing no work here, which is a statement about this dataset's terminal-sharing structure as much as about the feature.

## 12. False-positive composition at thresholds 25, 26, 30
Section 4's 10-point grid shows alerts collapsing and precision climbing between thresholds 20 and 30, but a 10-point grid cannot say WHAT clears out. This repeats the section 1 decomposition (ordinary-legitimate / N1 / N2) and the reason-code distribution at each of 25, 26, 30, with threshold 20 (the configured allow_to_step_up) included as the anchor the others are measured against.
Why 26 specifically: a saturated spend_baseline sub-score contributes at most 25.0 points (weight 0.25 x 100), so 26 is the first integer threshold at which a SPEND_BASELINE_HIGH_DRAW firing with nothing alongside it cannot alert, whatever its sub-score. That is arithmetic; whether it is what actually clears is measured below.

### threshold 20  (anchor -- current config)
  alerts=2,330  TP=399  FP=1,931  precision=17.12%  recall=72.94%
    ordinary_legitimate: 1,860 of 1,931 false positives (96.32%)
                     N1:    55 of 1,931 false positives (2.85%)
                     N2:    16 of 1,931 false positives (0.83%)
  reason codes across those FPs: {'SPEND_BASELINE_HIGH_DRAW': 1931, 'TERMINAL_REPUTATION_ELEVATED': 761, 'HOME_LOCATION_OUT_OF_ZONE': 55, 'GEO_VELOCITY_ELEVATED_SPEED': 6, 'TERMINAL_NEIGHBOUR_CLUSTER': 4, 'GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK': 3, 'HOME_LOCATION_NIGHT_AMPLIFIED': 1, 'POLICY_BALANCE_PROBE_THEN_PURCHASE': 1, 'POLICY_ISSUANCE_DAY_FAST_DRAIN': 1}
  whole reason-code sets (per-code totals above cannot separate 'fired alone' from 'fired alongside'):
    1,120  SPEND_BASELINE_HIGH_DRAW
      742  SPEND_BASELINE_HIGH_DRAW|TERMINAL_REPUTATION_ELEVATED
       35  HOME_LOCATION_OUT_OF_ZONE|SPEND_BASELINE_HIGH_DRAW
       18  HOME_LOCATION_OUT_OF_ZONE|SPEND_BASELINE_HIGH_DRAW|TERMINAL_REPUTATION_ELEVATED
        5  GEO_VELOCITY_ELEVATED_SPEED|SPEND_BASELINE_HIGH_DRAW
        4  SPEND_BASELINE_HIGH_DRAW|TERMINAL_NEIGHBOUR_CLUSTER
  SPEND_BASELINE_HIGH_DRAW as the ONLY code: 1,120 of 1,931 FPs (58.00%)

### threshold 25
  alerts=2,324  TP=393  FP=1,931  precision=16.91%  recall=71.85%
    ordinary_legitimate: 1,860 of 1,931 false positives (96.32%)
                     N1:    55 of 1,931 false positives (2.85%)
                     N2:    16 of 1,931 false positives (0.83%)
  reason codes across those FPs: {'SPEND_BASELINE_HIGH_DRAW': 1931, 'TERMINAL_REPUTATION_ELEVATED': 761, 'HOME_LOCATION_OUT_OF_ZONE': 55, 'GEO_VELOCITY_ELEVATED_SPEED': 6, 'TERMINAL_NEIGHBOUR_CLUSTER': 4, 'GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK': 3, 'HOME_LOCATION_NIGHT_AMPLIFIED': 1, 'POLICY_BALANCE_PROBE_THEN_PURCHASE': 1, 'POLICY_ISSUANCE_DAY_FAST_DRAIN': 1}
  whole reason-code sets (per-code totals above cannot separate 'fired alone' from 'fired alongside'):
    1,120  SPEND_BASELINE_HIGH_DRAW
      742  SPEND_BASELINE_HIGH_DRAW|TERMINAL_REPUTATION_ELEVATED
       35  HOME_LOCATION_OUT_OF_ZONE|SPEND_BASELINE_HIGH_DRAW
       18  HOME_LOCATION_OUT_OF_ZONE|SPEND_BASELINE_HIGH_DRAW|TERMINAL_REPUTATION_ELEVATED
        5  GEO_VELOCITY_ELEVATED_SPEED|SPEND_BASELINE_HIGH_DRAW
        4  SPEND_BASELINE_HIGH_DRAW|TERMINAL_NEIGHBOUR_CLUSTER
  SPEND_BASELINE_HIGH_DRAW as the ONLY code: 1,120 of 1,931 FPs (58.00%)

### threshold 26
  alerts=748  TP=312  FP=436  precision=41.71%  recall=57.04%
    ordinary_legitimate:   427 of 436 false positives (97.94%)
                     N1:     7 of 436 false positives (1.61%)
                     N2:     2 of 436 false positives (0.46%)
  reason codes across those FPs: {'SPEND_BASELINE_HIGH_DRAW': 436, 'TERMINAL_REPUTATION_ELEVATED': 386, 'HOME_LOCATION_OUT_OF_ZONE': 55, 'GEO_VELOCITY_ELEVATED_SPEED': 6, 'TERMINAL_NEIGHBOUR_CLUSTER': 4, 'GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK': 3, 'HOME_LOCATION_NIGHT_AMPLIFIED': 1, 'POLICY_BALANCE_PROBE_THEN_PURCHASE': 1, 'POLICY_ISSUANCE_DAY_FAST_DRAIN': 1}
  whole reason-code sets (per-code totals above cannot separate 'fired alone' from 'fired alongside'):
      367  SPEND_BASELINE_HIGH_DRAW|TERMINAL_REPUTATION_ELEVATED
       35  HOME_LOCATION_OUT_OF_ZONE|SPEND_BASELINE_HIGH_DRAW
       18  HOME_LOCATION_OUT_OF_ZONE|SPEND_BASELINE_HIGH_DRAW|TERMINAL_REPUTATION_ELEVATED
        5  GEO_VELOCITY_ELEVATED_SPEED|SPEND_BASELINE_HIGH_DRAW
        4  SPEND_BASELINE_HIGH_DRAW|TERMINAL_NEIGHBOUR_CLUSTER
        2  GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK|SPEND_BASELINE_HIGH_DRAW
  SPEND_BASELINE_HIGH_DRAW as the ONLY code: 0 of 436 FPs (0.00%)

### threshold 30
  alerts=431  TP=288  FP=143  precision=66.82%  recall=52.65%
    ordinary_legitimate:   141 of 143 false positives (98.60%)
                     N1:     2 of 143 false positives (1.40%)
                     N2:     0 of 143 false positives (0.00%)
  reason codes across those FPs: {'SPEND_BASELINE_HIGH_DRAW': 143, 'TERMINAL_REPUTATION_ELEVATED': 100, 'HOME_LOCATION_OUT_OF_ZONE': 55, 'GEO_VELOCITY_ELEVATED_SPEED': 4, 'GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK': 3, 'HOME_LOCATION_NIGHT_AMPLIFIED': 1, 'POLICY_ISSUANCE_DAY_FAST_DRAIN': 1}
  whole reason-code sets (per-code totals above cannot separate 'fired alone' from 'fired alongside'):
       81  SPEND_BASELINE_HIGH_DRAW|TERMINAL_REPUTATION_ELEVATED
       35  HOME_LOCATION_OUT_OF_ZONE|SPEND_BASELINE_HIGH_DRAW
       18  HOME_LOCATION_OUT_OF_ZONE|SPEND_BASELINE_HIGH_DRAW|TERMINAL_REPUTATION_ELEVATED
        3  GEO_VELOCITY_ELEVATED_SPEED|SPEND_BASELINE_HIGH_DRAW
        2  GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK|SPEND_BASELINE_HIGH_DRAW
        1  HOME_LOCATION_OUT_OF_ZONE|HOME_LOCATION_NIGHT_AMPLIFIED|SPEND_BASELINE_HIGH_DRAW
  SPEND_BASELINE_HIGH_DRAW as the ONLY code: 0 of 143 FPs (0.00%)

### What clears between each pair of thresholds
(False positives alerting at the lower threshold and not at the higher one, decomposed by their full reason-code set. Fraud lost over the same step is shown alongside, so no clearance reads as free.)

  20 -> 25: 0 false positives clear, 6 fraud rows lost
    (nothing clears over this step)

  25 -> 26: 1,495 false positives clear, 81 fraud rows lost
    risk_score range of the cleared FPs: 25.00 - 25.99
    1,120  SPEND_BASELINE_HIGH_DRAW
      375  SPEND_BASELINE_HIGH_DRAW|TERMINAL_REPUTATION_ELEVATED
    single-feature SPEND_BASELINE among them: 1,120 (74.9%)
    spend_baseline SATURATED at 25.0 points among them: 1,495 of 1,495; largest all-other-families contribution on any cleared row: 0.99 points

  26 -> 30: 293 false positives clear, 24 fraud rows lost
    risk_score range of the cleared FPs: 26.00 - 29.95
      286  SPEND_BASELINE_HIGH_DRAW|TERMINAL_REPUTATION_ELEVATED
        4  SPEND_BASELINE_HIGH_DRAW|TERMINAL_NEIGHBOUR_CLUSTER
        2  GEO_VELOCITY_ELEVATED_SPEED|SPEND_BASELINE_HIGH_DRAW
        1  SPEND_BASELINE_HIGH_DRAW|POLICY_BALANCE_PROBE_THEN_PURCHASE
    single-feature SPEND_BASELINE among them: 0 (0.0%)
    spend_baseline SATURATED at 25.0 points among them: 293 of 293; largest all-other-families contribution on any cleared row: 4.95 points

Measured answer to 'is it single-feature SPEND_BASELINE that clears out': largely yes, but the precise statement is narrower. The 20 -> 25 step removes nothing at all -- no false positive in this run scores between 20 and 25, so the configured threshold of 20 and a threshold of 25 produce an identical false-positive set. Everything happens at 25 -> 26, where 1,495 false positives clear at once, 1,120 of them (74.9%) firing SPEND_BASELINE_HIGH_DRAW and nothing else, all sitting in a 25.00-25.99 score band.
The remainder of that step is not a different mechanism, and the saturation line above is what shows it: all 1,495 cleared rows have spend_baseline saturated at 25.0 points, and no cleared row draws more than 0.99 points from all five other families combined. The rows carrying a second reason code are spend-baseline saturation plus a sub-point nudge -- single-feature firings in everything but the reason-code count. So the honest form of the claim is that the 20 -> 30 precision gain is bought almost entirely by excluding spend-baseline saturation, not by any broader improvement in discrimination -- and the price is visible above: 111 fraud rows lost across the same range.
