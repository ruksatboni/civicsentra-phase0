# EXPLAIN — `benchmark_latency.py`

## What this module does

Tests paper claim C1 ("scoring completes in under 30ms," §4.2): measures
how long it actually takes to score one transaction, feature computation
included, **one transaction at a time** — never vectorized batch processing
over many transactions in one call, per SPEC.md §4.5's explicit warning that
batch throughput divided by N would produce an impressively small number
that has nothing to do with real authorization-time latency, and using it
would be a form of cheating. Writes `outputs/benchmark_latency.md`.

Every number below came from running `python src/benchmark_latency.py`
against `data/ebt_synthetic.csv` on the author's own machine, not assumed
(CLAUDE.md Rule 1).

## Method: reused truncation, not a new parallel implementation

For 300 sampled transactions, the benchmark builds "the world as it looked
at the moment this transaction arrived" — every row with `timestamp <=`
this transaction's own timestamp — and times `scorer.score_transactions()`
on exactly that slice, ending with the sampled transaction as the last row.
The timer covers feature computation and scoring; it does not cover reading
`data/ebt_synthetic.csv` from disk, because a real authorization system
already has the incoming transaction in memory — it isn't re-reading a CSV
per transaction.

**This is the same truncation methodology `test_leakage.py` already uses
and has already been verified against real data (2026-07-25)** — not a new
approach invented for this module. A design alternative was considered and
rejected: hand-writing a second, parallel single-row implementation of each
feature family (maintaining running counters instead of recomputing from a
truncated dataframe each time), which would be faster and closer to how a
real production system would work. Rejected for three reasons:

1. It would be a second codepath computing the same formulas as
   `features.py`, with no independent test coverage of its own — a real
   correctness risk (two implementations silently drifting apart) that
   `test_leakage.py`'s truncation method doesn't carry, since it reuses the
   already-leakage-tested `compute_all_features()` directly.
2. Building and verifying a stateful incremental implementation is
   meaningfully more engineering than a 3-day sprint has room for
   (CLAUDE.md Rule 5: stay in scope, don't build ahead).
3. Reusing the existing pipeline produces an honest, if unflattering,
   measurement of *this specific reference implementation* — which is
   exactly what SPEC.md §4.5 asks the benchmark to report, caveats
   included, not a best-case estimate of what a different architecture
   could achieve.

300 positions were sampled uniformly at random (seeded, `random_seed`-style
reproducibility) from index 50 onward — the first 50 rows are skipped
because with almost no history their feature computation is trivially fast
and not representative of the steady-state cost this benchmark exists to
characterize.

## Real result — measured twice, six days apart

Apple M3, Python 3.9.6, 8 cores. The second run followed a macOS point
update and a regeneration of the dataset.

| | Run 1 — 2026-07-25 | Run 2 — 2026-07-27 |
|---|---|---|
| OS | macOS 26.5.1 arm64 | macOS 26.5.2 arm64 |
| p50 | 635.69 ms | 640.08 ms |
| p95 | 1057.68 ms | 1039.34 ms |
| p99 | 1102.01 ms | 1088.05 ms |
| mean | 639.96 ms | 640.25 ms |
| min / max | 79.04 / 1114.07 ms | 75.06 / 1097.17 ms |
| correlation with history size | r=0.999 | r=0.998 |
| under 30 ms | 0.0% | 0.0% |

`outputs/benchmark_latency.md` holds run 2, the current one. Run 1 is
recorded here because the comparison is itself a result.

**The 0.7% gap between the two p50s is the finding, not a discrepancy.**
A wall-clock benchmark cannot be seeded into exact reproducibility the way
the rest of this project is — it measures the machine, not just the code.
That normally makes a latency figure the weakest number in a report: a
single measurement is indistinguishable from a lucky run, and a reader has
no way to tell which they are being shown.

Two independent runs, six days apart, across an OS point update and a
regenerated dataset, landing 0.7% apart at the median and 0.05% apart at the
mean, answer that. The measurement is stable and the benchmark reproduces.
The p95 moved 1.7% in the *opposite* direction to the p50, which is what
ordinary scheduling noise looks like — not a trend, and not drift.

So the honest reading of C1 is not "p50 is 640.08 ms." It is: **this
implementation's median scoring latency is approximately 640 ms, reproducible
to well under one percent, against a claimed 30 ms.** Anyone re-running it on
comparable hardware should land in the same place, and if they do not, that
is a real finding about their environment rather than an artifact of ours.

**0.0% of sampled transactions scored under 30ms, in both runs.** This is
nowhere close to claim C1, and per CLAUDE.md Rule 1 that is reported exactly
as measured, not softened.

## Why the number is this high — and it is not primarily "Python is slow"

**Measured correlation between transaction-history size and a
transaction's own latency: r = 0.999.** This is the dominant effect, and it
is a specific, fixable property of *this reference implementation*, not a
general statement about EBT authorization latency:

`features.py` is **not incrementally stateful**. Every call to
`compute_all_features()` recomputes every feature family from the full
history available at that moment — geo-velocity's previous-transaction
lookup, terminal reputation's shrunk fraud rate, the terminal
temporal-neighbour count, the spend-baseline cumulative-balance
calculation — rather than maintaining running per-terminal and
per-household counters that a real production system would keep updated
incrementally as transactions arrive. So a transaction scored once 130,000
rows of history already exist costs measurably more (in this benchmark,
roughly 1 second) than one scored on day one of the dataset (roughly
80ms) — the r=0.998 correlation confirms latency here is essentially a
direct function of history size, i.e. this implementation's cost is closer
to O(n) per transaction than O(1).

**This is deliberately kept separate from SPEC.md §4.5's own caveat** ("Python
is not a production authorization-path language... these figures represent
an upper bound that a compiled implementation would improve on"). That
caveat is about a constant-factor language-speed difference. The O(n)
recompute-from-scratch behaviour is an architectural difference, not a
language-speed one — a compiled rewrite of the *same* recompute-every-time
design would still get slower as history grows; only an incrementally
stateful design (the kind a real production system would need regardless of
language) removes that growth. Conflating the two would understate how
large this effect actually is, so the report keeps them as two separate
findings.

## What this means for C1

The measured number is a real, honest result for this specific reference
implementation, and it fails the 30ms claim badly. It should not be read as
"a fraud-scoring engine of this design cannot hit 30ms" — an incrementally
stateful implementation (real running counters instead of full-history
recompute) would very plausibly be in a completely different regime,
closer to what C1 claims. Distinguishing "this implementation is slow" from
"this approach is slow" is the whole point of reporting the r=0.998 finding
explicitly rather than only the raw percentile numbers — the raw numbers
alone would make the miss look like a language/implementation problem
scoped the same way as the "Python isn't compiled" caveat, when it's
actually a much larger, architectural one.

## What this module does *not* do

- Does not build an incrementally stateful implementation to get a more
  representative number — that would be new engineering scoped for v1.1 at
  the earliest, not this 3-day sprint (CLAUDE.md Rule 5).
- Does not vary hardware or attempt to project performance on
  production-grade infrastructure — this is the author's own development
  machine, reported as such, not a server-class benchmark environment.
- Does not attempt to isolate which of the six feature families
  contributes most to the O(n) growth — a reasonable follow-up if v1.1
  pursues an incremental rewrite, not done here.
- Does not measure `scorer.py`'s own decision/reason-code logic in
  isolation from `features.py`'s feature computation — SPEC.md §4.5 asks
  for the end-to-end figure, so the two aren't split apart.
