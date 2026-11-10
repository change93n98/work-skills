"""Classify shared device symbols using same-trace GDN source scopes."""

from collections import defaultdict
import math

from device_step_window import DeviceStepIndex
from graph_source_mapping import is_graph_launch
from prof_analyze_perfetto import run_perfetto_query

CORE_OPS = (
    "vllm::qwen_gdn_attention_core",
    "vllm::qwen_gdn_attention_core_fused_norm_packed",
)
SHARED_CATEGORIES = {"其他elementwise", "Triton", "memcpy/memset"}
CORE_SUBSCOPES = {
    ": rearrange_mixed_qkv": "rearrange",
    ": fused_gdn_gating": "gating",
    "_C_sdaa::fused_gdn_gating": "gating",
    ": l2norm": "qk_norm",
    "_C_sdaa::chunk_gated_delta_rule_fwd": "chunk_fwd",
    ": fi_chunk_gated_delta_rule": "chunk_fwd",
    "_C_sdaa::fused_recurrent_gated_delta_rule_fwd": "recurrent",
    ": fused_recurrent_gated_delta_rule": "recurrent",
    ": fused_sigmoid_gating_delta_rule_update": "recurrent_fused",
    ": fused_recurrent_gated_delta_rule_packed_decode": "recurrent_packed",
}
OUTPUT_SYMBOLS = {
    "triton_per_fused__to_copy__unsafe_view_add_clone_mean_mul_pow_rsqrt_silu_view_0": "gdn_output_norm",
    "triton_poi_fused__to_copy__unsafe_view_add_clone_mean_mm_mul_pow_rsqrt_silu_t_view_1": "gdn_output_layout",
}


def _gdn_role(event, launches, scopes):
    if not launches:
        return None
    name = event["name"].lower()
    if launches <= scopes["metadata"]:
        return "gdn_metadata"
    if launches <= scopes["output_norm"]:
        return "gdn_output_norm"
    if name in OUTPUT_SYMBOLS and launches <= scopes["output"]:
        return OUTPUT_SYMBOLS[name]
    if not launches <= scopes["core"]:
        return None
    # Prefer the narrow operator scope for casts, copies and other shared symbols.
    for scope, role in (
        ("conv_update", "gdn_conv_update"),
        ("conv_forward", "gdn_conv"),
        ("rearrange", "gdn_rearrange_qkv"),
        ("gating", "gdn_gating"),
        ("qk_norm", "gdn_qk_norm"),
        ("chunk_fwd", "gdn_chunk_fwd_internal"),
        ("recurrent", "gdn_recurrent"),
        ("recurrent_fused", "gdn_recurrent_fused"),
        ("recurrent_packed", "gdn_recurrent_packed"),
    ):
        if launches <= scopes[scope]:
            return role
    if "fusednormargs" in name:
        return None
    if "causal_conv1d" in name:
        if "update" in name:
            return "gdn_conv_update"
        if "_fwd_" in name:
            return "gdn_conv"
        return "gdn_conv_shared"
    if name == "_fused_post_conv_kernel":
        return "gdn_gating_qk_fused"
    if event["category"] in ("gpu_memcpy", "gpu_memset"):
        return "gdn_memory"
    return "gdn_aux"


def _source_scopes(tp, index):
    cpu_ops = ", ".join(f"'{name}'" for name in (
        *CORE_OPS, "_C_sdaa::fused_norm", *(name for name in CORE_SUBSCOPES if name.startswith("_C_sdaa::"))))
    rows = run_perfetto_query(tp, f"""
        SELECT s.id, s.name, s.ts, s.dur, s.track_id, tt.utid AS host_thread,
            extract_arg(s.arg_set_id, 'args.Concrete Inputs[8]') AS norm_mode,
            extract_arg(s.arg_set_id, 'args.Input type[6]') AS gate_type
        FROM slice s LEFT JOIN thread_track tt ON tt.id=s.track_id
        WHERE s.dur >= 0 AND (
            (s.category='cpu_op' AND s.name IN ({cpu_ops}))
            OR (s.category='cpu_op' AND (
                s.name LIKE '%::%causal_conv1d_update'
                OR s.name LIKE '%::%causal_conv1d_fn'
            ))
            OR (s.category='python_function' AND (
                s.name LIKE '%/mamba/gdn/qwen_gdn_linear_attn.py(%): _output_projection'
                OR s.name LIKE '%/attention/backends/gdn_attn.py(%): _build_chunk_metadata'
                OR s.name LIKE '%/mamba/gdn/qwen_gdn_linear_attn.py(%): rearrange_mixed_qkv'
                OR s.name LIKE '%/mamba/gdn/qwen_gdn_linear_attn.py(%): fi_chunk_gated_delta_rule'
                OR s.name LIKE '%/mamba/gdn/qwen_gdn_linear_attn.py(%): fused_gdn_gating'
                OR s.name LIKE '%/vllm_sdaa/layers/mamba/gdn_linear_attn.py(%): fused_gdn_gating'
                OR s.name LIKE '%/vllm_sdaa/layers/fla/ops/chunk.py(%): l2norm'
                OR s.name LIKE '%/fla/ops/fused_recurrent.py(%): fused_recurrent_gated_delta_rule'
                OR s.name LIKE '%/flash_linear_attention/ops/fused_recurrent.py(%): fused_recurrent_gated_delta_rule_packed_decode'
                OR s.name LIKE '%/flash_linear_attention/ops/fused_sigmoid_gating.py(%): fused_sigmoid_gating_delta_rule_update'
                OR s.name LIKE '%): causal_conv1d_update'
                OR s.name LIKE '%): causal_conv1d_fn'
            ))
        )
    """)
    owners = defaultdict(set)
    for row in rows:
        name = row["name"]
        if name in CORE_OPS:
            owners["core"].update(index.runtime_ids(row))
        elif name.endswith(": _output_projection"):
            owners["output"].update(index.runtime_ids(row))
        elif name.endswith(": _build_chunk_metadata"):
            owners["metadata"].update(index.runtime_ids(row))

    for row in rows:
        name = row["name"]
        for suffix, scope in CORE_SUBSCOPES.items():
            if name.endswith(suffix):
                owners[scope].update(index.runtime_ids(row) & owners["core"])
                break
        if name.endswith("causal_conv1d_update"):
            owners["conv_update"].update(index.runtime_ids(row) & owners["core"])
        elif name.endswith("causal_conv1d_fn"):
            owners["conv_forward"].update(index.runtime_ids(row) & owners["core"])
        if name != "_C_sdaa::fused_norm":
            continue
        mode = str(row["norm_mode"])
        if mode == "5":
            owners["qk_norm"].update(index.runtime_ids(row) & owners["core"])
        elif mode == "2" and row["gate_type"]:
            owners["output_norm"].update(index.runtime_ids(row) & owners["output"])
    return owners


def _detail(role, bases):
    return dict(category="GDN", semantic_type=role, rule_id=f"gdn.context.{role}",
        rule_platform="trace", confidence="high", reason="gdn:verified-cpu-source",
        evidence=[f"Same-trace GDN source scope via {basis}." for basis in sorted(bases)],
        matched_pattern=None, ambiguity_reasons=[], category_candidates=["GDN"])


def gdn_context(tp, raw, classifier, metadata, index=None, **device_scope):
    """Return per-name assignments or exact event allocations for native input."""
    if classifier.schema_version < 3 or classifier.platform == "dcu":
        return {}
    raw_by_name = {row["name"]: row for row in raw}
    base = {name: classifier.classify_detail(name) for name in raw_by_name}
    has_recurrent = any(detail["category"] == "GDN" and detail["semantic_type"].startswith("gdn_recurrent")
                        for detail in base.values())
    # A dedicated recurrent symbol can still identify a graph-only GDN window.
    if not has_recurrent and not run_perfetto_query(tp, """SELECT 1 FROM slice WHERE category='cpu_op'
        AND name IN ('vllm::qwen_gdn_attention_core',
                     'vllm::qwen_gdn_attention_core_fused_norm_packed') LIMIT 1"""):
        return {}
    if index is None:
        index = DeviceStepIndex.from_processor(tp, **device_scope)
    scopes = _source_scopes(tp, index)
    start, end = (int(metadata[k]) for k in ("absolute_start_ts_ns", "absolute_end_ts_ns"))
    tracks = set(metadata["track_ids"])
    eligible = {name for name, detail in base.items() if detail["category"] in SHARED_CATEGORIES}
    graph_launches = {rid for rid, runtime in index.runtimes.items() if is_graph_launch(runtime)}
    grouped = defaultdict(lambda: defaultdict(list))
    graph_candidates = defaultdict(list)
    for event in index.events:
        if event["name"] not in eligible or event["track_id"] not in tracks or not start <= event["ts"] < end:
            continue
        link = index.links[event["id"]]
        launches = link["candidates"]
        replay_link = bool(link["possible"] & graph_launches)
        role = None if launches & graph_launches else _gdn_role(event, launches, scopes)
        grouped[event["name"]][role].append(event)
        name = event["name"].lower()
        if (not role and has_recurrent and replay_link and
                ("causal_conv1d" in name or "fusednormargs" in name or name in OUTPUT_SYMBOLS)):
            graph_candidates[event["name"]].append(event)

    result = {}
    for name, groups in grouped.items():
        candidates = graph_candidates.get(name, [])
        original = base[name]
        if candidates:
            original = dict(original, gdn_graph_candidate=dict(
                record_count=len(candidates), total_duration_us=sum(e["dur"] for e in candidates)/1000,
                basis="graph-replay-without-per-operator-source"),
                ambiguity_reasons=original["ambiguity_reasons"] + [
                    "Graph replay does not prove that these shared-symbol calls belong to GDN."],
                category_candidates=list(dict.fromkeys([*original["category_candidates"], "GDN"])))
        if not any(groups):
            if candidates:
                result[name] = original
            continue
        events_for_name = [event for events in groups.values() for event in events]
        expected = raw_by_name[name]
        if (len(events_for_name) != expected["record_count"] or
                not math.isclose(sum(e["dur"] for e in events_for_name)/1000,
                                 expected["total_duration_us"], abs_tol=1e-6)):
            raise ValueError(f"GDN event scope differs from the original SQL row for {name}")
        if len(groups) == 1:
            role, events = next(iter(groups.items()))
            result[name] = _detail(role, {index.links[e["id"]]["basis"] for e in events})
            continue
        parts = []
        for role, events in groups.items():
            dur = sum(e["dur"] for e in events)
            detail = _detail(role, {index.links[e["id"]]["basis"] for e in events}) if role else original.copy()
            parts.append(dict(record_count=len(events), duration_ns=dur,
                event_ids=[e["id"] for e in events], classification=detail,
                window_absolute_pct=dur/(end-start)*100))
        result[name] = dict(original, allocations=parts,
            ambiguity_reasons=original["ambiguity_reasons"] + [
                "Shared symbol has multiple invocation groups. The confirmed GDN calls are counted in the source-based parts."
            ])
    return result
