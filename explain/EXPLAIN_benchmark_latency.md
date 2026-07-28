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
against `data/ebt_synthetic.csv` on the author's own machine — measured,
not assumed or estimated.

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
   (out of scope for this sprint: build what is specified, not ahead of it).
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

## Real result — measured four times over four days

Apple M3, Python 3.9.6, 8 cores. Run 2 followed a macOS point update and a
regeneration of the dataset. Runs 3 and 4 are on the same OS as run 2.

| | Run 1 — 2026-07-25 | Run 2 — 2026-07-27 | Run 3 — 2026-07-28 | Run 4 — 2026-07-28 |
|---|---|---|---|---|
| OS | macOS 26.5.1 arm64 | macOS 26.5.2 arm64 | macOS 26.5.2 arm64 | macOS 26.5.2 arm64 |
| p50 | 635.69 ms | 640.08 ms | 636.79 ms | 637.16 ms |
| p95 | 1057.68 ms | 1039.34 ms | 1044.21 ms | 1037.45 ms |
| p99 | 1102.01 ms | 1088.05 ms | 1097.04 ms | 1083.36 ms |
| mean | 639.96 ms | 640.25 ms | 636.81 ms | 639.55 ms |
| min / max | 79.04 / 1114.07 ms | 75.06 / 1097.17 ms | 81.06 / 1111.10 ms | 76.43 / 1100.05 ms |
| correlation with history size | r=0.999 | r=0.998 | r=0.997 | r=0.997 |
| under 30 ms | 0.0% | 0.0% | 0.0% | 0.0% |
| machine record | **none — overwritten** | `benchmark_runs/benchmark_latency_2026-07-27.md` | `benchmark_runs/benchmark_latency_2026-07-28.md` | `benchmark_runs/benchmark_latency_2026-07-28T02-26-36Z.md` |

Run 4 was not run to get a better number — it was run to regenerate this
module's output after a wording change, and its figures are reported because
they exist, not because they were wanted. It also exercised the write-once
archive: the dated filename was already taken by run 3, so the archive fell
back to a second-resolution name rather than overwriting it, which is the
behaviour that was supposed to exist when run 2 destroyed run 1.

**On run 1's missing artifact, stated plainly.** Run 2 overwrote
`outputs/benchmark_latency.md`, so run 1's figures survive only as the prose
in this table — hand-transcribed, with no file behind them. That is exactly
the failure this project exists to avoid, and it is why the stability claim
below rests on **runs 2, 3 and 4, which all have machine records**, with run 1
cited as historical prose rather than as evidence. `benchmark_latency.py` now
writes a write-once dated archive under `outputs/benchmark_runs/` before it
touches the stable filename, and refuses to overwrite an existing archive, so
no future run can destroy its predecessor.

**The spread across runs is the finding, not a discrepancy.** A wall-clock
benchmark cannot be seeded into exact reproducibility the way the rest of this
project is — it measures the machine, not just the code. That normally makes a
latency figure the weakest number in a report: a single measurement is
indistinguishable from a lucky run, and a reader has no way to tell which they
are being shown.

Four runs over four days, across an OS point update and a regenerated
dataset, answer that:

- **p50 spans 635.69–640.08 ms — 0.69% between the extremes.** The three runs
  with machine records span 0.52%.
- **mean spans 636.81–640.25 ms — 0.54%.**
- p95 spans 1.95% and p99 1.72%, both wider than the median and **not moving
  in the same direction as it** run to run. That is what ordinary scheduling
  noise looks like: the tail is noisier than the middle, and nothing trends.
- The history-size correlation reproduces at r=0.997–0.999 every time.

A fourth run did not widen the spread at the median: the extremes are still
run 1 and run 2. That is the useful thing about repeating a measurement — the
range stopped moving.

So the honest reading of C1 is not "p50 is 637.16 ms." It is: **this
implementation's median scoring latency is approximately 635–640 ms,
reproducible to under one percent across four runs, against a claimed 30 ms.**
Anyone re-running it on comparable hardware should land in the same place, and
if they do not, that is a real finding about their environment rather than an
artifact of ours.

**0.0% of sampled transactions scored under 30ms, in all four runs.** This is
nowhere close to claim C1, and it is reported exactly as measured, not
softened toward the claim.

## Why the number is this high — and it is not primarily "Python is slow"

**Measured correlation between transaction-history size and a
transaction's own latency: r = 0.997** (run 4, the current run; 0.997 in run 3,
0.998 in run 2, 0.999 in run 1 — the effect reproduces in all four). This is the
dominant effect, and it
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
roughly 1 second — run 4 max 1100.05 ms) than one scored on day one of the
dataset (run 4 min 76.43 ms) — the r=0.997 correlation confirms latency is a
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
"this approach is slow" is the whole point of reporting the r≈0.998 finding
explicitly rather than only the raw percentile numbers — the raw numbers
alone would make the miss look like a language/implementation problem
scoped the same way as the "Python isn't compiled" caveat, when it's
actually a much larger, architectural one.

## What this module does *not* do

- Does not build an incrementally stateful implementation to get a more
  representative number — that would be new engineering scoped for v1.1 at
  the earliest, not this 3-day sprint — build what is specified, not ahead
  of it.
- Does not vary hardware or attempt to project performance on
  production-grade infrastructure — this is the author's own development
  machine, reported as such, not a server-class benchmark environment.
- Does not attempt to isolate which of the six feature families
  contributes most to the O(n) growth — a reasonable follow-up if v1.1
  pursues an incremental rewrite, not done here.
- Does not measure `scorer.py`'s own decision/reason-code logic in
  isolation from `features.py`'s feature computation — SPEC.md §4.5 asks
  for the end-to-end figure, so the two aren't split apart.
