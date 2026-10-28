#!/usr/bin/env python3
"""Read PHASE_GRAPH annotations and count same-thread runtime graph launches."""

import argparse
import bisect
import collections
import gzip
import json
import re
import sys
from pathlib import Path


def inspect_trace(path, prefix):
    try:
        import ijson
    except ImportError as exc:
        raise RuntimeError("ijson is required; use a profiling environment that provides it") from exc

    opener = gzip.open if path.suffix == ".gz" else open
    fields_pattern = re.compile(r"(\w+)=(\[[^\]]*\]|\S+)")
    launch_pattern = re.compile(r"^(?:sdaa|cuda|hip)GraphLaunch(?:_.*)?$")
    scopes = []
    launches = collections.defaultdict(list)
    categories = collections.Counter()
    total = 0
    with opener(path, "rb") as stream:
        for event in ijson.items(stream, "traceEvents.item"):
            total += 1
            category = event.get("cat", "")
            categories[category] += 1
            if event.get("ph") != "X":
                continue
            name = event.get("name", "")
            thread = (event.get("pid"), event.get("tid"))
            if launch_pattern.fullmatch(name):
                launches[thread].append(float(event["ts"]))
            if category != "user_annotation" or not name.startswith(prefix + " "):
                continue
            fields = dict(fields_pattern.findall(name))
            required = {"step", "phase", "tokens", "mode"}
            if not required.issubset(fields):
                raise ValueError(f"Annotation is missing fields: {name}")
            scopes.append({
                "name": name,
                "pid": event.get("pid"),
                "tid": event.get("tid"),
                "ts_us": float(event["ts"]),
                "duration_us": float(event.get("dur", 0)),
                "step": int(fields["step"]),
                "phase": fields["phase"],
                "tokens": int(fields["tokens"]),
                "mode": fields["mode"],
                **({"padded": int(fields["padded"])} if "padded" in fields else {}),
                **({key: json.loads(fields[key]) for key in ("computed", "prompt") if key in fields}),
            })

    if not scopes:
        raise ValueError(f"No {prefix} user_annotation found; profiler config alone does not create this scope")
    for times in launches.values():
        times.sort()
    scopes.sort(key=lambda row: row["ts_us"])
    for row in scopes:
        times = launches[(row["pid"], row["tid"])]
        start = row["ts_us"]
        end = start + row["duration_us"]
        row["graph_launches"] = bisect.bisect_left(times, end) - bisect.bisect_left(times, start)
    return {
        "trace": str(path.resolve()),
        "prefix": prefix,
        "trace_events": total,
        "compressed_stream_validated": path.suffix == ".gz",
        "categories": dict(categories),
        "scope_count": len(scopes),
        "scopes": scopes,
        "count_semantics": "Runtime launches on the same pid/tid in [scope start, scope end); not device time",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--prefix", default="PHASE_GRAPH")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = inspect_trace(args.trace, args.prefix)
        payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            if args.output.resolve() == args.trace.resolve():
                raise ValueError("Output must not overwrite the input trace")
            args.output.write_text(payload, encoding="utf-8")
            print(f"Found {result['scope_count']} scopes; saved {args.output}")
        else:
            print(payload, end="")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Trace inspection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
