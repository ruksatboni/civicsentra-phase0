# CivicSentra Phase 0 -- robustness run at realistic fraud prevalence
Generated 2026-07-29 03:08:32 UTC from data/ebt_synthetic_realistic.csv (2,598,309 rows).

Same scorer, same config.yaml, same weights and thresholds as the primary run. The only thing that changed is the input dataset. Nothing was retuned for this run -- retuning would defeat the purpose of the comparison.

## Dataset
Rows: 2,598,309   households: 38,000
Fraud rows: 518   transaction-level prevalence: 0.0199%

## Precision / recall at the same operating point
TP=379  FP=3256  FN=139
Precision: 10.43%   Recall: 73.17%
Block-only: TP=32 FP=0 precision=100.00%  [n=32<200: 95% CI 89.28%-100.00%]

## False-positive composition
  ordinary_legitimate: 2296 of 3256 (70.52%)
  N1: 915 of 3256 (28.10%)
  N2: 45 of 3256 (1.38%)

## Alert volume
Alerts per 1,000 transactions: 1.40

## Dollar cost matrix and savings-to-cost ratio (C4) at realistic prevalence
Fraud value caught (decision != allow): $66,547.77
Fraud value missed (decision == allow):  $1,875.76
Legitimate value wrongly BLOCKED (decision == block, is_fraud=False): $0.00
Total alerts (review-cost-consuming, decision != allow): 3,635

Savings-to-cost ratio = fraud value caught / total review cost, across the same $6.40-$9.20 review-cost range as the primary (SPEC.md §4.4: run the full range, not just the midpoint):
   low ($6.40/alert): total review cost=$23,264.00   ratio=2.86:1
   mid ($7.50/alert): total review cost=$27,262.50   ratio=2.44:1
  high ($9.20/alert): total review cost=$33,442.00   ratio=1.99:1

### Side by side with the primary run
Both columns computed in this process by the same `cost_matrix()` from `evaluate.py`, not quoted from `outputs/evaluate_metrics.md`.

| | primary (137,080 rows) | realistic (2,598,309 rows) |
|---|---|---|
| transaction-level prevalence | 0.3990% | 0.0199% |
| fraud value caught | $67,464.18 | $66,547.77 |
| fraud value missed | $1,438.79 | $1,875.76 |
| legitimate value wrongly blocked | $69.92 | $0.00 |
| total alerts | 2,330 | 3,635 |
| ratio, low ($6.40/alert) | 4.52:1 | 2.86:1 |
| ratio, mid ($7.50/alert) | 3.86:1 | 2.44:1 |
| ratio, high ($9.20/alert) | 3.15:1 | 1.99:1 |

Measured ratio at realistic prevalence ranges 1.99:1 to 2.86:1, against 3.15:1 to 4.52:1 on the primary. The paper claims 20-80x (§4.4) / 4-5x (§6); the realistic-prevalence range falls below the §6 claim and is far below the §4.4 one, and that is the figure to quote for a real-world deployment rather than the primary's.
Why it moves in this direction: the numerator is the value of fraud actually caught, which is bounded by how much fraud exists, while the denominator is review cost, which scales with total alerts and is dominated by false positives. Dropping prevalence ~20x removes very little from the numerator (a similar number of fraud episodes) but leaves a large false-positive base in the denominator, so the ratio falls. A savings-to-cost ratio measured at elevated prevalence therefore flatters the system, and the elevation was chosen for statistical power, not to make this number look better -- which is exactly why it has to be reported at realistic prevalence too.

## Why precision differs -- the comparison is not prevalence alone
  household never defrauded          : n=2,526,290  flagged=  414  rate=  0.02%
  victim household, BEFORE the fraud : n=   12,474  flagged=    0  rate=  0.00%
  victim household, AFTER the fraud  : n=   13,623  flagged=1,882  rate= 13.81%
Households containing at least one fraud row: 386 of 38,000 (1.0%)

The dominant false-positive mechanism in both datasets is the same: a victim's own legitimate transactions after their balance was drained. What changes between the two runs is how much of the population that mechanism can reach. Spreading a similar number of fraud episodes over 19x more households leaves a far smaller share of households contaminated, so the aggregate ordinary false-positive rate falls. Precision therefore moves for two reasons at once -- lower prevalence and lower victim-household density -- and this run does not separate them. Read the precision figure as 'measured at realistic prevalence in this dataset', not as a clean prevalence-only elasticity.

