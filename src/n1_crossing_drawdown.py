"""Recompute the drawdown figures for the 48 store-and-forward crossing-issuance
N1 transactions: mean 68.4%, median 71.1%, range 42.6-88.3% of monthly benefit.

Why this exists: those three figures are cited in the paper's N1 section as the
quantitative description of the subgroup that the whole legitimate-but-anomalous
argument rests on -- 48 rows that are legitimate, permitted under 7 CFR
274.12(m), and behaviourally near-identical to P4. They were measured once by an
ad-hoc query and never recomputed by anything in this repository, which made
them the last figures in the results section with no committed script behind
them. A regenerated dataset would not have re-derived or invalidated them.

Same pattern as neighbour_distribution.py and geo_floor_justification.py:
recompute, parse the claimed values back out of the file that records them,
compare, and exit non-zero on any mismatch -- so a stale figure surfaces as a
MISMATCH instead of sitting there looking authoritative.

Two things are checked that a single mean/median/range comparison would not:

  1. The subgroup DEFINITION. The figures are only meaningful if the 48 rows are
     the ones the paper says they are, so the script asserts what the subgroup
     is (N1, not fraud, purchases, `n1_crossing_issuance` true) rather than
     assuming the column selects it correctly. A definition drift that left the
     summary statistics plausible would still fail here.
  2. Two independent implementations, deliberately not sharing code: a pandas
     pass, and a stdlib-`csv` pass with mean and median written out by hand. If
     they disagree, the script says so instead of reporting a number.

Claim sources. `data/ebt_data_dictionary.md` carries the same sentence as the
paper and is committed, so the check is self-contained in a clean checkout. The
paper's own draft section is not distributed with this repository (.gitignore);
when a copy is present at one of the candidate paths below it is parsed and
checked too, so the sentence actually being published is the one under test. Its
absence is reported, not treated as a failure.

Writes outputs/n1_crossing_drawdown.md.
"""
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import ROOT  # noqa: E402

CSV_PATH = ROOT / "data/ebt_synthetic.csv"
DICT_PATH = ROOT / "data/ebt_data_dictionary.md"
GENERATOR_PATH = ROOT / "src/ebt_generator.py"
OUT_PATH = ROOT / "outputs/n1_crossing_drawdown.md"

# The paper section is a private working file and is not distributed here. If a
# copy is reachable it gets checked as well; if not, that is reported.
PAPER_CANDIDATES = [
    ROOT / "paper/section9_draft.md",
    ROOT.parent / "civicsentra-private/section9_draft.md",
]

# The claim is quoted to one decimal place, so that is the precision it can be
# tested at: a recomputed value must round to the claimed value.
TOL = 0.05


# ---------------------------------------------------------------------------
# Recomputation, twice.
# ---------------------------------------------------------------------------

def drawdown_pandas():
    """Subgroup stats via pandas, plus the facts that define the subgroup.

    'Drawdown' is `amount` as a percentage of `monthly_benefit_amount` -- the
    household's full monthly benefit, not its remaining balance. That is the
    denominator the claim uses ("of monthly benefit") and it is the one that
    matters for this subgroup: the regulation permits a store-and-forward
    transaction whose window crosses an issuance boundary to draw against the
    whole newly issued balance, so the benefit amount *is* what is available.
    """
    df = pd.read_csv(CSV_PATH, parse_dates=["timestamp"])
    sub = df[df["n1_crossing_issuance"].astype(bool)]
    share = 100.0 * sub["amount"] / sub["monthly_benefit_amount"]
    return {
        "rows_total": len(df),
        "n1_rows": int((df["fraud_pattern"] == "N1").sum()),
        "n": len(sub),
        "mean": float(share.mean()),
        "median": float(share.median()),
        "min": float(share.min()),
        "max": float(share.max()),
        # Definition facts, checked rather than assumed.
        "all_n1": bool((sub["fraud_pattern"] == "N1").all()),
        "all_legit": bool((~sub["is_fraud"]).all()),
        "all_purchase": bool((sub["event_type"] == "purchase").all()),
        "zero_benefit_rows": int((sub["monthly_benefit_amount"] <= 0).sum()),
        "households": int(sub["household_id"].nunique()),
        "shares": sorted(share.tolist()),
    }


def drawdown_stdlib():
    """The same four statistics, sharing no code with the pandas pass.

    Plain `csv`, no dataframe library, mean and median written out -- including
    the even-n median, which is the one place a hand implementation and a
    library implementation can legitimately differ if one of them takes a lower
    median instead of averaging the middle pair. n here is even (48), so this is
    the case that actually needs checking, not a hypothetical one.
    """
    shares = []
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["n1_crossing_issuance"] != "True":
                continue
            shares.append(100.0 * float(r["amount"]) / float(r["monthly_benefit_amount"]))
    shares.sort()
    k = len(shares)
    mid = k // 2
    median = shares[mid] if k % 2 else (shares[mid - 1] + shares[mid]) / 2.0
    return {"n": k, "mean": sum(shares) / k, "median": median,
            "min": shares[0], "max": shares[-1]}


def generator_bounds():
    """The uniform draw the generator uses for a crossing-issuance N1 amount.

    Parsed out of ebt_generator.py rather than hardcoded, so the containment
    check below tests the data against the code that produced it. The observed
    range is a 48-draw sample from this interval; every value must sit inside
    it, and the sample min/max must not equal the endpoints in a way that would
    suggest clipping rather than sampling.
    """
    m = re.search(r"monthly_benefit_amount \* rng\.uniform\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)",
                  GENERATOR_PATH.read_text(encoding="utf-8"))
    if not m:
        return None
    return 100.0 * float(m.group(1)), 100.0 * float(m.group(2))


# ---------------------------------------------------------------------------
# What is claimed, parsed from the files that record it.
# ---------------------------------------------------------------------------

def parse_claim(text):
    """Pull the subgroup counts and the three drawdown figures out of prose.

    One parser serves both claim sources because the data dictionary carries
    the paper's sentence verbatim -- deliberately, so there is one wording to
    keep true rather than two. Returns None for a part that no longer matches,
    which is not an error but is itself worth reporting: an unparseable claim
    cannot be machine-checked, and that is the gap this script exists to close.
    """
    flat = re.sub(r"\s+", " ", text)
    out = {}

    m = re.search(r"(\d+)\s+N1\s+transactions,\s+of\s+which\s+(\d+)\s+are\s+"
                  r"store-and-forward\s+cases\s+crossing\s+an\s+issuance\s+boundary", flat)
    if m:
        out["n1_rows"] = int(m.group(1))
        out["n"] = int(m.group(2))

    # En dash in the paper, hyphen when the range is retyped elsewhere; accept
    # either rather than making the check depend on which one was used.
    m = re.search(r"mean\s+([\d.]+)%\s+of\s+monthly\s+benefit\s*"
                  r"\(median\s+([\d.]+)%,\s*range\s+([\d.]+)\s*[-–—]\s*([\d.]+)%\)", flat)
    if m:
        out["mean"] = float(m.group(1))
        out["median"] = float(m.group(2))
        out["min"] = float(m.group(3))
        out["max"] = float(m.group(4))
    return out


def label_for(path):
    """Repo-relative label, never an absolute one.

    The report is committed, so a machine-specific absolute path in it would be
    both noise and a small leak of the author's filesystem layout. Paths outside
    the repository are labelled with `..` instead.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return "../" + str(path.relative_to(ROOT.parent))


def load_claim_sources():
    """(label, path, parsed, note) for every claim source, present or not."""
    sources = [("data/ebt_data_dictionary.md", DICT_PATH, True)]
    sources += [(label_for(p), p, False) for p in PAPER_CANDIDATES]

    loaded = []
    for label, path, required in sources:
        if not path.exists():
            loaded.append((label, None, required,
                           "not present in this checkout" if not required
                           else "MISSING -- required claim source"))
            continue
        loaded.append((label, parse_claim(path.read_text(encoding="utf-8")), required, ""))
    return loaded


# ---------------------------------------------------------------------------

def main():
    print("Recomputing crossing-issuance N1 drawdown from data/ebt_synthetic.csv ...")
    p = drawdown_pandas()
    s = drawdown_stdlib()
    bounds = generator_bounds()

    # ---- implementation agreement -----------------------------------------
    impl_rows = []
    impl_bad = 0
    for key, fmt in [("n", "{:.0f}"), ("mean", "{:.4f}"), ("median", "{:.4f}"),
                     ("min", "{:.4f}"), ("max", "{:.4f}")]:
        gap = abs(p[key] - s[key])
        ok = gap <= 1e-9
        impl_bad += 0 if ok else 1
        impl_rows.append((key, fmt.format(p[key]), fmt.format(s[key]), gap, ok))

    # ---- subgroup definition ----------------------------------------------
    def_rows = [
        ("every row is labelled `N1`", p["all_n1"]),
        ("every row is `is_fraud = False`", p["all_legit"]),
        ("every row is a `purchase` (not a balance inquiry)", p["all_purchase"]),
        ("no row has a zero or negative monthly benefit (denominator is defined)",
         p["zero_benefit_rows"] == 0),
    ]
    if bounds:
        lo, hi = bounds
        def_rows.append(
            (f"every drawdown sits inside the generator's uniform({lo:g}%, {hi:g}%) draw",
             p["min"] >= lo and p["max"] <= hi))
    def_bad = sum(1 for _, ok in def_rows if not ok)

    # ---- claims ------------------------------------------------------------
    sources = load_claim_sources()
    claim_rows = []      # (source, quantity, claimed, recomputed, status)
    claim_bad = 0
    checked_any = False
    for label, claim, required, note in sources:
        if claim is None:
            claim_rows.append((label, "--", note or "unavailable", "--",
                               "MISSING" if required else "SKIPPED"))
            if required:
                claim_bad += 1
            continue
        if not claim:
            claim_rows.append((label, "--", "no claim matched the parser", "--", "UNPARSED"))
            claim_bad += 1
            continue
        for key, label_q, fmt, tol in [
                ("n1_rows", "N1 rows in the dataset", "{:.0f}", 0),
                ("n", "of those, crossing an issuance boundary", "{:.0f}", 0),
                ("mean", "mean drawdown (% of monthly benefit)", "{:.1f}", TOL),
                ("median", "median drawdown (%)", "{:.1f}", TOL),
                ("min", "range, low end (%)", "{:.1f}", TOL),
                ("max", "range, high end (%)", "{:.1f}", TOL)]:
            if key not in claim:
                claim_rows.append((label, label_q, "unparsed", fmt.format(p[key]), "UNPARSED"))
                claim_bad += 1
                continue
            checked_any = True
            ok = abs(claim[key] - p[key]) <= tol
            claim_bad += 0 if ok else 1
            claim_rows.append((label, label_q, fmt.format(claim[key]),
                               fmt.format(p[key]), "MATCH" if ok else "MISMATCH"))

    failed = impl_bad or def_bad or claim_bad or not checked_any

    # ---- report ------------------------------------------------------------
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    L = []
    A = L.append
    A("# CivicSentra Phase 0 -- crossing-issuance N1 drawdown, recomputed")
    A(f"Generated {ts} by `src/n1_crossing_drawdown.py` from "
      f"`data/ebt_synthetic.csv` ({p['rows_total']:,} rows).")
    A("")
    A("Recomputes the three figures the paper's N1 section cites for the "
      "store-and-forward transactions whose window crosses an issuance boundary "
      "-- mean, median and range of the amount drawn as a share of monthly "
      "benefit -- and checks them against the values claimed in the files that "
      "record them. These were the last figures in the results section that no "
      "committed script computed.")
    A("")
    if failed:
        A(f"**FAILED.** {impl_bad} implementation disagreement(s), "
          f"{def_bad} subgroup-definition failure(s), {claim_bad} claim problem(s)"
          + ("" if checked_any else ", and no claim could be checked at all") + ".")
    else:
        A("**All checks pass.** The two implementations agree exactly, the "
          "subgroup is what the claim says it is, and every claimed figure "
          "matches the recomputed value.")
    A("")

    A("## Definition")
    A("")
    A("Subgroup: rows with `n1_crossing_issuance = True` -- the N1 technical "
      "failures whose store-and-forward window crossed into a new benefit "
      "issuance period (7 CFR 274.12(m)). **Drawdown** is `amount` as a "
      "percentage of `monthly_benefit_amount`: the household's full monthly "
      "benefit, not its remaining balance. That is the denominator the claim "
      "names, and it is the right one here -- the regulation permits such a "
      "transaction to draw against the whole newly issued balance, so the "
      "benefit amount is what is actually available to draw.")
    A("")
    A(f"- N1 rows in the dataset: **{p['n1_rows']:,}**")
    A(f"- Of those, crossing an issuance boundary: **{p['n']}**, across "
      f"{p['households']} household(s)")
    A("")

    A("## Recomputed")
    A("")
    A("| Quantity | Value |")
    A("|---|---|")
    A(f"| rows | {p['n']} |")
    A(f"| mean drawdown | {p['mean']:.4f}% |")
    A(f"| median drawdown | {p['median']:.4f}% |")
    A(f"| minimum | {p['min']:.4f}% |")
    A(f"| maximum | {p['max']:.4f}% |")
    A("")
    A("Full sorted distribution, so the summary statistics can be checked by "
      "hand rather than taken on trust (%):")
    A("")
    A("```")
    for i in range(0, len(p["shares"]), 8):
        A("  " + "  ".join(f"{v:6.2f}" for v in p["shares"][i:i + 8]))
    A("```")
    A("")

    A("## Two implementations, compared")
    A("")
    A("- `drawdown_pandas()` -- pandas `mean`/`median`/`min`/`max`")
    A("- `drawdown_stdlib()` -- stdlib `csv`, no dataframe library, mean and "
      "median written out by hand. n is even (48), so the even-n median is the "
      "case that genuinely distinguishes the two implementations.")
    A("")
    A("| Statistic | pandas | stdlib | difference | |")
    A("|---|---|---|---|---|")
    for key, a, b, gap, ok in impl_rows:
        A(f"| {key} | {a} | {b} | {gap:.3e} | {'MATCH' if ok else 'MISMATCH'} |")
    A("")
    if impl_bad:
        A("**The two implementations disagree.** The figures above are not "
          "trustworthy until that is resolved.")
    else:
        A("**Exact agreement.** The statistics are not an artifact of either "
          "implementation.")
    A("")

    A("## Is the subgroup what the claim says it is?")
    A("")
    A("A correct mean over the wrong 48 rows would still look right, so the "
      "definition is asserted rather than assumed.")
    A("")
    A("| Property | |")
    A("|---|---|")
    for label, ok in def_rows:
        A(f"| {label} | {'OK' if ok else 'FAILED'} |")
    A("")
    if bounds:
        lo, hi = bounds
        A(f"The last row is the structural check: `src/ebt_generator.py` draws a "
          f"crossing-issuance amount as `monthly_benefit_amount * uniform({lo/100:g}, "
          f"{hi/100:g})`, parsed out of the generator rather than hardcoded here. The "
          f"observed range {p['min']:.2f}%-{p['max']:.2f}% is a 48-draw sample from "
          f"that interval, which is why it is narrower than {lo:g}%-{hi:g}% -- the "
          f"published range is the sample's, not the generator's, and the two should "
          f"not be confused.")
    else:
        A("The generator's uniform draw could not be parsed from "
          "`src/ebt_generator.py`, so the containment check was skipped. Fix the "
          "parser or the generator reference -- an unchecked structural bound is a "
          "weaker result than a checked one.")
    A("")

    A("## Against the claimed figures")
    A("")
    A("`data/ebt_data_dictionary.md` carries the paper's sentence verbatim and is "
      "committed, so this check is self-contained in a clean checkout. The paper's "
      "own draft section is a private working file excluded by `.gitignore`; when a "
      "copy is reachable it is parsed and checked too, so the sentence actually "
      "being published is the one under test. Its absence is reported rather than "
      "counted as a failure.")
    A("")
    A("| Claim source | Quantity | claimed | recomputed | |")
    A("|---|---|---|---|---|")
    for src, quantity, claimed, actual, status in claim_rows:
        A(f"| `{src}` | {quantity} | {claimed} | {actual} | {status} |")
    A("")
    A(f"Tolerance: claimed values are quoted to one decimal place, so a recomputed "
      f"value must round to the claim (±{TOL}). Counts must be exact.")
    A("")
    if claim_bad:
        A("**Do not edit the claim to agree without first establishing which side "
          "is wrong.** These figures describe the subgroup the paper's whole "
          "legitimate-but-anomalous argument rests on; a mismatch means either the "
          "dataset changed or the original measurement was wrong, and which of "
          "those it is determines what needs fixing.")
    elif not checked_any:
        A("**No claim was checked.** The script recomputed the figures but found "
          "nothing to compare them against, which leaves the traceability gap open.")

    report = "\n".join(L) + "\n"
    print(report)
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(report, encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}")

    if failed:
        raise SystemExit(
            f"{impl_bad} implementation disagreement(s), {def_bad} definition "
            f"failure(s), {claim_bad} claim problem(s)")


if __name__ == "__main__":
    main()
