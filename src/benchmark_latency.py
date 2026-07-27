"""Latency benchmark — CivicSentra Phase 0 (SPEC.md §4.5).

Tests C1 (the paper's "scoring completes in under 30ms" claim): end-to-end
per-transaction scoring time, feature computation included, ONE transaction
at a time. Deliberately NOT vectorized batch processing over many
transactions at once -- SPEC.md is explicit that batch throughput would
produce an impressively small number with nothing to do with real
authorization-time latency, and using it would be a form of cheating.

Method (reusing the truncation approach already established and verified in
test_leakage.py, not a new methodology): for each sampled transaction, build
"the world as it looked at the moment this transaction arrived" -- every row
with timestamp <= this transaction's own timestamp -- and time
scorer.score_transactions() on exactly that slice, ending with this
transaction as the last row. The timer covers feature computation AND
scoring; it does not cover reading data/ebt_synthetic.csv from disk (a real
authorization system already has the incoming transaction in memory, it
doesn't re-read a CSV).

See explain/EXPLAIN_benchmark_latency.md for why this design was chosen over
a from-scratch, hand-written single-row implementation, and for the
resulting limitation this produces (latency grows with how much transaction
history exists, because features.py is not incrementally stateful).
"""
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import ROOT, load_config  # noqa: E402
from scorer import score_transactions  # noqa: E402

N_SAMPLES = 300
MIN_POSITION = 50
# Skip the first 50 rows of the dataset -- with almost no history, their
# feature computation is trivially fast and not representative of the
# steady-state cost this benchmark is meant to characterize (see
# explain/EXPLAIN_benchmark_latency.md).
SEED = 42


def get_hardware_info():
    info = {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "machine": platform.machine(),
        "cpu_count": None,
    }
    try:
        import os
        info["cpu_count"] = os.cpu_count()
    except Exception:
        pass
    if platform.system() == "Darwin":
        try:
            r = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5,
            )
            info["cpu"] = r.stdout.strip()
        except Exception:
            info["cpu"] = "unknown (sysctl call failed)"
    else:
        info["cpu"] = platform.processor() or "unknown"
    return info


def sample_positions(n_total, n_samples, min_position, seed):
    rng = np.random.default_rng(seed)
    pool = np.arange(min_position, n_total)
    n_samples = min(n_samples, len(pool))
    return np.sort(rng.choice(pool, size=n_samples, replace=False))


def percentile(sorted_values, p):
    """Linear-interpolation percentile, no scipy/numpy.percentile dependency
    beyond plain numpy (already a project dependency)."""
    return float(np.percentile(sorted_values, p))


def run_benchmark(df, cfg, positions):
    latencies_ms = []
    n_history = []
    for pos in positions:
        hist = df.iloc[:pos + 1]
        t0 = time.perf_counter()
        score_transactions(hist, cfg)
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000)
        n_history.append(len(hist))
    return np.array(latencies_ms), np.array(n_history)


def main():
    cfg = load_config()
    df = pd.read_csv(ROOT / "data/ebt_synthetic.csv", parse_dates=["timestamp"])
    assert df["timestamp"].is_monotonic_increasing, (
        "benchmark assumes the CSV is already chronologically sorted -- verified true for "
        "data/ebt_synthetic.csv, see PROGRESS.md; if this ever changes, sort before truncating."
    )

    positions = sample_positions(len(df), N_SAMPLES, MIN_POSITION, SEED)
    print(f"Benchmarking {len(positions)} transactions sampled across positions "
          f"{positions.min()}-{positions.max()} of {len(df)} total rows...")

    t_start = time.perf_counter()
    latencies_ms, n_history = run_benchmark(df, cfg, positions)
    t_total = time.perf_counter() - t_start
    print(f"Benchmark run took {t_total:.1f}s wall-clock (not part of the reported latency "
          f"figures -- that's this script's own overhead, not per-transaction cost).\n")

    sorted_lat = np.sort(latencies_ms)
    p50 = percentile(sorted_lat, 50)
    p95 = percentile(sorted_lat, 95)
    p99 = percentile(sorted_lat, 99)
    mean_lat = float(np.mean(latencies_ms))
    min_lat = float(np.min(latencies_ms))
    max_lat = float(np.max(latencies_ms))

    hw = get_hardware_info()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    corr = float(np.corrcoef(n_history, latencies_ms)[0, 1])

    lines = []
    lines.append("# CivicSentra Phase 0 -- benchmark_latency.py output")
    lines.append(f"Generated {ts}.")
    lines.append(f"Method: {len(positions)} transactions sampled from "
                  f"data/ebt_synthetic.csv ({len(df):,} rows total), each scored individually "
                  "via scorer.score_transactions() on only the history that existed at that "
                  "transaction's own timestamp (feature computation + scoring both timed; "
                  "CSV read is not). Single transaction at a time -- SPEC.md §4.5, not "
                  "vectorized batch processing.\n")

    lines.append("## Hardware / environment")
    lines.append(f"CPU: {hw.get('cpu', 'unknown')}")
    lines.append(f"Platform: {hw['platform']}")
    lines.append(f"CPU cores: {hw['cpu_count']}")
    lines.append(f"Python: {hw['python_version']}\n")

    lines.append("## Latency (ms), end-to-end per transaction, feature computation included")
    lines.append(f"p50: {p50:.2f} ms")
    lines.append(f"p95: {p95:.2f} ms")
    lines.append(f"p99: {p99:.2f} ms")
    lines.append(f"mean: {mean_lat:.2f} ms   min: {min_lat:.2f} ms   max: {max_lat:.2f} ms")
    lines.append(f"n samples: {len(positions)}\n")

    lines.append("## Paper claim C1: scoring completes in under 30ms")
    under_30 = float(np.mean(latencies_ms < 30.0)) * 100
    lines.append(f"{under_30:.1f}% of sampled transactions scored under 30ms. "
                  f"p50={p50:.2f}ms {'is' if p50 < 30 else 'is NOT'} under 30ms; "
                  f"p95={p95:.2f}ms {'is' if p95 < 30 else 'is NOT'} under 30ms; "
                  f"p99={p99:.2f}ms {'is' if p99 < 30 else 'is NOT'} under 30ms.\n")

    lines.append("## Known limitation: latency scales with historical volume")
    lines.append(f"Correlation between transaction history size (rows preceding the scored "
                  f"transaction) and its own latency: r={corr:.3f}. This reference "
                  "implementation is not incrementally stateful -- features.py recomputes "
                  "each feature family from the full history available at scoring time on "
                  "every call, rather than maintaining running per-terminal/per-household "
                  "counters that a production system would keep. So a transaction scored "
                  "when 130,000 rows of history already exist costs measurably more than one "
                  "scored on day one. This is a real, measured property of this specific "
                  "implementation, not a claim about EBT authorization latency in general -- "
                  "an incrementally-stateful implementation would not show this growth. "
                  "Reported here, not hidden, per CLAUDE.md Rule 1.\n")

    lines.append("## Caveat (SPEC.md §4.5)")
    lines.append("Python is not a production authorization-path language. These figures "
                  "represent an upper bound that a compiled implementation would improve on, "
                  "not a claim about achievable production latency.\n")

    lines.append("## Raw distribution (ms), 20 evenly spaced percentiles")
    for p in range(5, 100, 5):
        lines.append(f"  p{p}: {percentile(sorted_lat, p):.2f} ms")

    report_text = "\n".join(lines)
    print(report_text)

    out_path = ROOT / "outputs" / "benchmark_latency.md"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(report_text)
    print(f"\nWrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
