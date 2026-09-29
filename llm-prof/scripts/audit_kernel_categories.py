#!/usr/bin/env python3
"""Audit kernel classification on trace JSON(.gz) or aggregated XLSX tables.

The audit reports matched rule reasons and unknown fallbacks instead of silently
accepting every fallback as a correct elementwise classification.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
from pathlib import Path

from kernel_categories import classify_kernel_with_reason


def iter_trace_names(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        data = json.load(f)
    events = data.get("traceEvents", data.get("events", [])) if isinstance(data, dict) else data
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("cat") in ("kernel", "gpu_memcpy", "gpu_memset"):
            yield str(event.get("name", "")), float(event.get("dur", 0) or 0), 1


def iter_xlsx_names(path: Path):
    try:
        import openpyxl
    except ImportError as exc:
        raise SystemExit("XLSX audit requires openpyxl: pip install openpyxl") from exc
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    ws.calculate_dimension(force=True)
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    name_col = headers.index("name") + 1 if "name" in headers else 1
    duration_col = headers.index("total_duration_us") + 1 if "total_duration_us" in headers else None
    count_col = headers.index("record_count") + 1 if "record_count" in headers else None
    for row in range(2, ws.max_row + 1):
        name = ws.cell(row, name_col).value
        if not name:
            continue
        duration = float(ws.cell(row, duration_col).value or 0) if duration_col else 0
        count = int(ws.cell(row, count_col).value or 1) if count_col else 1
        yield str(name), duration, count


def audit(paths):
    agg = collections.defaultdict(lambda: {"category": None, "reason": None, "duration_us": 0.0, "count": 0})
    for path in paths:
        iterator = iter_xlsx_names(path) if path.suffix.lower() == ".xlsx" else iter_trace_names(path)
        for name, duration, count in iterator:
            category, reason = classify_kernel_with_reason(name)
            key = (name, category, reason)
            agg[key]["category"] = category
            agg[key]["reason"] = reason
            agg[key]["duration_us"] += duration
            agg[key]["count"] += count
    rows = []
    for (name, category, reason), values in agg.items():
        rows.append({"name": name, **values})
    rows.sort(key=lambda x: x["duration_us"], reverse=True)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-fallback", action="store_true")
    args = parser.parse_args()
    rows = audit(args.paths)
    summary = collections.defaultdict(lambda: {"count": 0, "duration_us": 0.0})
    for row in rows:
        key = (row["category"], row["reason"])
        summary[key]["count"] += row["count"]
        summary[key]["duration_us"] += row["duration_us"]
    print("category\treason\tcount\tduration_ms")
    for (category, reason), values in sorted(summary.items(), key=lambda x: -x[1]["duration_us"]):
        print(f"{category}\t{reason}\t{values['count']}\t{values['duration_us'] / 1000:.3f}")
    unknown = [r for r in rows if r["reason"] == "fallback:unknown"]
    print(f"\nunknown_fallback_names={len(unknown)}")
    for row in unknown[:50]:
        print(f"  {row['duration_us'] / 1000:.3f} ms\t{row['count']} calls\t{row['name'][:180]}")
    if args.output:
        args.output.write_text(json.dumps({"summary": summary_to_json(summary), "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.fail_on_fallback and unknown:
        raise SystemExit(2)


def summary_to_json(summary):
    return {f"{category}|{reason}": values for (category, reason), values in summary.items()}


if __name__ == "__main__":
    main()
