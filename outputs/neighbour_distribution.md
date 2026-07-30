# CivicSentra Phase 0 -- same-terminal temporal-neighbour distribution
Generated 2026-07-30 01:55:20 UTC by `src/neighbour_distribution.py` from `data/ebt_synthetic.csv` (137,080 rows).

This is the measurement that justifies `min_neighbours_flagged` in config.yaml. It was previously a hand-measured figure in a comment with no script behind it (outputs/TRACEABILITY.md §7). It is now recomputed here, by two independent implementations, and the config comment's own numbers are parsed back out and checked against them.

Definition: for each transaction, the number of OTHER transactions at the same `terminal_id` in the 15 minutes immediately BEFORE it. Never after -- an 'after' count needs a future transaction and would be leakage (config.yaml, features.py). Minute resolution.

## Two implementations, compared
- `neighbour_distribution.py` `independent_counts()` -- pure Python, bisect over a per-terminal sorted list, imports nothing from features.py
- `features.py` `compute_terminal_temporal_neighbour()` -- numpy searchsorted over grouped arrays

**137,080 of 137,080 rows agree exactly.** The two implementations produce identical counts, so the distribution below is not an artifact of either one.

## Distribution

| Prior same-terminal neighbours in window | Rows | Share |
|---|---|---|
| 0 | 130,678 | 95.33% |
| 1 | 6,145 | 4.48% |
| 2 or more | 257 | 0.19% |

Rows at or above the configured `min_neighbours_flagged` (2): 257 (0.19%).

## Against the figures in config.yaml's comment

| Quantity | config.yaml comment | recomputed | |
|---|---|---|---|
| zero neighbours (%) | 95.33 | 95.33 | MATCH |
| exactly one (%) | 4.48 | 4.48 | MATCH |
| two or more (%) | 0.19 | 0.19 | MATCH |
| window (minutes) | 15.00 | 15.00 | MATCH |

**All match.** The hand-measured figures from 2026-07-25 are confirmed against the current dataset, and the justification for `min_neighbours_flagged` is now reproducible rather than asserted.
