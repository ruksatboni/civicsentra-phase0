# CivicSentra Phase 0 -- evaluate.py output
Generated 2026-07-28 02:23:16 UTC from data/ebt_scored.csv (137,080 rows).
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
