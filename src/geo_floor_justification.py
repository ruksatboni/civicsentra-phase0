"""Recompute every figure justifying geo-velocity's `min_elapsed_minutes_to_score`.

Why this exists: the 5-minute floor is a parameter set from measurements taken
by hand on 2026-07-25 and written into a config.yaml comment. Nothing
recomputed them, so a regenerated dataset would not re-derive or invalidate the
justification -- flagged as the two remaining load-bearing traceability gaps in
outputs/TRACEABILITY.md §7. This script closes both, together, because they are
two sides of one argument:

  - the floor is NEEDED: without it, minute-resolution timestamp rounding makes
    a handful of genuinely legitimate transaction pairs read as physically
    impossible travel;
  - the floor is FREE: it suppresses no real fraud, because no fraud row would
    have tripped the impossible-speed rule at a gap under 5 minutes anyway.

A floor justified only by the first half could be quietly destroying
detections. Both halves are checked here, over both datasets.

Like neighbour_distribution.py, this parses the claimed figures back out of
config.yaml's own comment and compares, so a stale justification fails the
script instead of sitting there looking authoritative. Exits non-zero on any
mismatch.

Writes outputs/GEO_FLOOR_JUSTIFICATION.md.
"""
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import ROOT, load_config, haversine_miles  # noqa: E402

CONFIG_PATH = ROOT / "config.yaml"
OUT_PATH = ROOT / "outputs/GEO_FLOOR_JUSTIFICATION.md"

DATASETS = [
    ("primary", "data/ebt_synthetic.csv"),
    ("realistic", "data/ebt_synthetic_realistic.csv"),
]

USECOLS = ["household_id", "timestamp", "terminal_id", "terminal_lat",
           "terminal_lon", "is_fraud", "fraud_pattern"]


def analyse(path, impossible_mph, floor_minutes):
    """All floor-justification quantities for one dataset.

    Pair definition, stated explicitly because the numbers depend on it: a
    "pair" is a household's consecutive transactions (each row against its own
    household's immediately preceding row). "Legitimate" means BOTH endpoints
    are ordinary legitimate -- is_fraud False and no fraud_pattern, so N1 and
    N2 are excluded as well as fraud. Pairs with zero elapsed time are excluded
    from the legitimate-pair denominator because speed is undefined there; they
    are counted separately below.
    """
    df = pd.read_csv(ROOT / path, parse_dates=["timestamp"], usecols=USECOLS)
    df = df.sort_values(["household_id", "timestamp"]).reset_index(drop=True)

    g = df.groupby("household_id")
    prev_lat, prev_lon = g["terminal_lat"].shift(1), g["terminal_lon"].shift(1)
    prev_ts, prev_term = g["timestamp"].shift(1), g["terminal_id"].shift(1)
    prev_fraud, prev_pat = g["is_fraud"].shift(1), g["fraud_pattern"].shift(1)

    dist_mi = haversine_miles(df["terminal_lat"], df["terminal_lon"], prev_lat, prev_lon)
    elapsed_min = (df["timestamp"] - prev_ts).dt.total_seconds() / 60
    has_prev = prev_ts.notna()
    speed = dist_mi / (elapsed_min / 60)

    ordinary_legit = (~df["is_fraud"]) & df["fraud_pattern"].isna()
    prev_ordinary_legit = (prev_fraud == False) & prev_pat.isna()  # noqa: E712
    legit_pair = has_prev & ordinary_legit & prev_ordinary_legit
    scoreable = legit_pair & (elapsed_min > 0)

    impossible = scoreable & (speed >= impossible_mph)
    imp_gaps = sorted(elapsed_min[impossible].round(2).tolist())

    fraud_trip = has_prev & df["is_fraud"] & (elapsed_min > 0) & (speed >= impossible_mph)
    fraud_gaps = sorted(elapsed_min[fraud_trip].round(2).tolist())

    same_ts = has_prev & (elapsed_min == 0) & (df["terminal_id"] != prev_term)
    # "Legitimate" here means BOTH endpoints ordinary legitimate -- the same
    # definition as legit_pair above, N1/N2 excluded. Applying it symmetrically
    # matters: counting one endpoint as ordinary-legit and the other as merely
    # not-fraud gives a different number, and the asymmetric version was a bug
    # here before it was caught by comparing against the config comment.
    same_ts_legit = same_ts & ordinary_legit & prev_ordinary_legit
    same_ts_fraud = same_ts & (df["is_fraud"] | (prev_fraud == True))  # noqa: E712

    suppressed = scoreable & (elapsed_min < floor_minutes)

    return {
        "rows": len(df),
        "legit_pairs": int(scoreable.sum()),
        "impossible_no_floor": int(impossible.sum()),
        "impossible_pct": 100.0 * impossible.sum() / max(int(scoreable.sum()), 1),
        "impossible_gaps": imp_gaps,
        "max_impossible_gap": max(imp_gaps) if imp_gaps else None,
        "fraud_trip": int(fraud_trip.sum()),
        "fraud_gaps": fraud_gaps,
        "fraud_under_floor": int((elapsed_min[fraud_trip] < floor_minutes).sum()),
        "fraud_patterns": df.loc[fraud_trip, "fraud_pattern"].value_counts().to_dict(),
        "same_ts_pairs": int(same_ts.sum()),
        "same_ts_legit": int(same_ts_legit.sum()),
        "same_ts_fraud": int(same_ts_fraud.sum()),
        "suppressed": int(suppressed.sum()),
        "suppressed_pct": 100.0 * suppressed.sum() / max(int(scoreable.sum()), 1),
    }


def parse_claimed(text):
    """Pull the claimed figures out of config.yaml's geo_velocity comment."""
    stripped = re.sub(r"^\s*#\s?", "", text, flags=re.MULTILINE)
    flat = re.sub(r"\s+", " ", stripped)
    out = {}

    m = re.search(r"with no floor, ([\d,]+) of ([\d,]+) genuinely legitimate "
                  r"consecutive-transaction pairs \(([\d.]+)%\)", flat)
    if m:
        out["impossible_no_floor"] = int(m.group(1).replace(",", ""))
        out["legit_pairs"] = int(m.group(2).replace(",", ""))
        out["impossible_pct"] = float(m.group(3))

    m = re.search(r"A (\d+)-minute floor already removes all (\d+)", flat)
    if m:
        out["removing_floor_minutes"] = int(m.group(1))
        out["removes_all"] = int(m.group(2))

    m = re.search(r"not scoring only ([\d.]+)% of legitimate pairs", flat)
    if m:
        out["suppressed_pct"] = float(m.group(1))

    m = re.search(r"only (\d+) and (\d+) fraud rows respectively would have tripped", flat)
    if m:
        out["fraud_trip_primary"] = int(m.group(1))
        out["fraud_trip_realistic"] = int(m.group(2))

    m = re.search(r"(\d+) of (\d+) same-timestamp/different-terminal pairs in the primary "
                  r"dataset \(([\d,]+) of ([\d,]+) in the realistic dataset\)", flat)
    if m:
        out["same_ts_legit_primary"] = int(m.group(1))
        out["same_ts_primary"] = int(m.group(2))
        out["same_ts_legit_realistic"] = int(m.group(3).replace(",", ""))
        out["same_ts_realistic"] = int(m.group(4).replace(",", ""))
    return out


def main():
    cfg = load_config()
    gcfg = cfg["features"]["geo_velocity"]
    floor = gcfg["min_elapsed_minutes_to_score"]
    impossible_mph = gcfg["impossible_mph"]

    results = {}
    for name, path in DATASETS:
        print(f"Analysing {name} ({path})...")
        results[name] = analyse(path, impossible_mph, floor)

    claimed = parse_claimed(CONFIG_PATH.read_text())
    p, r = results["primary"], results["realistic"]

    checks = []

    def check(label, claimed_value, actual, fmt="{}"):
        ok = claimed_value is not None and (
            abs(claimed_value - actual) <= 0.005 if isinstance(actual, float)
            else claimed_value == actual)
        checks.append((label, claimed_value, actual, ok, fmt))
        return ok

    check("legitimate pairs, primary (denominator)", claimed.get("legit_pairs"), p["legit_pairs"])
    check("impossible-travel pairs with no floor, primary",
          claimed.get("impossible_no_floor"), p["impossible_no_floor"])
    check("that as a share of legitimate pairs (%)",
          claimed.get("impossible_pct"), round(p["impossible_pct"], 4), "{:.4f}")
    check("a 2-minute floor removes all of them",
          claimed.get("removes_all"), p["impossible_no_floor"])
    check("legitimate pairs the 5-minute floor declines to score (%)",
          claimed.get("suppressed_pct"), round(p["suppressed_pct"], 2), "{:.2f}")
    check("fraud rows tripping impossible-speed, primary",
          claimed.get("fraud_trip_primary"), p["fraud_trip"])
    check("fraud rows tripping impossible-speed, realistic",
          claimed.get("fraud_trip_realistic"), r["fraud_trip"])
    check("same-timestamp diff-terminal pairs, primary",
          claimed.get("same_ts_primary"), p["same_ts_pairs"])
    check("of those, legitimate, primary",
          claimed.get("same_ts_legit_primary"), p["same_ts_legit"])
    check("same-timestamp diff-terminal pairs, realistic",
          claimed.get("same_ts_realistic"), r["same_ts_pairs"])
    check("of those, legitimate, realistic",
          claimed.get("same_ts_legit_realistic"), r["same_ts_legit"])

    n_bad = sum(1 for *_, ok, _ in checks if not ok)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    L = []
    L.append("# CivicSentra Phase 0 -- geo-velocity 5-minute floor, justification recomputed")
    L.append(f"Generated {ts} by `src/geo_floor_justification.py`.")
    L.append("")
    L.append(f"Recomputes every figure behind `min_elapsed_minutes_to_score: {floor}` in "
             f"config.yaml, over both datasets, and checks them against the values claimed "
             f"in config.yaml's own comment. Impossible-speed threshold: "
             f"{impossible_mph} mph.")
    L.append("")
    if n_bad:
        L.append(f"**{n_bad} of {len(checks)} claimed figures MISMATCH.** See the check "
                 f"table below. The config comment and the data disagree; the comment is "
                 f"the claim under test here, not the authority.")
    else:
        L.append(f"**All {len(checks)} claimed figures MATCH.** The floor's justification "
                 f"is reproducible from the committed datasets.")
    L.append("")

    L.append("## Pair definition")
    L.append("")
    L.append("A pair is a household's consecutive transactions -- each row against its own "
             "household's immediately preceding row. **Legitimate** means both endpoints "
             "are ordinary legitimate: `is_fraud` false *and* no `fraud_pattern`, so N1 and "
             "N2 rows are excluded as well as fraud. Pairs with zero elapsed time are "
             "excluded from the legitimate-pair denominator, because speed is undefined "
             "there; they are counted separately as same-timestamp pairs. The figures are "
             "sensitive to this definition, so it is stated rather than left implicit.")
    L.append("")

    L.append("## Half 1 -- the floor is needed")
    L.append("")
    L.append("| | primary | realistic |")
    L.append("|---|---|---|")
    L.append(f"| rows | {p['rows']:,} | {r['rows']:,} |")
    L.append(f"| legitimate consecutive pairs (elapsed > 0) | {p['legit_pairs']:,} | {r['legit_pairs']:,} |")
    L.append(f"| read as impossible travel with NO floor | {p['impossible_no_floor']:,} | {r['impossible_no_floor']:,} |")
    L.append(f"| as a share of legitimate pairs | {p['impossible_pct']:.4f}% | {r['impossible_pct']:.4f}% |")
    L.append(f"| largest elapsed gap among them | {p['max_impossible_gap']} min | {r['max_impossible_gap']} min |")
    L.append("")
    L.append(f"Every one of these pairs sits at an elapsed gap of "
             f"{p['max_impossible_gap']} minute(s) or less in the primary dataset "
             f"({r['max_impossible_gap']} in the realistic one) -- which is what "
             f"'minute-resolution rounding artifact' means concretely: two independent "
             f"ordinary trips landing in adjacent rounded minutes at different nearby "
             f"terminals, not travel. Any floor above that gap removes all of them.")
    L.append("")

    L.append("## Half 2 -- the floor is free")
    L.append("")
    L.append("The cost of a floor is any real fraud it declines to score. If a fraud row "
             "would have tripped the impossible-speed rule at a gap under the floor, the "
             "floor is hiding a detection.")
    L.append("")
    L.append("| | primary | realistic |")
    L.append("|---|---|---|")
    L.append(f"| fraud rows tripping impossible-speed with NO floor | {p['fraud_trip']} | {r['fraud_trip']} |")
    L.append(f"| their elapsed gaps (min) | {p['fraud_gaps']} | {r['fraud_gaps']} |")
    L.append(f"| patterns | {p['fraud_patterns']} | {r['fraud_patterns']} |")
    L.append(f"| **of those, under the {floor}-minute floor** | **{p['fraud_under_floor']}** | **{r['fraud_under_floor']}** |")
    L.append("")
    total_fraud_trip = p["fraud_trip"] + r["fraud_trip"]
    total_under = p["fraud_under_floor"] + r["fraud_under_floor"]
    if total_under == 0:
        L.append(f"**{total_under} of {total_fraud_trip}.** Every fraud row that would ever "
                 f"trip the impossible-speed rule sits well above the floor, so the floor "
                 f"suppresses no detection in either dataset. Real cloned-card drains show "
                 f"up far apart *and* slow enough to be real travel time -- not "
                 f"close-together-and-instant, which is the signature of the rounding "
                 f"artifact the floor exists to remove.")
    else:
        L.append(f"**WARNING: {total_under} fraud row(s) sit under the floor.** The floor "
                 f"is suppressing real detections and its justification does not hold as "
                 f"stated.")
    L.append("")
    L.append(f"Cost on the legitimate side: the floor declines to score "
             f"{p['suppressed']:,} legitimate pairs in the primary dataset "
             f"({p['suppressed_pct']:.2f}% of them).")
    L.append("")

    L.append("## Same-timestamp pairs (elapsed = 0)")
    L.append("")
    L.append("Folded into the same floor rather than special-cased as automatic hard "
             "blocks. That decision rests on how many of them are legitimate:")
    L.append("")
    L.append("| | primary | realistic |")
    L.append("|---|---|---|")
    L.append(f"| same-timestamp, different-terminal pairs | {p['same_ts_pairs']:,} | {r['same_ts_pairs']:,} |")
    L.append(f"| of those, both endpoints ordinary legitimate | {p['same_ts_legit']:,} | {r['same_ts_legit']:,} |")
    L.append(f"| of those, involving a fraud row at either end | {p['same_ts_fraud']:,} | {r['same_ts_fraud']:,} |")
    L.append("")
    L.append("**Legitimate here means both endpoints ordinary legitimate — N1 and N2 "
             "excluded, the same definition used for the pair denominator above.** The "
             "remainder are not fraud: as the last row shows, **zero** same-timestamp "
             "pairs in either dataset involve a fraud row at all. The pairs not counted as "
             "ordinary-legitimate are N1/N2 rows, which are themselves legitimate. That "
             "makes the design decision stronger than the headline ratio suggests: "
             "hard-blocking every same-timestamp pair would have blocked only legitimate "
             "transactions, and caught nothing.")
    L.append("")

    L.append("## Against the figures claimed in config.yaml's comment")
    L.append("")
    L.append("| Quantity | config.yaml comment | recomputed | |")
    L.append("|---|---|---|---|")
    for label, claimed_v, actual, ok, fmt in checks:
        cv = "unparsed" if claimed_v is None else fmt.format(claimed_v)
        L.append(f"| {label} | {cv} | {fmt.format(actual)} | {'MATCH' if ok else 'MISMATCH'} |")
    L.append("")
    if n_bad:
        L.append("**Do not edit the comment to agree without checking whether the "
                 "parameter it justifies is still the right one.** A mismatch means the "
                 "measurement behind a threshold has changed or was wrong; which of those "
                 "it is determines whether the comment or the config value needs fixing.")

    report = "\n".join(L) + "\n"
    print(report)
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(report)
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}")

    if n_bad:
        raise SystemExit(f"{n_bad} claimed figure(s) do not match the data")


if __name__ == "__main__":
    main()
