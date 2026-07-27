# CivicSentra Phase 0 -- robustness run at realistic fraud prevalence
Generated 2026-07-27 14:26:45 UTC from data/ebt_synthetic_realistic.csv (2,598,309 rows).

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

## Why precision differs -- the comparison is not prevalence alone
  household never defrauded          : n=2,526,290  flagged=  414  rate=  0.02%
  victim household, BEFORE the fraud : n=   12,474  flagged=    0  rate=  0.00%
  victim household, AFTER the fraud  : n=   13,623  flagged=1,882  rate= 13.81%
Households containing at least one fraud row: 386 of 38,000 (1.0%)

The dominant false-positive mechanism in both datasets is the same: a victim's own legitimate transactions after their balance was drained. What changes between the two runs is how much of the population that mechanism can reach. Spreading a similar number of fraud episodes over 19x more households leaves a far smaller share of households contaminated, so the aggregate ordinary false-positive rate falls. Precision therefore moves for two reasons at once -- lower prevalence and lower victim-household density -- and this run does not separate them. Read the precision figure as 'measured at realistic prevalence in this dataset', not as a clean prevalence-only elasticity.

