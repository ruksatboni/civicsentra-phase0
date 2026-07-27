# CivicSentra Phase 0 -- benchmark_latency.py output
Generated 2026-07-27 14:18:08 UTC.
Method: 300 transactions sampled from data/ebt_synthetic.csv (137,080 rows total), each scored individually via scorer.score_transactions() on only the history that existed at that transaction's own timestamp (feature computation + scoring both timed; CSV read is not). Single transaction at a time -- SPEC.md §4.5, not vectorized batch processing.

## Hardware / environment
CPU: Apple M3
Platform: macOS-26.5.2-arm64-arm-64bit
CPU cores: 8
Python: 3.9.6

## Latency (ms), end-to-end per transaction, feature computation included
p50: 640.08 ms
p95: 1039.34 ms
p99: 1088.05 ms
mean: 640.25 ms   min: 75.06 ms   max: 1097.17 ms
n samples: 300

## Paper claim C1: scoring completes in under 30ms
0.0% of sampled transactions scored under 30ms. p50=640.08ms is NOT under 30ms; p95=1039.34ms is NOT under 30ms; p99=1088.05ms is NOT under 30ms.

## Known limitation: latency scales with historical volume
Correlation between transaction history size (rows preceding the scored transaction) and its own latency: r=0.998. This reference implementation is not incrementally stateful -- features.py recomputes each feature family from the full history available at scoring time on every call, rather than maintaining running per-terminal/per-household counters that a production system would keep. So a transaction scored when 130,000 rows of history already exist costs measurably more than one scored on day one. This is a real, measured property of this specific implementation, not a claim about EBT authorization latency in general -- an incrementally-stateful implementation would not show this growth. Reported here, not hidden, per CLAUDE.md Rule 1.

## Caveat (SPEC.md §4.5)
Python is not a production authorization-path language. These figures represent an upper bound that a compiled implementation would improve on, not a claim about achievable production latency.

## Raw distribution (ms), 20 evenly spaced percentiles
  p5: 223.53 ms
  p10: 271.43 ms
  p15: 327.16 ms
  p20: 367.98 ms
  p25: 438.39 ms
  p30: 484.12 ms
  p35: 530.08 ms
  p40: 586.07 ms
  p45: 606.84 ms
  p50: 640.08 ms
  p55: 691.77 ms
  p60: 739.06 ms
  p65: 779.61 ms
  p70: 817.79 ms
  p75: 866.78 ms
  p80: 893.68 ms
  p85: 923.63 ms
  p90: 985.83 ms
  p95: 1039.34 ms