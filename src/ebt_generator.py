"""EBT synthetic transaction generator — CivicSentra Phase 0.

Produces two datasets from the same population/behaviour model, differing
only in fraud prevalence (see config.yaml: ebt_generator.prevalence_regimes):
  - primary:    elevated prevalence, for statistical power
  - realistic:  ~0.02% prevalence, derived from GAO-25-107964, for testing
                whether conclusions hold outside the power-boosted regime

See explain/EXPLAIN_ebt_generator.md for what every design choice means and
where each parameter comes from (public record vs. The author's experience vs.
labelled assumption).
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
DATA_DIR = ROOT / "data"

MILES_PER_DEG_LAT = 69.0
EARTH_RADIUS_MILES = 3958.8
CYCLE_LENGTH_DAYS = 30

# Three synthetic regional hubs, not real specific cities — spaced far apart
# so P5 (out-of-state) distances are realistic. Coordinates are plausible
# continental-US values chosen only to make Haversine distances meaningful.
HUBS = {
    "State_A": (39.5, -84.2),
    "State_B": (35.8, -86.3),
    "State_C": (44.9, -93.1),
}
HUB_NAMES = list(HUBS.keys())

LOCALITY_RADIUS_MILES = {
    "urban": (0.0, 5.0),
    "suburban": (5.0, 15.0),
    "rural": (15.0, 40.0),
}


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def offset_latlon(lat, lon, miles, bearing_rad):
    dlat = (miles * np.cos(bearing_rad)) / MILES_PER_DEG_LAT
    dlon = (miles * np.sin(bearing_rad)) / (MILES_PER_DEG_LAT * np.cos(np.radians(lat)))
    return lat + dlat, lon + dlon


def haversine_miles(lat1, lon1, lat2, lon2):
    lat1r, lon1r, lat2r, lon2r = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def cycle_starts_for_household(issuance_day, n_days):
    starts = []
    cur = issuance_day - 1
    while cur < n_days:
        starts.append(cur)
        cur += CYCLE_LENGTH_DAYS
    return starts


def days_since_issuance_for(abs_day, issuance_day):
    """abs_day is an absolute day offset from the window start (day 0), not
    from this household's own cycle start — households whose issuance_day
    isn't 1 need the phase offset removed before taking `% CYCLE_LENGTH_DAYS`,
    or the result is measured from the wrong origin."""
    first_cycle_start = issuance_day - 1
    return (abs_day - first_cycle_start) % CYCLE_LENGTH_DAYS


# ---------------------------------------------------------------------------
# Population
# ---------------------------------------------------------------------------

def generate_households(n, cfg, rng):
    mix = cfg["population"]["locality_class_mix"]
    classes = list(mix.keys())
    probs = list(mix.values())
    locality = rng.choice(classes, size=n, p=probs)
    hubs = rng.choice(HUB_NAMES, size=n)

    lats = np.empty(n)
    lons = np.empty(n)
    for i in range(n):
        lo, hi = LOCALITY_RADIUS_MILES[locality[i]]
        miles = rng.uniform(lo, hi)
        bearing = rng.uniform(0, 2 * np.pi)
        hub_lat, hub_lon = HUBS[hubs[i]]
        lats[i], lons[i] = offset_latlon(hub_lat, hub_lon, miles, bearing)

    issuance_day = rng.integers(1, 29, size=n)
    # Synthetic benefit-size distribution shaped like a typical SNAP
    # allotment (a few hundred dollars/month), NOT calibrated to official
    # USDA average-benefit statistics — see EXPLAIN doc.
    monthly_benefit = np.round(rng.lognormal(mean=np.log(300), sigma=0.4, size=n), 2)
    monthly_benefit = np.clip(monthly_benefit, 50, 900)

    freq_lo, freq_hi = cfg["population"]["transactions_per_household_per_month"]
    monthly_txn_trait = rng.uniform(freq_lo, freq_hi, size=n)

    n2_frac = cfg["n2_secondary_user"]["fraction_households_with_secondary_user"]
    has_secondary = rng.random(n) < n2_frac

    return pd.DataFrame({
        "household_id": [f"H{i:06d}" for i in range(n)],
        "locality_class": locality,
        "home_state": hubs,
        "home_lat": lats,
        "home_lon": lons,
        "issuance_day": issuance_day,
        "monthly_benefit_amount": monthly_benefit,
        "monthly_txn_trait": monthly_txn_trait,
        "has_secondary_user": has_secondary,
    })


def generate_terminals(n, rng):
    hubs = rng.choice(HUB_NAMES, size=n)
    size_classes = rng.choice(["small", "medium", "large"], size=n, p=[0.6, 0.3, 0.1])
    lats = np.empty(n)
    lons = np.empty(n)
    for i in range(n):
        miles = rng.uniform(0, 40)
        bearing = rng.uniform(0, 2 * np.pi)
        hub_lat, hub_lon = HUBS[hubs[i]]
        lats[i], lons[i] = offset_latlon(hub_lat, hub_lon, miles, bearing)

    return pd.DataFrame({
        "terminal_id": [f"T{i:05d}" for i in range(n)],
        "state": hubs,
        "lat": lats,
        "lon": lons,
        "store_size_class": size_classes,
    })


def assign_home_clusters(households, terminals, cfg, rng):
    lo, hi = cfg["population"]["home_cluster_size"]
    clusters = {}
    for state in HUB_NAMES:
        state_terms = terminals[terminals["state"] == state].reset_index(drop=True)
        state_households = households[households["home_state"] == state]
        term_lats = state_terms["lat"].values
        term_lons = state_terms["lon"].values
        term_ids = state_terms["terminal_id"].values
        for _, h in state_households.iterrows():
            d = haversine_miles(h["home_lat"], h["home_lon"], term_lats, term_lons)
            k = int(rng.integers(lo, hi + 1))
            nearest = np.argsort(d)[:k]
            clusters[h["household_id"]] = list(term_ids[nearest])
    return clusters


def select_compromised_terminals(terminals, cfg, rng, n_days):
    frac = cfg["compromised_terminals"]["fraction_ever_compromised"]
    n_compromised = max(1, int(round(len(terminals) * frac)))
    compromised_ids = rng.choice(terminals["terminal_id"].values, size=n_compromised, replace=False)
    win_lo, win_hi = cfg["compromised_terminals"]["compromise_window_days"]
    rows = []
    for tid in compromised_ids:
        window_len = int(rng.integers(win_lo, win_hi + 1))
        start_day = int(rng.integers(0, max(1, n_days - window_len)))
        rows.append({
            "terminal_id": tid,
            "compromise_start_day": start_day,
            "compromise_end_day": start_day + window_len,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Legitimate + N1 + N2 transaction walk (chronological, per household-cycle,
# with real balance depletion — see EXPLAIN doc for why this ordering matters)
# ---------------------------------------------------------------------------

def pick_terminal(cluster_ids, rng, prefer_first=True):
    if prefer_first and len(cluster_ids) > 1:
        weights = np.array([0.5] + [0.5 / (len(cluster_ids) - 1)] * (len(cluster_ids) - 1))
    else:
        weights = np.ones(len(cluster_ids)) / len(cluster_ids)
    return rng.choice(cluster_ids, p=weights)


def sample_time_of_day(rng, evening_weighted=False):
    if evening_weighted:
        hour = int(np.clip(rng.normal(17, 3), 0, 23))
    else:
        hour = int(np.clip(rng.normal(13, 4), 0, 23))
    minute = int(rng.integers(0, 60))
    return hour, minute


def generate_legit_n1_n2(households, terminals_by_id, clusters, cfg, rng, start_date, n_days):
    gen_cfg = cfg
    primary_lo, primary_hi = gen_cfg["primary_user_amount_fraction_of_balance"]
    late_trip_prob = gen_cfg["late_cycle_trip_probability"]
    n1_cfg = gen_cfg["n1_technical_failure"]
    n2_cfg = gen_cfg["n2_secondary_user"]

    rows = []
    for h in households.itertuples():
        cluster = clusters[h.household_id]
        primary_cluster = cluster
        secondary_cluster = list(reversed(cluster)) if len(cluster) > 1 else cluster

        for cycle_start in cycle_starts_for_household(h.issuance_day, n_days):
            cycle_len = min(CYCLE_LENGTH_DAYS, n_days - cycle_start)
            if cycle_len <= 0:
                continue

            n_primary = int(round(np.clip(rng.normal(h.monthly_txn_trait, 1.0), 6, 16)))
            # Mixture, not pure Beta(2,5): a front-loaded majority (big
            # shop soon after issuance, tapering) plus a late_trip_prob
            # share of trips uniform across the whole cycle, modelling
            # occasional late-cycle top-up shops. Pure Beta(2,5) left
            # days_since_issuance >= 25 almost entirely empty of normal
            # transactions (0.06% of rows) while N1 events cluster there
            # (24.4%) — a detector would have learned "late cycle = N1"
            # from a generator artifact, not genuine behaviour.
            is_late_trip = rng.random(n_primary) < late_trip_prob
            front_loaded = rng.beta(2, 5, size=n_primary) * cycle_len
            uniform_late = rng.uniform(0, cycle_len, size=n_primary)
            primary_offsets = np.sort(np.where(is_late_trip, uniform_late, front_loaded))

            events = [(off, "primary") for off in primary_offsets]

            if h.has_secondary_user:
                n2_lo, n2_hi = n2_cfg["transactions_per_month"]
                n_secondary = int(rng.integers(n2_lo, n2_hi + 1))
                secondary_offsets = rng.uniform(0, cycle_len, size=n_secondary)
                events += [(off, "secondary") for off in secondary_offsets]

            n1_this_cycle = False
            if rng.random() < n1_cfg["candidate_probability_per_household_month"]:
                is_crossing = rng.random() < n1_cfg["crossing_issuance_boundary_fraction"]
                is_reversed = rng.random() < n1_cfg["auto_reversal_fraction"]
                if not is_reversed:
                    n1_this_cycle = True
                    if is_crossing:
                        n1_offset = cycle_len - 1
                        n1_kind = "crossing"
                    else:
                        n1_offset = rng.uniform(0, cycle_len)
                        n1_kind = "ordinary"
                    events.append((n1_offset, "n1"))

            events.sort(key=lambda e: e[0])

            balance = h.monthly_benefit_amount
            for offset, role in events:
                abs_day = cycle_start + offset
                ts = start_date + pd.Timedelta(days=abs_day)
                is_balance_inquiry = role == "primary" and rng.random() < 0.02

                if role == "primary":
                    hour, minute = sample_time_of_day(rng, evening_weighted=False)
                    terminal_id = pick_terminal(primary_cluster, rng, prefer_first=True)
                    if is_balance_inquiry:
                        amount = 0.0
                    else:
                        frac = rng.uniform(primary_lo, primary_hi)
                        amount = round(min(balance, balance * frac), 2)
                    fraud_pattern = ""
                elif role == "secondary":
                    hour, minute = sample_time_of_day(rng, evening_weighted=True)
                    terminal_id = pick_terminal(secondary_cluster, rng, prefer_first=True)
                    amt_lo, amt_hi = n2_cfg["amount_fraction_of_balance"]
                    frac = rng.uniform(amt_lo, amt_hi)
                    amount = round(min(balance, balance * frac), 2)
                    fraud_pattern = "N2"
                else:  # n1
                    hour, minute = sample_time_of_day(rng, evening_weighted=False)
                    terminal_id = pick_terminal(primary_cluster, rng, prefer_first=True)
                    if n1_kind == "crossing":
                        amount = round(h.monthly_benefit_amount * rng.uniform(0.4, 0.9), 2)
                    else:
                        frac = rng.uniform(primary_lo, primary_hi)
                        amount = round(min(balance, balance * frac), 2)
                    fraud_pattern = "N1"

                ts = ts.replace(hour=hour, minute=minute, second=0, microsecond=0, nanosecond=0)
                term = terminals_by_id[terminal_id]

                rows.append({
                    "household_id": h.household_id,
                    "user_role": "secondary" if role == "secondary" else "primary",
                    "event_type": "balance_inquiry" if is_balance_inquiry else "purchase",
                    "timestamp": ts,
                    "amount": amount,
                    "terminal_id": terminal_id,
                    "terminal_lat": term["lat"],
                    "terminal_lon": term["lon"],
                    "terminal_state": term["state"],
                    "home_lat": h.home_lat,
                    "home_lon": h.home_lon,
                    "home_state": h.home_state,
                    "locality_class": h.locality_class,
                    "issuance_day": h.issuance_day,
                    "days_since_issuance": round(offset, 2),
                    "monthly_benefit_amount": h.monthly_benefit_amount,
                    "is_fraud": False,
                    "fraud_pattern": fraud_pattern,
                    "n1_crossing_issuance": role == "n1" and n1_kind == "crossing",
                })

                if role != "n1" or n1_kind == "ordinary":
                    balance = max(0.0, balance - amount)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Fraud injection (P1-P8)
# ---------------------------------------------------------------------------

def estimate_remaining_balance(monthly_benefit, days_since_issuance):
    frac_remaining = max(0.05, 1 - (days_since_issuance / CYCLE_LENGTH_DAYS) * 0.9)
    return monthly_benefit * frac_remaining


def inject_fraud(households, terminals_by_id, clusters, compromised, cfg, rng, start_date, n_days, target_prevalence, baseline_row_count):
    fp_cfg = cfg["fraud_patterns"]
    fraud_row_budget = max(8, int(round(target_prevalence * baseline_row_count / (1 - target_prevalence))))

    # P6 gets a fixed share of the budget, delivered as clustered cashout
    # batches; the rest is split across the single-victim patterns.
    p6_budget = max(0, int(round(fraud_row_budget * 0.15)))
    remaining_budget = fraud_row_budget - p6_budget
    # P1 is not injected as fraud (see note below) — its budget share is
    # dropped, not redistributed silently; the other patterns simply split
    # what remains.
    single_patterns = ["P2", "P3", "P4", "P5", "P7", "P8"]
    per_pattern_budget = max(1, remaining_budget // len(single_patterns))

    household_ids = households["household_id"].values
    household_by_id = households.set_index("household_id")

    # Households whose legitimate activity overlapped a compromised terminal
    # during its compromise window — the real P1 harvest pool for patterns
    # that need a preceding "capture" event (P2, P3, P8).
    exposed_households = []
    if len(compromised):
        for _, comp in compromised.iterrows():
            eligible = [
                hid for hid in household_ids
                if comp["terminal_id"] in clusters.get(hid, [])
            ]
            for hid in eligible:
                exposed_households.append((hid, comp["compromise_start_day"], comp["compromise_end_day"]))

    rows = []

    def make_row(hid, terminal_id, ts, amount, pattern, event_type="purchase"):
        h = household_by_id.loc[hid]
        term = terminals_by_id[terminal_id]
        ts = ts.round("min")  # Timedelta(hours=float)/(minutes=float) arithmetic
        # upstream leaves sub-minute fractional noise; transaction logs don't.
        abs_day = (ts - start_date) / pd.Timedelta(days=1)
        dsi = days_since_issuance_for(abs_day, int(h["issuance_day"]))
        rows.append({
            "household_id": hid,
            "user_role": "primary",
            "event_type": event_type,
            "timestamp": ts,
            "amount": round(max(0.0, amount), 2),
            "terminal_id": terminal_id,
            "terminal_lat": term["lat"],
            "terminal_lon": term["lon"],
            "terminal_state": term["state"],
            "home_lat": h["home_lat"],
            "home_lon": h["home_lon"],
            "home_state": h["home_state"],
            "locality_class": h["locality_class"],
            "issuance_day": h["issuance_day"],
            "days_since_issuance": round(dsi, 2),
            "monthly_benefit_amount": h["monthly_benefit_amount"],
            "is_fraud": True,
            "fraud_pattern": pattern,
        })

    def random_victim():
        return household_ids[rng.integers(0, len(household_ids))]

    terminal_ids_all = list(terminals_by_id.keys())

    def victim_cluster_terminal(hid):
        cl = clusters.get(hid)
        if not cl:
            return terminal_ids_all[rng.integers(0, len(terminal_ids_all))]
        return cl[rng.integers(0, len(cl))]

    def anchor_ts(day_offset, evening_weighted=False):
        # The hour/minute is sampled once and anchored to this event's own
        # date — deliberately NOT resampled again for any later event
        # derived from it. Sequential events (test->drain, probe->drain,
        # attempt->attempt->drain) must be built with pd.Timedelta from a
        # prior event's timestamp instead, or their clock times end up
        # independently randomized and can appear out of order even though
        # the underlying day offsets are correctly sequenced.
        date_part = start_date + pd.Timedelta(days=int(np.floor(day_offset)))
        hour, minute = sample_time_of_day(rng, evening_weighted=evening_weighted)
        return date_part.replace(hour=hour, minute=minute, second=0, microsecond=0, nanosecond=0)

    def balance_for_ts(hid, ts):
        abs_day = (ts - start_date) / pd.Timedelta(days=1)
        dsi = days_since_issuance_for(abs_day, int(household_by_id.loc[hid, "issuance_day"]))
        return estimate_remaining_balance(household_by_id.loc[hid, "monthly_benefit_amount"], dsi)

    # P1 (skimmer harvest) is deliberately NOT injected as a fraud row here.
    # The author, 2026-07-24: P1 is the real cardholder's own legitimate purchase —
    # the skimmer captures data passively; the transaction itself has
    # nothing wrong with it at the moment it happens. Labelling it fraud
    # would ask the detector to flag a transaction using information (that
    # the terminal is compromised) that doesn't exist yet, and every such
    # row would be a guaranteed, meaningless miss dragging recall down.
    # Real P1-equivalent rows already exist in the baseline data as
    # ordinary legitimate transactions that happen to land on a compromised
    # terminal during its window — ground truth for that is the
    # `terminal_compromised_at_time` column added in generate_dataset(),
    # which lets evaluate.py test whether terminal-reputation eventually
    # flags the compromised terminal without counting legitimate purchases
    # as missed fraud.

    # --- P2: test transaction, then drain (real elapsed time between them) ---
    n_p2 = 0
    while n_p2 < per_pattern_budget and exposed_households:
        hid, c_start, c_end = exposed_households[rng.integers(0, len(exposed_households))]
        capture_day = rng.uniform(c_start, c_end)
        term = victim_cluster_terminal(hid)
        test_amt_lo, test_amt_hi = fp_cfg["p2_test_transaction_amount_usd"]
        test_ts = anchor_ts(capture_day)
        make_row(hid, term, test_ts, rng.uniform(test_amt_lo, test_amt_hi), "P2")
        delay_lo, delay_hi = fp_cfg["p2_delay_before_drain_hours"]
        drain_ts = test_ts + pd.Timedelta(hours=rng.uniform(delay_lo, delay_hi))
        bal = balance_for_ts(hid, drain_ts)
        make_row(hid, term, drain_ts, bal * rng.uniform(0.6, 1.0), "P2")
        n_p2 += 2

    # --- P3: balance probe immediately before drain ---
    n_p3 = 0
    while n_p3 < per_pattern_budget and exposed_households:
        hid, c_start, c_end = exposed_households[rng.integers(0, len(exposed_households))]
        capture_day = rng.uniform(c_start, c_end)
        term = victim_cluster_terminal(hid)
        drain_ts = anchor_ts(capture_day + rng.uniform(0.1, 3))
        lead_lo, lead_hi = fp_cfg["p3_balance_probe_lead_minutes"]
        probe_ts = drain_ts - pd.Timedelta(minutes=rng.uniform(lead_lo, lead_hi))
        make_row(hid, term, probe_ts, 0.0, "P3", event_type="balance_inquiry")
        bal = balance_for_ts(hid, drain_ts)
        make_row(hid, term, drain_ts, bal * rng.uniform(0.6, 1.0), "P3")
        n_p3 += 2

    # --- P4: issuance-day fast drain — hour is derived directly from the
    # issuance-window offset, not resampled, so it stays inside the window ---
    n_p4 = 0
    while n_p4 < per_pattern_budget:
        hid = random_victim()
        h = household_by_id.loc[hid]
        cycle_starts = cycle_starts_for_household(int(h["issuance_day"]), n_days)
        if not cycle_starts:
            continue
        issuance_abs_day = cycle_starts[rng.integers(0, len(cycle_starts))]
        win_lo, win_hi = fp_cfg["p4_issuance_day_drain_window_hours"]
        drain_ts = (start_date + pd.Timedelta(days=issuance_abs_day)
                    + pd.Timedelta(hours=rng.uniform(win_lo, win_hi)))
        term = victim_cluster_terminal(hid)
        make_row(hid, term, drain_ts, h["monthly_benefit_amount"] * rng.uniform(0.8, 1.0), "P4")
        n_p4 += 1

    # --- P5: out-of-state drain ---
    n_p5 = 0
    while n_p5 < per_pattern_budget:
        hid = random_victim()
        h = household_by_id.loc[hid]
        other_states = [s for s in HUB_NAMES if s != h["home_state"]]
        far_state = other_states[rng.integers(0, len(other_states))]
        far_terms = [tid for tid, t in terminals_by_id.items() if t["state"] == far_state]
        term = far_terms[rng.integers(0, len(far_terms))]
        drain_ts = anchor_ts(rng.uniform(0, n_days))
        bal = balance_for_ts(hid, drain_ts)
        make_row(hid, term, drain_ts, bal * rng.uniform(0.6, 1.0), "P5")
        n_p5 += 1

    # --- P6: terminal clustering — batches of victims cashed out through
    # one terminal within a short shared window; hour is derived directly
    # from position within that window, not resampled ---
    p6_count = 0
    cashout_pool = terminals_by_id  # any terminal can host a cashout burst
    cashout_terminal_ids = list(cashout_pool.keys())
    while p6_count < p6_budget:
        cashout_terminal = cashout_terminal_ids[rng.integers(0, len(cashout_terminal_ids))]
        win_lo, win_hi = fp_cfg["p6_cards_per_cashout_terminal"]
        k = int(rng.integers(win_lo, win_hi + 1))
        window_hours = fp_cfg["p6_cashout_window_hours"]
        window_start = rng.uniform(0, max(1, n_days - window_hours / 24.0))
        window_start_ts = start_date + pd.Timedelta(days=window_start)
        for _ in range(k):
            if p6_count >= p6_budget:
                break
            hid = random_victim()
            drain_ts = window_start_ts + pd.Timedelta(hours=rng.uniform(0, window_hours))
            bal = balance_for_ts(hid, drain_ts)
            make_row(hid, cashout_terminal, drain_ts, bal * rng.uniform(0.6, 1.0), "P6")
            p6_count += 1

    # --- P7: off-hours drain ---
    n_p7 = 0
    off_start_str, off_end_str = fp_cfg["p7_off_hours_range"]
    off_start_hour = int(off_start_str.split(":")[0])
    off_end_hour = int(off_end_str.split(":")[0])
    while n_p7 < per_pattern_budget:
        hid = random_victim()
        h = household_by_id.loc[hid]
        term = victim_cluster_terminal(hid)
        day_offset = rng.uniform(0, n_days)
        # off_end_hour < off_start_hour (wraps past midnight): sample within
        # [off_start_hour, 24) union [0, off_end_hour)
        if rng.random() < 0.5:
            hour = int(rng.integers(off_start_hour, 24))
        else:
            hour = int(rng.integers(0, off_end_hour))
        minute = int(rng.integers(0, 60))
        drain_ts = (start_date + pd.Timedelta(days=int(np.floor(day_offset)))).replace(
            hour=hour, minute=minute, second=0, microsecond=0, nanosecond=0)
        bal = balance_for_ts(hid, drain_ts)
        make_row(hid, term, drain_ts, bal * rng.uniform(0.6, 1.0), "P7")
        n_p7 += 1

    # --- P8: repeated PIN-guessing attempts, then drain — each event built
    # from the previous one's actual timestamp, so ordering can't invert ---
    n_p8 = 0
    while n_p8 < per_pattern_budget and exposed_households:
        hid, c_start, c_end = exposed_households[rng.integers(0, len(exposed_households))]
        capture_day = rng.uniform(c_start, c_end)
        term = victim_cluster_terminal(hid)
        attempts_lo, attempts_hi = fp_cfg["p8_pin_guess_attempts"]
        n_attempts = int(rng.integers(attempts_lo, attempts_hi + 1))
        t_ts = anchor_ts(capture_day)
        for _ in range(n_attempts):
            if n_p8 >= per_pattern_budget:
                break
            t_ts = t_ts + pd.Timedelta(minutes=rng.uniform(1, 20))
            make_row(hid, term, t_ts, 0.0, "P8", event_type="balance_inquiry")
            n_p8 += 1
        drain_ts = t_ts + pd.Timedelta(minutes=rng.uniform(1, 30))
        bal = balance_for_ts(hid, drain_ts)
        make_row(hid, term, drain_ts, bal * rng.uniform(0.6, 1.0), "P8")
        n_p8 += 1

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def add_terminal_compromised_flag(df, compromised, start_date):
    """Ground truth for whether a row's terminal was mid-compromise at the
    time of the transaction — independent of is_fraud. Lets evaluate.py test
    terminal reputation (does it eventually flag the compromised terminal?)
    without treating the real cardholder's own legitimate P1 purchase as a
    missed-fraud case (the author, 2026-07-24)."""
    merged = df.merge(
        compromised[["terminal_id", "compromise_start_day", "compromise_end_day"]],
        on="terminal_id", how="left",
    )
    abs_day = (merged["timestamp"] - start_date) / pd.Timedelta(days=1)
    merged["terminal_compromised_at_time"] = (
        merged["compromise_start_day"].notna()
        & (abs_day >= merged["compromise_start_day"])
        & (abs_day <= merged["compromise_end_day"])
    )
    return merged.drop(columns=["compromise_start_day", "compromise_end_day"])


def generate_dataset(regime_name, cfg, seed_offset):
    t0 = time.time()
    gcfg = cfg["ebt_generator"]
    regime = gcfg["prevalence_regimes"][regime_name]
    rng = np.random.default_rng(cfg["random_seed"] + seed_offset)

    n_days = gcfg["time_window"]["n_days"]
    start_date = pd.Timestamp(gcfg["time_window"]["start_date"])
    n_households = regime["n_households"]
    n_terminals = gcfg["population"]["n_terminals"]

    pop_cfg = dict(gcfg["population"])
    pop_cfg["n_households"] = n_households

    run_cfg = dict(gcfg)
    run_cfg["population"] = pop_cfg

    households = generate_households(n_households, run_cfg, rng)
    terminals = generate_terminals(n_terminals, rng)
    terminals_by_id = terminals.set_index("terminal_id").to_dict(orient="index")
    clusters = assign_home_clusters(households, terminals, run_cfg, rng)
    compromised = select_compromised_terminals(terminals, run_cfg, rng, n_days)

    baseline = generate_legit_n1_n2(households, terminals_by_id, clusters, run_cfg, rng, start_date, n_days)

    fraud = inject_fraud(
        households, terminals_by_id, clusters, compromised, run_cfg, rng,
        start_date, n_days, regime["target_fraud_prevalence"], len(baseline),
    )

    full = pd.concat([baseline, fraud], ignore_index=True)
    full["n1_crossing_issuance"] = full["n1_crossing_issuance"].fillna(False).astype(bool)
    full = add_terminal_compromised_flag(full, compromised, start_date)
    full = full.sort_values("timestamp").reset_index(drop=True)
    full = add_remaining_balance(full, start_date)
    full.insert(0, "transaction_id", [f"TXN{i:08d}" for i in range(len(full))])

    elapsed = time.time() - t0
    return full, elapsed


def add_remaining_balance(df, start_date):
    """Publish the point-in-time ledger balance as a column.

    Added 2026-07-27. `features.py` computes this internally to derive the
    spend-baseline sub-score, but it was never written to the CSV, so the
    feature could not be independently verified from the published data --
    an outside checker had to *reconstruct* the balance and could only do so
    approximately, because `days_since_issuance` carries sub-day jitter and
    cycle boundaries are ambiguous near an exhausted balance. Publishing it
    removes the ambiguity: `src/verify_independent.py` can now recompute the
    sub-score exactly rather than within a tolerance.

    Definition matches `features.py::compute_spend_baseline` exactly -- the
    benefit amount minus this household's actual prior spend in the same
    benefit cycle, clipped at zero. Cycle membership uses the same
    issuance-aligned floor division, not the calendar month: a cycle that
    starts mid-month spans two calendar months, and grouping by month would
    silently split it.

    This is a pure post-processing step over the assembled frame. It draws
    no random numbers, so it cannot perturb generation. There is no automated
    regeneration check in this repo asserting that; it was verified once, by
    hand, on 2026-07-27 -- both datasets were regenerated and compared column
    by column against the pre-change files, and all 21 original columns came
    back byte-identical at unchanged row counts (137,080 and 2,598,309).
    Treat that as a one-time result, not a standing guarantee: nothing here
    re-checks it on later runs.
    """
    abs_day = (df["timestamp"] - start_date).dt.total_seconds() / 86400
    cycle_number = np.floor(
        (abs_day - (df["issuance_day"] - 1)) / CYCLE_LENGTH_DAYS).astype(int)
    cycle_key = df["household_id"] + "_c" + cycle_number.astype(str)

    # Sort by household then time so the cumulative sum runs in ledger order,
    # then restore the original row order before returning.
    order = df.sort_values(["household_id", "timestamp"]).index
    ordered_amount = df.loc[order, "amount"]
    ordered_key = cycle_key.loc[order]
    prior_spend = ordered_amount.groupby(ordered_key).cumsum() - ordered_amount

    remaining = (df.loc[order, "monthly_benefit_amount"] - prior_spend).clip(lower=0)
    df["remaining_balance_at_transaction"] = remaining.reindex(df.index).round(2)
    return df


def main():
    cfg = load_config()
    DATA_DIR.mkdir(exist_ok=True)

    summary = {}
    for regime_name in ["primary", "realistic"]:
        df, elapsed = generate_dataset(regime_name, cfg, seed_offset=0 if regime_name == "primary" else 1)
        out_path = ROOT / cfg["ebt_generator"]["prevalence_regimes"][regime_name]["output_file"]
        df.to_csv(out_path, index=False)
        size_mb = out_path.stat().st_size / (1024 * 1024)

        fraud_count = int(df["is_fraud"].sum())
        n1_count = int((df["fraud_pattern"] == "N1").sum())
        n2_count = int((df["fraud_pattern"] == "N2").sum())
        pattern_counts = df.loc[df["is_fraud"], "fraud_pattern"].value_counts().to_dict()
        compromised_exposure_count = int(df["terminal_compromised_at_time"].sum())

        # In-memory ordinary rows carry fraud_pattern="" (empty string), not
        # NaN — NaN only appears after a CSV round-trip turns blanks into
        # missing values. Match both so this works whether df came straight
        # from generate_dataset() or from re-reading the CSV.
        is_ordinary = df["fraud_pattern"].isna() | (df["fraud_pattern"] == "")
        normal_mask = (~df["is_fraud"]) & is_ordinary
        late_normal_pct = float(round(100 * (df.loc[normal_mask, "days_since_issuance"] >= 25).mean(), 3))
        late_n1_pct = float(round(100 * (df.loc[df["fraud_pattern"] == "N1", "days_since_issuance"] >= 25).mean(), 3))

        # Bucket by the household's OWN issuance-aligned cycle, not calendar
        # month — a cycle starting mid-month spans two calendar months, and
        # grouping by dt.to_period("M") silently fragments it, corrupting
        # this measurement (caught 2026-07-24: it understated true drawdown
        # by ~2.6 points).
        normal_df = df.loc[normal_mask]
        summary_start_date = pd.Timestamp(cfg["ebt_generator"]["time_window"]["start_date"])
        abs_day = (normal_df["timestamp"] - summary_start_date) / pd.Timedelta(days=1)
        cycle_number = np.floor((abs_day - (normal_df["issuance_day"] - 1)) / CYCLE_LENGTH_DAYS).astype(int)
        cycle_key = normal_df.assign(cycle_key=normal_df["household_id"] + "_c" + cycle_number.astype(str))
        drawdown = cycle_key.groupby("cycle_key").agg(spent=("amount", "sum"), benefit=("monthly_benefit_amount", "first"))
        mean_drawdown_pct = float(round(100 * (drawdown["spent"] / drawdown["benefit"]).mean(), 2))

        summary[regime_name] = {
            "rows": len(df),
            "fraud_rows": fraud_count,
            "fraud_rate_pct": round(100 * fraud_count / len(df), 4),
            "n1_rows": n1_count,
            "n2_rows": n2_count,
            "pattern_counts": {k: int(v) for k, v in pattern_counts.items()},
            "terminal_compromised_at_time_rows": compromised_exposure_count,
            "normal_rows_at_dsi_ge_25_pct": late_normal_pct,
            "n1_rows_at_dsi_ge_25_pct": late_n1_pct,
            "mean_household_cycle_drawdown_pct": mean_drawdown_pct,
            "file_size_mb": round(size_mb, 2),
            "seconds": round(elapsed, 1),
            "path": str(out_path.relative_to(ROOT)),
        }

    print(yaml.dump(summary, sort_keys=False))


if __name__ == "__main__":
    main()
