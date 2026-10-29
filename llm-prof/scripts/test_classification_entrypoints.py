#!/usr/bin/env python3
"""External-rule CLI propagation and source-backed classification regressions."""

import json
import gzip
import sqlite3
import types
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kernel_categories import DEFAULT_RULES_PATH, KernelClassifier


class SemanticRulesTests(unittest.TestCase):
    def test_ffn_compute_and_activation_helper_are_separate(self):
        classifier = KernelClassifier(platform="teco")
        fused = classifier.classify_detail("void tecolmk_slave_ffn_layer_general_fused_for_small<4,32>(FfnLayerGeneralV2Args)")
        activation = classifier.classify_detail("_Z42tecolmk_slave_ffn_layer_general_activationIL16ActivationMode_t3EEvii")
        self.assertEqual((fused["category"], fused["semantic_type"]), ("gemm", "fused_ffn"))
        self.assertTrue(fused["evidence"])
        self.assertEqual((activation["category"], activation["semantic_type"]), ("其他elementwise", "activation"))

    def test_expected_prepare_gemv_and_linear_fusion(self):
        classifier = KernelClassifier(platform="teco")
        self.assertEqual(classifier.classify_detail("prepare_for_group_gemm_kernel_impl(Args)")["category"], "其他elementwise")
        self.assertEqual(classifier.classify_detail("custom_gemv_ace(Args)")["category"], "gemm")
        self.assertEqual(classifier.classify_detail("fused_activation_linear(Args)")["category"], "gemm")

    def test_verified_gemm_allreduce_is_local_not_collective(self):
        classifier=KernelClassifier(platform="teco")
        for variant in ("NN", "NT"):
            detail = classifier.classify_detail(
                f"tecoblas::ual::slave::teco_slave_gemm_{variant}_Afp16_Bfp16_Cfp16_allReduce(GemmWrapArgs)")
            self.assertEqual(detail["category"], "gemm")
            self.assertEqual(detail["confidence"], "high")
            self.assertFalse(detail["ambiguity_reasons"])
            self.assertEqual(detail["semantic_type"], "gemm_small_mn_local_reduce")
            self.assertEqual(detail["category_candidates"], ["gemm"])

    def test_unverified_blas_variant_does_not_become_communication(self):
        detail = KernelClassifier(platform="teco").classify_detail(
            "tecoblas::ual::slave::teco_slave_gemm_NN_Afp8_Bfp8_Cfp16_allReduce(GemmWrapArgs)")
        self.assertEqual(detail["confidence"], "unknown")
        self.assertTrue(detail["ambiguity_reasons"])

    def test_local_layout_helpers_are_not_arithmetic(self):
        classifier=KernelClassifier(platform="teco")
        self.assertEqual(classifier.classify_detail("teco_slave_no_broadcast_float_between_half(NoBroadcastArgs)")["semantic_type"],"dtype_transform")
        self.assertEqual(classifier.classify_detail("teco_slave_broadcast_expand_2d(BroadcastArgs)")["semantic_type"],"layout_expand")

    def test_wait_marker_differs_from_collective_wait(self):
        classifier = KernelClassifier(platform="teco")
        self.assertIsNone(classifier.classify_detail("WAIT")["category"])
        self.assertEqual(classifier.classify_detail("tcclStreamWaitFlagKernel(Args)")["category"], "通信 (comm)")

    def test_cache_and_linear_attention_have_distinct_subtypes(self):
        classifier = KernelClassifier(platform="teco")
        cache = classifier.classify_detail("tecolmk_slave_prefill_cache(BlockAttentionLayerArgs)")
        state = classifier.classify_detail("tecolmk_slave_compute_o(ChunkGatedDeltaRuleArgs)")
        self.assertEqual(cache["category"], "其他elementwise")
        self.assertEqual(state["category"], "其他elementwise")
        self.assertIn("cache", cache["semantic_type"])
        self.assertIn("linear_attention", state["semantic_type"])

    def test_explicit_gemm_beats_epilogue_names(self):
        for platform, name in (
            ("dcu", "ck::DeviceGemm_Xdl_CShuffle<Gelu, Args>"),
            ("dcu", "kernel_gemm_layernorm_xdl_cshuffle_v1<Args>"),
            ("nv", "cutlass::gemm::kernel::GemmUniversal<LinearCombinationRelu>"),
        ):
            with self.subTest(name=name):
                self.assertEqual(KernelClassifier(platform=platform).classify_detail(name)["category"], "gemm")

    def test_blas_namespace_does_not_turn_helpers_into_gemm(self):
        for platform, name in (("dcu", "hipblasLtMatrixTransform()"), ("dcu", "rocblas_saxpy()"),
                               ("nv", "cublasSaxpy()")):
            self.assertEqual(KernelClassifier(platform=platform).classify_detail(name)["category"], "其他elementwise")
        self.assertEqual(KernelClassifier(platform="nv").classify_detail("cutlass::UnidentifiedKernel()")
                         ["reason"], "fallback:unknown")

    def test_expected_moe_helpers_are_local(self):
        classifier = KernelClassifier(platform="teco")
        reduced = classifier.classify_detail("local_reduce_fused(Args)")
        routing = classifier.classify_detail("_C_sdaa::moe_routing")
        self.assertEqual((reduced["category"], reduced["semantic_type"]), ("其他elementwise", "moe_weighted_reduce"))
        self.assertEqual(routing["category"], "其他elementwise")


class ClassificationCliTests(unittest.TestCase):
    def test_audit_detects_fallback_even_when_reason_is_customized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = json.loads(DEFAULT_RULES_PATH.read_text(encoding="utf8"))
            artifact["fallback"]["reason"] = "custom:unmatched"
            rules = root / "rules.json"
            rules.write_text(json.dumps(artifact), encoding="utf8")
            trace = root / "trace.json"
            trace.write_text(json.dumps({"traceEvents": [dict(name="opaque_zeta", cat="kernel", dur=2)]}), encoding="utf8")
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("audit_kernel_categories.py")),
                                     str(trace), "--kernel-rules", str(rules), "--fail-on-fallback"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)

    def test_rule_override_reaches_all_entrypoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = json.loads(DEFAULT_RULES_PATH.read_text(encoding="utf8"))
            artifact["version"] = "test-cli-override"
            artifact["platforms"]["teco"].insert(0, {
                "id": "teco.cli.proof", "category": "group gemm", "reason": "test:external-json",
                "priority": -1, "patterns": ["^proof_kernel$"], "semantic_type": "test_group_gemm",
                "confidence": "high", "evidence": ["Synthetic behavioral fixture"],
            })
            rules = root / "rules.json"
            rules.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf8")
            events = []
            for start in (0, 100, 200):
                events.extend([
                    dict(name="model_forward", cat="user_annotation", ph="X", ts=start, dur=80, pid=42, tid=7),
                    dict(name="proof_kernel", cat="kernel", ph="X", ts=start+10, dur=5, pid=0, tid=19, args={"device": 0}),
                ])
            trace = root / "trace.json"
            trace.write_text(json.dumps({"traceEvents": events}), encoding="utf8")
            scripts = Path(__file__).parent
            for script in ("prof_analyze.py", "prof_analyze_perfetto.py"):
                with self.subTest(script=script):
                    output = root / script
                    # Force the documented missing-Perfetto fallback to verify
                    # rule arguments survive delegation to the JSON analyzer.
                    command = [sys.executable, str(scripts / script)]
                    if script == "prof_analyze_perfetto.py":
                        command = [sys.executable, "-c",
                                   "import sys;sys.path.insert(0,sys.argv.pop(1));"
                                   "sys.modules['perfetto.trace_processor']=None;"
                                   "import prof_analyze_perfetto;prof_analyze_perfetto.main()", str(scripts)]
                    result = subprocess.run(command + ["--trace-file", str(trace), "--output-dir", str(output),
                        "--kernel-rules", str(rules), "--platform", "teco"], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    report = json.loads((output / "prof_analysis.json").read_text(encoding="utf8"))
                    self.assertEqual(report["decode"]["group gemm"]["total_dur_ms"], .005)
                    self.assertEqual(report["classification_rules"]["version"], "test-cli-override")
                    self.assertEqual(report["decode_detailed"][0]["semantic_type"], "test_group_gemm")
            audit_out = root / "audit.json"
            result = subprocess.run([sys.executable, str(scripts / "audit_kernel_categories.py"), str(trace),
                "--kernel-rules", str(rules), "--platform", "teco", "--output", str(audit_out)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            audit = json.loads(audit_out.read_text(encoding="utf8"))
            self.assertEqual(audit["rows"][0]["count"], 3)
            self.assertEqual(audit["rows"][0]["semantic_type"], "test_group_gemm")
            mapping = root / "mapping.json"
            mapping.write_text(trace.read_text(encoding="utf8"), encoding="utf8")
            result = subprocess.run([sys.executable, str(scripts / "prof_graph_analyze.py"),
                "--mapping-trace", str(mapping), "--formal-trace", str(trace), "--stage", "all",
                "--output-dir", str(root / "graph"), "--kernel-rules", str(rules), "--platform", "teco"],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            graph = json.loads((root / "graph/graph_analysis.json").read_text(encoding="utf8"))
            self.assertEqual(graph["classification_rules"]["version"], "test-cli-override")
            self.assertEqual(graph["formal_total_duration_us"], 15)
            self.assertEqual(graph["kernels"][0]["semantic_type"], "test_group_gemm")


class PerfettoContractTests(unittest.TestCase):
    def test_gzip_decompression_preserves_binary_utf8(self):
        from prof_analyze_perfetto import decompress_trace
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.json.gz"
            payload = json.dumps({"name": "中文 kernel"}, ensure_ascii=False).encode("utf8")
            with gzip.open(path, "wb") as handle:
                handle.write(payload)
            decompressed = Path(decompress_trace(str(path)))
            try:
                self.assertEqual(decompressed.read_bytes(), payload)
            finally:
                decompressed.unlink()

    def test_device_sql_excludes_host_names_and_handles_sdk_rows(self):
        from prof_analyze_perfetto import get_kernels_perfetto
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.executescript("CREATE TABLE track(id INTEGER,name TEXT);"
                                 "CREATE TABLE slice(name TEXT,ts INTEGER,dur INTEGER,category TEXT,track_id INTEGER);"
                                 "INSERT INTO track VALUES(1,'host'),(2,'stream 19');")
        connection.executemany("INSERT INTO slice VALUES(?,?,?,?,?)", [
            ("teco_slave_gemm(Args)", 10, 5, "kernel", 2),
            ("teco_slave_gemm_host", 10, 500, "cpu_op", 1),
            ("WAIT", 20, 100, "gpu_memset", 2),
            ("MEMCPY_P2P", 30, 7, "gpu_memcpy", 2),
        ])
        class Processor:
            def query(self, sql):
                cursor = connection.execute(sql)
                names = [column[0] for column in cursor.description]
                class Rows:
                    column_names = names
                    def __iter__(self):
                        return iter(types.SimpleNamespace(**dict(zip(names, values))) for values in cursor.fetchall())
                return Rows()
        kernels = get_kernels_perfetto(Processor(), 0, 1000)
        self.assertEqual({kernel["name"] for kernel in kernels}, {"teco_slave_gemm(Args)", "MEMCPY_P2P"})
        self.assertEqual(sum(kernel["dur"] for kernel in kernels), 12)


if __name__ == "__main__":
    unittest.main()
