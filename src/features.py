"""Feature engineering — CivicSentra Phase 0.

Every feature is computed using only information available at or before the
transaction being scored ("point-in-time correctness") -- see the leakage
test at the bottom of this file. See explain/EXPLAIN_features.md for design
rationale, breakpoint sourcing, and known limitations for each feature
family.

Built one family at a time (CLAUDE.md Rule 7): geo-velocity first.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
EARTH_RADIUS_MILES = 3958.8


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def haversine_miles(lat1, lon1, lat2, lon2):
    lat1r, lon1r, lat2r, lon2r = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2r - lat1r, lon2r - lon1r
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def _assert_sorted_by_household_time(df):
    ok = df.groupby("household_id")["timestamp"].apply(lambda s: s.is_monotonic_increasing).all()
    if not ok:
        raise ValueError(
            "features require df sorted by household_id, then timestamp ascending "
            "within each household -- caller must sort before calling"
        )


# ---------------------------------------------------------------------------
# Geo-velocity
# ---------------------------------------------------------------------------

def compute_geo_velocity(df, cfg):
    """Implied travel speed (mph) from a household's previous transaction to
    this one, and a 0-1 sub-score.

    Requires df sorted by household_id, then timestamp ascending -- each
    row's previous transaction must be its own household's most recent
    strictly-earlier row, or the "point-in-time" guarantee breaks.

    Below `min_elapsed_minutes_to_score`, including exactly simultaneous
    timestamps, the pair is not scored at all (sub-score 0) rather than
    computing a speed -- see config.yaml for why: at minute-resolution
    timestamps, very short gaps are dominated by rounding coincidence
    between two independent ordinary transactions, not real signal. This is
    deliberately the SAME rule for zero-elapsed as for "1 minute apart" --
    there is no special case for exactly-simultaneous timestamps.
    """
    gcfg = cfg["features"]["geo_velocity"]
    floor_hr = gcfg["min_elapsed_minutes_to_score"] / 60
    ordinary_max = gcfg["ordinary_max_mph"]
    impossible_mph = gcfg["impossible_mph"]

    _assert_sorted_by_household_time(df)

    g = df.groupby("household_id")
    prev_lat = g["terminal_lat"].shift(1)
    prev_lon = g["terminal_lon"].shift(1)
    prev_ts = g["timestamp"].shift(1)

    dist_mi = haversine_miles(df["terminal_lat"], df["terminal_lon"], prev_lat, prev_lon)
    elapsed_hr = (df["timestamp"] - prev_ts).dt.total_seconds() / 3600

    has_prev = prev_ts.notna()
    scoreable = has_prev & (elapsed_hr >= floor_hr)

    with np.errstate(divide="ignore", invalid="ignore"):
        speed_mph = dist_mi / elapsed_hr
    speed_mph = speed_mph.where(scoreable)  # NaN where not scoreable, incl. elapsed==0

    ramp = ((speed_mph - ordinary_max) / (impossible_mph - ordinary_max)).clip(lower=0, upper=1)
    subscore = ramp.where(scoreable, other=0.0).fillna(0.0)

    impossible_override = scoreable & (subscore >= 1.0)

    return pd.DataFrame({
        "geo_velocity_mph": speed_mph,
        "geo_velocity_elapsed_min": elapsed_hr * 60,
        "geo_velocity_scoreable": scoreable,
        "geo_velocity_subscore": subscore,
        "geo_velocity_impossible_override": impossible_override,
    }, index=df.index)


# ---------------------------------------------------------------------------
# Home-location plausibility
# ---------------------------------------------------------------------------

def compute_home_location_plausibility(df, cfg):
    """Distance from the household's registered home to the terminal, as an
    interaction with hour-of-day. Order-independent -- every input (home
    coordinates, terminal coordinates, the transaction's own timestamp) is
    already known at the moment this transaction arrives, so there is no
    history dependency and no leakage risk here.
    """
    hcfg = cfg["features"]["home_location_plausibility"]
    zone_radius = df["locality_class"].map(hcfg["zone_radius_miles"]).astype(float)
    dist_mi = haversine_miles(df["terminal_lat"], df["terminal_lon"], df["home_lat"], df["home_lon"])

    base = pd.Series(0.0, index=df.index)
    base = base.where(dist_mi <= zone_radius, hcfg["near_zone_subscore"])
    base = base.where(dist_mi <= 2 * zone_radius, hcfg["far_zone_subscore"])

    is_night = df["timestamp"].dt.hour.isin(hcfg["night_hours"])
    multiplier = np.where(is_night, hcfg["night_hour_multiplier"], 1.0)
    subscore = (base * multiplier).clip(lower=0, upper=1)

    return pd.DataFrame({
        "home_dist_miles": dist_mi,
        "home_zone_radius_miles": zone_radius,
        "home_location_is_night": is_night,
        "home_location_subscore": subscore,
    }, index=df.index)


# ---------------------------------------------------------------------------
# Terminal temporal-neighbour (before-only, see config.yaml for why this
# diverges from SPEC.md's literal bidirectional description)
# ---------------------------------------------------------------------------

def compute_terminal_temporal_neighbour(df, cfg):
    """Count of this terminal's OTHER transactions in the window_minutes
    immediately BEFORE this one (never after -- see config.yaml). Requires
    df indexed 0..len(df)-1 with a real 'timestamp' column; does not require
    any particular sort order on entry (sorts internally per terminal).
    """
    ncfg = cfg["features"]["terminal_temporal_neighbour"]
    window_min = ncfg["window_minutes"]
    min_flagged = ncfg["min_neighbours_flagged"]

    counts = np.zeros(len(df), dtype=int)
    for _, g in df[["terminal_id", "timestamp"]].groupby("terminal_id"):
        idx = g.index.values
        ts = g["timestamp"].values.astype("datetime64[m]").astype(np.int64)
        order = np.argsort(ts, kind="stable")
        ts_sorted = ts[order]
        idx_sorted = idx[order]
        for i in range(len(ts_sorted)):
            lo = np.searchsorted(ts_sorted[:i], ts_sorted[i] - window_min, side="left")
            counts[idx_sorted[i]] = i - lo

    neighbour_count = pd.Series(counts, index=df.index)
    # Sub-score ramps with count: 2 neighbours = 0.25, up to 5+ = 1.0. Below
    # min_flagged (2), zero contribution.
    subscore = ((neighbour_count - (min_flagged - 1)) / 4.0).clip(lower=0, upper=1)
    subscore = subscore.where(neighbour_count >= min_flagged, 0.0)

    return pd.DataFrame({
        "terminal_neighbour_count_before": neighbour_count,
        "terminal_neighbour_subscore": subscore,
    }, index=df.index)


# ---------------------------------------------------------------------------
# Terminal reputation, Bayesian shrinkage
# ---------------------------------------------------------------------------

def compute_terminal_reputation(df, cfg):
    """Point-in-time shrunk fraud rate per terminal: uses only transactions
    strictly before this one, both for the terminal's own history and for
    the global prior. Requires a global chronological sort, not a
    per-household one -- sorts internally.
    """
    rcfg = cfg["features"]["terminal_reputation"]
    m = rcfg["shrinkage_m"]
    saturation = rcfg["saturation_rate"]

    order = df[["timestamp", "transaction_id"]].sort_values(["timestamp", "transaction_id"]).index
    ordered = df.loc[order]

    # Both global_rate and the subscore baseline below use ONLY prior-in-time
    # data -- no dataset-wide constant anywhere in this function. The very
    # first transaction globally (n_prior=0) has no history at all; it gets
    # global_rate=0 (there is nothing to base an average on yet), not a
    # dataset-wide average -- using the dataset's eventual average as a
    # fallback was the leakage bug test_leakage.py caught on 2026-07-25 (a
    # truncated dataset's mean differs from the full dataset's mean, so every
    # row's subscore silently depended on data that hadn't happened yet).
    is_fraud_int = ordered["is_fraud"].astype(int)
    global_fraud_prior = is_fraud_int.cumsum().shift(1)
    global_n_prior = pd.Series(np.arange(len(ordered)), index=ordered.index)
    global_rate = (global_fraud_prior / global_n_prior).fillna(0.0)

    term_fraud_prior = ordered.groupby("terminal_id")["is_fraud"].apply(
        lambda s: s.astype(int).cumsum().shift(1)
    ).reset_index(level=0, drop=True)
    term_n_prior = ordered.groupby("terminal_id").cumcount()

    shrunk_rate = (term_fraud_prior.fillna(0) + m * global_rate) / (term_n_prior + m)
    subscore = ((shrunk_rate - global_rate) / (saturation - global_rate).clip(lower=1e-9)).clip(lower=0, upper=1)

    out = pd.DataFrame({
        "terminal_reputation_prior_n": term_n_prior,
        "terminal_reputation_shrunk_rate": shrunk_rate,
        "terminal_reputation_subscore": subscore,
    }, index=ordered.index)
    return out.loc[df.index]


# ---------------------------------------------------------------------------
# Spend-baseline deviation: % of remaining balance x days-since-issuance
# ---------------------------------------------------------------------------

CYCLE_LENGTH_DAYS = 30


def _add_cycle_fields(df, cfg):
    start_date = pd.Timestamp(cfg["ebt_generator"]["time_window"]["start_date"])
    abs_day = (df["timestamp"] - start_date).dt.total_seconds() / 86400
    days_since_issuance = (abs_day - (df["issuance_day"] - 1)) % CYCLE_LENGTH_DAYS
    cycle_number = np.floor((abs_day - (df["issuance_day"] - 1)) / CYCLE_LENGTH_DAYS).astype(int)
    return days_since_issuance, cycle_number


def compute_spend_baseline(df, cfg):
    """% of remaining balance this transaction draws, combined with
    days-since-issuance. Remaining balance is each household's own ACTUAL
    prior spend this benefit cycle (point-in-time cumulative sum, reset at
    each issuance) -- not the generator's internal estimate_remaining_
    balance() curve. A real EBT authorization system knows the exact ledger
    balance, so this is the more accurate choice, not a shortcut. Requires
    df sorted by household_id, then timestamp ascending.
    """
    scfg = cfg["features"]["spend_baseline"]
    _assert_sorted_by_household_time(df)

    days_since_issuance, cycle_number = _add_cycle_fields(df, cfg)
    cycle_key = df["household_id"] + "_c" + cycle_number.astype(str)

    prior_spend = df.groupby(cycle_key)["amount"].cumsum() - df["amount"]
    remaining_before = (df["monthly_benefit_amount"] - prior_spend).clip(lower=0)
    pct_of_remaining = df["amount"] / remaining_before.clip(lower=1.0)

    normal_max = scfg["normal_max_pct"]
    strong_min = scfg["strong_min_pct"]
    mid_max = scfg["mid_band_base_max"]
    day_factor = scfg["day_factor_min"] + (scfg["day_factor_max"] - scfg["day_factor_min"]) * (
        days_since_issuance.clip(lower=0, upper=CYCLE_LENGTH_DAYS) / CYCLE_LENGTH_DAYS
    )

    mid_band_ramp = ((pct_of_remaining - normal_max) / (strong_min - normal_max) * mid_max) * day_factor
    subscore = pd.Series(0.0, index=df.index)
    in_mid_band = (pct_of_remaining >= normal_max) & (pct_of_remaining < strong_min)
    subscore = subscore.where(~in_mid_band, mid_band_ramp.clip(lower=0, upper=mid_max))
    subscore = subscore.where(pct_of_remaining < strong_min, 1.0)

    return pd.DataFrame({
        "days_since_issuance_computed": days_since_issuance,
        "remaining_balance_before": remaining_before,
        "pct_of_remaining_balance": pct_of_remaining,
        "spend_baseline_subscore": subscore,
    }, index=df.index)


# ---------------------------------------------------------------------------
# EBT policy rules
# ---------------------------------------------------------------------------

def compute_ebt_policy_rules(df, cfg, spend_baseline_out):
    """Three discrete rule checks (max of whichever fire, not summed):
    out-of-state, issuance-day fast drain, balance-probe-immediately-before.
    Requires df sorted by household_id, then timestamp ascending (for the
    balance-probe check's "previous transaction" lookup).
    """
    pcfg = cfg["features"]["ebt_policy_rules"]
    _assert_sorted_by_household_time(df)

    out_of_state = (df["terminal_state"] != df["home_state"]).astype(float) * pcfg["out_of_state_subscore"]

    fast_drain_window_days = pcfg["issuance_day_fast_drain_window_hours"] / 24
    days_since_issuance = spend_baseline_out["days_since_issuance_computed"]
    pct_remaining = spend_baseline_out["pct_of_remaining_balance"]
    fast_drain = (
        (days_since_issuance <= fast_drain_window_days)
        & (pct_remaining >= pcfg["issuance_day_fast_drain_pct"])
    ).astype(float) * pcfg["issuance_day_fast_drain_subscore"]

    g = df.groupby("household_id")
    prev_event_type = g["event_type"].shift(1)
    prev_ts = g["timestamp"].shift(1)
    elapsed_min = (df["timestamp"] - prev_ts).dt.total_seconds() / 60
    balance_probe = (
        (df["event_type"] == "purchase")
        & (prev_event_type == "balance_inquiry")
        & (elapsed_min >= 0)
        & (elapsed_min <= pcfg["balance_probe_lead_minutes"])
    ).astype(float) * pcfg["balance_probe_subscore"]

    subscore = pd.concat([out_of_state, fast_drain, balance_probe], axis=1).max(axis=1)

    return pd.DataFrame({
        "policy_out_of_state_flag": out_of_state > 0,
        "policy_fast_drain_flag": fast_drain > 0,
        "policy_balance_probe_flag": balance_probe > 0,
        "ebt_policy_rules_subscore": subscore,
    }, index=df.index)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def compute_all_features(df, cfg):
    """Runs every family and returns one DataFrame of feature/sub-score
    columns aligned to df's original index. df must NOT already be sorted
    in a way the caller depends on -- this function sorts its own working
    copy and returns results reindexed to match the input df's order.
    """
    work = df.sort_values(["household_id", "timestamp"]).reset_index(drop=False)
    work = work.rename(columns={"index": "_orig_index"})

    geo = compute_geo_velocity(work, cfg)
    home = compute_home_location_plausibility(work, cfg)
    spend = compute_spend_baseline(work, cfg)
    policy = compute_ebt_policy_rules(work, cfg, spend)
    neighbour = compute_terminal_temporal_neighbour(work, cfg)
    reputation = compute_terminal_reputation(work, cfg)

    combined = pd.concat([geo, home, spend, policy, neighbour, reputation], axis=1)
    combined.index = work["_orig_index"].values
    return combined.loc[df.index]


SUBSCORE_COLS = [
    "geo_velocity_subscore",
    "home_location_subscore",
    "terminal_neighbour_subscore",
    "terminal_reputation_subscore",
    "spend_baseline_subscore",
    "ebt_policy_rules_subscore",
]


if __name__ == "__main__":
    cfg = load_config()
    raw = pd.read_csv(ROOT / "data/ebt_synthetic.csv", parse_dates=["timestamp"])

    feats = compute_all_features(raw, cfg)
    out = pd.concat([raw[["transaction_id", "household_id", "timestamp", "locality_class",
                           "is_fraud", "fraud_pattern"]], feats], axis=1)

    print("=== sub-score summary, all six families ===")
    print(out[SUBSCORE_COLS].describe().T[["count", "mean", "std", "min", "50%", "max"]])
    print()

    print("=== geo_velocity: impossible-travel hard-override rows ===")
    print(out[out["geo_velocity_impossible_override"]].to_string())
    print()

    print("=== home_location_plausibility: 5 rows beyond 2x zone radius ===")
    far = out[out["home_dist_miles"] > 2 * out["home_zone_radius_miles"]]
    print(far.sample(min(5, len(far)), random_state=42)[
        ["transaction_id", "locality_class", "home_dist_miles", "home_zone_radius_miles",
         "home_location_is_night", "home_location_subscore", "is_fraud", "fraud_pattern"]
    ].to_string())
    print()

    print("=== terminal_temporal_neighbour: 5 rows with >=2 prior neighbours ===")
    clustered = out[out["terminal_neighbour_count_before"] >= 2]
    print(clustered.sample(min(5, len(clustered)), random_state=42)[
        ["transaction_id", "terminal_neighbour_count_before", "terminal_neighbour_subscore",
         "is_fraud", "fraud_pattern"]
    ].to_string())
    print()

    print("=== terminal_reputation: top 5 by shrunk rate ===")
    top_rep = out.sort_values("terminal_reputation_shrunk_rate", ascending=False).head(5)
    print(top_rep[["transaction_id", "terminal_reputation_prior_n", "terminal_reputation_shrunk_rate",
                    "terminal_reputation_subscore", "is_fraud", "fraud_pattern"]].to_string())
    print()

    print("=== spend_baseline: the >=70%-of-balance verification row (P4 sample) ===")
    p4 = out[out["fraud_pattern"] == "P4"].head(3)
    print(p4[["transaction_id", "pct_of_remaining_balance", "days_since_issuance_computed",
              "spend_baseline_subscore"]].to_string())
    print()
    print("--- synthetic check: a transaction at exactly 75% of remaining balance, nothing else firing ---")
    synth = raw.iloc[[0]].copy()
    synth["amount"] = 0.75 * 100.0
    synth["monthly_benefit_amount"] = 100.0
    synth_feats = compute_spend_baseline(
        raw.sort_values(["household_id", "timestamp"]).reset_index(drop=True).assign(
            amount=lambda d: d["amount"].where(d.index != 0, 75.0),
            monthly_benefit_amount=lambda d: d["monthly_benefit_amount"].where(d.index != 0, 100.0),
        ), cfg
    )
    print(f"pct_of_remaining_balance={synth_feats.iloc[0]['pct_of_remaining_balance']:.3f}, "
          f"spend_baseline_subscore={synth_feats.iloc[0]['spend_baseline_subscore']:.3f} "
          f"(expect subscore=1.0 -> weighted contribution 0.25*1.0*100=25 -> step-up, not block)")
    print()

    print("=== ebt_policy_rules: flag rate by fraud_pattern ===")
    lbl = out["fraud_pattern"].fillna("(ordinary)").replace("", "(ordinary)")
    for col in ["policy_out_of_state_flag", "policy_fast_drain_flag", "policy_balance_probe_flag"]:
        print(f"-- {col} --")
        print((out[col].groupby(lbl).mean() * 100).round(2).astype(str) + "%")
        print()

    print("=== not-scoreable / edge rows: first transaction per household ===")
    print(f"geo_velocity not scoreable: {(~out['geo_velocity_scoreable']).sum()} / {len(out)}")
