#!/usr/bin/env python3
"""Compare current benchmark results against previous run.

Detects regressions > threshold and exits with code 1 if any found.
Used by .github/workflows/benchmark.yml.

Usage:
    python3 scripts/compare_benchmarks.py \\
        --previous benchmark/prev_results.jsonl \\
        --current benchmark/output.txt \\
        --threshold 0.15
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_jsonl(path: Path) -> list[dict]:
    """Parse a JSONL file or a text file containing embedded JSON lines."""
    results: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("{"):
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return results


def find_latest(results: list[dict]) -> dict[str, dict]:
    """Return the latest result (by timestamp) for each unique label."""
    latest: dict[str, dict] = {}
    for r in results:
        label = r.get("label", "")
        ts = r.get("ts", "")
        if label not in latest or ts > latest[label].get("ts", ""):
            latest[label] = r
    return latest


REGRESSION: bool = False


def compare(prev: dict, curr: dict, threshold: float) -> None:
    """Compare two result dicts and print diff. Sets REGRESSION global."""
    global REGRESSION

    label = curr.get("label", "???")
    prev_exec = prev.get("execution_seconds") or 0
    curr_exec = curr.get("execution_seconds") or 0
    prev_mem = prev.get("peak_mem_kb") or 0
    curr_mem = curr.get("peak_mem_kb") or 0

    # Guard against missing / zero data
    if not prev_exec or not curr_exec:
        print(f"  {label:30s}  SKIP — no previous or current execution time")
        return
    if not prev_mem or not curr_mem:
        print(f"  {label:30s}  SKIP — no previous or current memory data")
        return

    exec_ratio = curr_exec / prev_exec - 1.0
    mem_ratio = curr_mem / prev_mem - 1.0

    flags: list[str] = []
    if exec_ratio > threshold:
        flags.append(f"⚠️  EXECUTION +{exec_ratio*100:.1f}% (threshold +{threshold*100:.0f}%)")
        REGRESSION = True
    elif exec_ratio < -0.05:
        flags.append(f"✅ execution -{abs(exec_ratio)*100:.1f}% (faster)")

    if mem_ratio > threshold:
        flags.append(f"⚠️  MEMORY +{mem_ratio*100:.1f}%")
        REGRESSION = True
    elif mem_ratio < -0.05:
        flags.append(f"✅ memory -{abs(mem_ratio)*100:.1f}% (lighter)")

    if not flags:
        flags.append("✅ within threshold")

    print(f"  {label:30s}  {prev_exec:6.2f}s → {curr_exec:6.2f}s  "
          f"mem {int(prev_mem/1024):4d}M → {int(curr_mem/1024):4d}M  "
          f"{'  |  '.join(flags)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare benchmark results")
    parser.add_argument("--previous", required=True, type=Path, help="Previous results.jsonl")
    parser.add_argument("--current", required=True, type=Path, help="Current output.txt")
    parser.add_argument("--threshold", default=0.15, type=float, help="Regression threshold (default 0.15 = 15%%)")
    args = parser.parse_args()

    prev_results = parse_jsonl(args.previous)
    curr_results = parse_jsonl(args.current)

    if not curr_results:
        print("No current results found — skipping comparison.")
        return

    if not prev_results:
        print("No previous results found — this is the first run.")
        return

    prev_latest = find_latest(prev_results)
    print("Benchmark comparison:")
    print()

    for curr in curr_results:
        label = curr.get("label", "")
        prev = prev_latest.get(label)
        if prev:
            compare(prev, curr, args.threshold)
        else:
            print(f"  {label:30s}  NEW — no previous data")

    print()
    if REGRESSION:
        print("❌ REGRESSION DETECTED — one or more benchmarks exceeded threshold.")
        sys.exit(1)
    else:
        print("✅ All benchmarks within threshold.")


if __name__ == "__main__":
    main()
