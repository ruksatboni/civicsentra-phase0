# CivicSentra Phase 0 -- geo-velocity 5-minute floor, justification recomputed
Generated 2026-07-28 01:36:56 UTC by `src/geo_floor_justification.py`.

Recomputes every figure behind `min_elapsed_minutes_to_score: 5` in config.yaml, over both datasets, and checks them against the values claimed in config.yaml's own comment. Impossible-speed threshold: 621.4 mph.

**All 11 claimed figures MATCH.** The floor's justification is reproducible from the committed datasets.

## Pair definition

A pair is a household's consecutive transactions -- each row against its own household's immediately preceding row. **Legitimate** means both endpoints are ordinary legitimate: `is_fraud` false *and* no `fraud_pattern`, so N1 and N2 rows are excluded as well as fraud. Pairs with zero elapsed time are excluded from the legitimate-pair denominator, because speed is undefined there; they are counted separately as same-timestamp pairs. The figures are sensitive to this definition, so it is stated rather than left implicit.

## Half 1 -- the floor is needed

| | primary | realistic |
|---|---|---|
| rows | 137,080 | 2,598,309 |
| legitimate consecutive pairs (elapsed > 0) | 130,631 | 2,480,799 |
| read as impossible travel with NO floor | 6 | 49 |
| as a share of legitimate pairs | 0.0046% | 0.0020% |
| largest elapsed gap among them | 1.0 min | 2.0 min |

Every one of these pairs sits at an elapsed gap of 1.0 minute(s) or less in the primary dataset (2.0 in the realistic one) -- which is what 'minute-resolution rounding artifact' means concretely: two independent ordinary trips landing in adjacent rounded minutes at different nearby terminals, not travel. Any floor above that gap removes all of them.

## Half 2 -- the floor is free

The cost of a floor is any real fraud it declines to score. If a fraud row would have tripped the impossible-speed rule at a gap under the floor, the floor is hiding a detection.

| | primary | realistic |
|---|---|---|
| fraud rows tripping impossible-speed with NO floor | 1 | 3 |
| their elapsed gaps (min) | [15.0] | [20.0, 28.0, 46.0] |
| patterns | {'P5': 1} | {'P5': 2, 'P6': 1} |
| **of those, under the 5-minute floor** | **0** | **0** |

**0 of 4.** Every fraud row that would ever trip the impossible-speed rule sits well above the floor, so the floor suppresses no detection in either dataset. Real cloned-card drains show up far apart *and* slow enough to be real travel time -- not close-together-and-instant, which is the signature of the rounding artifact the floor exists to remove.

Cost on the legitimate side: the floor declines to score 447 legitimate pairs in the primary dataset (0.34% of them).

## Same-timestamp pairs (elapsed = 0)

Folded into the same floor rather than special-cased as automatic hard blocks. That decision rests on how many of them are legitimate:

| | primary | realistic |
|---|---|---|
| same-timestamp, different-terminal pairs | 36 | 725 |
| of those, both endpoints ordinary legitimate | 35 | 705 |
| of those, involving a fraud row at either end | 0 | 0 |

**Legitimate here means both endpoints ordinary legitimate — N1 and N2 excluded, the same definition used for the pair denominator above.** The remainder are not fraud: as the last row shows, **zero** same-timestamp pairs in either dataset involve a fraud row at all. The pairs not counted as ordinary-legitimate are N1/N2 rows, which are themselves legitimate. That makes the design decision stronger than the headline ratio suggests: hard-blocking every same-timestamp pair would have blocked only legitimate transactions, and caught nothing.

## Against the figures claimed in config.yaml's comment

| Quantity | config.yaml comment | recomputed | |
|---|---|---|---|
| legitimate pairs, primary (denominator) | 130631 | 130631 | MATCH |
| impossible-travel pairs with no floor, primary | 6 | 6 | MATCH |
| that as a share of legitimate pairs (%) | 0.0046 | 0.0046 | MATCH |
| a 2-minute floor removes all of them | 6 | 6 | MATCH |
| legitimate pairs the 5-minute floor declines to score (%) | 0.34 | 0.34 | MATCH |
| fraud rows tripping impossible-speed, primary | 1 | 1 | MATCH |
| fraud rows tripping impossible-speed, realistic | 3 | 3 | MATCH |
| same-timestamp diff-terminal pairs, primary | 36 | 36 | MATCH |
| of those, legitimate, primary | 35 | 35 | MATCH |
| same-timestamp diff-terminal pairs, realistic | 725 | 725 | MATCH |
| of those, legitimate, realistic | 705 | 705 | MATCH |

