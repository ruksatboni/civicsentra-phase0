# EXPLAIN — `features.py`

## What this module does

For every transaction in `data/ebt_synthetic.csv`, it computes six risk
signals ("feature families"), each turned into a 0–1 sub-score, using only
information that would have been available at the moment that transaction
arrived — no peeking at what happens later in the file, and no peeking at
the dataset's own eventual statistics. `src/scorer.py` (next) combines these
sub-scores into the 0–100 risk score and allow/step-up/block decision.

Every number below was produced by running `python src/features.py` and
`python src/test_leakage.py` against `data/ebt_synthetic.csv`, not assumed.

## The six families

### 1. Geo-velocity (the one hard-override rule)

Implied travel speed (mph) between a household's consecutive card-present
transactions. This is the **only** feature allowed to BLOCK a transaction on
its own, regardless of every other signal — the author's core design principle
(2026-07-25): a false block on EBT means a person can't buy food that day,
often with no second card, so the one rule allowed to act alone has to be
one where being wrong is close to physically impossible, not just unlikely.

- **0 contribution** at or below 100 mph (`ordinary_max_mph`) — data-derived:
  at a 5-minute floor (see below), 99.99% of genuinely legitimate
  consecutive-transaction pairs imply under 94.5 mph; the true max is 209 mph.
  100 mph leaves headroom above real legitimate travel before any
  contribution starts.
- **Ramps linearly** from 100 mph to 621.4 mph.
- **Saturates to 1.0 (hard BLOCK) at 621.4 mph** (1,000 km/h) — physics-
  derived, not domain judgment: commercial aircraft cruise around 900 km/h,
  so anything faster is a physical impossibility regardless of context
  (SPEC.md §4.2).

**Three things caught by testing this against real data before trusting it
(all in `PROGRESS.md`, 2026-07-25):**

1. **A 5-minute minimum-elapsed-time floor exists because of a measured
   rounding artifact, not a domain figure.** With no floor, 6 of 130,631
   genuinely legitimate consecutive-transaction pairs (0.0046%) read as
   physically-impossible travel — two independent ordinary trips landing one
   minute apart at different nearby terminals, an artifact of minute-
   resolution timestamps, not real behaviour. Verified the floor costs
   nothing against real fraud: only 1 (primary dataset) and 3 (realistic
   dataset) fraud rows would ever trip the impossible-speed rule at all, and
   zero of those four sit under 5 minutes elapsed — real cloned-card drains
   are far *and* slow-enough-to-be-real-travel-time, not
   close-together-and-instant.
2. **Same-timestamp transactions are not a special case.** The original
   design treated exactly-simultaneous timestamps at different terminals as
   an automatic hard block (zero elapsed time makes speed undefined, not
   just fast). Checked against data: 35 of 36 such pairs in the primary
   dataset (705 of 725 in the realistic dataset) are legitimate — two
   independent ordinary transactions coinciding in the same rounded minute,
   not evidence of anything. Folded into the same 5-minute floor instead of
   special-cased; there is no code path where elapsed=0 behaves differently
   from elapsed=4 minutes.
3. **Shadow-mode collateral trigger — reported as both a limitation and a
   finding, not fixed.** 3 of the 4 impossible-travel triggers in the
   primary dataset are not the fraud row itself but the *victim's own next
   legitimate transaction*, immediately following an out-of-state drain on
   their own card. The check compares the legitimate purchase's location
   against the *fraudster's* location, not the victim's own prior movement,
   and cannot tell the difference from historical data alone. **Not fixed:**
   a fix would require using `is_fraud` ground truth to decide what counts
   as the "real" previous transaction, which is leakage (SPEC.md's own
   leakage warning) and also unbuildable in a real system — a production
   authorization pipeline does not know transaction N-1 was fraud at the
   moment N-1 happens. Reported both ways (`outputs/evaluate_metrics.md`
   section 6 carries the measured counts):
   - *Limitation:* pure historical velocity can collaterally hard-block a
     fraud victim's own next legitimate transaction (0.55% of the primary
     dataset's 547 fraud events; 0% of the realistic dataset's 518 fraud
     events — small-n, reported with a 95% CI per SPEC.md §4.4).
   - *Finding:* the same trigger is a **lagging detector** of the compromise
     geo-velocity missed at the moment of the drain — in shadow mode, where
     nothing is actually blocked, this becomes a detection signal one
     transaction late, not merely a false positive.
   - *v1.1 design implication (not built now):* in live mode, "impossible
     travel following a same-card out-of-state transaction" should flag the
     **card** for review rather than hard-blocking the **current** purchase
     — surfaces the compromise without denying the victim food for
     something the fraudster did.

### 2. Home-location plausibility

Distance from the household's registered home to the terminal, as an
**interaction** with hour-of-day (not two additive features — the same
distance scores higher at 2am than 2pm). Grounded in the author's real
banking casework: comparing a transaction against a broad zone around the
cardholder's *registered home*, not a whitelist of previously-visited
locations (a whitelist would falsely flag every first visit to a new store).

- **Zone radius by `locality_class`: urban 3mi, suburban 5mi, rural 9mi.**
  Data-derived from the actual home-to-terminal distance of ordinary
  legitimate rows (95th percentile: urban 2.5mi, suburban 4.8mi, rural
  8.3mi), with headroom for genuine outlier trips. **Correction made while
  building this:** the zone edges are *not* the generator's household-to-hub
  placement radius (urban 0–5/suburban 5–15/rural 15–40mi) — that parameter
  governs where households are populated relative to a regional hub, not how
  far they actually shop from home. Reusing it would have made the rural
  zone four times looser than real shopping behaviour.
- Within the zone: 0 contribution. Up to 2x the zone edge: 0.35 base
  (`near_zone_subscore`). Beyond 2x: 0.75 base (`far_zone_subscore`).
- Between 00:00–05:00, the base contribution is multiplied by 1.5, capped at
  1.0. A transaction inside the normal zone still scores 0 regardless of
  hour — there's nothing for the hour interaction to amplify.
- Never blocks alone: weight is 0.25, so even a saturated (1.0) sub-score
  caps the weighted contribution at 25, below the 50-point block line.

Real check: the five rows the self-test prints from beyond 2× the zone radius
are all P5/P6 fraud, at 283.55, 594.55, 690.57, 720.84 and 748.41 miles from
home, correctly landing at or near the maximum sub-score. These are a sample
of qualifying rows, not the five farthest — the actual maximum home distance
in the dataset is 760.41 miles (`TXN00062284`, P5).

### 3. Terminal temporal-neighbour (before-only, diverging from SPEC.md's text)

Count of *other* transactions at the same terminal shortly before this one.
Grounded in the author's real investigative method: a single disputed
transaction told them little, but the neighbouring transactions at the same
terminal often did.

**SPEC.md §4.2 describes this feature as bidirectional** ("the transaction
immediately before and after, in both directions"). Built it **before-only**
instead: "after" requires a transaction that hasn't happened yet at the
moment the scored transaction arrives — that is leakage by SPEC's own
definition, and would fail `test_leakage.py`. Before-only is what a real
authorization system could actually compute, and it still catches a burst:
later transactions in a cluster accumulate visible history even though the
first one in the cluster doesn't.

- **Window: 15 minutes. Flag threshold: 2+ prior neighbours.** Data-derived:
  95.33% of rows have zero prior same-terminal neighbours within 15 minutes,
  4.48% have one, only 0.19% have two or more — "2 or more" is where
  ordinary terminal traffic essentially stops.
- Sub-score ramps with the actual count (2 → 0.25, up to 5+ → 1.0) rather
  than a flat flag, so a bigger burst scores higher.

**Measured limitation, reported not tuned away (2026-07-25):** this
feature's sub-score is non-zero on 14.10% of P8 rows (11 of 78 — PIN-guessing
attempts are minutes apart by construction) and 1.28% of P3 (1 of 78), but
**0% of P6** (terminal-clustering cashouts).

> **What this 14.10% is, and what it is not** (added 2026-07-27, after three
> different P8 percentages appeared across this document and the working
> notes). Three separate quantities were being quoted, and they do not
> conflict — they measure different things:
>
> | Figure | Exactly what it measures | Computed by | Status |
> |---|---|---|---|
> | **14.10%** (11/78) | P8 rows where *this feature's* sub-score is non-zero — i.e. the terminal temporal-neighbour signal fired at all, whether or not it changed the decision | `features.py`, `terminal_neighbour_subscore_points` column | **current** — verified against `data/ebt_scored.csv` 2026-07-27 |
> | **25.64%** (20/78) | P8 rows the system actually *detects* (`decision != allow`). Identical set to the rows where the balance-probe policy rule fires, and identical again to the 20 `purchase` rows | `evaluate.py` §5, cross-checked by `verify_independent.py` | **current** — verified 2026-07-27 |
> | **42%** | share of P8 rows a **bidirectional** ±15-minute neighbour window would have flagged | a pre-implementation prototype that no longer exists in the repository | **WITHDRAWN** |
>
> **The 42% figure is withdrawn and must not be quoted.** It was measured on a
> prototype that looked ±15 minutes around the scored transaction, both
> before *and after* it. Looking forward is future information at scoring
> time, so the shipped feature looks **before only** (see the leakage note in
> this family above, and `src/test_leakage.py`). Looking backwards alone finds
> fewer neighbours, which is why the rate fell from 42% to 14.10%. The
> prototype was never committed and no code in this repository produces 42%.
> Confirmed 2026-07-27 by grep across every `.md`, `.py` and `.yaml` in the
> repository: the string appears only in this passage, which exists to
> withdraw it.
>
> **A structural fact that makes the P8 numbers easier to read.** P8 episodes
> are generated as several `balance_inquiry` rows (the PIN guesses) followed
> by one `purchase` row (the drain). The 78 P8 rows are 58 inquiries and 20
> purchases — and the 20 detected rows are *exactly* the 20 purchases.
> **Not one of the 58 PIN-guessing attempts is detected.** The system does not
> detect PIN guessing at all; it detects the drain that follows it, one step
> too late to prevent the loss. The 25.64% "P8 detection rate" is therefore
> better read as "100% of the drains, 0% of the attack that produced them."
>
> **The uncomfortable part, measured 2026-07-27:** the 20 P8 rows this system
> detects are *exactly* the 20 where the balance-probe rule fires — an
> identical set, not an overlap. Of the 11 P8 rows where terminal-neighbour
> fires, 4 are detected, and all 4 also fired balance-probe. Removing the
> probe rule would drop P8 detection to zero. **Terminal temporal-neighbour
> contributes no P8 detections of its own**, because at weight 0.10 its
> maximum possible contribution is 10 points against a 20-point step-up
> line — it cannot reach an alert without stacking. It is currently a
> corroborating signal only, on this dataset. That is a limitation of the
> weight, not of the idea, and it is reported rather than adjusted, since
> re-weighting a feature to make it look productive against data whose fraud
> we injected would be circular.

P6 is generated over a 48-hour window because the author's domain
judgment is that real cashout bursts spread over hours to days as a
fraudster works through a stack of cloned cards, not minutes. **We did not
tighten P6's generation window to make it detectable by this feature** —
that would be tuning the data to flatter the detector. Burst-clustering
(P8) and slow-burn clustering (P6) are genuinely different signatures;
graph-based ring detection (v1.1, deferred) is the intended mechanism for
the latter, not this feature.

### 4. Terminal reputation, Bayesian shrinkage

Rolling historical fraud rate per terminal, shrunk toward the population
average so a terminal with 2 transactions and 1 fraud doesn't score as 50%
risk: `shrunk_rate = (n·observed_rate + m·global_rate) / (n + m)`.

- **m = 50 pseudo-transactions.** Data-derived: at the 18 terminals later
  found compromised, median prior (pre-compromise) transaction history was
  49 rows — m=50 means a terminal's own emerging signal reaches equal
  weight with the global prior right around the point real compromise
  typically begins in this dataset.
- **Saturation at a 10% shrunk rate.** The highest shrunk rate observed
  anywhere in the dataset is 13.6%; 10% saturates the sub-score before that
  true maximum without being reachable by an average terminal.
- **A leakage bug was caught and fixed here by `test_leakage.py`
  (2026-07-25) — the most important result this test produced.** The raw
  shrunk rate was correctly point-in-time (built from an expanding
  cumulative sum, using only strictly-prior rows). But the sub-score's
  normalization baseline used `df["is_fraud"].mean()` — the mean of
  *whichever dataframe got passed to the function*. Run on the full 137,080
  rows that's one number; run on any earlier prefix of the data (simulating
  "the world as it looked at that moment") it's a different number — so every
  transaction's sub-score silently depended on the dataset's *eventual*
  average fraud rate, which hadn't happened yet at scoring time for any
  transaction before the last one. `test_leakage.py` caught this directly:
  recomputing on a truncated dataset gave a different sub-score for the same
  transaction on 11 of 34 sampled rows. **Fixed** by using each row's own
  point-in-time expanding global rate as the baseline instead of a
  dataset-wide constant; all 34 sampled rows pass after the fix. This is
  concrete proof of exactly the danger SPEC.md's leakage warning describes:
  "the mistake is invisible in the metrics" until you specifically test for
  it, because the raw signal (shrunk_rate) looked completely correct on its
  own.

### 5. Spend-baseline deviation

Percentage of remaining balance this transaction draws, combined with
days-since-issuance — not a z-score on raw dollar amount, because EBT
spending isn't open-ended: a household draws down a fixed monthly benefit on
a predictable curve.

- Remaining balance is tracked as each household's **actual** prior spend
  this benefit cycle (point-in-time cumulative sum, reset at issuance), not
  the generator's internal `estimate_remaining_balance()` curve. A real EBT
  authorization system knows the exact ledger balance in real time, so using
  the true point-in-time balance is more accurate, not a shortcut.
- **Under 40% of remaining balance: 0 contribution.**
- **40–70%: step-up, ramping 0→0.6, scaled by a day-in-cycle factor** from
  0.7x (day 0, when a big draw is expected) to 1.0x (day 30, when it isn't)
  — "a big draw on day 2 is more normal than the same draw on day 20."
- **70%+: saturates to 1.0** ("strong step-up") regardless of day-in-cycle.
- **Verified 2026-07-25, before any code was written:** a transaction at 75%
  with nothing else present scores exactly 25 (weight 0.25 × sub-score 1.0 ×
  100) — step-up, not block. Confirmed computationally after building the
  feature: `pct_of_remaining_balance=0.750, spend_baseline_subscore=1.000`.
  This is what protects the 48 legitimate crossing-issuance-boundary N1
  cases from being denied rather than merely challenged.
- Real check against actual P4 (issuance-day drain) rows: 85.7%, 96.3%, and
  90.2% of remaining balance, 1.2–3.8 hours after issuance — all correctly
  saturate to sub-score 1.0.

### 6. EBT policy rules

Three discrete rule checks, combined as the **max** of whichever fire (not
summed — these are policy triggers, not a continuous measurement). Governing
principle, same as everywhere else in the scorer: policy rules **raise**
suspicion and must **stack** — only geo-velocity's impossible-travel case
blocks alone (family 1 above); at weight 0.10 against a 50-point block line,
no policy rule can reach block even saturated (max contribution 10 points).
The author set all three values directly (2026-07-25), ranked by how strongly each
indicates fraud versus how often it fires on legitimate behaviour:

1. **Out-of-state: `terminal_state != home_state` → 0.4** (lowered from an
   earlier 0.5 default). A real signal, but legitimately common — travel,
   family, relocation — and it overlaps with N2 legitimate third-party use
   (§3.3). The author does not want out-of-state alone routinely pushing people
   toward step-up, so it's kept modest: it contributes and stacks, rather
   than dominating. Real check: fires on 100% of P5 rows (out-of-state by
   construction) and 75.6% of P6 rows (cashout terminal chosen from any of
   the three synthetic states, so roughly 2/3 land out-of-state by chance).

2. **Issuance-day fast drain: within 6 hours of this cycle's issuance *and*
   draws ≥70% of remaining balance → 0.8.** The author's strongest policy signal,
   correctly the highest of the three. **Set in full knowledge that this
   rule also fires on the 48 legitimate store-and-forward
   crossing-issuance-boundary N1 cases (§3.3)** — that collision is real,
   expected, and a deliberate accepted trade-off, not an oversight:
   - At 0.8 sub-score × 0.10 weight, this rule *alone* contributes 8 points
     — step-up, not block. A legitimate crossing case is challenged and
     proceeds; it is not denied.
   - Genuine issuance-day drains (P4) stack with other signals — out-of-
     state, impossible travel, compromised-terminal neighbour — to reach
     block. So real fraud is still caught via stacking, while legitimate
     crossing cases pay only a survivable step-up, not a denial.
   - **Measured, 2026-07-25 (`evaluate.py` section 7):** of the 48
     crossing-boundary cases, **48/48 = 100% receive step-up, 0% are
     blocked** (95% CI [92.59%, 100%] — n<200, so the interval is reported
     per SPEC.md §4.4's small-subgroup rule). The trade-off cost is exactly
     what it was designed to be: every legitimate crossing transaction is
     challenged, and not one is denied.
   - Real check: fires on exactly 100% of P4 rows, matching how P4 was
     generated.

3. **Balance-probe-immediately-before: a purchase directly preceded (≤30
   minutes) by this same household's own balance inquiry → 0.45** (lowered
   from an earlier 0.6 default). A balance inquiry before a purchase is
   common, unremarkable legitimate behaviour on its own — people check
   balances. Its real predictive power is in the *sequence*
   (probe-then-immediate-drain), but this rule only sees the probe in
   isolation, so the author wants it to nudge, not shout. Real check: fires on
   48.7% of P3 rows and 25.6% of P8 rows — roughly half of P3's rows,
   because P3 generates *two* rows per episode (the probe itself and the
   drain), and only the drain (the purchase-side row) is eligible to
   trigger this rule; the probe row can't flag itself. Same reasoning
   applies to P8's lower rate (multiple probe attempts, one drain).

Never blocks alone: weight 0.10. The 0.4/0.8/0.45 values themselves are
The author's direct domain judgment, not data-derived — the "fires on X% of
pattern Y" figures above are measured *consequences* of those judgment
calls, not their source.

## The leakage test (`src/test_leakage.py`)

Run: `python src/test_leakage.py`. Method: for 34 sampled real transactions
(one per fraud pattern, all four geo-velocity hard-override rows, three
first-transaction-per-household edge cases, three terminal-neighbour-
clustered rows, plus 15 random rows), truncate the dataset to only rows with
`timestamp <= that transaction's own timestamp`, recompute every feature on
the truncated data, and assert the sampled transaction's own feature values
are identical to the full-dataset computation. If any feature secretly used
a later row, truncating would change its value — this is a direct test, not
an inspection of the code.

**First run found a real leakage bug** (terminal reputation's normalization
baseline, described above) — 11 of 34 rows failed. Fixed, re-ran: **34 of
34 pass.**

## Known limitations, all deliberately not engineered away

- **Terminal reputation assumes prior fraud is knowable at the time it's
  used**, i.e. it uses `is_fraud` for strictly-earlier transactions as
  though those labels are already confirmed by the time a later transaction
  arrives. This dataset has no separate "confirmed date" distinct from
  "occurred date," so "earlier in time" is used as a proxy for "already
  known." A real system's reputation signal would lag further behind actual
  compromise by however long fraud confirmation takes (disputes,
  investigation) — this is a simplifying assumption for Phase 0, not
  modeled, and is different from the leakage the test above checks for
  (using a *future row*, not an *unconfirmed label*).
- **Terminal temporal-neighbour catches P8, not P6** — a real, reported
  finding, not a bug (see family 3 above).
- **Geo-velocity's shadow-mode collateral trigger** — reported as both a
  limitation and a finding, not fixed (see family 1 above).
- **`terminal_temporal_neighbour`'s per-terminal loop is O(n) per terminal
  with a Python-level inner loop**, not fully vectorized. Runs in under a
  second on the 137,080-row primary dataset; not yet benchmarked on the
  2.6M-row realistic dataset. If the Day 2 robustness pass on that file is
  slow, this is the function to optimize first — not urgent for now.
- **Every breakpoint sourced as "domain judgment, not data-derived"** (home-
  location zone bands' near/far sub-score values, the spend-baseline
  percentage bands, the EBT policy rule sub-scores) came from the author directly
  and is labelled as such in `config.yaml` — these are not measured
  figures and should be defended as expert judgment, not evidence.
