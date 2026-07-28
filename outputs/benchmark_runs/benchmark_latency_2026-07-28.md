# CivicSentra Phase 0 -- benchmark_latency.py output
Generated 2026-07-28 01:11:31 UTC.
Method: 300 transactions sampled from data/ebt_synthetic.csv (137,080 rows total), each scored individually via scorer.score_transactions() on only the history that existed at that transaction's own timestamp (feature computation + scoring both timed; CSV read is not). Single transaction at a time -- SPEC.md §4.5, not vectorized batch processing.

## Hardware / environment
CPU: Apple M3
Platform: macOS-26.5.2-arm64-arm-64bit
CPU cores: 8
Python: 3.9.6

## Latency (ms), end-to-end per transaction, feature computation included
p50: 636.79 ms
p95: 1044.21 ms
p99: 1097.04 ms
mean: 636.81 ms   min: 81.06 ms   max: 1111.10 ms
n samples: 300

## Paper claim C1: scoring completes in under 30ms
0.0% of sampled transactions scored under 30ms. p50=636.79ms is NOT under 30ms; p95=1044.21ms is NOT under 30ms; p99=1097.04ms is NOT under 30ms.

## Known limitation: latency scales with historical volume
Correlation between transaction history size (rows preceding the scored transaction) and its own latency: r=0.997. This reference implementation is not incrementally stateful -- features.py recomputes each feature family from the full history available at scoring time on every call, rather than maintaining running per-terminal/per-household counters that a production system would keep. So a transaction scored when 130,000 rows of history already exist costs measurably more than one scored on day one. This is a real, measured property of this specific implementation, not a claim about EBT authorization latency in general -- an incrementally-stateful implementation would not show this growth. Reported here, not hidden, per CLAUDE.md Rule 1.

## Caveat (SPEC.md §4.5)
Python is not a production authorization-path language. These figures represent an upper bound that a compiled implementation would improve on, not a claim about achievable production latency.

## Raw distribution (ms), 20 evenly spaced percentiles
  p5: 221.70 ms
  p10: 285.93 ms
  p15: 320.78 ms
  p20: 371.19 ms
  p25: 432.55 ms
  p30: 485.83 ms
  p35: 521.31 ms
  p40: 576.71 ms
  p45: 596.02 ms
  p50: 636.79 ms
  p55: 678.90 ms
  p60: 722.60 ms
  p65: 778.00 ms
  p70: 811.78 ms
  p75: 875.55 ms
  p80: 893.27 ms
  p85: 922.03 ms
  p90: 967.05 ms
  p95: 1044.21 ms

## Run identity
Archive of record: outputs/benchmark_runs/benchmark_latency_2026-07-28.md (write-once; never overwritten by a later run).
outputs/benchmark_latency.md is a copy of the most recent run, kept at a stable path for citation. Cite the archive when you mean a specific run.