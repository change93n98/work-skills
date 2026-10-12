#!/usr/bin/env python3
"""Behavior tests for the editable cross-platform rule artifact."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from kernel_categories import (
    CATEGORIES, DEFAULT_RULES_PATH, EXCLUDE_PATTERNS, OP_CATEGORIES,
    KernelClassifier, RuleConfigurationError, add_classification_args,
    classification_reason, classify_kernel, classify_kernel_detail,
    classify_kernel_with_reason, configure_classifier, get_rule_provenance,
    should_exclude_kernel,
)


class KernelRuleArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "rules.json"
        self.artifact = json.loads(DEFAULT_RULES_PATH.read_text(encoding="utf-8-sig"))

    def tearDown(self):
        configure_classifier()
        self.temporary.cleanup()

    def write(self, artifact=None):
        value = self.artifact if artifact is None else artifact
        self.path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return self.path

    def rule(self, rule_id, category, priority, pattern, **extra):
        value = {
            "id": rule_id, "category": category, "reason": "test:" + rule_id,
            "priority": priority, "patterns": [pattern], "semantic_type": "test_semantic",
            "evidence": ["test fixture evidence"], "confidence": "medium",
        }
        value.update(extra)
        return value

    def test_bundled_artifact_is_default_and_records_exact_hash(self):
        classifier = KernelClassifier()
        provenance = classifier.get_rule_provenance()
        self.assertEqual(provenance["path"], str(DEFAULT_RULES_PATH.resolve()))
        self.assertEqual(provenance["sha256"], hashlib.sha256(DEFAULT_RULES_PATH.read_bytes()).hexdigest())
        self.assertEqual(provenance["version"], self.artifact["version"])
        self.assertEqual(provenance["platform"], "auto")

    def test_platform_scope_with_framework_common_rules(self):
        examples = {
            "nv": "nvjet_sm90_tst_192x8_64x8",
            "dcu": "Cijk_Alik_Bljk_F8BS_MT16x16x64",
            "teco": "slave_mm_dequantize_v3<1536u>(Args)",
        }
        for platform, name in examples.items():
            with self.subTest(platform=platform):
                self.assertEqual(KernelClassifier(platform=platform).classify_detail(name)["category"], "gemm")
                self.assertEqual(KernelClassifier().classify_detail(name)["category"], "gemm")
                for other in set(examples) - {platform}:
                    self.assertEqual(KernelClassifier(platform=other).classify_detail(name)["reason"], "fallback:unknown")
        for platform in examples:
            self.assertEqual(KernelClassifier(platform=platform).classify_detail("triton_poi_fused_add")["category"], "Triton")
            self.assertIsNone(KernelClassifier(platform=platform).classify_detail("WAIT")["category"])

    def test_editable_override_changes_behavior_and_provenance(self):
        name = "unique_custom_kernel_xyz"
        old = KernelClassifier().classify_detail(name)
        self.assertEqual(old["reason"], "fallback:unknown")
        self.artifact["platforms"]["teco"].append(self.rule("custom.override", "gemm", -10, "unique_custom_kernel_xyz"))
        configured = configure_classifier(self.write(), "teco")
        self.assertEqual(classify_kernel(name), "gemm")
        self.assertEqual(classify_kernel_with_reason(name), ("gemm", "test:custom.override"))
        self.assertEqual(classify_kernel_detail(name), configured.classify_detail(name))
        initial_hash = get_rule_provenance()["sha256"]
        self.artifact["platforms"]["teco"][-1]["category"] = "FlashAttention (fa)"
        self.write()
        configure_classifier(self.path, "teco")
        self.assertEqual(classify_kernel(name), "FlashAttention (fa)")
        self.assertNotEqual(get_rule_provenance()["sha256"], initial_hash)

    def test_global_priority_wins_before_group_and_file_order(self):
        self.artifact["platforms"]["common"] = [self.rule("late.common", "gemm", 100, "collision")]
        self.artifact["platforms"]["teco"] = [self.rule("early.teco", "FlashAttention (fa)", -100, "collision")]
        detail = KernelClassifier(self.write(), "teco").classify_detail("collision")
        self.assertEqual(detail["rule_id"], "early.teco")
        self.assertEqual(KernelClassifier(self.path, "nv").classify_detail("collision")["rule_id"], "late.common")

    def test_equal_priority_is_stable_in_artifact_order(self):
        self.artifact["platforms"]["common"] = [self.rule("first", "gemm", 1, "collision"), self.rule("second", "Triton", 1, "collision")]
        self.artifact["platforms"]["teco"] = [self.rule("third", "FlashAttention (fa)", 1, "collision")]
        self.assertEqual(KernelClassifier(self.write(), "teco").classify_detail("collision")["rule_id"], "first")

    def test_detail_preserves_evidence_ambiguity_and_pattern(self):
        self.artifact["platforms"]["common"].insert(0, self.rule(
            "detailed", "gemm", -1, r"detail_[0-9]+", confidence="low",
            ambiguity_reasons=["May be a preparation kernel"], notes="Inspect the source",
        ))
        classifier = KernelClassifier(self.write())
        detail = classifier.classify_detail("DETAIL_42")
        self.assertEqual(detail["matched_pattern"], r"detail_[0-9]+")
        self.assertEqual(detail["semantic_type"], "test_semantic")
        self.assertEqual(detail["evidence"], ["test fixture evidence"])
        self.assertEqual(detail["confidence"], "low")
        self.assertEqual(detail["ambiguity_reasons"], ["May be a preparation kernel"])
        self.assertEqual(detail["notes"], "Inspect the source")
        detail["evidence"].clear()
        detail["ambiguity_reasons"].clear()
        self.assertTrue(classifier.classify_detail("DETAIL_42")["evidence"])
        self.assertTrue(classifier.classify_detail("DETAIL_42")["ambiguity_reasons"])

    def test_fallback_marks_unknown_without_semantic_confirmation(self):
        detail = KernelClassifier().classify_detail("unknown_xyz_no_marker")
        self.assertEqual(detail["category"], "其他elementwise")
        self.assertEqual(detail["reason"], "fallback:unknown")
        self.assertEqual(detail["semantic_type"], "unknown")
        self.assertEqual(detail["confidence"], "unknown")
        self.assertIsNone(detail["matched_pattern"])
        self.assertTrue(detail["ambiguity_reasons"])

    def test_public_legacy_api_and_report_order_remain_compatible(self):
        configure_classifier()
        self.assertEqual(tuple(OP_CATEGORIES), CATEGORIES)
        self.assertEqual(classify_kernel("nvjet_sm90_tst_192x8"), "gemm")
        self.assertEqual(classify_kernel("CKFmhaFwdKernel<Args>"), "FlashAttention (fa)")
        self.assertEqual(classify_kernel("tecodnn::ual::slave::teco_slave_broadcast_add(Args)"), "其他elementwise")
        self.assertEqual(classification_reason("tecodnn::ual::slave::teco_slave_broadcast_add(Args)"), "elementwise:CUDA/ROCm/T100")
        self.assertTrue(should_exclude_kernel("WAIT"))
        self.assertTrue(should_exclude_kernel("ProfilerStep#1"))
        self.assertFalse(should_exclude_kernel("wait_for_tensor"))
        self.assertEqual(classification_reason("gemma_norm_kernel"), "fallback:unknown")

    def test_configuration_updates_compatibility_objects_in_place(self):
        mapping, hints = OP_CATEGORIES, EXCLUDE_PATTERNS
        self.artifact["compatibility_keywords"]["gemm"].append("added_custom_hint")
        self.artifact["exclude_hints"].append("added_exclude_hint")
        configure_classifier(self.write())
        self.assertIs(mapping, OP_CATEGORIES)
        self.assertIs(hints, EXCLUDE_PATTERNS)
        self.assertIn("added_custom_hint", mapping["gemm"])
        self.assertIn("added_exclude_hint", hints)

    def test_failed_configuration_does_not_replace_active_classifier(self):
        configure_classifier(platform="teco")
        provenance = get_rule_provenance()
        self.artifact["platforms"]["common"][0]["patterns"] = ["["]
        with self.assertRaises(RuleConfigurationError):
            configure_classifier(self.write(), "nv")
        self.assertEqual(get_rule_provenance(), provenance)

    def test_invalid_json_and_missing_file_fail_with_path(self):
        self.path.write_text('{"invalid":', encoding="utf-8")
        with self.assertRaisesRegex(RuleConfigurationError, "invalid kernel rules") as error:
            KernelClassifier(self.path)
        self.assertIn(str(self.path), str(error.exception))
        with self.assertRaisesRegex(RuleConfigurationError, "cannot read kernel rules"):
            KernelClassifier(self.path.parent / "missing.json")

    def test_duplicate_json_keys_are_rejected(self):
        self.path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaisesRegex(RuleConfigurationError, "duplicate JSON key"):
            KernelClassifier(self.path)

    def test_malformed_artifact_fields_fail_clearly(self):
        mutations = [
            ("schema_version", lambda a: a.update(schema_version=2)),
            ("categories", lambda a: a.update(categories=["wrong"])),
            ("compatibility_keywords", lambda a: a.update(compatibility_keywords={})),
            ("platforms", lambda a: a["platforms"].update(unknown=[])),
            ("category", lambda a: a["platforms"]["common"][0].update(category="bogus")),
            ("priority", lambda a: a["platforms"]["common"][0].update(priority=True)),
            ("invalid regex", lambda a: a["platforms"]["common"][0].update(patterns=["["])),
            ("patterns", lambda a: a["platforms"]["common"][0].update(patterns=[])),
            ("evidence", lambda a: a["platforms"]["common"][0].update(evidence="not a list")),
            ("confidence", lambda a: a["platforms"]["common"][0].update(confidence="sure")),
            ("duplicate rule id", lambda a: a["platforms"]["nv"].append(copy.deepcopy(a["platforms"]["common"][0]))),
            ("ambiguity_reasons", lambda a: a["platforms"]["common"][0].update(ambiguity_reasons="maybe")),
        ]
        for message, mutate in mutations:
            with self.subTest(message=message):
                artifact = copy.deepcopy(self.artifact)
                mutate(artifact)
                with self.assertRaisesRegex(RuleConfigurationError, message):
                    KernelClassifier(self.write(artifact))

    def test_unselected_platform_is_also_validated(self):
        self.artifact["platforms"]["dcu"][0]["patterns"] = ["["]
        with self.assertRaisesRegex(RuleConfigurationError, "invalid regex"):
            KernelClassifier(self.write(), "nv")

    def test_unsupported_platform_fails(self):
        with self.assertRaisesRegex(RuleConfigurationError, "unsupported platform"):
            KernelClassifier(platform="cuda")

    def test_cli_arguments_have_expected_destinations(self):
        parser = argparse.ArgumentParser()
        add_classification_args(parser)
        arguments = parser.parse_args(["--kernel-rules", "edited.json", "--platform", "teco"])
        self.assertEqual(arguments.kernel_rules, "edited.json")
        self.assertEqual(arguments.platform, "teco")
        self.assertEqual(parser.parse_args([]).platform, "auto")


if __name__ == "__main__":
    unittest.main(verbosity=2)
