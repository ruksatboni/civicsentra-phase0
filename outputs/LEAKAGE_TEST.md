# CivicSentra Phase 0 -- leakage test
Generated 2026-07-28 01:39:05 UTC by `src/test_leakage.py` from `data/ebt_synthetic.csv` (137,080 rows).

**RESULT: 34 of 34 sampled transactions PASS. No leakage detected.**

## What this proves, and what it does not

For each sampled transaction, every feature is recomputed against a dataset truncated to only the rows existing at or before that transaction's own timestamp, and compared to the value the same functions produce over the full 137,080 rows. If any feature secretly consulted a later row -- a terminal's eventual fraud rate, a subsequent neighbour -- the truncated value would differ and the row fails.

This is a **sampled** test, not a proof over the whole dataset. It demonstrates by direct comparison rather than by reading the code and reasoning that it looks correct -- which is the point, since the bug it caught (below) was invisible to exactly that kind of reasoning. A clean run means no leakage in these rows against these feature families, not a guarantee for every row.

## The sample, and why each row is in it

The sample is seeded (`np.random.default_rng(42)`), so it is the same every run. It deliberately covers each fraud pattern, every geo-velocity hard-override row, first-per-household rows with no prior history, and terminal-clustered rows -- not 34 random transactions that might all be easy cases. A row selected by more than one rule lists every reason.

| # | Transaction | Pattern | Chosen to exercise | Rows visible at cutoff | Result |
|---|---|---|---|---|---|
| 1 | `TXN00006403` | ordinary | first transaction for its household (no geo-velocity history) | 6,404 | PASS |
| 2 | `TXN00010512` | P6 | fraud pattern P6 | 10,513 | PASS |
| 3 | `TXN00012629` | ordinary | random, general coverage | 12,630 | PASS |
| 4 | `TXN00013319` | ordinary | first transaction for its household (no geo-velocity history) | 13,321 | PASS |
| 5 | `TXN00013656` | ordinary | first transaction for its household (no geo-velocity history) | 13,657 | PASS |
| 6 | `TXN00018421` | N2 | fraud pattern N2 | 18,422 | PASS |
| 7 | `TXN00025021` | ordinary | random, general coverage | 25,023 | PASS |
| 8 | `TXN00031149` | ordinary | random, general coverage | 31,150 | PASS |
| 9 | `TXN00041777` | P4 | fraud pattern P4 | 41,778 | PASS |
| 10 | `TXN00050824` | ordinary | random, general coverage | 50,826 | PASS |
| 11 | `TXN00051624` | P5 | geo-velocity impossible-travel hard override | 51,628 | PASS |
| 12 | `TXN00055160` | ordinary | random, general coverage | 55,161 | PASS |
| 13 | `TXN00060781` | ordinary | random, general coverage | 60,782 | PASS |
| 14 | `TXN00061020` | P8 | fraud pattern P8 | 61,021 | PASS |
| 15 | `TXN00061732` | ordinary | random, general coverage | 61,733 | PASS |
| 16 | `TXN00061747` | ordinary | random, general coverage | 61,748 | PASS |
| 17 | `TXN00063235` | P3 | fraud pattern P3 | 63,237 | PASS |
| 18 | `TXN00065336` | ordinary | geo-velocity impossible-travel hard override | 65,338 | PASS |
| 19 | `TXN00068581` | ordinary | random, general coverage | 68,582 | PASS |
| 20 | `TXN00073018` | P2 | fraud pattern P2 | 73,019 | PASS |
| 21 | `TXN00074764` | ordinary | random, general coverage | 74,765 | PASS |
| 22 | `TXN00076022` | ordinary | random, general coverage | 76,023 | PASS |
| 23 | `TXN00084821` | P5 | fraud pattern P5 | 84,823 | PASS |
| 24 | `TXN00088255` | ordinary | random, general coverage | 88,256 | PASS |
| 25 | `TXN00091171` | ordinary | 2+ prior same-terminal neighbours in window | 91,172 | PASS |
| 26 | `TXN00106936` | ordinary | geo-velocity impossible-travel hard override | 106,937 | PASS |
| 27 | `TXN00107130` | ordinary | random, general coverage | 107,131 | PASS |
| 28 | `TXN00112779` | ordinary | random, general coverage | 112,780 | PASS |
| 29 | `TXN00114809` | N1 | fraud pattern N1 | 114,810 | PASS |
| 30 | `TXN00119452` | ordinary | 2+ prior same-terminal neighbours in window | 119,453 | PASS |
| 31 | `TXN00120711` | P7 | fraud pattern P7 | 120,712 | PASS |
| 32 | `TXN00126480` | ordinary | 2+ prior same-terminal neighbours in window | 126,481 | PASS |
| 33 | `TXN00127031` | ordinary | random, general coverage | 127,032 | PASS |
| 34 | `TXN00133396` | ordinary | geo-velocity impossible-travel hard override | 133,398 | PASS |

## Features compared, per row

All 17 feature columns across the six families: `geo_velocity_mph`, `geo_velocity_subscore`, `geo_velocity_impossible_override`, `home_dist_miles`, `home_location_subscore`, `terminal_neighbour_count_before`, `terminal_neighbour_subscore`, `terminal_reputation_prior_n`, `terminal_reputation_shrunk_rate`, `terminal_reputation_subscore`, `remaining_balance_before`, `pct_of_remaining_balance`, `spend_baseline_subscore`, `policy_out_of_state_flag`, `policy_fast_drain_flag`, `policy_balance_probe_flag`, `ebt_policy_rules_subscore`.

## Historical note: the bug this test caught (2026-07-25)

**The first run of this test failed on 11 of 34 sampled rows**, and finding that is the most valuable thing it has done.

Terminal reputation's *raw* shrunk rate was correctly point-in-time, built from an expanding cumulative sum over strictly-prior rows only. But the sub-score's normalization baseline used `df["is_fraud"].mean()` -- the mean of whichever dataframe was passed in. Over the full 137,080 rows that is one number; over any earlier prefix of the data it is a different one. So every transaction's sub-score silently depended on the dataset's *eventual* average fraud rate, which had not happened yet at the moment that transaction was scored.

The raw feature looked correct under inspection, and the leak sat in the normalization step rather than the feature logic -- which is why it survived code review and was caught only by recomputing against a truncated dataset.

**Fixed** by using each row's own point-in-time expanding global rate as the baseline instead of a dataset-wide constant. All 34 rows passed after the fix, and the fix landed before any result in this repository was produced -- no published figure was ever computed with the leaking version. See `explain/EXPLAIN_features.md` family 4.
