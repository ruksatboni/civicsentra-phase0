"""Risk scoring — CivicSentra Phase 0 (SPEC.md §4.3).

Combines the six sub-scores from features.py into a 0-100 risk score and an
allow / step_up / block decision, with reason codes naming every contributing
factor. See explain/EXPLAIN_scorer.md for architecture rationale, why this
diverges from SPEC.md's pure linear-weighted-sum description, and the
verification cases checked before this was trusted.

Shadow mode: nothing here actually blocks a real transaction. The decision
column is a label evaluate.py measures against ground truth.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import ROOT, compute_all_features, load_config  # noqa: E402

# subscore column (features.py) -> weight key (config.yaml scoring.weights)
SUBSCORE_TO_WEIGHT_KEY = {
    "geo_velocity_subscore": "geo_velocity",
    "home_location_subscore": "home_location_plausibility",
    "spend_baseline_subscore": "spend_baseline",
    "terminal_reputation_subscore": "terminal_reputation",
    "terminal_neighbour_subscore": "terminal_temporal_neighbour",
    "ebt_policy_rules_subscore": "ebt_policy_rules",
}

CONTRIBUTION_COLS = [f"{col}_points" for col in SUBSCORE_TO_WEIGHT_KEY]


def compute_weighted_score(feats, cfg):
    """Weighted score 0-100: sum over the six families of
    (sub-score x weight x 100). Weights sum to 1.0 (config.yaml), so this
    alone ranges 0-100 without clipping -- clipped defensively anyway in
    case a sub-score ever exceeds [0,1] upstream.
    """
    weights = cfg["scoring"]["weights"]
    contributions = pd.DataFrame(index=feats.index)
    for subscore_col, weight_key in SUBSCORE_TO_WEIGHT_KEY.items():
        contributions[f"{subscore_col}_points"] = feats[subscore_col] * weights[weight_key] * 100
    weighted_score = contributions.sum(axis=1).clip(lower=0, upper=100)
    return weighted_score, contributions


def compute_decision(weighted_score, hard_override, cfg):
    """allow / step_up / block. Two independent paths to block (the author,
    2026-07-25; rationale in explain/EXPLAIN_scorer.md, "Why this isn't a
    plain weighted sum"): the weighted score crossing step_up_to_block
    via STACKED features, or geo-velocity's hard override firing ALONE.
    Neither path is a fallback for the other -- both are checked every time.
    """
    thresholds = cfg["scoring"]["thresholds"]
    decision = np.select(
        [hard_override, weighted_score >= thresholds["step_up_to_block"],
         weighted_score >= thresholds["allow_to_step_up"]],
        ["block", "block", "step_up"],
        default="allow",
    )
    return pd.Series(decision, index=weighted_score.index)


def compute_reason_codes(feats, contributions, hard_override):
    """One or more reason codes per row naming every contributing factor
    (SPEC.md §4.3: "every decision returns reason codes naming the
    contributing factors"). A factor is "contributing" if its sub-score is
    above zero -- this is independent of whether it was enough to change the
    decision, so a step_up decision's reason codes show everything that fed
    it, not just the largest contributor.

    EBT policy rules get THREE separate codes, one per underlying rule check
    (out-of-state / fast-drain / balance-probe), even though the three
    collapse into a single MAX'd sub-score for scoring (features.py) -- for
    an investigator reading reason codes, "which rule fired" matters even
    when only one drove the number.
    """
    flags = pd.DataFrame(index=feats.index)

    flags["GEO_IMPOSSIBLE_TRAVEL_HARD_BLOCK"] = hard_override
    flags["GEO_VELOCITY_ELEVATED_SPEED"] = (feats["geo_velocity_subscore"] > 0) & ~hard_override
    flags["HOME_LOCATION_OUT_OF_ZONE"] = feats["home_location_subscore"] > 0
    flags["HOME_LOCATION_NIGHT_AMPLIFIED"] = (
        (feats["home_location_subscore"] > 0) & feats["home_location_is_night"]
    )
    flags["SPEND_BASELINE_HIGH_DRAW"] = feats["spend_baseline_subscore"] > 0
    flags["TERMINAL_REPUTATION_ELEVATED"] = feats["terminal_reputation_subscore"] > 0
    flags["TERMINAL_NEIGHBOUR_CLUSTER"] = feats["terminal_neighbour_subscore"] > 0
    flags["POLICY_OUT_OF_STATE"] = feats["policy_out_of_state_flag"]
    flags["POLICY_ISSUANCE_DAY_FAST_DRAIN"] = feats["policy_fast_drain_flag"]
    flags["POLICY_BALANCE_PROBE_THEN_PURCHASE"] = feats["policy_balance_probe_flag"]

    def row_codes(row):
        codes = [code for code, fired in row.items() if fired]
        return codes if codes else ["NO_RISK_SIGNALS_DETECTED"]

    return flags.apply(row_codes, axis=1)


def score_transactions(df, cfg=None):
    """Full pipeline: raw transactions -> features -> weighted score ->
    decision -> reason codes. Returns a DataFrame aligned to df's index with
    one row per input transaction. df need not be pre-sorted -- features.py
    handles its own internal sorting.
    """
    if cfg is None:
        cfg = load_config()

    feats = compute_all_features(df, cfg)
    weighted_score, contributions = compute_weighted_score(feats, cfg)
    hard_override = feats["geo_velocity_impossible_override"]
    decision = compute_decision(weighted_score, hard_override, cfg)
    reason_codes = compute_reason_codes(feats, contributions, hard_override)

    out = pd.concat([contributions, pd.DataFrame({
        "risk_score": weighted_score,
        "geo_hard_override": hard_override,
        "decision": decision,
        "reason_codes": reason_codes.apply(lambda codes: "|".join(codes)),
    }, index=df.index)], axis=1)
    return out


if __name__ == "__main__":
    cfg = load_config()
    raw = pd.read_csv(ROOT / "data/ebt_synthetic.csv", parse_dates=["timestamp"])

    print("--- verification case: transaction tripping ONLY spend-baseline, at 75% of "
          "remaining balance, nothing else firing ---")
    synth = raw.sort_values(["household_id", "timestamp"]).reset_index(drop=True)
    synth.loc[0, "amount"] = 75.0
    synth.loc[0, "monthly_benefit_amount"] = 100.0
    synth_scored = score_transactions(synth, cfg)
    r = synth_scored.iloc[0]
    print(f"risk_score={r['risk_score']:.2f}  decision={r['decision']}  "
          f"reason_codes={r['reason_codes']}")
    assert r["decision"] == "step_up", "expected step_up, spend-baseline alone must not block"
    assert abs(r["risk_score"] - 25.0) < 1e-6, f"expected risk_score=25.0, got {r['risk_score']}"
    print("PASS: 75%-of-balance alone scores exactly 25.0 -> step_up, not block.\n")

    print("Scoring full dataset...")
    scored = score_transactions(raw, cfg)
    out = pd.concat([raw, scored], axis=1)
    out.to_csv(ROOT / "data/ebt_scored.csv", index=False)
    print(f"Wrote data/ebt_scored.csv ({len(out)} rows)\n")

    print("=== decision counts ===")
    print(out["decision"].value_counts())
    print()

    print("=== decision counts among is_fraud=True rows ===")
    print(out[out["is_fraud"]]["decision"].value_counts())
    print()

    print("=== decision counts among N1 rows (fraud_pattern == 'N1') ===")
    n1 = out[out["fraud_pattern"] == "N1"]
    print(n1["decision"].value_counts() if len(n1) else "(no N1 rows found under this label)")
    print()

    print("=== 10 sample scored transactions (5 real fraud, 5 random ordinary) ===")
    fraud_sample = out[out["is_fraud"]].sample(min(5, out["is_fraud"].sum()), random_state=42)
    ordinary_sample = out[~out["is_fraud"]].sample(5, random_state=42)
    cols = ["transaction_id", "fraud_pattern", "is_fraud", "risk_score", "decision", "reason_codes"]
    print(pd.concat([fraud_sample, ordinary_sample])[cols].to_string(index=False))
