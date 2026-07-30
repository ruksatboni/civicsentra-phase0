# CivicSentra Phase 0 -- crossing-issuance N1 drawdown, recomputed
Generated 2026-07-30 01:55:19 UTC by `src/n1_crossing_drawdown.py` from `data/ebt_synthetic.csv` (137,080 rows).

Recomputes the three figures the paper's N1 section cites for the store-and-forward transactions whose window crosses an issuance boundary -- mean, median and range of the amount drawn as a share of monthly benefit -- and checks them against the values claimed in the files that record them. These were the last figures in the results section that no committed script computed.

**All checks pass.** The two implementations agree exactly, the subgroup is what the claim says it is, and every claimed figure matches the recomputed value.

## Definition

Subgroup: rows with `n1_crossing_issuance = True` -- the N1 technical failures whose store-and-forward window crossed into a new benefit issuance period (7 CFR 274.12(m)). **Drawdown** is `amount` as a percentage of `monthly_benefit_amount`: the household's full monthly benefit, not its remaining balance. That is the denominator the claim names, and it is the right one here -- the regulation permits such a transaction to draw against the whole newly issued balance, so the benefit amount is what is actually available to draw.

- N1 rows in the dataset: **339**
- Of those, crossing an issuance boundary: **48**, across 48 household(s)

## Recomputed

| Quantity | Value |
|---|---|
| rows | 48 |
| mean drawdown | 68.4280% |
| median drawdown | 71.1031% |
| minimum | 42.5824% |
| maximum | 88.2680% |

Full sorted distribution, so the summary statistics can be checked by hand rather than taken on trust (%):

```
   42.58   44.90   45.27   46.29   48.22   49.00   49.15   52.66
   53.93   54.57   56.83   57.20   59.35   59.57   60.03   61.55
   63.24   64.92   65.73   66.04   67.22   67.36   68.32   71.05
   71.16   71.93   73.92   75.28   75.66   77.04   77.23   77.30
   77.34   77.44   77.56   78.82   79.27   79.39   79.74   82.03
   82.54   82.70   83.57   84.16   84.73   86.19   86.28   88.27
```

## Two implementations, compared

- `drawdown_pandas()` -- pandas `mean`/`median`/`min`/`max`
- `drawdown_stdlib()` -- stdlib `csv`, no dataframe library, mean and median written out by hand. n is even (48), so the even-n median is the case that genuinely distinguishes the two implementations.

| Statistic | pandas | stdlib | difference | |
|---|---|---|---|---|
| n | 48 | 48 | 0.000e+00 | MATCH |
| mean | 68.4280 | 68.4280 | 1.421e-14 | MATCH |
| median | 71.1031 | 71.1031 | 0.000e+00 | MATCH |
| min | 42.5824 | 42.5824 | 0.000e+00 | MATCH |
| max | 88.2680 | 88.2680 | 0.000e+00 | MATCH |

**Exact agreement.** The statistics are not an artifact of either implementation.

## Is the subgroup what the claim says it is?

A correct mean over the wrong 48 rows would still look right, so the definition is asserted rather than assumed.

| Property | |
|---|---|
| every row is labelled `N1` | OK |
| every row is `is_fraud = False` | OK |
| every row is a `purchase` (not a balance inquiry) | OK |
| no row has a zero or negative monthly benefit (denominator is defined) | OK |
| every drawdown sits inside the generator's uniform(40%, 90%) draw | OK |

The last row is the structural check: `src/ebt_generator.py` draws a crossing-issuance amount as `monthly_benefit_amount * uniform(0.4, 0.9)`, parsed out of the generator rather than hardcoded here. The observed range 42.58%-88.27% is a 48-draw sample from that interval, which is why it is narrower than 40%-90% -- the published range is the sample's, not the generator's, and the two should not be confused.

## Against the claimed figures

`data/ebt_data_dictionary.md` carries the paper's sentence verbatim and is committed, so this check is self-contained in a clean checkout. The paper's own draft section is a private working file excluded by `.gitignore`; when a copy is reachable it is parsed and checked too, so the sentence actually being published is the one under test. Its absence is reported rather than counted as a failure.

| Claim source | Quantity | claimed | recomputed | |
|---|---|---|---|---|
| `data/ebt_data_dictionary.md` | N1 rows in the dataset | 339 | 339 | MATCH |
| `data/ebt_data_dictionary.md` | of those, crossing an issuance boundary | 48 | 48 | MATCH |
| `data/ebt_data_dictionary.md` | mean drawdown (% of monthly benefit) | 68.4 | 68.4 | MATCH |
| `data/ebt_data_dictionary.md` | median drawdown (%) | 71.1 | 71.1 | MATCH |
| `data/ebt_data_dictionary.md` | range, low end (%) | 42.6 | 42.6 | MATCH |
| `data/ebt_data_dictionary.md` | range, high end (%) | 88.3 | 88.3 | MATCH |
| `paper/section9_draft.md` | -- | not present in this checkout | -- | SKIPPED |
| `../civicsentra-private/section9_draft.md` | N1 rows in the dataset | 339 | 339 | MATCH |
| `../civicsentra-private/section9_draft.md` | of those, crossing an issuance boundary | 48 | 48 | MATCH |
| `../civicsentra-private/section9_draft.md` | mean drawdown (% of monthly benefit) | 68.4 | 68.4 | MATCH |
| `../civicsentra-private/section9_draft.md` | median drawdown (%) | 71.1 | 71.1 | MATCH |
| `../civicsentra-private/section9_draft.md` | range, low end (%) | 42.6 | 42.6 | MATCH |
| `../civicsentra-private/section9_draft.md` | range, high end (%) | 88.3 | 88.3 | MATCH |

Tolerance: claimed values are quoted to one decimal place, so a recomputed value must round to the claim (±0.05). Counts must be exact.

