"""Evaluation — CivicSentra Phase 0 (SPEC.md §4.4).

Reads data/ebt_scored.csv (scorer.py's decisions) and compares them against
ground truth (is_fraud, fraud_pattern) to produce every metric SPEC.md §4.4
requires, plus the author's 2026-07-25 additions (the 48-crossing-case step-up
rate). Every number below comes from this file being executed against
data/ebt_scored.csv -- nothing is assumed or invented.

Writes outputs/evaluate_metrics.md, a plain-text record of the real numbers
this run produced (the standard this project holds itself to: real numbers, obtained by
execution, recorded in outputs/). This is NOT outputs/PHASE0_REPORT.md --
that polished, charted, fully-reproducible report is report.py's job
(SPEC.md §4.7, not yet built).
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import ROOT, load_config  # noqa: E402

SMALL_N_THRESHOLD = 200
# SPEC.md §4.4, the author 2026-07-24: any subgroup metric computed on fewer than
# ~200 cases must carry its raw count and a 95% CI, not the point estimate
# alone.
Z_95 = 1.959963984540054
# Exact two-sided 95% normal critical value, used by the Wilson score
# interval below. Hardcoded rather than pulled from scipy.stats.norm.ppf(
# 0.975) -- scipy is not an installed dependency (this project keeps
# dependencies minimal) and this constant does not change.

FRAUD_PATTERNS = ["P2", "P3", "P4", "P5", "P6", "P7", "P8"]
# P1 (skimmer harvest) deliberately excluded: it is the compromise mechanism
# underlying P2-P8, not itself a labelled fraud row -- victims transact
# normally at a compromised terminal (see explain/EXPLAIN_ebt_generator.md,
# "P1 is not written as a fraud row"). There is nothing to compute a
# detection rate against for P1 specifically.

RECALL_TARGETS = [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
THRESHOLD_GRID = list(range(0, 101, 10))

NEIGHBOUR_POINTS_COL = "terminal_neighbour_subscore_points"
NEIGHBOUR_REASON_CODE = "TERMINAL_NEIGHBOUR_CLUSTER"

# The six per-family point columns scorer.py publishes. Named here rather than
# imported from scorer.py: evaluate.py reads only the published CSV.
CONTRIBUTION_COLS_ALL = [
    "geo_velocity_subscore_points",
    "home_location_subscore_points",
    "spend_baseline_subscore_points",
    "terminal_reputation_subscore_points",
    "terminal_neighbour_subscore_points",
    "ebt_policy_rules_subscore_points",
]

# Section 12 zooms in on the interval where section 4's coarse 10-point grid
# shows alerts collapsing (20 -> 30). 26 is in the list deliberately: it is the
# first integer threshold above the largest score a saturated spend-baseline
# sub-score can produce alone (weight 0.25 x 100 = 25.0 points), so it is the
# exact point where single-feature SPEND_BASELINE firings become arithmetically
# unable to alert. Whether that is what actually clears is measured below, not
# assumed from the arithmetic.
FP_COMPOSITION_THRESHOLDS = [25, 26, 30]
FP_COMPOSITION_BASELINE = 20  # current allow_to_step_up; the anchor to measure against


# ---------------------------------------------------------------------------
# Small-n statistics
# ---------------------------------------------------------------------------

def wilson_ci(k, n, z=Z_95):
    """Wilson score interval -- better-behaved than a normal approximation
    for small n or rates near 0/1, both of which apply here (N1 crossing
    subgroup: n=48; several rates are near-zero)."""
    if n == 0:
        return float("nan"), float("nan")
    phat = k / n
    denom = 1 + z**2 / n
    center = (phat + z**2 / (2 * n)) / denom
    margin = z * np.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def rate_stat(mask, label):
    n = int(len(mask))
    k = int(mask.sum())
    rate = k / n if n else float("nan")
    stat = {"label": label, "n": n, "count": k, "rate": rate, "small_n": n < SMALL_N_THRESHOLD}
    if stat["small_n"]:
        stat["ci_95_low"], stat["ci_95_high"] = wilson_ci(k, n)
    return stat


def fmt_rate(stat):
    line = f"{stat['label']}: {stat['count']}/{stat['n']} = {stat['rate']*100:.2f}%"
    if stat["small_n"]:
        line += (f"  [n<{SMALL_N_THRESHOLD}: 95% CI {stat['ci_95_low']*100:.2f}%"
                  f"-{stat['ci_95_high']*100:.2f}%]")
    return line


# ---------------------------------------------------------------------------
# Precision / recall / PR-AUC
# ---------------------------------------------------------------------------

def average_precision(is_fraud, risk_score):
    """PR-AUC via the standard step-function average-precision definition
    (AP = sum_i (recall_i - recall_{i-1}) * precision_i over score-sorted
    points), not ROC-AUC (SPEC.md §4.4: ROC-AUC flatters classifiers on
    imbalanced data). Implemented directly rather than via scikit-learn --
    not an installed dependency (this project keeps its dependency list minimal) and
    this is a ~10-line computation.
    """
    order = np.argsort(-risk_score.values)
    y = is_fraud.values[order].astype(float)
    tp_cum = np.cumsum(y)
    fp_cum = np.cumsum(1 - y)
    total_pos = y.sum()
    precision = tp_cum / (tp_cum + fp_cum)
    recall = tp_cum / total_pos
    recall_prev = np.concatenate(([0.0], recall[:-1]))
    ap = float(np.sum((recall - recall_prev) * precision))
    scores_sorted = risk_score.values[order]
    return ap, precision, recall, scores_sorted


def alerts_per_1000_at_recall(out, targets):
    """Alerts per 1,000 transactions at fixed recall levels (SPEC.md §4.4).

    Threshold-based, deliberately: for each recall target this finds the
    highest `risk_score >= t` rule that still achieves the target, and
    reports the alert volume that rule actually produces. SPEC.md §4.4
    justifies this section as review-capacity planning, and a capacity plan
    has to rest on a rule an agency can implement.

    An earlier implementation cut the score-sorted ranking at the top-N rows
    reaching each target and reported the score of the last included row as
    the "threshold". That was wrong whenever the cut fell inside a block of
    tied scores, which here it does severely: 102,208 rows tie at exactly
    0.00. A rank cut takes some of them; the rule `risk_score >= 0.00` takes
    all 137,080. The old section 3 therefore printed alert volumes that the
    threshold it named could not produce, and disagreed with section 4's
    genuine threshold sweep on the same data.

    Consequence, now reported rather than hidden: 55 fraud rows score
    exactly 0.00, so no threshold above zero can exceed 89.95% recall.
    Targets past that ceiling are reported as unreachable instead of being
    given a fictional threshold.
    """
    is_fraud = out["is_fraud"].values
    risk_score = out["risk_score"].values
    hard_override = out["geo_hard_override"].values.astype(bool)
    n_total = len(out)
    total_fraud = int(is_fraud.sum())

    # Sort descending once, then every candidate threshold is a prefix of
    # that order -- O(n log n) instead of re-scanning the frame per
    # threshold. `k` below = number of rows with score >= t.
    order = np.argsort(-risk_score, kind="mergesort")
    s_desc = risk_score[order]
    fraud_desc = is_fraud[order].astype(np.int64)
    ovr_desc = hard_override[order].astype(np.int64)

    cum_fraud = np.concatenate(([0], np.cumsum(fraud_desc)))
    cum_ovr = np.concatenate(([0], np.cumsum(ovr_desc)))
    cum_ovr_fraud = np.concatenate(([0], np.cumsum(ovr_desc * fraud_desc)))
    tot_ovr, tot_ovr_fraud = int(ovr_desc.sum()), int((ovr_desc * fraud_desc).sum())

    # Candidate thresholds: every distinct score, descending. 0.0 is always
    # included so the "alert on everything" rule is always among them.
    candidates = np.unique(np.concatenate(([0.0], risk_score)))[::-1]
    # rows with score >= t, for each candidate, via the descending order
    ks = n_total - np.searchsorted(s_desc[::-1], candidates, side="left")

    rows = []
    for target in targets:
        best = None
        for t, k in zip(candidates, ks):
            # alerted = (score >= t) OR hard_override; the override rows
            # below the cut have to be added back in, without double-count.
            tp = cum_fraud[k] + (tot_ovr_fraud - cum_ovr_fraud[k])
            if tp / total_fraud >= target:
                n_alerts = int(k + (tot_ovr - cum_ovr[k]))
                fp = n_alerts - int(tp)
                best = {
                    "recall_target": target,
                    "achieved": True,
                    "score_threshold": float(t),
                    "recall_achieved": int(tp) / total_fraud,
                    "precision_at_point": int(tp) / n_alerts if n_alerts else float("nan"),
                    "alerts_per_1000": n_alerts / n_total * 1000,
                    "n_alerts": n_alerts,
                    # True when the only rule reaching this target alerts on
                    # every transaction -- i.e. the target is not reachable
                    # by any usable threshold. Reported, not silently passed.
                    "degenerate": n_alerts == n_total,
                }
                break  # candidates descend, so the first hit is the tightest
        rows.append(best or {"recall_target": target, "achieved": False})
    return rows


def fp_victim_contamination(out):
    """Where do the ordinary-legitimate false positives actually come from?

    Measured 2026-07-27, and it overturned the earlier reading of this
    number. The false positives are not spread across ordinary shoppers
    whose large early-cycle trips happen to look like drains. They are
    almost entirely the *victims' own* legitimate transactions, occurring
    after a fraudster has emptied the balance: the household's next genuine
    purchase then draws a large percentage of a now-tiny remaining balance
    and trips SPEND_BASELINE_HIGH_DRAW.

    This is the same failure mode already documented for geo-velocity in
    EXPLAIN_features.md family 1 (a victim's own next transaction scored
    against the fraudster's location), but roughly two orders of magnitude
    larger in volume.
    """
    ordinary = (~out["is_fraud"]) & out["fraud_pattern"].isna()
    alerted = out["decision"] != "allow"
    ts = pd.to_datetime(out["timestamp"])
    first_fraud = ts[out["is_fraud"]].groupby(out.loc[out["is_fraud"], "household_id"]).min()

    o = out[ordinary]
    o_ts = ts[ordinary]
    ff = o["household_id"].map(first_fraud)
    is_victim_hh = ff.notna()
    after_fraud = is_victim_hh & (o_ts > ff)
    a = alerted[ordinary]

    def rate(mask):
        n = int(mask.sum())
        return {"n": n, "flagged": int((mask & a).sum()),
                "rate": float((a[mask]).mean()) if n else float("nan")}

    return {
        "clean_household": rate(~is_victim_hh),
        "victim_household_before_fraud": rate(is_victim_hh & ~after_fraud),
        "victim_household_after_fraud": rate(after_fraud),
        "share_of_ordinary_fp_after_fraud":
            float((after_fraud & a).sum() / (a).sum()) if int(a.sum()) else float("nan"),
    }


def recall_ceiling(out):
    """Highest recall any threshold strictly above zero can reach.

    55 fraud rows score exactly 0.00 with no feature firing at all, so they
    are indistinguishable from the 102,153 legitimate rows tied with them.
    That puts a hard ceiling on what threshold tuning alone can achieve, and
    it is a property of the feature set, not of where the thresholds sit.
    """
    is_fraud = out["is_fraud"]
    alerted = (out["risk_score"] > 0) | out["geo_hard_override"].astype(bool)
    tp = int((alerted & is_fraud).sum())
    total = int(is_fraud.sum())
    invisible = out[(is_fraud) & (out["risk_score"] == 0)]
    return {
        "ceiling_recall": tp / total,
        "n_invisible": len(invisible),
        "total_fraud": total,
        "by_pattern": invisible["fraud_pattern"].value_counts().to_dict(),
    }


def threshold_sensitivity_table(out, thresholds):
    """How precision/recall/alert-volume move as the alert threshold shifts
    (SPEC.md §4.4). "Alerted" here = risk_score >= threshold OR the
    geo-velocity hard override fired -- the hard override cannot be
    un-triggered by moving the score threshold, matching how scorer.py
    actually behaves (see explain/EXPLAIN_scorer.md).
    """
    is_fraud = out["is_fraud"]
    hard_override = out["geo_hard_override"]
    risk_score = out["risk_score"]
    n_total = len(out)
    rows = []
    for t in thresholds:
        alerted = (risk_score >= t) | hard_override
        tp = int((alerted & is_fraud).sum())
        fp = int((alerted & ~is_fraud).sum())
        fn = int((~alerted & is_fraud).sum())
        rows.append({
            "score_threshold": t,
            "n_alerts": int(alerted.sum()),
            "alerts_per_1000": alerted.sum() / n_total * 1000,
            "precision": tp / (tp + fp) if (tp + fp) else float("nan"),
            "recall": tp / (tp + fn) if (tp + fn) else float("nan"),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Detection by pattern
# ---------------------------------------------------------------------------

def detection_by_pattern(out):
    """Per-pattern detection rate, plus -- for the missed rows specifically
    -- mean risk_score and the most common reason codes that DID fire but
    weren't enough to cross allow_to_step_up. Answers "which of the missed
    fraud rows are missed and why," not just "how many."
    """
    alerted = out["decision"] != "allow"
    rows = []
    for pattern in FRAUD_PATTERNS:
        mask = out["fraud_pattern"] == pattern
        n = int(mask.sum())
        if n == 0:
            rows.append({"pattern": pattern, "n": 0})
            continue
        detected = int((mask & alerted).sum())
        missed = out[mask & ~alerted]
        top_reasons = (
            missed["reason_codes"].str.split("|").explode().value_counts().head(3).to_dict()
            if len(missed) else {}
        )
        # Every pattern population here is well under SMALL_N_THRESHOLD
        # (77-82 rows each), so each rate carries its Wilson interval per
        # SPEC.md §4.4. A bare "25.64%" on 78 rows reads far more precisely
        # than the data supports.
        ci_low, ci_high = wilson_ci(detected, n)
        rows.append({
            "pattern": pattern,
            "n": n,
            "detected": detected,
            "detection_rate": detected / n,
            "small_n": n < SMALL_N_THRESHOLD,
            "ci_95_low": ci_low,
            "ci_95_high": ci_high,
            "missed": n - detected,
            "missed_mean_risk_score": float(missed["risk_score"].mean()) if len(missed) else float("nan"),
            "missed_top_reason_codes": top_reasons,
        })
    return rows


# ---------------------------------------------------------------------------
# Dollar cost matrix (C4)
# ---------------------------------------------------------------------------

def cost_matrix(out, cfg):
    """SPEC.md §4.4: fraud value caught, fraud value missed, legitimate
    value wrongly blocked, review cost per alert -> savings-to-cost ratio.

    Methodology choices made here (not domain fraud figures -- flagged for
    The author to react to, per explain/EXPLAIN_evaluate.md):
    - "Alerted" (consumes review cost) = decision != allow, i.e. step_up OR
      block. Both require a human/compliance review in a real EBT system,
      including an automatic block, not just step_up.
    - "Fraud value caught" = amount of fraud rows where decision != allow --
      in shadow mode nothing is truly stopped, so this is the value that
      WOULD have been prevented had this decision been acted on live, not a
      measured prevention.
    - "Legitimate value wrongly blocked" = amount of legitimate rows with
      decision == block specifically (an actual denial), not step_up (a
      challenge that still proceeds) -- this is the harm SPEC.md's "wrongly
      blocked" wording describes.
    - The headline savings-to-cost ratio = fraud_value_caught /
      total_review_cost, matching the paper's "spend 1, save 99" framing
      literally: money spent running the review process vs. money saved.
      legit_value_wrongly_blocked is reported as its own line, not folded
      into the ratio -- folding a denied-benefit dollar amount into an
      operational-cost denominator is a framing choice with real
      implications for how "cost" reads, and is left visible rather than
      pre-decided.
    """
    is_fraud = out["is_fraud"]
    alerted = out["decision"] != "allow"
    blocked = out["decision"] == "block"

    fraud_value_caught = float(out.loc[is_fraud & alerted, "amount"].sum())
    fraud_value_missed = float(out.loc[is_fraud & ~alerted, "amount"].sum())
    legit_value_wrongly_blocked = float(out.loc[~is_fraud & blocked, "amount"].sum())
    n_alerts = int(alerted.sum())

    cost_cfg = cfg["review_cost_per_alert_usd"]
    by_level = []
    for level in ["low", "mid", "high"]:
        cost_per_alert = cost_cfg[level]
        total_review_cost = n_alerts * cost_per_alert
        ratio = fraud_value_caught / total_review_cost if total_review_cost else float("inf")
        by_level.append({
            "cost_level": level,
            "review_cost_per_alert_usd": cost_per_alert,
            "n_alerts": n_alerts,
            "total_review_cost_usd": total_review_cost,
            "savings_to_cost_ratio": ratio,
        })
    return {
        "fraud_value_caught_usd": fraud_value_caught,
        "fraud_value_missed_usd": fraud_value_missed,
        "legit_value_wrongly_blocked_usd": legit_value_wrongly_blocked,
        "n_alerts": n_alerts,
        "by_cost_level": by_level,
    }


# ---------------------------------------------------------------------------
# Precision by decision tier -- block requires stacking (or the hard
# override alone), step_up does not; so block-only precision should be much
# higher than the all-alert (17%) figure. The author, 2026-07-25: show both, don't
# let one number stand in for a system with two very different tiers.
# ---------------------------------------------------------------------------

def precision_by_tier(out):
    is_fraud = out["is_fraud"]
    alerted = out["decision"] != "allow"
    blocked = out["decision"] == "block"

    def tier_stats(mask):
        tp = int((mask & is_fraud).sum())
        fp = int((mask & ~is_fraud).sum())
        n = tp + fp
        precision = tp / n if n else float("nan")
        s = {"tp": tp, "fp": fp, "n": n, "precision": precision,
             "small_n": n < SMALL_N_THRESHOLD}
        # SPEC.md §4.4 small-subgroup rule: the block tier is a small
        # subgroup (n=42 here), so its precision gets a CI like any other.
        # Missing this was an inconsistency in earlier versions -- the rule
        # was applied to N1/N2 but not to the tier split or to per-pattern
        # detection, which are the same kind of small-n estimate.
        if s["small_n"] and n:
            s["ci_95_low"], s["ci_95_high"] = wilson_ci(tp, n)
        return s

    return {"alert": tier_stats(alerted), "block": tier_stats(blocked)}


# ---------------------------------------------------------------------------
# Legitimate transactions: challenged (step_up) vs denied (block) -- the
# headline contrast for the block-alone-asymmetry design principle.
# ---------------------------------------------------------------------------

def challenged_vs_denied(out):
    legit = ~out["is_fraud"]
    challenged = out[(out["decision"] == "step_up") & legit]
    denied = out[(out["decision"] == "block") & legit]
    all_denied_geo_override = (
        bool(denied["reason_codes"].str.contains("GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK").all())
        if len(denied) else None
    )
    return {
        "n_challenged": len(challenged),
        "challenged_value_usd": float(challenged["amount"].sum()),
        "n_denied": len(denied),
        "denied_value_usd": float(denied["amount"].sum()),
        "all_denied_are_geo_collateral": all_denied_geo_override,
    }


# ---------------------------------------------------------------------------
# False-positive decomposition -- pressure-tests precision (the author, 2026-07-25):
# is low precision explained by the deliberate N1/N2 challenge trade-off, or
# by something else? Answer with a breakdown, not an assertion either way.
# ---------------------------------------------------------------------------

def fp_breakdown(out):
    alerted = out["decision"] != "allow"
    fp_mask = alerted & ~out["is_fraud"]
    fp = out[fp_mask]
    n_fp = len(fp)
    category = fp["fraud_pattern"].where(fp["fraud_pattern"].isin(["N1", "N2"]), "ordinary_legitimate")
    counts = category.value_counts()
    by_category = [
        {"category": cat, "n": int(n), "pct_of_fp": (n / n_fp * 100) if n_fp else float("nan")}
        for cat, n in counts.items()
    ]
    ordinary_fp = fp[category == "ordinary_legitimate"]
    top_reasons_ordinary = (
        ordinary_fp["reason_codes"].str.split("|").explode().value_counts().to_dict()
        if len(ordinary_fp) else {}
    )
    return {
        "n_fp": n_fp,
        "by_category": by_category,
        "ordinary_fp_top_reason_codes": top_reasons_ordinary,
        "ordinary_fp_mean_risk_score": float(ordinary_fp["risk_score"].mean()) if len(ordinary_fp) else float("nan"),
    }


# ---------------------------------------------------------------------------
# TERMINAL_NEIGHBOUR_CLUSTER -- whole-run firing census
#
# Existing sections show this feature contributing nothing: it is absent from
# every per-pattern missed-reason list in section 5, and it appears 4 times in
# section 1's ordinary-legitimate false-positive reason codes. What none of
# them answer is whether it ever fires on a fraud row anywhere in the run. A
# weighted feature (terminal_temporal_neighbour, 0.10 of the score) with no
# fraud-side firings at all would be a feature carrying weight on no evidence,
# and section 9 of the paper has to say so if that is the case. This census
# answers it by counting directly rather than inferring from the sections that
# happen to surface reason codes.
# ---------------------------------------------------------------------------

def _decision_from_score(score, hard_override, cfg):
    """allow / step_up / block from a score, mirroring scorer.compute_decision.

    Reimplemented here rather than imported: evaluate.py deliberately reads
    only the published CSV (see this file's docstring), and the counterfactual
    below needs to re-derive decisions from a modified score. Kept to the same
    two-path structure as scorer.py -- hard override blocks regardless of
    score, so removing points can never un-block an override row.
    """
    t = cfg["scoring"]["thresholds"]
    return pd.Series(
        np.select(
            [hard_override, score >= t["step_up_to_block"], score >= t["allow_to_step_up"]],
            ["block", "block", "step_up"],
            default="allow",
        ),
        index=score.index,
    )


def neighbour_cluster_census(out, cfg):
    """Every TERMINAL_NEIGHBOUR_CLUSTER firing in the run, split fraud vs.
    legitimate, with the fraud side broken down by pattern.

    "Fires" = terminal_neighbour_subscore_points > 0, which is exactly the
    condition scorer.py uses to emit the reason code (scorer.py
    compute_reason_codes). Both are checked against each other here so the
    count does not depend on which of the two is treated as authoritative.

    Firing is not the same as mattering, so this also runs the counterfactual
    that firing counts alone cannot answer: recompute every decision in the run
    with this family's points subtracted, and count how many decisions change.
    A feature can fire on fraud rows and still be decisive nowhere.
    """
    fired_pts = out[NEIGHBOUR_POINTS_COL] > 0
    fired_code = out["reason_codes"].str.split("|").apply(lambda c: NEIGHBOUR_REASON_CODE in c)
    is_fraud = out["is_fraud"]
    alerted = out["decision"] != "allow"

    fraud_fired = fired_pts & is_fraud
    legit_fired = fired_pts & ~is_fraud

    # Fraud side, per pattern. Every pattern in FRAUD_PATTERNS is listed even
    # at zero -- "P6: 0 firings" is the finding, and a value_counts() dict
    # would silently omit it.
    by_pattern = []
    for pattern in FRAUD_PATTERNS:
        mask = out["fraud_pattern"] == pattern
        n = int(mask.sum())
        k = int((mask & fired_pts).sum())
        by_pattern.append({
            "pattern": pattern, "n": n, "fired": k,
            "fire_rate": k / n if n else float("nan"),
            "fired_and_alerted": int((mask & fired_pts & alerted).sum()),
        })

    # Legitimate side, same three categories section 1's fp_breakdown uses.
    legit_cat = out["fraud_pattern"].where(out["fraud_pattern"].isin(["N1", "N2"]),
                                            "ordinary_legitimate")
    by_legit_category = []
    for cat in ["ordinary_legitimate", "N1", "N2"]:
        mask = (~is_fraud) & (legit_cat == cat)
        n = int(mask.sum())
        k = int((mask & fired_pts).sum())
        by_legit_category.append({"category": cat, "n": n, "fired": k,
                                  "fire_rate": k / n if n else float("nan")})

    n_fraud, n_legit = int(is_fraud.sum()), int((~is_fraud).sum())
    k_fraud, k_legit = int(fraud_fired.sum()), int(legit_fired.sum())
    rate_fraud = k_fraud / n_fraud if n_fraud else float("nan")
    rate_legit = k_legit / n_legit if n_legit else float("nan")

    # Counterfactual: same run, this family's contribution removed.
    hard_override = out["geo_hard_override"].astype(bool)
    score_without = out["risk_score"] - out[NEIGHBOUR_POINTS_COL]
    decision_without = _decision_from_score(score_without, hard_override, cfg)
    changed = decision_without != out["decision"]

    max_possible = cfg["scoring"]["weights"]["terminal_temporal_neighbour"] * 100
    return {
        "codes_agree_with_points": bool((fired_pts == fired_code).all()),
        "n_fired_total": int(fired_pts.sum()),
        "fraud": {"n": n_fraud, "fired": k_fraud, "rate": rate_fraud,
                  "ci_95": wilson_ci(k_fraud, n_fraud)},
        "legit": {"n": n_legit, "fired": k_legit, "rate": rate_legit,
                  "ci_95": wilson_ci(k_legit, n_legit)},
        "lift": rate_fraud / rate_legit if rate_legit else float("nan"),
        "by_pattern": by_pattern,
        "by_legit_category": by_legit_category,
        "max_points_possible": max_possible,
        "max_points_observed": float(out[NEIGHBOUR_POINTS_COL].max()),
        "max_points_observed_on_fraud": (float(out.loc[fraud_fired, NEIGHBOUR_POINTS_COL].max())
                                          if k_fraud else float("nan")),
        "n_decisions_changed_if_removed": int(changed.sum()),
        "n_fraud_decisions_changed_if_removed": int((changed & is_fraud).sum()),
        "n_legit_decisions_changed_if_removed": int((changed & ~is_fraud).sum()),
    }


# ---------------------------------------------------------------------------
# False-positive composition at thresholds 25, 26 and 30
#
# Section 4's 10-point grid shows alerts falling 2,330 -> 431 and precision
# rising 17.12% -> 66.82% between thresholds 20 and 30, but a 10-point grid
# cannot say WHAT clears out. This repeats section 1's fp_breakdown
# decomposition (ordinary-legitimate / N1 / N2) plus the reason-code
# distribution at each of 25, 26 and 30, and -- the part that actually answers
# the question -- decomposes the false positives that clear between each pair
# of adjacent thresholds. Measured, not inferred from the score arithmetic.
# ---------------------------------------------------------------------------

def _alerted_at(out, t):
    """Alert mask at threshold t. Identical rule to
    threshold_sensitivity_table: score >= t OR the geo-velocity hard override,
    which no threshold move can un-trigger."""
    return (out["risk_score"] >= t) | out["geo_hard_override"].astype(bool)


def _fp_profile(out, t):
    alerted = _alerted_at(out, t)
    is_fraud = out["is_fraud"]
    fp = out[alerted & ~is_fraud]
    n_fp = len(fp)
    tp = int((alerted & is_fraud).sum())
    fn = int((~alerted & is_fraud).sum())
    category = fp["fraud_pattern"].where(fp["fraud_pattern"].isin(["N1", "N2"]),
                                          "ordinary_legitimate")
    by_category = [
        {"category": cat,
         "n": int((category == cat).sum()),
         "pct_of_fp": float((category == cat).sum()) / n_fp * 100 if n_fp else float("nan")}
        for cat in ["ordinary_legitimate", "N1", "N2"]
    ]
    codes = (fp["reason_codes"].str.split("|").explode().value_counts().to_dict()
             if n_fp else {})
    # Whole reason-code SETS, not just per-code totals. The per-code counts
    # cannot distinguish "SPEND_BASELINE fired alone" from "SPEND_BASELINE
    # fired alongside something else", which is the entire question here.
    combos = fp["reason_codes"].value_counts() if n_fp else pd.Series(dtype=int)
    solo = int((fp["reason_codes"] == "SPEND_BASELINE_HIGH_DRAW").sum()) if n_fp else 0
    return {
        "threshold": t,
        "n_alerts": int(alerted.sum()),
        "tp": tp,
        "n_fp": n_fp,
        "precision": tp / (tp + n_fp) if (tp + n_fp) else float("nan"),
        "recall": tp / (tp + fn) if (tp + fn) else float("nan"),
        "by_category": by_category,
        "reason_codes": {k: int(v) for k, v in codes.items()},
        "top_combos": [(k, int(v)) for k, v in combos.head(6).items()],
        "n_solo_spend_baseline_fp": solo,
        "pct_solo_spend_baseline_fp": solo / n_fp * 100 if n_fp else float("nan"),
    }


def fp_composition_at_thresholds(out, thresholds, baseline, cfg):
    """Per-threshold FP profiles, plus the between-threshold clearance
    decomposition that names what each step actually removes."""
    grid = [baseline] + list(thresholds)
    profiles = [_fp_profile(out, t) for t in grid]

    # "Single-feature SPEND_BASELINE" by reason-code set alone undercounts the
    # mechanism: a row can carry a second code contributing a fraction of a
    # point and still be a spend-baseline firing in every meaningful sense.
    # So the saturation itself is measured too, alongside the largest
    # everything-else contribution among the cleared rows -- which is what
    # decides whether the second code is doing any work.
    spend_max = cfg["scoring"]["weights"]["spend_baseline"] * 100
    other_cols = [c for c in CONTRIBUTION_COLS_ALL if c != "spend_baseline_subscore_points"]

    cleared = []
    for lo, hi in zip(grid, grid[1:]):
        mask = _alerted_at(out, lo) & ~_alerted_at(out, hi) & ~out["is_fraud"]
        gone = out[mask]
        n = len(gone)
        combos = gone["reason_codes"].value_counts() if n else pd.Series(dtype=int)
        solo = int((gone["reason_codes"] == "SPEND_BASELINE_HIGH_DRAW").sum()) if n else 0
        # Fraud lost over the same step, so the clearance is never read as
        # free: precision does not rise for nothing.
        fraud_lost = int((_alerted_at(out, lo) & ~_alerted_at(out, hi) & out["is_fraud"]).sum())
        cleared.append({
            "from": lo, "to": hi, "n_fp_cleared": n, "n_fraud_lost": fraud_lost,
            "combos": [(k, int(v)) for k, v in combos.head(5).items()],
            "n_solo_spend_baseline": solo,
            "pct_solo_spend_baseline": solo / n * 100 if n else float("nan"),
            "n_spend_saturated": (int((gone["spend_baseline_subscore_points"] >= spend_max - 1e-9).sum())
                                   if n else 0),
            "max_non_spend_points": (float(gone[other_cols].sum(axis=1).max())
                                      if n else float("nan")),
            "score_min": float(gone["risk_score"].min()) if n else float("nan"),
            "score_max": float(gone["risk_score"].max()) if n else float("nan"),
        })
    return {"profiles": profiles, "cleared": cleared, "spend_max_points": spend_max}


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_report(out, cfg):
    lines = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines.append("# CivicSentra Phase 0 -- evaluate.py output")
    lines.append(f"Generated {ts} from data/ebt_scored.csv ({len(out):,} rows).")
    lines.append("Every number below is computed by this script's own execution, "
                  "not assumed or carried over from a previous run.\n")

    # -- 1/2: precision, recall, PR-AUC ------------------------------------
    is_fraud = out["is_fraud"]
    alerted = out["decision"] != "allow"
    tp = int((alerted & is_fraud).sum())
    fp = int((alerted & ~is_fraud).sum())
    fn = int((~alerted & is_fraud).sum())
    precision_op = tp / (tp + fp) if (tp + fp) else float("nan")
    recall_op = tp / (tp + fn) if (tp + fn) else float("nan")
    ap, pr_curve_precision, pr_curve_recall, pr_curve_scores = average_precision(
        out["is_fraud"], out["risk_score"])

    lines.append("## 1. Precision / recall at the current operating point "
                  "(scorer.py's configured thresholds)")
    lines.append(f"Alerted = decision != allow. TP={tp}  FP={fp}  FN={fn}")
    lines.append(f"Precision: {precision_op*100:.2f}%   Recall: {recall_op*100:.2f}%\n")

    lines.append("### Precision by decision tier -- block vs. all alerts")
    lines.append("Block requires either stacked features crossing the 50-point line or the "
                  "geo-velocity hard override firing alone (explain/EXPLAIN_scorer.md); "
                  "step_up requires neither. These are different tiers and one precision "
                  "number hides that:")
    tiers = precision_by_tier(out)
    def tier_line(label, t):
        ci = (f"  [n={t['n']}<{SMALL_N_THRESHOLD}: 95% CI {t['ci_95_low']*100:.2f}%"
              f"-{t['ci_95_high']*100:.2f}%]") if t.get("small_n") else ""
        return f"  {label} TP={t['tp']} FP={t['fp']}  precision={t['precision']*100:.2f}%{ci}"
    lines.append(tier_line("ALL ALERTS (step_up or block):", tiers["alert"]))
    lines.append(tier_line("BLOCK ONLY:                   ", tiers["block"]))
    # The all-alert percentage is interpolated, not typed: a hardcoded "17%"
    # here would keep reading as measured after the measurement moved.
    lines.append("Block-tier precision is far above the all-alert figure, consistent with "
                  "block requiring stacked corroborating signals rather than one feature "
                  f"alone -- this is what makes the {tiers['alert']['precision']*100:.0f}% "
                  "all-alert figure defensible: most of "
                  "the volume behind it is step_up (a challenge, not a denial), not block.\n")

    lines.append("### False-positive composition -- pressure-testing precision")
    lines.append("Is low precision explained by the deliberate N1/N2 challenge trade-off, "
                  "or by something else? Decomposed by category, not asserted either way "
                  "(the author, 2026-07-25):")
    fpb = fp_breakdown(out)
    for row in fpb["by_category"]:
        lines.append(f"  {row['category']}: {row['n']} of {fpb['n_fp']} false positives "
                      f"({row['pct_of_fp']:.2f}%)")
    lines.append(f"\nOrdinary-legitimate FPs -- mean risk_score={fpb['ordinary_fp_mean_risk_score']:.2f}, "
                  f"reason codes behind them: {fpb['ordinary_fp_top_reason_codes']}")
    # Every figure in the sentence below is interpolated from the same frame
    # section 7 uses. Typed-in versions of these silently survive a change in
    # the data and then read as measured -- the defect this file exists to
    # avoid.
    _n1 = out["fraud_pattern"] == "N1"
    _n2 = out["fraud_pattern"] == "N2"
    _ord = (~out["is_fraud"]) & out["fraud_pattern"].isna()
    _n1_rate = 100 * (alerted & _n1).sum() / max(int(_n1.sum()), 1)
    lines.append("N1 and N2 combined explain only a small minority of false positives by count "
                  f"(see percentages above) despite N1's comparatively high {_n1_rate:.0f}% "
                  "false-flag rate "
                  "on its own small population (see section 7) -- the ordinary-legitimate "
                  f"population is ~{int(round(_ord.sum() / max(int(_n1.sum()), 1), -1))}x larger "
                  f"than N1 and ~{int(round(_ord.sum() / max(int(_n2.sum()), 1), -1))}x larger "
                  "than N2, so even a low "
                  "per-category alert rate there dominates the raw false-positive count. Read "
                  "together with section 7's N1/N2 rates, not in isolation from them.\n")

    lines.append("### Where the ordinary-legitimate false positives actually come from")
    vc = fp_victim_contamination(out)
    lines.append("Ordinary legitimate rows split by whether their household was also "
                  "defrauded, and by whether the row falls before or after that fraud:")
    for key, label in [("clean_household", "household never defrauded          "),
                        ("victim_household_before_fraud", "victim household, BEFORE the fraud "),
                        ("victim_household_after_fraud", "victim household, AFTER the fraud  ")]:
        s = vc[key]
        lines.append(f"  {label}: n={s['n']:>7,}  flagged={s['flagged']:>5,}  "
                      f"rate={s['rate']*100:6.2f}%")
    lines.append(f"Share of all ordinary-legitimate false positives that fall after their own "
                  f"household's fraud: {vc['share_of_ordinary_fp_after_fraud']*100:.1f}%")
    lines.append(
        "This is the dominant false-positive mechanism, and it is not what the "
        "aggregate rate suggests. A household whose balance a fraudster has just "
        "drained will have its own next legitimate purchases read as drawing a large "
        "percentage of a now-tiny remaining balance, tripping SPEND_BASELINE_HIGH_DRAW. "
        "Households never defrauded almost never false-positive. The operational "
        "consequence belongs in the report: the people most likely to be repeatedly "
        "challenged by this system are the people who were just robbed. Same failure "
        "mode as the geo-velocity collateral trigger (EXPLAIN_features.md family 1), "
        "roughly two orders of magnitude larger.\n")

    lines.append("## 2. PR-AUC (threshold-independent, average precision over risk_score)")
    lines.append(f"PR-AUC = {ap:.4f}  (not ROC-AUC -- SPEC.md §4.4: ROC-AUC flatters "
                  "classifiers on imbalanced data)\n")

    # -- 3: alerts per 1000 at fixed recall levels -------------------------
    lines.append("## 3. Alerts per 1,000 transactions at fixed recall levels")
    lines.append("(How many of every 1,000 transactions would need review to catch this "
                  "much fraud, if the score threshold were moved to hit each recall target.)")
    ceil = recall_ceiling(out)
    lines.append(
        f"Recall ceiling: no threshold above zero can exceed "
        f"{ceil['ceiling_recall']*100:.2f}% recall. {ceil['n_invisible']} of "
        f"{ceil['total_fraud']} fraud rows score exactly 0.00 with no feature firing "
        f"at all ({ceil['by_pattern']}), so they are indistinguishable from the "
        "legitimate rows tied with them at 0.00. Targets above the ceiling are "
        "reachable only by alerting on every transaction, and are marked below.")
    apr_rows = alerts_per_1000_at_recall(out, RECALL_TARGETS)
    for r in apr_rows:
        if not r["achieved"]:
            lines.append(f"  recall={r['recall_target']*100:.0f}%: not achievable "
                          "(fewer positives than this target implies)")
            continue
        note = ("   <-- DEGENERATE: only reachable by alerting on every "
                "transaction; not an operating point") if r["degenerate"] else ""
        lines.append(f"  recall={r['recall_target']*100:.0f}%: score_threshold>="
                      f"{r['score_threshold']:.2f}, alerts/1000={r['alerts_per_1000']:.2f}, "
                      f"precision at this point={r['precision_at_point']*100:.2f}%{note}")
    lines.append("\nThresholds here are genuine `risk_score >= t` rules, matching section 4. "
                  "An earlier version of this section cut the score-sorted ranking at the "
                  "top-N rows instead, which understated alert volume wherever the cut fell "
                  "inside a block of tied scores -- see alerts_per_1000_at_recall()'s "
                  "docstring for what that produced and why it disagreed with section 4.")
    lines.append("")

    # -- 4: threshold sensitivity -------------------------------------------
    lines.append("## 4. Threshold sensitivity")
    lines.append("(How the alert threshold on risk_score would move precision/recall/volume "
                  "if allow_to_step_up were set differently. Current config value: "
                  f"{cfg['scoring']['thresholds']['allow_to_step_up']}.)")
    tst = threshold_sensitivity_table(out, THRESHOLD_GRID)
    lines.append(tst.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    lines.append("")

    # -- 5: detection by pattern ---------------------------------------------
    lines.append("## 5. Detection rate by fraud pattern")
    lines.append("(P1, skimmer harvest, has no labelled fraud rows by design -- it is the "
                  "compromise mechanism underlying P2-P8, not itself a fraud transaction; "
                  "see explain/EXPLAIN_ebt_generator.md.)")
    for row in detection_by_pattern(out):
        if row["n"] == 0:
            lines.append(f"  {row['pattern']}: n=0 (no rows in this dataset)")
            continue
        ci = (f"  [n<{SMALL_N_THRESHOLD}: 95% CI {row['ci_95_low']*100:.2f}%"
              f"-{row['ci_95_high']*100:.2f}%]") if row["small_n"] else ""
        lines.append(f"  {row['pattern']}: {row['detected']}/{row['n']} detected "
                      f"({row['detection_rate']*100:.2f}%), {row['missed']} missed{ci}")
        if row["missed"] > 0:
            lines.append(f"    missed rows -- mean risk_score={row['missed_mean_risk_score']:.2f}, "
                          f"top reason codes among missed: {row['missed_top_reason_codes']}")
    lines.append("")

    # -- 6: dollar cost matrix -----------------------------------------------
    lines.append("## 6. Dollar cost matrix and savings-to-cost ratio (C4)")
    cm = cost_matrix(out, cfg)
    lines.append(f"Fraud value caught (decision != allow): ${cm['fraud_value_caught_usd']:,.2f}")
    lines.append(f"Fraud value missed (decision == allow):  ${cm['fraud_value_missed_usd']:,.2f}")
    lines.append(f"Legitimate value wrongly BLOCKED (decision == block, is_fraud=False): "
                  f"${cm['legit_value_wrongly_blocked_usd']:,.2f}")
    lines.append(f"Total alerts (review-cost-consuming, decision != allow): {cm['n_alerts']:,}")
    lines.append("")

    cvd = challenged_vs_denied(out)
    lines.append("### Legitimate transactions: challenged vs. denied")
    lines.append(f"CHALLENGED (step_up -- proceeds after review): {cvd['n_challenged']:,} rows, "
                  f"${cvd['challenged_value_usd']:,.2f} in transaction value")
    lines.append(f"DENIED (block -- does not proceed):            {cvd['n_denied']:,} rows, "
                  f"${cvd['denied_value_usd']:,.2f} in transaction value")
    if cvd["all_denied_are_geo_collateral"]:
        lines.append(f"All {cvd['n_denied']} denials carry GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK -- "
                      "these are the documented geo-velocity collateral-trigger cases "
                      "(explain/EXPLAIN_features.md family 1: a fraud victim's own next "
                      "legitimate transaction, scored against the fraudster's out-of-state "
                      "location), not a general pattern of denying ordinary legitimate "
                      "purchases. This is the block-alone-asymmetry design principle "
                      "(explain/EXPLAIN_scorer.md) working as intended: almost nothing "
                      "legitimate is ever actually denied.\n")
    else:
        lines.append("")

    lines.append("Savings-to-cost ratio = fraud value caught / total review cost, across the "
                  "full $6.40-$9.20 review-cost range (SPEC.md §4.4: run the full range, not "
                  "just the midpoint):")
    for row in cm["by_cost_level"]:
        lines.append(f"  {row['cost_level']:>4} (${row['review_cost_per_alert_usd']:.2f}/alert): "
                      f"total review cost=${row['total_review_cost_usd']:,.2f}   "
                      f"ratio={row['savings_to_cost_ratio']:.2f}:1")
    ratios = [r["savings_to_cost_ratio"] for r in cm["by_cost_level"]]
    lines.append(f"\nPaper claims 20-80x (§4.4) / 4-5x (§6), never 99x. Measured ratio here "
                  f"ranges {min(ratios):.2f}:1 to {max(ratios):.2f}:1 across the review-cost "
                  "range -- read together with the report's C4 discussion, not in isolation.\n")

    # -- 7/8: N1 / N2 false-flag rates ---------------------------------------
    lines.append("## 7. N1 false-flag rate (technical failure, legitimate -- is_fraud=False)")
    n1_mask = out["fraud_pattern"] == "N1"
    n1_alerted = alerted[n1_mask]
    lines.append("  " + fmt_rate(rate_stat(n1_alerted, "All N1 rows flagged (step_up or block)")))
    # int() per value: value_counts() yields numpy scalars, whose repr in a
    # dict is np.int64(284) rather than 284 -- an artifact of the printing,
    # not of the number.
    n1_decisions = {k: int(v) for k, v in out.loc[n1_mask, "decision"].value_counts().items()}
    lines.append(f"  N1 decision breakdown: {n1_decisions}")

    crossing_mask = out["n1_crossing_issuance"]
    crossing_alerted = alerted[crossing_mask]
    lines.append("  " + fmt_rate(rate_stat(
        crossing_alerted,
        "Crossing-issuance-boundary N1 subset flagged (step_up or block) -- "
        "the accepted trade-off from config.yaml's ebt_policy_rules 0.8 value")))
    crossing_decisions = {k: int(v) for k, v
                          in out.loc[crossing_mask, "decision"].value_counts().items()}
    lines.append(f"  Crossing-subset decision breakdown: {crossing_decisions}\n")

    lines.append("## 8. N2 false-flag rate (legitimate third-party use -- is_fraud=False)")
    n2_mask = out["fraud_pattern"] == "N2"
    n2_alerted = alerted[n2_mask]
    lines.append("  " + fmt_rate(rate_stat(n2_alerted, "All N2 rows flagged (step_up or block)")))
    lines.append("")

    # -- 9: ordinary legitimate FP rate --------------------------------------
    lines.append("## 9. Ordinary legitimate-transaction false-positive rate")
    lines.append("(is_fraud=False, fraud_pattern is null -- i.e. excluding N1 and N2, which "
                  "are reported separately above per SPEC.md §4.4.)")
    ordinary_mask = (~out["is_fraud"]) & out["fraud_pattern"].isna()
    ordinary_alerted = alerted[ordinary_mask]
    lines.append("  " + fmt_rate(rate_stat(ordinary_alerted, "Ordinary legitimate rows flagged")))
    lines.append("")

    # -- 10: FP rate by locality_class ---------------------------------------
    lines.append("## 10. False-positive rate by locality_class (ordinary legitimate rows)")
    for loc in sorted(out.loc[ordinary_mask, "locality_class"].unique()):
        loc_mask = ordinary_mask & (out["locality_class"] == loc)
        loc_alerted = alerted[loc_mask]
        lines.append("  " + fmt_rate(rate_stat(loc_alerted, f"locality_class={loc}")))
    lines.append("")

    # -- 11: TERMINAL_NEIGHBOUR_CLUSTER firing census ------------------------
    lines.append("## 11. TERMINAL_NEIGHBOUR_CLUSTER -- whole-run firing census")
    nc = neighbour_cluster_census(out, cfg)
    lines.append(
        "The terminal_temporal_neighbour family carries "
        f"{cfg['scoring']['weights']['terminal_temporal_neighbour']:.2f} of the risk score "
        f"({nc['max_points_possible']:.1f} of 100 points at saturation) but is nearly "
        "invisible in the sections above: it appears in no per-pattern missed-reason list "
        "in section 5, and only a handful of times in section 1's false-positive reason "
        "codes. Those sections only surface it where it happens to accompany an alert or a "
        "miss, so neither answers whether it fires on fraud rows at all. This section "
        "counts every firing in the run.")
    lines.append(
        f"'Fires' = {NEIGHBOUR_POINTS_COL} > 0, the same condition scorer.py uses to emit "
        f"{NEIGHBOUR_REASON_CODE}. Points column and reason code agree on every row: "
        f"{nc['codes_agree_with_points']}.")
    lines.append(f"\nTotal firings across all {len(out):,} rows: {nc['n_fired_total']:,}")

    fr, lg = nc["fraud"], nc["legit"]
    lines.append(f"  on FRAUD rows      : {fr['fired']:>5,} of {fr['n']:>7,} "
                  f"= {fr['rate']*100:.2f}%  [95% CI {fr['ci_95'][0]*100:.2f}%"
                  f"-{fr['ci_95'][1]*100:.2f}%]")
    lines.append(f"  on LEGITIMATE rows : {lg['fired']:>5,} of {lg['n']:>7,} "
                  f"= {lg['rate']*100:.2f}%  [95% CI {lg['ci_95'][0]*100:.2f}%"
                  f"-{lg['ci_95'][1]*100:.2f}%]")

    lines.append("\nFraud side, by pattern (every pattern listed, including those with zero "
                  "firings -- a zero is the finding here, and a counts-only table would "
                  "omit it):")
    for row in nc["by_pattern"]:
        rate = f"{row['fire_rate']*100:6.2f}%" if row["n"] else "     --"
        lines.append(f"  {row['pattern']}: fired on {row['fired']:>3} of {row['n']:>3} rows "
                      f"({rate}); of those firings, {row['fired_and_alerted']} are on rows "
                      "that alerted")
    lines.append("\nLegitimate side, by category (same split as section 1's "
                  "false-positive decomposition):")
    for row in nc["by_legit_category"]:
        lines.append(f"  {row['category']:>19}: fired on {row['fired']:>5,} of "
                      f"{row['n']:>7,} rows ({row['fire_rate']*100:.2f}%)")

    # The headline answer is interpolated from the census, not typed: if the
    # data changes so that this feature stops firing on fraud entirely, this
    # sentence has to change with it rather than keep asserting a stale count.
    if fr["fired"] == 0:
        lines.append(
            f"\nIt fires on NO fraud row anywhere in the run ({fr['fired']}/{fr['n']}), "
            f"while firing {lg['fired']:,} times on legitimate rows. On this dataset the "
            f"{nc['max_points_possible']:.1f}-point weight this family carries is supported "
            "by no fraud-side evidence at all, and that has to be stated in the paper as a "
            "weight assigned on prior belief rather than on measured discrimination.")
    else:
        lines.append(
            f"\nIt DOES fire on fraud: {fr['fired']} times, concentrated in "
            + ", ".join(f"{r['pattern']} ({r['fired']})" for r in nc["by_pattern"] if r["fired"])
            + f". The fraud-side firing rate ({fr['rate']*100:.2f}%) is "
            f"{nc['lift']:.1f}x the legitimate-side rate ({lg['rate']*100:.2f}%), so the "
            "feature is not firing at random with respect to the label -- the correct "
            "statement is that it discriminates weakly but non-trivially, NOT that it has "
            "no supporting evidence in the evaluation.")
    _overlap = not (fr["ci_95"][0] > lg["ci_95"][1] or lg["ci_95"][0] > fr["ci_95"][1])
    lines.append(
        f"The two 95% intervals {'overlap' if _overlap else 'do not overlap'}"
        + ("" if _overlap else
           f" ({fr['ci_95'][0]*100:.2f}%-{fr['ci_95'][1]*100:.2f}% against "
           f"{lg['ci_95'][0]*100:.2f}%-{lg['ci_95'][1]*100:.2f}%), so the enrichment is not "
           "an artefact of the small fraud population")
        + f". It still rests on {fr['fired']} fraud rows, which is the caveat that belongs "
        "next to the lift figure whenever it is quoted.")

    lines.append(
        f"\nMagnitude: the largest contribution this family makes anywhere in the run is "
        f"{nc['max_points_observed']:.2f} points of a possible {nc['max_points_possible']:.1f}"
        + (f"; on fraud rows specifically it never exceeds "
           f"{nc['max_points_observed_on_fraud']:.2f} points."
           if fr["fired"] else "; it never contributes to a fraud row at all."))
    lines.append(
        "Counterfactual -- the run re-decided with this family's points subtracted from "
        "every score (allow/step_up/block recomputed by the same two-path rule scorer.py "
        f"uses): {nc['n_decisions_changed_if_removed']} decisions change "
        f"({nc['n_fraud_decisions_changed_if_removed']} on fraud rows, "
        f"{nc['n_legit_decisions_changed_if_removed']} on legitimate rows).")
    if nc["n_decisions_changed_if_removed"] == 0:
        lines.append(
            "Deleting the feature outright would leave every decision in this evaluation "
            "exactly as it stands. That is the finding section 9 should carry, and it is "
            "sharper than a firing count either way: the family fires, it fires "
            "preferentially on fraud, and it is still decisive nowhere -- its contribution "
            "is always too small to move a row across a threshold on its own, and it never "
            "arrives as the marginal point on a row sitting at the line. A weight of "
            f"{cfg['scoring']['weights']['terminal_temporal_neighbour']:.2f} is doing no "
            "work here, which is a statement about this dataset's terminal-sharing "
            "structure as much as about the feature.")
    lines.append("")

    # -- 12: FP composition at thresholds 25, 26, 30 -------------------------
    lines.append("## 12. False-positive composition at thresholds "
                  + ", ".join(str(t) for t in FP_COMPOSITION_THRESHOLDS))
    fpc = fp_composition_at_thresholds(out, FP_COMPOSITION_THRESHOLDS,
                                        FP_COMPOSITION_BASELINE, cfg)
    weights = cfg["scoring"]["weights"]
    lines.append(
        "Section 4's 10-point grid shows alerts collapsing and precision climbing between "
        "thresholds 20 and 30, but a 10-point grid cannot say WHAT clears out. This repeats "
        "the section 1 decomposition (ordinary-legitimate / N1 / N2) and the reason-code "
        f"distribution at each of {', '.join(str(t) for t in FP_COMPOSITION_THRESHOLDS)}, "
        f"with threshold {FP_COMPOSITION_BASELINE} (the configured allow_to_step_up) "
        "included as the anchor the others are measured against.")
    lines.append(
        f"Why 26 specifically: a saturated spend_baseline sub-score contributes at most "
        f"{weights['spend_baseline']*100:.0f}.0 points "
        f"(weight {weights['spend_baseline']:.2f} x 100), so 26 is the first integer "
        "threshold at which a SPEND_BASELINE_HIGH_DRAW firing with nothing alongside it "
        "cannot alert, whatever its sub-score. That is arithmetic; whether it is what "
        "actually clears is measured below.")

    for p in fpc["profiles"]:
        anchor = "  (anchor -- current config)" if p["threshold"] == FP_COMPOSITION_BASELINE else ""
        lines.append(f"\n### threshold {p['threshold']}{anchor}")
        lines.append(f"  alerts={p['n_alerts']:,}  TP={p['tp']:,}  FP={p['n_fp']:,}  "
                      f"precision={p['precision']*100:.2f}%  recall={p['recall']*100:.2f}%")
        for row in p["by_category"]:
            lines.append(f"    {row['category']:>19}: {row['n']:>5,} of {p['n_fp']:,} "
                          f"false positives ({row['pct_of_fp']:.2f}%)")
        lines.append(f"  reason codes across those FPs: {p['reason_codes']}")
        lines.append("  whole reason-code sets (per-code totals above cannot separate "
                      "'fired alone' from 'fired alongside'):")
        for combo, n in p["top_combos"]:
            lines.append(f"    {n:>5,}  {combo}")
        lines.append(f"  SPEND_BASELINE_HIGH_DRAW as the ONLY code: "
                      f"{p['n_solo_spend_baseline_fp']:,} of {p['n_fp']:,} FPs "
                      f"({p['pct_solo_spend_baseline_fp']:.2f}%)")

    lines.append("\n### What clears between each pair of thresholds")
    lines.append("(False positives alerting at the lower threshold and not at the higher "
                  "one, decomposed by their full reason-code set. Fraud lost over the same "
                  "step is shown alongside, so no clearance reads as free.)")
    for c in fpc["cleared"]:
        lines.append(f"\n  {c['from']} -> {c['to']}: {c['n_fp_cleared']:,} false positives "
                      f"clear, {c['n_fraud_lost']} fraud rows lost")
        if c["n_fp_cleared"] == 0:
            lines.append("    (nothing clears over this step)")
            continue
        lines.append(f"    risk_score range of the cleared FPs: "
                      f"{c['score_min']:.2f} - {c['score_max']:.2f}")
        for combo, n in c["combos"]:
            lines.append(f"    {n:>5,}  {combo}")
        lines.append(f"    single-feature SPEND_BASELINE among them: "
                      f"{c['n_solo_spend_baseline']:,} ({c['pct_solo_spend_baseline']:.1f}%)")
        lines.append(f"    spend_baseline SATURATED at {fpc['spend_max_points']:.1f} points "
                      f"among them: {c['n_spend_saturated']:,} of {c['n_fp_cleared']:,}; "
                      f"largest all-other-families contribution on any cleared row: "
                      f"{c['max_non_spend_points']:.2f} points")

    # The interpretive sentence is built from the measured 25->26 step rather
    # than typed, for the same reason as elsewhere in this file.
    step = next((c for c in fpc["cleared"] if c["from"] == 25 and c["to"] == 26), None)
    if step and step["n_fp_cleared"]:
        lines.append(
            f"\nMeasured answer to 'is it single-feature SPEND_BASELINE that clears out': "
            f"largely yes, but the precise statement is narrower. The 20 -> 25 step removes "
            "nothing at all -- no false positive in this run scores between 20 and 25, so "
            "the configured threshold of 20 and a threshold of 25 produce an identical "
            f"false-positive set. Everything happens at 25 -> 26, where {step['n_fp_cleared']:,} "
            f"false positives clear at once, {step['n_solo_spend_baseline']:,} of them "
            f"({step['pct_solo_spend_baseline']:.1f}%) firing SPEND_BASELINE_HIGH_DRAW and "
            f"nothing else, all sitting in a {step['score_min']:.2f}-{step['score_max']:.2f} "
            "score band.")
        lines.append(
            "The remainder of that step is not a different mechanism, and the saturation "
            f"line above is what shows it: all {step['n_spend_saturated']:,} cleared rows "
            f"have spend_baseline saturated at {fpc['spend_max_points']:.1f} points, and no "
            "cleared row draws more than "
            f"{step['max_non_spend_points']:.2f} points from all five other families "
            "combined. The rows carrying a second reason code are spend-baseline "
            "saturation plus a sub-point nudge -- single-feature firings in everything but "
            "the reason-code count. So the honest form of the claim is that the 20 -> 30 "
            "precision gain is bought almost entirely by excluding spend-baseline "
            "saturation, not by any broader improvement in discrimination -- and the price "
            f"is visible above: {sum(c['n_fraud_lost'] for c in fpc['cleared'])} fraud rows "
            "lost across the same range.")
    lines.append("")

    return "\n".join(lines)


def main():
    cfg = load_config()
    out = pd.read_csv(ROOT / "data/ebt_scored.csv", parse_dates=["timestamp"])

    report_text = build_report(out, cfg)
    print(report_text)

    out_path = ROOT / "outputs" / "evaluate_metrics.md"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(report_text)
    print(f"\nWrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
