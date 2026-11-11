import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from device_step_window import DeviceStepIndex
from gdn_comparison import summarize_gdn
from gdn_context import gdn_context
from kernel_categories import KernelClassifier
from prof import classify_rows


class GdnClassificationTests(unittest.TestCase):
    def test_legacy_delivery_scope_classifies_only_linked_device_calls(self):
        trace = sqlite3.connect(":memory:")
        self.addCleanup(trace.close)
        trace.row_factory = sqlite3.Row
        trace.create_function("extract_arg", 2, lambda *_: None)
        trace.execute("CREATE TABLE thread_track (id, utid)")
        trace.execute("INSERT INTO thread_track VALUES (1, 1)")
        trace.execute("CREATE TABLE slice (id, name, category, ts, dur, track_id, arg_set_id)")
        trace.executemany("INSERT INTO slice VALUES (?, ?, ?, ?, ?, 1, NULL)", [
            (10, "vllm::gdn_attention_core", "cpu_op", 0, 30),
            (11, "_C_sdaa::causal_conv1d_fn", "cpu_op", 1, 8),
            (12, "/vllm/model_executor/layers/mamba/gdn_linear_attn.py(493): rearrange_mixed_qkv",
             "python_function", 10, 8),
            (13, "/vllm_sdaa/layers/fla/ops/chunk.py(16): l2norm", "python_function", 20, 8),
        ])
        conv = "teco_slave_causal_conv1d_perf(Args)"
        copy = "Memcpy DtoD"
        norm = "fused_norm(FusedNormArgs)"
        runtimes = [dict(id=i, name="sdaaLaunchKernel", category="privateuse1_runtime",
                         correlation=i, ts=ts, dur=1, host_thread=1, track_id=1)
                    for i, ts in enumerate((2, 12, 22, 32), start=1)]
        events = [dict(id=100+r["id"], name=name, category=category, correlation=r["id"],
                       ts=r["ts"]+1, dur=1000, device=0, stream=1, track_id=2)
                  for r, (name, category) in zip(runtimes, [
                      (conv, "kernel"), (copy, "gpu_memcpy"), (norm, "kernel"), (copy, "gpu_memcpy")])]
        index = DeviceStepIndex(events, runtimes, [], [], 0, lambda sid: [])
        raw = [dict(name=name, record_count=count, total_duration_us=count, window_absolute_pct=count)
               for name, count in ((conv, 1), (copy, 2), (norm, 1))]
        classifier = KernelClassifier(platform="teco")
        with patch("gdn_context.run_perfetto_query",
                   side_effect=lambda tp, sql: [dict(row) for row in tp.execute(sql)]):
            evidence = gdn_context(trace, raw, classifier, dict(
                absolute_start_ts_ns="0", absolute_end_ts_ns="100000", track_ids=[2]), index)
        self.assertEqual(evidence[conv]["semantic_type"], "gdn_conv")
        self.assertEqual(evidence[norm]["semantic_type"], "gdn_qk_norm")
        self.assertEqual([(part["classification"]["semantic_type"], part["event_ids"])
                          for part in evidence[copy]["allocations"] if part["classification"]["category"] == "GDN"],
                         [("gdn_rearrange_qkv", [102])])

    def test_verified_symbols_resolve_to_distinct_subtypes(self):
        teco = KernelClassifier(platform="teco")
        kernels = {
            "tecolmk_slave_compute_decay_mask_u_w<1>(ChunkGatedDeltaRuleArgs)": "gdn_chunk_prepare",
            "tecolmk_slave_compute_v_new_last_state<1>(ChunkGatedDeltaRuleArgs)": "gdn_chunk_state",
            "tecolmk_slave_compute_o<1>(ChunkGatedDeltaRuleArgs)": "gdn_chunk_output",
        }
        for name, role in kernels.items():
            detail = teco.classify_detail(name)
            self.assertEqual((detail["category"], detail["semantic_type"]), ("GDN", role))
        nv = KernelClassifier(platform="nv")
        detail = nv.classify_detail("kernel_cutlass_kernel_flashinfergdn_kernelsdelta_rule_dsl"
                                    "delta_rule_cp_sm90CPDeltaRuleFixupSimtSm90_object_at")
        self.assertEqual((detail["category"], detail["semantic_type"]), ("GDN", "gdn_chunk_fixup"))
        for name, role in (
            ("fused_recurrent_gated_delta_rule_packed_decode_kernel", "gdn_recurrent_packed"),
            ("fused_sigmoid_gating_delta_rule_update_kernel", "gdn_recurrent_fused"),
            ("fused_gdn_gating_kernel", "gdn_gating"),
        ):
            detail = nv.classify_detail(name)
            self.assertEqual((detail["category"], detail["semantic_type"]), ("GDN", role))
        for name in ("causal_conv1d_fwd_kernel", "fused_norm(FusedNormArgs)", "compute_o(ChunkGatedDeltaRuleArgs)"):
            self.assertNotEqual(teco.classify_detail(name)["category"], "GDN")

    def test_shared_conv_only_counts_source_confirmed_calls(self):
        name = "teco_slave_causal_conv1d_perf(Args)"
        runtimes = [dict(id=i, name="sdaaLaunchKernel", category="sdaa_runtime",
            correlation=i, ts=t, dur=1, host_thread=1, track_id=1)
            for i,t in enumerate((2,12,32),start=1)]
        events = [dict(id=100+r["id"], name=name, category="kernel", correlation=r["id"],
            ts=r["ts"]+1, dur=1000, device=0, stream=1, track_id=2) for r in runtimes]
        index = DeviceStepIndex(events,runtimes,[],[],0,lambda sid: [])
        scopes = [
            dict(id=20,name="vllm::qwen_gdn_attention_core",ts=0,dur=20,host_thread=1,track_id=1),
            dict(id=21,name="_C_sdaa::custom_causal_conv1d_fn",ts=1,dur=7,host_thread=1,track_id=1),
            dict(id=22,name="_C_sdaa::custom_causal_conv1d_update",ts=11,dur=7,host_thread=1,track_id=1),
        ]
        raw = [dict(name=name,record_count=3,total_duration_us=3,window_absolute_pct=3)]
        classifier = KernelClassifier(platform="teco")
        with patch("gdn_context.run_perfetto_query",side_effect=[[{"exists":1}],scopes]):
            evidence = gdn_context(None,raw,classifier,dict(
                absolute_start_ts_ns="0",absolute_end_ts_ns="100000",track_ids=[2]),index)
        kernels, summary, _, busy = classify_rows(raw,classifier,evidence)
        self.assertEqual(busy,3)
        self.assertEqual(kernels[0]["record_count"],3)
        parts = kernels[0]["category_parts"]
        self.assertEqual([part["event_ids"] for part in parts],[[101],[102],[103]])
        self.assertEqual([part["classification"]["semantic_type"] for part in parts[:2]],
                         ["gdn_conv","gdn_conv_update"])
        by_category = {row["category"]:row for row in summary}
        self.assertEqual(by_category["GDN"]["record_count"],2)
        self.assertEqual(by_category["GDN"]["kernel_kinds"],1)
        self.assertEqual(by_category["其他elementwise"]["total_duration_us"],1)

    def test_operator_scopes_split_a_shared_copy_and_keep_l2_separate(self):
        name = "Memcpy DtoD"
        times = (2, 4, 12, 22, 24, 32, 42)
        runtimes = [dict(id=i, name="sdaaLaunchKernel", category="sdaa_runtime",
            correlation=i, ts=t, dur=1, host_thread=1, track_id=1)
            for i, t in enumerate(times, start=1)]
        events = [dict(id=100+r["id"], name=name, category="gpu_memcpy", correlation=r["id"],
            ts=r["ts"]+1, dur=1000, device=0, stream=1, track_id=2) for r in runtimes]
        index = DeviceStepIndex(events, runtimes, [], [], 0, lambda sid: [])
        scopes = [dict(id=i, name=scope, ts=start, dur=dur, host_thread=1, track_id=1)
            for i, (scope, start, dur) in enumerate([
                ("vllm::qwen_gdn_attention_core", 0, 40),
                ("vllm/model_executor/layers/mamba/gdn/qwen_gdn_linear_attn.py(792): rearrange_mixed_qkv", 0, 9),
                ("/vllm_sdaa/layers/mamba/gdn_linear_attn.py(97): fused_gdn_gating", 10, 9),
                ("/vllm_sdaa/layers/fla/ops/chunk.py(16): l2norm", 21, 2),
                ("/vllm_sdaa/layers/fla/ops/chunk.py(16): l2norm", 23, 3),
                ("_C_sdaa::chunk_gated_delta_rule_fwd", 30, 9),
            ], start=20)]
        raw = [dict(name=name, record_count=7, total_duration_us=7, window_absolute_pct=7)]
        classifier = KernelClassifier(platform="teco")
        with patch("gdn_context.run_perfetto_query", side_effect=[[{"exists": 1}], scopes]):
            evidence = gdn_context(None, raw, classifier, dict(
                absolute_start_ts_ns="0", absolute_end_ts_ns="100000", track_ids=[2]), index)
        kernels, _, _, _ = classify_rows(raw, classifier, evidence)
        self.assertEqual([(part["classification"]["semantic_type"], part["event_ids"])
                          for part in kernels[0]["category_parts"][:4]], [
            ("gdn_rearrange_qkv", [101, 102]), ("gdn_gating", [103]),
            ("gdn_qk_norm", [104, 105]), ("gdn_chunk_fwd_internal", [106]),
        ])
        self.assertEqual(kernels[0]["category_parts"][-1]["category"], "memcpy/memset")

    def test_decode_recurrent_scope_and_graph_ambiguity_are_separate(self):
        recurrent = "tecolmk_slave_fused_recurrent_gated_delta_rule<1>(FusedRecurrentGatedDeltaRuleArgs)"
        conv = "teco_slave_causal_conv1d_perf(Args)"
        rows = [dict(name=name, record_count=1, total_duration_us=1, window_absolute_pct=1)
                for name in (recurrent, conv, "Memcpy DtoD")]
        runtimes = [dict(id=i, name=runtime, category="privateuse1_runtime", correlation=i,
                         ts=ts, dur=1, host_thread=1, track_id=1)
                    for i, ts, runtime in [(1, 2, "sdaaGraphLaunch"), (2, 12, "sdaaMemcpyAsync")]]
        events = [dict(id=i+100, name=row["name"], category=cat, correlation=correlation,
                       ts=ts, dur=1000, device=0, stream=1, track_id=2)
                  for i, (row, ts, correlation, cat) in enumerate(zip(rows, (3, 4, 13), (1, 1, 2),
                      ("kernel", "kernel", "gpu_memcpy")))]
        index = DeviceStepIndex(events, runtimes, [], [], 0, lambda sid: [])
        scopes = [dict(id=i, name=scope, ts=ts, dur=dur, host_thread=1, track_id=1)
                  for i, scope, ts, dur in [(20, "vllm::qwen_gdn_attention_core", 0, 20),
                      (21, "_C_sdaa::custom_causal_conv1d_update", 0, 7),
                      (22, "_C_sdaa::fused_recurrent_gated_delta_rule_fwd", 10, 8)]]
        classifier = KernelClassifier(platform="teco")
        with patch("gdn_context.run_perfetto_query", return_value=scopes):
            evidence = gdn_context(None, rows, classifier, dict(
                absolute_start_ts_ns="0", absolute_end_ts_ns="100000", track_ids=[2]), index)
        kernels, summary, _, busy = classify_rows(rows, classifier, evidence)
        self.assertEqual([item["category"] for item in kernels], ["GDN", "其他elementwise", "GDN"])
        self.assertEqual(kernels[2]["classification"]["semantic_type"], "gdn_recurrent")
        self.assertEqual(kernels[1]["classification"]["gdn_graph_candidate"]["record_count"], 1)
        self.assertIn("GDN", kernels[1]["classification"]["category_candidates"])
        self.assertEqual(next(item for item in summary if item["category"] == "GDN")["total_duration_us"], 2)
        self.assertEqual(busy, 3)

    def test_comparison_aligns_fusions_and_keeps_mixed_windows_marked(self):
        layout = Path(__file__).resolve().parents[1] / "assets" / "report-layout.json"
        groups = json.loads(layout.read_text(encoding="utf8"))["gdn_comparison_groups"]

        def part(name, role, us):
            return dict(name=name, category="GDN", total_duration_us=us, record_count=1,
                        classification=dict(semantic_type=role))

        copy = part("copy", "gdn_rearrange_qkv", 5)
        teco = [dict(copy, category_parts=[copy]),
                part("gate", "gdn_gating", 7), part("norm", "gdn_qk_norm", 3)]
        nv = [part("_fused_post_conv_kernel", "gdn_gating_qk_fused", 4)]
        for kernels, us, kinds in ((teco, 15, 3), (nv, 4, 1)):
            result = summarize_gdn(kernels, dict(stage="prefill"), groups)
            self.assertEqual(result["scope"], "prefill")
            self.assertEqual([(r["group"], r["total_duration_us"], r["kernel_kinds"]) for r in result["rows"]],
                             [("卷积后准备", us, kinds)])
        for kernels, us in ((teco + [part("rec", "gdn_recurrent", 8)], 23),
                            ([part("packed", "gdn_recurrent_packed", 6)], 6)):
            result = summarize_gdn(kernels, dict(stage="decode"), groups)
            self.assertEqual(result["scope"], "decode")
            self.assertEqual([(r["group"], r["total_duration_us"]) for r in result["rows"]],
                             [("卷积后准备与递推", us)])
        mixed = summarize_gdn(nv + [part("rec", "gdn_recurrent_fused", 6)], dict(stage="decode"), groups)
        self.assertEqual(mixed["scope"], "mixed-or-stage-mismatch")
        self.assertEqual(sum(row["total_duration_us"] for row in mixed["rows"]), 10)
        annotation = {"name": "execute_context_1(1994)_generation_2(4)"}
        metadata = dict(stage="decode", device_step={"start": {"annotation": annotation}})
        result = summarize_gdn([part("rec", "gdn_recurrent_fused", 6)], metadata, groups)
        self.assertEqual(result["scope"], "mixed-or-stage-mismatch")
