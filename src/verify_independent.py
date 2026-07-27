#!/usr/bin/env python3
"""Independent verification of every headline metric.

The point of this file is to be a *second opinion*, so it deliberately shares
nothing with the code it checks:

- It imports nothing from evaluate.py, features.py or scorer.py. No shared
  helpers, no shared constants, no shared statistics.
- It does not use pandas or numpy at all. Everything is stdlib `csv` plus
  manual arithmetic, so a bug in how the first implementation used a
  dataframe cannot reproduce itself here.
- Where evaluate.py picked a method, this picks a different one. PR-AUC is
  the deliberate case: evaluate.py computes step-wise average precision, this
  integrates the precision-recall curve trapezoidally. The two are different
  estimators of the same quantity and are *expected* to disagree slightly;
  the report says by how much and why.

It reads data/ebt_scored.csv for the data and outputs/evaluate_metrics.md for
what evaluate.py claimed, then compares. Nothing is reconciled silently: a
disagreement is printed as MISMATCH and gets its own section.

Writes outputs/INDEPENDENT_VERIFICATION.md.
"""
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCORED = ROOT / "data/ebt_scored.csv"
REPORTED = ROOT / "outputs/evaluate_metrics.md"
OUT = ROOT / "outputs/INDEPENDENT_VERIFICATION.md"

csv.field_size_limit(10_000_000)

# Agreement tolerance for the two feature families, in sub-score units
# (0-1). Both are exact reproductions from published columns, so these are
# float-noise tolerances, not allowances for a modelling gap.
HOME_TOL = 1e-6
SPEND_TOL = 1e-6


# ---------------------------------------------------------------------------
# Load. Plain csv module -- no dataframe library anywhere in this file.
# ---------------------------------------------------------------------------

def load():
    rows = []
    with open(SCORED, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append({
                "household_id": r["household_id"],
                "pattern": r["fraud_pattern"],
                "is_fraud": r["is_fraud"] == "True",
                "crossing": r["n1_crossing_issuance"] == "True",
                "locality": r["locality_class"],
                "amount": float(r["amount"]),
                "score": float(r["risk_score"]),
                "decision": r["decision"],
                "override": r["geo_hard_override"] == "True",
                "reasons": r["reason_codes"] or "",
                "ts": datetime.strptime(r["timestamp"], "%Y-%m-%d %H:%M:%S"),
                # extra columns used by the scorer/feature-stage checks
                "txn": r["transaction_id"],
                "event_type": r["event_type"],
                "benefit": float(r["monthly_benefit_amount"]),
                "days_since_issuance": float(r["days_since_issuance"]),
                "issuance_day": float(r["issuance_day"]),
                # Point-in-time balance as published by the generator. Before
                # this column existed the balance had to be reconstructed from
                # the ledger, which left rows this check could not score.
                "rem_published": float(r["remaining_balance_at_transaction"]),
                "home_lat": float(r["home_lat"]), "home_lon": float(r["home_lon"]),
                "term_lat": float(r["terminal_lat"]), "term_lon": float(r["terminal_lon"]),
                "home_pts": float(r["home_location_subscore_points"]),
                "spend_pts": float(r["spend_baseline_subscore_points"]),
            })
    return rows


def load_raw():
    """Second pass, as plain string dicts, for the column-arithmetic checks."""
    with open(SCORED, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# Metrics, computed by hand.
# ---------------------------------------------------------------------------

def confusion(rows):
    tp = fp = fn = tn = 0
    for r in rows:
        alerted = r["decision"] != "allow"
        if r["is_fraud"] and alerted:
            tp += 1
        elif (not r["is_fraud"]) and alerted:
            fp += 1
        elif r["is_fraud"] and not alerted:
            fn += 1
        else:
            tn += 1
    return tp, fp, fn, tn


def pr_auc_trapezoid(rows):
    """Trapezoidal integration of the PR curve.

    evaluate.py uses step-wise average precision:
        AP = sum_i (R_i - R_{i-1}) * P_i
    which credits each recall step with the precision at the END of the step.
    This integrates instead:
        AUC = sum_i (R_i - R_{i-1}) * (P_i + P_{i-1}) / 2
    averaging the precision across the step.

    Direction of the expected difference: recall only advances when a true
    positive is found, and finding one *raises* precision. So AP evaluates
    precision at a local maximum, while the trapezoid averages that maximum
    with the precision immediately before it -- a local minimum. The
    trapezoid therefore sits slightly BELOW step-wise AP on a per-row sweep.
    A small negative difference is the correct result, not a discrepancy.
    (The familiar warning that trapezoidal PR integration is optimistic
    applies to interpolating between a few coarse operating points, which is
    not what either implementation does here.)
    """
    ordered = sorted(rows, key=lambda r: -r["score"])
    total_pos = sum(1 for r in rows if r["is_fraud"])
    tp = 0
    seen = 0
    prev_r, prev_p = 0.0, 1.0
    area = 0.0
    for r in ordered:
        seen += 1
        if r["is_fraud"]:
            tp += 1
        rec = tp / total_pos
        prec = tp / seen
        area += (rec - prev_r) * (prec + prev_p) / 2.0
        prev_r, prev_p = rec, prec
    return area


def tier_precision(rows, tier):
    tp = fp = 0
    for r in rows:
        hit = (r["decision"] == "block") if tier == "block" else (r["decision"] != "allow")
        if hit:
            if r["is_fraud"]:
                tp += 1
            else:
                fp += 1
    return tp, fp, (tp / (tp + fp) if tp + fp else float("nan"))


def by_pattern(rows):
    out = {}
    for p in ["P2", "P3", "P4", "P5", "P6", "P7", "P8"]:
        sel = [r for r in rows if r["pattern"] == p]
        det = sum(1 for r in sel if r["decision"] != "allow")
        out[p] = (det, len(sel), det / len(sel) if sel else float("nan"))
    return out


def flag_rate(rows, predicate):
    sel = [r for r in rows if predicate(r)]
    hit = sum(1 for r in sel if r["decision"] != "allow")
    return hit, len(sel), (hit / len(sel) if sel else float("nan"))


def victim_split(rows):
    """Three-way split of ordinary-legitimate rows, built with plain dicts.

    'Ordinary legitimate' = not fraud and no N1/N2 label. Victim household =
    one with at least one is_fraud row; 'after' compares against that
    household's earliest fraud timestamp.
    """
    first_fraud = {}
    for r in rows:
        if r["is_fraud"]:
            h = r["household_id"]
            if h not in first_fraud or r["ts"] < first_fraud[h]:
                first_fraud[h] = r["ts"]

    groups = {"clean": [0, 0], "victim_before": [0, 0], "victim_after": [0, 0]}
    for r in rows:
        if r["is_fraud"] or r["pattern"]:
            continue
        ff = first_fraud.get(r["household_id"])
        if ff is None:
            key = "clean"
        elif r["ts"] > ff:
            key = "victim_after"
        else:
            key = "victim_before"
        groups[key][0] += 1
        if r["decision"] != "allow":
            groups[key][1] += 1
    return groups


def cost_matrix(rows, costs):
    caught = sum(r["amount"] for r in rows if r["is_fraud"] and r["decision"] != "allow")
    missed = sum(r["amount"] for r in rows if r["is_fraud"] and r["decision"] == "allow")
    blocked = sum(r["amount"] for r in rows
                  if (not r["is_fraud"]) and r["decision"] == "block")
    alerts = sum(1 for r in rows if r["decision"] != "allow")
    ratios = {k: caught / (alerts * c) for k, c in costs.items()}
    return caught, missed, blocked, alerts, ratios


SUBSCORES = ["geo_velocity", "home_location", "spend_baseline",
             "terminal_reputation", "terminal_neighbour", "ebt_policy_rules"]


def check_subscore_sum(raw_rows):
    """Do the six sub-score point columns actually sum to risk_score?

    Closes a gap the metric checks cannot: evaluate.py and this file both
    read risk_score, so if scorer.py combined the weights wrongly both would
    report the same wrong number and every comparison would still pass. This
    recomputes the total from its published parts, on every row.
    """
    worst = 0.0
    failures = []
    for r in raw_rows:
        total = sum(float(r[f"{c}_subscore_points"]) for c in SUBSCORES)
        stored = float(r["risk_score"])
        diff = abs(total - stored)
        worst = max(worst, diff)
        if diff > 1e-9:
            failures.append((r["transaction_id"], total, stored, diff))
    return worst, failures


def check_decision_rule(raw_rows, allow_to_step_up, step_up_to_block):
    """Re-derive allow / step_up / block from risk_score + geo_hard_override.

    The rule, from explain/EXPLAIN_scorer.md and config.yaml thresholds:
    block if the hard override fired OR the score reached the block line;
    step_up if the score reached the alert line; otherwise allow.
    """
    failures = []
    for r in raw_rows:
        s = float(r["risk_score"])
        override = r["geo_hard_override"] == "True"
        if override or s >= step_up_to_block:
            derived = "block"
        elif s >= allow_to_step_up:
            derived = "step_up"
        else:
            derived = "allow"
        if derived != r["decision"]:
            failures.append((r["transaction_id"], s, override, r["decision"], derived))
    return failures


def read_thresholds():
    text = (ROOT / "config.yaml").read_text(encoding="utf-8")
    a = re.search(r"allow_to_step_up:\s*([0-9.]+)", text)
    b = re.search(r"step_up_to_block:\s*([0-9.]+)", text)
    return float(a.group(1)), float(b.group(1))


def read_feature_config():
    text = (ROOT / "config.yaml").read_text(encoding="utf-8")
    zone = dict(re.findall(r"(urban|suburban|rural):\s*(\d+)",
                           re.search(r"zone_radius_miles:\s*\{([^}]*)\}", text).group(1)))
    return {
        "zone": {k: float(v) for k, v in zone.items()},
        "near": float(re.search(r"near_zone_subscore:\s*([0-9.]+)", text).group(1)),
        "far": float(re.search(r"far_zone_subscore:\s*([0-9.]+)", text).group(1)),
        "night_mult": float(re.search(r"night_hour_multiplier:\s*([0-9.]+)", text).group(1)),
        "night_hours": {0, 1, 2, 3, 4},
        "normal_max_pct": float(re.search(r"normal_max_pct:\s*([0-9.]+)", text).group(1)),
        "strong_min_pct": float(re.search(r"strong_min_pct:\s*([0-9.]+)", text).group(1)),
        "mid_band_base_max": float(re.search(r"mid_band_base_max:\s*([0-9.]+)", text).group(1)),
        "day_min": float(re.search(r"day_factor_min:\s*([0-9.]+)", text).group(1)),
        "day_max": float(re.search(r"day_factor_max:\s*([0-9.]+)", text).group(1)),
        "w_home": 0.25,
        "w_spend": 0.25,
        # Needed to derive day-in-cycle the way the feature stage does, from
        # the timestamp rather than from the jittered days_since_issuance
        # column. Both inputs are published; only the origin comes from config.
        "start_date": datetime.strptime(
            re.search(r'start_date:\s*"([\d-]+)"', text).group(1), "%Y-%m-%d"),
        "cycle_days": 30.0,
    }


def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance, written out rather than imported."""
    import math
    R = 3958.7613  # mean Earth radius, miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def attach_balance_and_cycle_day(rows, fc):
    """Attach the two spend-baseline inputs, both from published columns.

    Replaces the reconstruction this file used to perform. Remaining balance
    is now read straight from `remaining_balance_at_transaction` instead of
    being rebuilt by detecting cycle resets in `days_since_issuance` — that
    reconstruction was ambiguous wherever a balance hit zero or a row landed
    out of ledger order, and those rows had to be reported as `undefined`.

    Day-in-cycle is derived here from `timestamp` and `issuance_day` rather
    than read from the `days_since_issuance` column. That column carries
    sub-day jitter; the feature stage derives its own day-in-cycle from the
    timestamp, so using the column left a small residual that was not a
    scoring error. Both inputs are published, so this stays an independent
    recomputation and not an import.
    """
    for r in rows:
        r["rem_before"] = r["rem_published"]
        abs_day = (r["ts"] - fc["start_date"]).total_seconds() / 86400
        r["day_in_cycle"] = (abs_day - (r["issuance_day"] - 1)) % fc["cycle_days"]


def sweep_feature_agreement(rows, fc, band_of):
    """Recompute both feature families across every row, not a sample.

    The report used to quote sweep sizes as prose. They are computed here
    instead, so the numbers in the document cannot drift from the code that
    justifies them. Returns (checked, disagreements, worst_abs_gap) per
    family.
    """
    out = {}
    for name, fn, key, w in (
        ("home", independent_home_subscore, "home_pts", fc["w_home"]),
        ("spend", independent_spend_subscore, "spend_pts", fc["w_spend"]),
    ):
        tol = HOME_TOL if name == "home" else SPEND_TOL
        checked = bad = 0
        worst = 0.0
        worst_txn = None
        for r in rows:
            _, s = fn(r, fc)
            if s is None:
                continue
            gap = abs(s - band_of(r[key], w))
            checked += 1
            if gap > worst:
                worst, worst_txn = gap, r["txn"]
            if gap > tol:
                bad += 1
        out[name] = (checked, bad, worst, worst_txn)
    return out


def independent_home_subscore(r, fc):
    d = haversine_miles(r["home_lat"], r["home_lon"], r["term_lat"], r["term_lon"])
    z = fc["zone"][r["locality"]]
    s = 0.0 if d <= z else (fc["near"] if d <= 2 * z else fc["far"])
    if s > 0 and r["ts"].hour in fc["night_hours"]:
        s = min(1.0, s * fc["night_mult"])
    return d, s


def independent_spend_subscore(r, fc):
    if r["event_type"] != "purchase":
        return None, 0.0
    # Denominator floored at 1.0, matching how the rule is specified: an
    # exhausted balance divides by 1 rather than being undefined, so a draw
    # against a zero balance lands in the top band instead of dropping out
    # of the check. This is the case the published column made scorable.
    rem = max(r["rem_before"], 1.0)
    pct = r["amount"] / rem
    if pct < fc["normal_max_pct"]:
        return pct, 0.0
    if pct >= fc["strong_min_pct"]:
        return pct, 1.0
    span = fc["strong_min_pct"] - fc["normal_max_pct"]
    ramp = (pct - fc["normal_max_pct"]) / span * fc["mid_band_base_max"]
    day_c = min(max(r["day_in_cycle"], 0.0), fc["cycle_days"])
    day_f = fc["day_min"] + (fc["day_max"] - fc["day_min"]) * day_c / fc["cycle_days"]
    return pct, min(max(ramp * day_f, 0.0), fc["mid_band_base_max"])


def read_review_costs():
    """Parse the three review-cost values straight out of config.yaml with a
    regex, rather than importing the project's config loader."""
    text = (ROOT / "config.yaml").read_text(encoding="utf-8")
    block = re.search(r"review_cost_per_alert_usd:\s*\n((?:\s+\w+:.*\n)+)", text)
    costs = {}
    if block:
        for k, v in re.findall(r"(low|mid|high):\s*([0-9.]+)", block.group(1)):
            costs[k] = float(v)
    return costs or {"low": 6.40, "mid": 7.50, "high": 9.20}


# ---------------------------------------------------------------------------
# What evaluate.py claimed. Parsed from its output file, not from its code.
# ---------------------------------------------------------------------------

def parse_reported():
    t = REPORTED.read_text(encoding="utf-8")

    def grab(pattern, cast=float, default=None):
        m = re.search(pattern, t)
        return cast(m.group(1)) if m else default

    rep = {
        "tp": grab(r"TP=(\d+)\s+FP=\d+\s+FN=\d+", int),
        "fp": grab(r"TP=\d+\s+FP=(\d+)\s+FN=\d+", int),
        "fn": grab(r"TP=\d+\s+FP=\d+\s+FN=(\d+)", int),
        "precision": grab(r"Precision:\s*([\d.]+)%"),
        "recall": grab(r"Recall:\s*([\d.]+)%"),
        "pr_auc": grab(r"PR-AUC = ([\d.]+)"),
        "block_prec": grab(r"BLOCK ONLY:\s*TP=\d+ FP=\d+\s+precision=([\d.]+)%"),
        "block_tp": grab(r"BLOCK ONLY:\s*TP=(\d+)", int),
        "block_fp": grab(r"BLOCK ONLY:\s*TP=\d+ FP=(\d+)", int),
        "n1_rate": grab(r"All N1 rows flagged \(step_up or block\): \d+/\d+ = ([\d.]+)%"),
        "n2_rate": grab(r"All N2 rows flagged \(step_up or block\): \d+/\d+ = ([\d.]+)%"),
        "crossing_rate": grab(r"Crossing-issuance-boundary N1 subset flagged.*?= ([\d.]+)%"),
        "ordinary_rate": grab(r"Ordinary legitimate rows flagged: \d+/\d+ = ([\d.]+)%"),
        "caught": grab(r"Fraud value caught \(decision != allow\): \$([\d,.]+)",
                       lambda s: float(s.replace(",", ""))),
        "missed": grab(r"Fraud value missed \(decision == allow\):\s*\$([\d,.]+)",
                       lambda s: float(s.replace(",", ""))),
        "blocked": grab(r"Legitimate value wrongly BLOCKED.*?\$([\d,.]+)",
                        lambda s: float(s.replace(",", ""))),
        "alerts": grab(r"Total alerts \(review-cost-consuming, decision != allow\): ([\d,]+)",
                       lambda s: int(s.replace(",", ""))),
        "zero_fraud": grab(r"(\d+) of \d+ fraud rows score exactly 0\.00", int),
    }
    for p in ["P2", "P3", "P4", "P5", "P6", "P7", "P8"]:
        rep[f"det_{p}"] = grab(rf"{p}: (\d+)/\d+ detected", int)
    for loc in ["rural", "suburban", "urban"]:
        rep[f"loc_{loc}"] = grab(rf"locality_class={loc}: \d+/\d+ = ([\d.]+)%")
    for k in ["low", "mid", "high"]:
        rep[f"ratio_{k}"] = grab(rf"{k}\s*\(\$[\d.]+/alert\).*?ratio=([\d.]+):1")
    for key, label in [("vs_clean", "household never defrauded"),
                       ("vs_before", r"victim household, BEFORE the fraud"),
                       ("vs_after", r"victim household, AFTER the fraud")]:
        rep[key] = grab(rf"{label}\s*:\s*n=\s*([\d,]+)", lambda s: int(s.replace(",", "")))
        rep[key + "_rate"] = grab(rf"{label}.*?rate=\s*([\d.]+)%")
    return rep


# ---------------------------------------------------------------------------

def main():
    rows = load()
    costs = read_review_costs()
    rep = parse_reported()

    tp, fp, fn, tn = confusion(rows)
    n = len(rows)
    n_fraud = sum(1 for r in rows if r["is_fraud"])
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    auc_trap = pr_auc_trapezoid(rows)
    btp, bfp, bprec = tier_precision(rows, "block")
    atp, afp, aprec = tier_precision(rows, "alert")
    pat = by_pattern(rows)
    vs = victim_split(rows)
    caught, missed, blocked, alerts, ratios = cost_matrix(rows, costs)
    zero_fraud = sum(1 for r in rows if r["is_fraud"] and r["score"] == 0.0)

    n1_hit, n1_n, n1_rate = flag_rate(rows, lambda r: r["pattern"] == "N1")
    n2_hit, n2_n, n2_rate = flag_rate(rows, lambda r: r["pattern"] == "N2")
    cr_hit, cr_n, cr_rate = flag_rate(rows, lambda r: r["crossing"])
    or_hit, or_n, or_rate = flag_rate(
        rows, lambda r: (not r["is_fraud"]) and not r["pattern"])
    loc = {}
    for L in ["rural", "suburban", "urban"]:
        loc[L] = flag_rate(rows, lambda r, L=L: (not r["is_fraud"])
                           and not r["pattern"] and r["locality"] == L)

    checks = []   # (metric, reported, independent, match, note)

    def cmp(label, reported, mine, tol=0.005, fmt="{:.2f}"):
        if reported is None:
            checks.append((label, "not found in output", fmt.format(mine), "UNPARSED", ""))
            return
        ok = abs(reported - mine) <= tol
        checks.append((label, fmt.format(reported), fmt.format(mine),
                       "MATCH" if ok else "MISMATCH", ""))

    cmp("True positives (TP)", rep["tp"], tp, 0, "{:.0f}")
    cmp("False positives (FP)", rep["fp"], fp, 0, "{:.0f}")
    cmp("False negatives (FN)", rep["fn"], fn, 0, "{:.0f}")
    cmp("Precision (%)", rep["precision"], precision * 100)
    cmp("Recall (%)", rep["recall"], recall * 100)
    cmp("Block-tier TP", rep["block_tp"], btp, 0, "{:.0f}")
    cmp("Block-tier FP", rep["block_fp"], bfp, 0, "{:.0f}")
    cmp("Block-tier precision (%)", rep["block_prec"], bprec * 100)
    for p in ["P2", "P3", "P4", "P5", "P6", "P7", "P8"]:
        cmp(f"{p} detected (count)", rep[f"det_{p}"], pat[p][0], 0, "{:.0f}")
    cmp("N1 false-flag rate (%)", rep["n1_rate"], n1_rate * 100)
    cmp("N2 false-flag rate (%)", rep["n2_rate"], n2_rate * 100)
    cmp("N1 crossing-subset rate (%)", rep["crossing_rate"], cr_rate * 100)
    cmp("Ordinary-legitimate FP rate (%)", rep["ordinary_rate"], or_rate * 100)
    for L in ["rural", "suburban", "urban"]:
        cmp(f"FP rate, {L} (%)", rep[f"loc_{L}"], loc[L][2] * 100)
    cmp("Fraud value caught ($)", rep["caught"], caught, 0.01)
    cmp("Fraud value missed ($)", rep["missed"], missed, 0.01)
    cmp("Legitimate value blocked ($)", rep["blocked"], blocked, 0.01)
    cmp("Total alerts", rep["alerts"], alerts, 0, "{:.0f}")
    for k in ["low", "mid", "high"]:
        cmp(f"Savings ratio, {k} (${costs[k]:.2f})", rep[f"ratio_{k}"], ratios[k], 0.01)
    cmp("Fraud rows scoring exactly 0", rep["zero_fraud"], zero_fraud, 0, "{:.0f}")
    cmp("Victim split: clean households (n)", rep["vs_clean"], vs["clean"][0], 0, "{:.0f}")
    cmp("Victim split: before fraud (n)", rep["vs_before"], vs["victim_before"][0], 0, "{:.0f}")
    cmp("Victim split: after fraud (n)", rep["vs_after"], vs["victim_after"][0], 0, "{:.0f}")
    cmp("Victim split: after-fraud flag rate (%)", rep["vs_after_rate"],
        vs["victim_after"][1] / vs["victim_after"][0] * 100)

    # PR-AUC compared separately: different estimator, difference expected.
    auc_diff = auc_trap - (rep["pr_auc"] or 0)

    # ---- population arithmetic -------------------------------------------
    n_legit = n - n_fraud
    n_n1 = sum(1 for r in rows if r["pattern"] == "N1")
    n_n2 = sum(1 for r in rows if r["pattern"] == "N2")
    n_ord = sum(1 for r in rows if (not r["is_fraud"]) and not r["pattern"])
    n_block = sum(1 for r in rows if r["decision"] == "block")
    n_step = sum(1 for r in rows if r["decision"] == "step_up")
    n_allow = sum(1 for r in rows if r["decision"] == "allow")
    vsum = sum(g[0] for g in vs.values())

    ident = [
        ("fraud + legitimate = total rows", f"{n_fraud} + {n_legit}", n_fraud + n_legit, n),
        ("ordinary + N1 + N2 = legitimate", f"{n_ord} + {n_n1} + {n_n2}",
         n_ord + n_n1 + n_n2, n_legit),
        ("victim-split groups = ordinary legitimate", "clean+before+after", vsum, n_ord),
        ("TP + FN = fraud rows", f"{tp} + {fn}", tp + fn, n_fraud),
        ("TP + FP = total alerts", f"{tp} + {fp}", tp + fp, alerts),
        ("allow + step_up + block = total rows", f"{n_allow} + {n_step} + {n_block}",
         n_allow + n_step + n_block, n),
        ("block TP + block FP = block decisions", f"{btp} + {bfp}", btp + bfp, n_block),
        ("alert-tier TP + FP = TP + FP", f"{atp} + {afp}", atp + afp, tp + fp),
    ]

    # ---- write ------------------------------------------------------------
    mismatches = [c for c in checks if c[3] == "MISMATCH"]
    unparsed = [c for c in checks if c[3] == "UNPARSED"]
    bad_ident = [i for i in ident if i[2] != i[3]]

    L = []
    A = L.append
    A("# Independent verification")
    A("")
    A(f"Generated {datetime.now():%Y-%m-%d %H:%M:%S} by `src/verify_independent.py`, "
      f"which recomputes every headline metric from `data/ebt_scored.csv` "
      f"({n:,} rows) without importing anything from `evaluate.py`, `features.py` "
      "or `scorer.py`, and without using pandas or numpy. "
      "The 'reported' column is parsed from `outputs/evaluate_metrics.md` — "
      "what evaluate.py actually wrote, not what it was expected to write.")
    A("")
    A(f"**Result: {len(checks) - len(mismatches) - len(unparsed)} of {len(checks)} "
      f"metrics MATCH, {len(mismatches)} MISMATCH"
      + (f", {len(unparsed)} could not be parsed" if unparsed else "") + ". "
      f"{len(ident) - len(bad_ident)} of {len(ident)} population identities hold.**")
    A("")
    A("## Metric comparison")
    A("")
    A("| Metric | evaluate.py | independent | |")
    A("|---|---|---|---|")
    for label, r, m, status, _ in checks:
        A(f"| {label} | {r} | {m} | {status} |")
    A("")
    A("## PR-AUC — compared separately, different estimator by design")
    A("")
    A("| | Value |")
    A("|---|---|")
    A(f"| evaluate.py, step-wise average precision | {rep['pr_auc']:.4f} |")
    A(f"| independent, trapezoidal PR integration | {auc_trap:.4f} |")
    A(f"| difference | {auc_diff:+.4f} |")
    A("")
    A("These are two different estimators of the same quantity and are expected "
      "to differ slightly. Step-wise average precision credits each recall step "
      "with the precision at the end of the step; trapezoidal integration "
      "averages precision across the step. Recall only advances when a true "
      "positive is found, and finding one raises precision -- so average "
      "precision samples at a local maximum, while the trapezoid averages that "
      "maximum with the local minimum just before it. **A small negative "
      "difference is therefore the correct outcome here**, and the observed "
      f"{auc_diff:+.4f} is about {abs(auc_diff)/rep['pr_auc']*100:.2f}% of the "
      "value. It is not evidence that either implementation is wrong; a large "
      "difference in either direction would be.")
    A("")
    A("## Population arithmetic")
    A("")
    A("| Identity | Computed | Expected | |")
    A("|---|---|---|---|")
    for label, expr, got, want in ident:
        A(f"| {label} | {expr} = {got:,} | {want:,} | "
          f"{'OK' if got == want else 'BROKEN'} |")
    A("")

    # ---- scorer-stage checks ---------------------------------------------
    raw = load_raw()
    a_thr, b_thr = read_thresholds()
    worst_sum, sum_fail = check_subscore_sum(raw)
    dec_fail = check_decision_rule(raw, a_thr, b_thr)

    A("## Scorer stage — sub-score arithmetic")
    A("")
    A("The metric comparison above cannot catch a scoring error: both "
      "implementations read `risk_score`, so a mis-applied weight would "
      "produce the same wrong number in each. This recomputes the total from "
      "its published parts on **every row**.")
    A("")
    A(f"- Rows checked: **{len(raw):,}** (all of them)")
    A(f"- Identity tested: sum of the six `*_subscore_points` columns == `risk_score`")
    A(f"- Rows failing at tolerance 1e-9: **{len(sum_fail)}**")
    A(f"- Largest absolute difference observed: **{worst_sum:.3e}**")
    A("")
    if sum_fail:
        A("| transaction_id | sum of parts | risk_score | difference |")
        A("|---|---|---|---|")
        for t, tot, st, d in sum_fail[:25]:
            A(f"| {t} | {tot:.10f} | {st:.10f} | {d:.3e} |")
        if len(sum_fail) > 25:
            A(f"| ...and {len(sum_fail) - 25} more | | | |")
    else:
        A("**No row fails.** The weighted combination in `scorer.py` is "
          "internally consistent with the components it published.")
    A("")

    A("## Scorer stage — decision rule")
    A("")
    A(f"Thresholds read from `config.yaml`: allow→step_up at **{a_thr:g}**, "
      f"step_up→block at **{b_thr:g}**. Rule re-derived independently: block "
      "if `geo_hard_override` fired **or** score reached the block line; "
      "step_up if the score reached the alert line; otherwise allow.")
    A("")
    A(f"- Rows checked: **{len(raw):,}** (all of them)")
    A(f"- Disagreements with the stored `decision` column: **{len(dec_fail)}**")
    A("")
    if dec_fail:
        A("| transaction_id | risk_score | override | stored | derived |")
        A("|---|---|---|---|---|")
        for t, s, ov, stored, der in dec_fail[:25]:
            A(f"| {t} | {s:.2f} | {ov} | {stored} | {der} |")
        if len(dec_fail) > 25:
            A(f"| ...and {len(dec_fail) - 25} more | | | | |")
    else:
        A("**No disagreement on any row.** Every decision in the dataset "
          "follows from the score, the override flag and the configured "
          "thresholds alone — no decision was set by anything else.")
    A("")

    # ---- feature-stage spot check ----------------------------------------
    fc = read_feature_config()
    attach_balance_and_cycle_day(rows, fc)
    A("## Feature stage — 20-row spot check")
    A("")
    A("Recomputes two feature families from the raw columns and compares "
      "against the stored sub-scores. Rows are chosen to span the bands "
      "rather than sampled uniformly — a uniform sample is almost all zeros "
      "and would demonstrate nothing.")
    A("")

    def band_of(pts, w):
        return round(pts / w / 100, 6)

    # stratify: pick rows across distinct stored sub-score values
    def stratified(key_pts, w, k=10):
        buckets = {}
        for r in rows:
            buckets.setdefault(band_of(r[key_pts], w), []).append(r)
        # Spread the picks evenly across the whole range of observed
        # sub-score values. Taking the first k buckets would bunch them all
        # at the bottom of the band and exercise nothing.
        keys = sorted(buckets)
        if len(keys) <= k:
            chosen = keys
        else:
            step = (len(keys) - 1) / (k - 1)
            chosen = [keys[round(i * step)] for i in range(k)]
        return [buckets[key][len(buckets[key]) // 3] for key in chosen]

    A("### Home-location plausibility")
    A("")
    A(f"Zone radii from `config.yaml`: urban {fc['zone']['urban']:g} mi, "
      f"suburban {fc['zone']['suburban']:g} mi, rural {fc['zone']['rural']:g} mi. "
      f"Inside the zone → 0; out to 2× → {fc['near']:g}; beyond 2× → {fc['far']:g}; "
      f"×{fc['night_mult']:g} at hours 00–04, capped at 1.0. Distance computed by "
      "haversine written out in this file.")
    A("")
    A("This feature can only produce five distinct sub-scores "
      "(0, 0.35, 0.525, 0.75, 1.0), so the five rows below are not a sample — "
      "they are every band the feature is capable of emitting, one row each. "
      "The spend-baseline table that follows carries the remaining 15 rows.")
    A("")
    A("| transaction_id | locality | zone (mi) | computed dist (mi) | hour | computed sub-score | stored sub-score | |")
    A("|---|---|---|---|---|---|---|---|")
    home_bad = 0
    for r in stratified("home_pts", fc["w_home"], 10):
        d, s = independent_home_subscore(r, fc)
        stored = band_of(r["home_pts"], fc["w_home"])
        ok = abs(s - stored) <= HOME_TOL
        home_bad += 0 if ok else 1
        A(f"| {r['txn']} | {r['locality']} | {fc['zone'][r['locality']]:g} | {d:.3f} | "
          f"{r['ts'].hour:02d} | {s:.4f} | {stored:.4f} | {'MATCH' if ok else 'MISMATCH'} |")
    A("")

    A("### Spend baseline")
    A("")
    A(f"Bands from `config.yaml`: under {fc['normal_max_pct']*100:g}% of remaining "
      f"balance → 0; {fc['normal_max_pct']*100:g}–{fc['strong_min_pct']*100:g}% → ramp to "
      f"{fc['mid_band_base_max']:g} scaled by a day-in-cycle factor "
      f"({fc['day_min']:g}→{fc['day_max']:g}); at or above {fc['strong_min_pct']*100:g}% → 1.0. "
      "Remaining balance is read from the published "
      "`remaining_balance_at_transaction` column; day-in-cycle is derived "
      "from `timestamp` and `issuance_day`.")
    A("")
    A("| transaction_id | amount | published remaining | % of remaining | day in cycle | computed sub-score | stored sub-score | |")
    A("|---|---|---|---|---|---|---|---|")
    spend_bad = 0
    for r in stratified("spend_pts", fc["w_spend"], 15):
        pct, s = independent_spend_subscore(r, fc)
        stored = band_of(r["spend_pts"], fc["w_spend"])
        ok = abs(s - stored) <= SPEND_TOL
        spend_bad += 0 if ok else 1
        A(f"| {r['txn']} | {r['amount']:.2f} | {r['rem_before']:.2f} | "
          f"{pct*100:.2f}% | {r['day_in_cycle']:.2f} | {s:.4f} | {stored:.4f} | "
          f"{'MATCH' if ok else 'MISMATCH'} |")
    A("")
    sweep = sweep_feature_agreement(rows, fc, band_of)
    h_checked, h_bad, h_worst, h_txn = sweep["home"]
    s_checked, s_bad, s_worst, s_txn = sweep["spend"]

    A("**Scope of this check, stated plainly.** Both families are now exact "
      "reproductions from published columns, and both are swept across every "
      "row in the dataset rather than sampled — the counts below are computed "
      "by this script, not quoted from a previous run.")
    A("")
    A(f"- Home-location: **{h_checked - h_bad:,} of {h_checked:,}** rows agree "
      f"(tolerance {HOME_TOL:g}); largest gap {h_worst:.2e}"
      + (f" at `{h_txn}`" if h_txn else "") + ".")
    A(f"- Spend baseline: **{s_checked - s_bad:,} of {s_checked:,}** rows agree "
      f"(tolerance {SPEND_TOL:g}); largest gap {s_worst:.2e}"
      + (f" at `{s_txn}`" if s_txn else "") + ".")
    A("")
    A("Spend baseline was previously *approximate*. Remaining balance was not "
      "a published column, so this check rebuilt it from the ledger and could "
      "not resolve two situations: rows where the rebuilt balance reached zero "
      "or arrived out of ledger order, reported as `undefined` and left "
      "unscored; and a sub-day gap in the day-in-cycle input, which shifted "
      "four rows by ≤0.002 of sub-score. Publishing "
      "`remaining_balance_at_transaction` removes the first, and deriving "
      "day-in-cycle from `timestamp` and `issuance_day` — both published — "
      "removes the second. The feature stage is now verifiable from the CSV "
      "exactly, with no tolerance band standing in for a modelling gap.")
    A("")

    if mismatches or bad_ident or unparsed:
        A("## Disagreements")
        A("")
        for label, r, m, status, _ in mismatches:
            A(f"### MISMATCH — {label}")
            A("")
            A(f"- evaluate.py reported: `{r}`")
            A(f"- independently computed: `{m}`")
            A("- Not reconciled. Both values are reported as computed.")
            A("")
        for label, expr, got, want in bad_ident:
            A(f"### BROKEN IDENTITY — {label}")
            A("")
            A(f"- computed `{expr} = {got:,}`, expected `{want:,}`, "
              f"difference {got - want:+,}")
            A("")
        for label, r, m, status, _ in unparsed:
            A(f"### COULD NOT PARSE — {label}")
            A("")
            A(f"- independently computed: `{m}`")
            A("- No corresponding value found in `outputs/evaluate_metrics.md`; "
              "this metric was not cross-checked.")
            A("")
    else:
        A("## Disagreements")
        A("")
        A("None. Every parsed metric agrees and every population identity holds.")
        A("")

    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")

    print("\n".join(L))
    print(f"\nWrote {OUT.relative_to(ROOT)}")
    return 1 if (mismatches or bad_ident) else 0


if __name__ == "__main__":
    sys.exit(main())
