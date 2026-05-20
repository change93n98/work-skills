#!/usr/bin/env python3
"""
Perfetto trace_processor based analyzer for vLLM/SGLang profiling traces.
Uses Perfetto SQL queries for accurate operator timing analysis.

Usage:
    python3 prof_analyze_perfetto.py --trace-file <path> [--output-dir <dir>] [--decode-step 2]

Requires: pip install perfetto
"""

import argparse
import gzip
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

# Operator classification patterns
OP_CATEGORIES = {
    "gemm": [
        "gemm", "Gemm", "GEMM", "mm", "linear", "addbmm", "hgemm",
        "Hipblaslt_Launch", "hipblaslt", "rocblas", "ROCBLAS",
        "CKGemm", "ck_gemm", "DeviceGemm", "GroupedGemm",
        "SplitkGemm", "StreamkGemm",
    ],
    "通信 (comm)": [
        "AllReduce", "all_reduce", "nccl", "rccl", "NCCL", "RCCL",
        "broadcast", "Broadcast", "AllGather", "all_gather",
        "ReduceScatter", "reduce_scatter", "CustomAllReduce",
        "allreduce", "AllReduceRing", "AllReduceTree",
        "ncclKernel", "rcclKernel",
    ],
    "FlashAttention (fa)": [
        "flash_attn", "flash_fwd", "flash_bwd", "fmha", "fmoe",
        "FlashAttention", "flash_attention", "FlashDecoding",
        "flash_decoding", "MHA", "mha_fwd", "mha_bwd",
        "ck_fmha", "CKFmha", "fwd_split", "fwd_combine",
    ],
    "Triton": [
        "triton", "Triton", "triton_kernel",
    ],
    "其他elementwise": [
        "elementwise", "ElementWise",
        "softmax", "Softmax", "layernorm", "LayerNorm",
        "rmsnorm", "RMSNorm", "SiluGelu", "silu", "gelu", "relu",
        "embedding", "Embedding", "rope", "RoPE", "RotaryEmbedding",
        "topk", "TopK", "top_k", "sampling", "Sampling",
        "transpose", "reshape", "view", "contiguous",
        "copy_", "clone", "fill_", "scale", "Scale",
        "Reduce", "reduce", "add", "mul", "div", "sub",
        "exp", "log", "sqrt", "pow", "abs", "neg",
    ],
    "memcpy/memset": [
        "memcpy", "memset", "Memcpy", "Memset", "MemCpy", "MemSet",
        "D2H", "H2D", "H2H", "D2D",
        "hipMemcpy", "hipMemset", "hipMem",
        "AsyncMemcpy", "async_memcpy", "MemcpyAsync", "memcpy_async",
    ],
}

EXCLUDE_PATTERNS = [
    "profiler_step", "ProfilerStep", "profiler", "Profile", "PROFILER",
    "torch.autograd", "autograd",
]


def decompress_trace(trace_path: str) -> str:
    """Decompress gzipped trace to temp file if needed."""
    path = Path(trace_path)
    if path.suffix == ".gz":
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        with gzip.open(path, "rt", encoding="utf-8") as f:
            tmp.write(f.read())
        tmp.close()
        return tmp.name
    return str(path)


def run_perfetto_query(tp, sql: str) -> list:
    """Execute a SQL query on the trace processor."""
    result = tp.query(sql)
    rows = []
    for row in result:
        rows.append(dict(row))
    return rows


def find_phases_perfetto(tp, decode_step: int = 2) -> dict:
    """Find prefill/decode phase boundaries using Perfetto SQL.

    Detects slow vs fast decode steps by finding the last large gap (>100ms)
    between consecutive model_forward slices. Steps after this gap are the
    fast decode cadence.

    Prefill = trace_start → first fast step start (includes warmup gap)
    Decode = the Nth fast step (1-indexed: decode_step=2 → 2nd fast step)

    Note: Perfetto ts/dur are in nanoseconds.
    """
    # Find model_forward slices
    query = """
    SELECT s.ts, s.dur, s.name
    FROM slice s
    JOIN track t ON s.track_id = t.id
    WHERE s.name LIKE '%model_forward%'
       OR s.name LIKE '%ModelForward%'
       OR s.name LIKE '%forward%'
    ORDER BY s.ts
    """
    slices = run_perfetto_query(tp, query)

    if not slices:
        # Try broader search
        query = """
        SELECT s.ts, s.dur, s.name
        FROM slice s
        WHERE s.name LIKE '%prefill%'
           OR s.name LIKE '%Prefill%'
           OR s.name LIKE '%decode%'
           OR s.name LIKE '%Decode%'
        ORDER BY s.ts
        """
        slices = run_perfetto_query(tp, query)

    if not slices:
        return {}

    # Get trace start
    trace_start_query = "SELECT MIN(ts) as min_ts FROM slice"
    trace_start = run_perfetto_query(tp, trace_start_query)[0]["min_ts"]

    # Find the last large gap (>100ms = 100_000_000 ns) between consecutive slices
    transition_idx = -1
    for i in range(len(slices) - 1):
        gap = slices[i + 1]["ts"] - (slices[i]["ts"] + slices[i]["dur"])
        if gap > 100_000_000:  # > 100ms in nanoseconds
            transition_idx = i

    if transition_idx >= 0:
        # Prefill: trace start → first fast step start (includes gap)
        prefill_start = trace_start
        prefill_end = slices[transition_idx + 1]["ts"]

        # Fast decode steps: everything after the last large gap
        fast_steps = slices[transition_idx + 1:]

        # decode_step N: fast_steps[N].start → fast_steps[N+1].start
        if decode_step < len(fast_steps) - 1:
            decode_start = fast_steps[decode_step]["ts"]
            decode_end = fast_steps[decode_step + 1]["ts"]
        elif fast_steps:
            decode_start = fast_steps[-1]["ts"]
            decode_end = fast_steps[-1]["ts"] + fast_steps[-1]["dur"]
        else:
            return {}

        return {
            "prefill": {"start": prefill_start, "end": prefill_end},
            "decode": {"start": decode_start, "end": decode_end},
            "forward_slices": slices,
            "transition_idx": transition_idx,
            "fast_steps_count": len(fast_steps),
        }
    else:
        # No large gap → original simple logic
        prefill_end = slices[0]["ts"] + slices[0]["dur"]

        if len(slices) > decode_step:
            decode_start = slices[decode_step]["ts"]
            decode_end = slices[decode_step]["ts"] + slices[decode_step]["dur"]
        elif len(slices) > 1:
            decode_start = slices[-1]["ts"]
            decode_end = slices[-1]["ts"] + slices[-1]["dur"]
        else:
            return {}

        return {
            "prefill": {"start": trace_start, "end": prefill_end},
            "decode": {"start": decode_start, "end": decode_end},
            "forward_slices": slices,
        }


def get_kernels_perfetto(tp, start_ts: int, end_ts: int) -> list:
    """Query GPU kernels in time range using Perfetto SQL."""
    query = f"""
    SELECT s.name, s.ts, s.dur, s.cat, t.name as track_name
    FROM slice s
    JOIN track t ON s.track_id = t.id
    WHERE s.ts >= {start_ts}
      AND s.ts + s.dur <= {end_ts}
      AND s.dur > 0
      AND (
        t.name LIKE '%GPU%'
        OR t.name LIKE '%gpu%'
        OR t.name LIKE '%CUDA%'
        OR t.name LIKE '%HIP%'
        OR t.name LIKE '%stream%'
        OR s.cat LIKE '%kernel%'
        OR s.cat LIKE '%gpu%'
        OR s.name LIKE '%gemm%'
        OR s.name LIKE '%Gemm%'
        OR s.name LIKE '%flash%'
        OR s.name LIKE '%Flash%'
        OR s.name LIKE '%reduce%'
        OR s.name LIKE '%Reduce%'
        OR s.name LIKE '%nccl%'
        OR s.name LIKE '%rccl%'
        OR s.name LIKE '%memcpy%'
        OR s.name LIKE '%memset%'
        OR s.name LIKE '%triton%'
        OR s.name LIKE '%Triton%'
        OR s.name LIKE '%ck_%'
        OR s.name LIKE '%CK_%'
        OR s.name LIKE '%softmax%'
        OR s.name LIKE '%layernorm%'
        OR s.name LIKE '%rmsnorm%'
        OR s.name LIKE '%silu%'
        OR s.name LIKE '%gelu%'
        OR s.name LIKE '%relu%'
        OR s.name LIKE '%rope%'
        OR s.name LIKE '%topk%'
        OR s.name LIKE '%embedding%'
        OR s.name LIKE '%elementwise%'
        OR s.name LIKE '%fmha%'
        OR s.name LIKE '%fmoe%'
      )
    ORDER BY s.ts
    """
    return run_perfetto_query(tp, query)


def classify_kernel(name: str) -> str:
    """Classify kernel by name patterns."""
    name_lower = name.lower()

    # Check exclusions first
    for pattern in EXCLUDE_PATTERNS:
        if pattern.lower() in name_lower:
            return None

    for category, patterns in OP_CATEGORIES.items():
        for pattern in patterns:
            if pattern.lower() in name_lower:
                return category

    return "其他elementwise"


def analyze_kernels(kernels: list) -> dict:
    """Compute statistics per category."""
    stats = defaultdict(lambda: {"total_dur": 0, "count": 0})

    for kernel in kernels:
        cat = classify_kernel(kernel["name"])
        if cat is None:
            continue
        stats[cat]["total_dur"] += kernel["dur"]
        stats[cat]["count"] += 1

    total_dur = sum(s["total_dur"] for s in stats.values())
    result = {}

    for cat in list(OP_CATEGORIES.keys()) + ["总计"]:
        if cat in stats:
            s = stats[cat]
            result[cat] = {
                "total_dur_ms": s["total_dur"] / 1e6,
                "count": s["count"],
                "percentage": (s["total_dur"] / total_dur * 100) if total_dur > 0 else 0,
            }
        elif cat == "总计":
            result[cat] = {
                "total_dur_ms": total_dur / 1e6,
                "count": sum(s["count"] for s in stats.values()),
                "percentage": 100.0,
            }
        else:
            result[cat] = {"total_dur_ms": 0, "count": 0, "percentage": 0}

    return result


def format_table(phase_name: str, stats: dict) -> str:
    """Format results as a table."""
    lines = []
    lines.append(f"\n{'=' * 60}")
    lines.append(f"  {phase_name}算子耗时分析")
    lines.append(f"{'=' * 60}")
    lines.append(f"{'类别':<20s} {'总耗时(ms)':>12s} {'调用次数':>10s} {'占比(%)':>10s}")
    lines.append(f"{'-' * 60}")

    order = ["gemm", "通信 (comm)", "FlashAttention (fa)", "Triton",
             "其他elementwise", "memcpy/memset", "总计"]

    for cat in order:
        if cat in stats:
            s = stats[cat]
            if cat == "总计":
                lines.append(f"{'-' * 60}")
            lines.append(
                f"{cat:<20s} {s['total_dur_ms']:>12.2f} {s['count']:>10d} {s['percentage']:>9.2f}%"
            )

    lines.append(f"{'=' * 60}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Perfetto-based prof trace analyzer")
    parser.add_argument("--trace-file", required=True, help="Path to trace JSON(.gz)")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    parser.add_argument("--decode-step", type=int, default=2, help="Decode step to analyze (default: 2)")
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    if args.output_dir is None:
        args.output_dir = os.path.dirname(os.path.abspath(args.trace_file))

    # Try to use perfetto trace_processor
    try:
        from perfetto.trace_processor import TraceProcessor
    except ImportError:
        print("ERROR: perfetto package not installed. Install with: pip install perfetto")
        print("Falling back to basic analyzer...")
        # Import and run the basic analyzer
        import prof_analyze
        sys.argv = [sys.argv[0], "--trace-file", args.trace_file,
                    "--output-dir", args.output_dir,
                    "--decode-step", str(args.decode_step)]
        if args.verbose:
            sys.argv.append("--verbose")
        prof_analyze.main()
        return

    print(f"Loading trace with Perfetto: {args.trace_file}")
    trace_path = decompress_trace(args.trace_file)

    try:
        tp = TraceProcessor(trace=trace_path)

        # Find phases
        print("Identifying phases...")
        phases = find_phases_perfetto(tp, decode_step=args.decode_step)

        if not phases or "prefill" not in phases:
            print("ERROR: Could not identify phases")
            sys.exit(1)

        prefill = phases["prefill"]
        decode = phases["decode"]

        print(f"Prefill: {(prefill['end'] - prefill['start']) / 1e6:.2f} ms")
        print(f"Decode (step {args.decode_step}): {(decode['end'] - decode['start']) / 1e6:.2f} ms")

        if phases.get("forward_slices"):
            print(f"Total forward steps: {len(phases['forward_slices'])}")

        # Get kernels
        print("Querying GPU kernels...")
        prefill_kernels = get_kernels_perfetto(tp, prefill["start"], prefill["end"])
        decode_kernels = get_kernels_perfetto(tp, decode["start"], decode["end"])

        print(f"Prefill kernels: {len(prefill_kernels)}, Decode kernels: {len(decode_kernels)}")

        if args.verbose:
            print("\nSample kernels:")
            for k in prefill_kernels[:5]:
                print(f"  {k['name']} -> {classify_kernel(k['name'])}")

        # Analyze
        prefill_stats = analyze_kernels(prefill_kernels)
        decode_stats = analyze_kernels(decode_kernels)

        print(format_table("Prefill阶段", prefill_stats))
        print(format_table(f"Decode阶段 (Step {args.decode_step})", decode_stats))

        # Save
        os.makedirs(args.output_dir, exist_ok=True)

        summary_path = os.path.join(args.output_dir, "prof_analysis_summary.txt")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("大模型推理Profiling算子耗时分析报告\n")
            f.write(f"分析方法: Perfetto trace_processor SQL\n")
            f.write(format_table("Prefill阶段", prefill_stats))
            f.write(format_table(f"Decode阶段 (Step {args.decode_step})", decode_stats))

        json_path = os.path.join(args.output_dir, "prof_analysis.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"prefill": prefill_stats, "decode": decode_stats}, f, indent=2, ensure_ascii=False)

        print(f"\nResults saved to: {args.output_dir}")

    finally:
        # Cleanup temp file
        if trace_path != args.trace_file:
            os.unlink(trace_path)


if __name__ == "__main__":
    main()
