#!/usr/bin/env python3
"""Load editable name-based classification rules for profiling kernels.

Rules live in ``../rules/kernel-classification-rules.json`` rather than code.
``auto`` preserves cross-platform behavior; a selected platform uses its own
rules plus ``common``. A name match is evidence, not runtime source attribution.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Optional


CATEGORIES = (
    "gemm",
    "group gemm",
    "通信 (comm)",
    "FlashAttention (fa)",
    "Triton",
    "其他elementwise",
    "memcpy/memset",
)
DENSE_CATEGORIES = tuple(category for category in CATEGORIES if category != "group gemm")
PLATFORMS = ("auto", "nv", "dcu", "teco")
DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "kernel-classification-rules.json"


def active_categories(present, *, moe: bool = False) -> tuple[str, ...]:
    """Keep the dense six-row report; expose expert group GEMM when observed.

    ``present`` contains classified categories, not raw kernel/model names.
    Verified MoE helpers may expose an empty expert row, but never turn
    routing or generic batched products into expert arithmetic by themselves.
    """
    return CATEGORIES if moe or "group gemm" in present else DENSE_CATEGORIES


class RuleConfigurationError(ValueError):
    """An invalid rule artifact; callers must fix it rather than ignore it."""


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    platform: str
    category: Optional[str]
    reason: str
    priority: int
    patterns: tuple[tuple[str, re.Pattern[str]], ...]
    semantic_type: str
    evidence: tuple[str, ...]
    confidence: str
    ambiguity_reasons: tuple[str, ...]
    category_candidates: tuple[str, ...]
    notes: Optional[str]
    match_on: str = "kernel_name"
    source_categories: tuple[str, ...] = ()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuleConfigurationError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _nonempty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuleConfigurationError(f"{context} must be a non-empty string")
    return value


def _string_list(value: Any, context: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "a list" if allow_empty else "a non-empty list"
        raise RuleConfigurationError(f"{context} must be {qualifier} of strings")
    return [_nonempty_string(item, f"{context}[{index}]") for index, item in enumerate(value)]


def _validate_detail(value: Any, context: str, *, allow_excluded: bool) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuleConfigurationError(f"{context} must be an object")
    detail = {}
    for key in ("id", "reason", "semantic_type"):
        detail[key] = _nonempty_string(value.get(key), f"{context}.{key}")
    if "category" not in value:
        raise RuleConfigurationError(f"{context}.category is required")
    category = value["category"]
    if category not in CATEGORIES and not (allow_excluded and category is None):
        raise RuleConfigurationError(f"{context}.category {category!r} is not a supported report category")
    detail["category"] = category
    detail["evidence"] = _string_list(value.get("evidence"), f"{context}.evidence", allow_empty=True)
    confidence = value.get("confidence")
    if confidence not in ("high", "medium", "low", "unknown"):
        raise RuleConfigurationError(f"{context}.confidence must be high, medium, low, or unknown")
    detail["confidence"] = confidence
    detail["ambiguity_reasons"] = _string_list(value.get("ambiguity_reasons", []), f"{context}.ambiguity_reasons", allow_empty=True)
    candidates = _string_list(value.get("category_candidates", [category] if category is not None else []),
                              f"{context}.category_candidates", allow_empty=True)
    if any(candidate not in CATEGORIES for candidate in candidates):
        raise RuleConfigurationError(f"{context}.category_candidates contains an unsupported category")
    detail["category_candidates"] = candidates
    detail["notes"] = _nonempty_string(value["notes"], f"{context}.notes") if "notes" in value else None
    return detail


class KernelClassifier:
    """Compile a rule artifact once, with an explicit platform scope.

    Lower ``priority`` values win globally across enabled groups. Equal
    priorities use artifact group order and then rule order. Editing a rule
    file takes effect in the next instance or ``configure_classifier`` call.
    """

    def __init__(self, rules_path: Optional[str | Path] = None, platform: str = "auto"):
        if platform not in PLATFORMS:
            raise RuleConfigurationError(f"unsupported platform {platform!r}; choose from {', '.join(PLATFORMS)}")
        self.platform = platform
        self.path = Path(rules_path if rules_path is not None else DEFAULT_RULES_PATH).expanduser().resolve()
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            raise RuleConfigurationError(f"cannot read kernel rules {self.path}: {exc}") from exc
        try:
            artifact = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
            self._load_artifact(artifact)
        except (UnicodeError, json.JSONDecodeError, RuleConfigurationError) as exc:
            raise RuleConfigurationError(f"invalid kernel rules {self.path}: {exc}") from exc
        self.sha256 = hashlib.sha256(raw).hexdigest()

    def _load_artifact(self, artifact: Any) -> None:
        if not isinstance(artifact, dict):
            raise RuleConfigurationError("root must be an object")
        if type(artifact.get("schema_version")) is not int or artifact["schema_version"] not in (1, 2):
            raise RuleConfigurationError("schema_version must be 1 (legacy dense) or 2 (group GEMM)")
        self.schema_version = artifact["schema_version"]
        self.version = _nonempty_string(artifact.get("version"), "version")
        declared_categories = DENSE_CATEGORIES if self.schema_version == 1 else CATEGORIES
        if artifact.get("categories") != list(declared_categories):
            raise RuleConfigurationError("categories must match the declared schema's supported report categories and order")
        keywords = artifact.get("compatibility_keywords")
        if not isinstance(keywords, dict) or set(keywords) != set(declared_categories):
            raise RuleConfigurationError("compatibility_keywords must contain exactly the declared report categories")
        self.compatibility_keywords = {
            category: _string_list(keywords.get(category, []), f"compatibility_keywords.{category}", allow_empty=True)
            for category in CATEGORIES
        }
        self.exclude_hints = _string_list(artifact.get("exclude_hints"), "exclude_hints", allow_empty=True)
        self.fallback = _validate_detail(artifact.get("fallback"), "fallback", allow_excluded=False)
        if self.fallback["category"] not in declared_categories:
            raise RuleConfigurationError("fallback.category is not declared by this schema")
        platforms = artifact.get("platforms")
        expected_groups = {"common", "nv", "dcu", "teco"}
        if not isinstance(platforms, dict) or set(platforms) != expected_groups:
            raise RuleConfigurationError("platforms must contain exactly common, nv, dcu, and teco groups")
        compiled = []
        context_rules = []
        seen_ids = {self.fallback["id"]}
        # Validate all groups even when a specific platform is selected. A typo
        # must fail consistently instead of remaining hidden until a later run.
        for group, rules in platforms.items():
            if not isinstance(rules, list):
                raise RuleConfigurationError(f"platforms.{group} must be a list of rules")
            for index, value in enumerate(rules):
                context = f"platforms.{group}[{index}]"
                detail = _validate_detail(value, context, allow_excluded=True)
                if detail["category"] is not None and detail["category"] not in declared_categories:
                    raise RuleConfigurationError(f"{context}.category is not declared by this schema")
                if detail["id"] in seen_ids:
                    raise RuleConfigurationError(f"duplicate rule id {detail['id']!r} in {context}")
                seen_ids.add(detail["id"])
                priority = value.get("priority")
                if type(priority) is not int:
                    raise RuleConfigurationError(f"{context}.priority must be an integer")
                patterns = []
                for pattern in _string_list(value.get("patterns"), f"{context}.patterns"):
                    try:
                        patterns.append((pattern, re.compile(pattern, re.IGNORECASE)))
                    except re.error as exc:
                        raise RuleConfigurationError(f"{context} ({detail['id']}) has invalid regex {pattern!r}: {exc}") from exc
                match_on = value.get("match_on", "kernel_name")
                if match_on not in ("kernel_name", "cpu_op"):
                    raise RuleConfigurationError(f"{context}.match_on must be kernel_name or cpu_op")
                sources = tuple(_string_list(value.get("source_categories", []), f"{context}.source_categories", allow_empty=True))
                if match_on == "cpu_op" and (detail['category'] != 'group gemm' or sources != ('gemm',)):
                    raise RuleConfigurationError(f"{context}: CPU context rules may only promote gemm to group gemm")
                rule = _Rule(
                    rule_id=detail["id"], platform=group,
                    category=detail["category"], reason=detail["reason"],
                    priority=priority, patterns=tuple(patterns),
                    semantic_type=detail["semantic_type"], evidence=tuple(detail["evidence"]),
                    confidence=detail["confidence"], ambiguity_reasons=tuple(detail["ambiguity_reasons"]),
                    category_candidates=tuple(detail["category_candidates"]),
                    notes=detail["notes"],
                    match_on=match_on, source_categories=sources,
                )
                if self.platform == "auto" or group in ("common", self.platform):
                    (context_rules if match_on == 'cpu_op' else compiled).append(rule)
        self.rules = tuple(sorted(compiled, key=lambda rule: rule.priority))
        self.context_rules = tuple(sorted(context_rules, key=lambda rule: rule.priority))

    def classify_host_operation(self, name: str) -> Optional[dict[str, Any]]:
        """Return an explicit expert API rule, never a host duration to add."""
        for rule in self.context_rules:
            for pattern, compiled in rule.patterns:
                if compiled.search(name):
                    return dict(category=rule.category, reason=rule.reason, rule_id=rule.rule_id,
                        rule_platform=rule.platform, semantic_type=rule.semantic_type,
                        evidence=list(rule.evidence), confidence=rule.confidence,
                        matched_pattern=pattern, ambiguity_reasons=list(rule.ambiguity_reasons),
                        category_candidates=list(rule.category_candidates), source_categories=list(rule.source_categories))
        return None

    def classify_detail(self, name: str) -> dict[str, Any]:
        """Return category, rule, matched regex and curated evidence.

        ``confidence`` describes rule evidence, not a probability and not proof
        that a particular runtime invocation has the declared semantics.
        ``None`` categories denote excluded profiler/runtime markers.
        """
        text = str(name)
        for rule in self.rules:
            for pattern, compiled in rule.patterns:
                if compiled.search(text):
                    detail = {
                        "category": rule.category, "reason": rule.reason,
                        "rule_id": rule.rule_id, "rule_platform": rule.platform,
                        "semantic_type": rule.semantic_type, "evidence": list(rule.evidence),
                        "confidence": rule.confidence, "matched_pattern": pattern,
                        "ambiguity_reasons": list(rule.ambiguity_reasons),
                        "category_candidates": list(rule.category_candidates),
                    }
                    if rule.notes is not None:
                        detail["notes"] = rule.notes
                    return detail
        detail = {
            "category": self.fallback["category"], "reason": self.fallback["reason"],
            "rule_id": self.fallback["id"], "rule_platform": "common",
            "semantic_type": self.fallback["semantic_type"], "evidence": list(self.fallback["evidence"]),
            "confidence": self.fallback["confidence"], "matched_pattern": None,
            "ambiguity_reasons": list(self.fallback["ambiguity_reasons"]),
            "category_candidates": list(self.fallback["category_candidates"]),
        }
        if self.fallback["notes"] is not None:
            detail["notes"] = self.fallback["notes"]
        return detail

    def classify_kernel_with_reason(self, name: str) -> tuple[Optional[str], str]:
        detail = self.classify_detail(name)
        return detail["category"], detail["reason"]

    def get_rule_provenance(self) -> dict[str, str]:
        return {"path": str(self.path), "sha256": self.sha256, "version": self.version, "platform": self.platform}


_DEFAULT_CLASSIFIER = KernelClassifier()
# Keep the mapping and list objects stable for existing ``from ... import``
# callers. They are presentation hints; regex rules perform classification.
OP_CATEGORIES = {category: list(words) for category, words in _DEFAULT_CLASSIFIER.compatibility_keywords.items()}
EXCLUDE_PATTERNS = list(_DEFAULT_CLASSIFIER.exclude_hints)


def configure_classifier(rules_path: Optional[str | Path] = None, platform: str = "auto") -> KernelClassifier:
    """Replace the active classifier only after the complete artifact validates."""
    global _DEFAULT_CLASSIFIER
    classifier = KernelClassifier(rules_path, platform)
    _DEFAULT_CLASSIFIER = classifier
    OP_CATEGORIES.clear()
    OP_CATEGORIES.update({category: list(words) for category, words in classifier.compatibility_keywords.items()})
    EXCLUDE_PATTERNS[:] = classifier.exclude_hints
    return classifier


def get_rule_provenance() -> dict[str, str]:
    """Identify the exact artifact used by the public classification wrappers."""
    return _DEFAULT_CLASSIFIER.get_rule_provenance()


def add_classification_args(parser: Any) -> None:
    """Add shared CLI arguments; callers configure after parsing them."""
    parser.add_argument("--kernel-rules", default=None, help="Editable kernel rule JSON (default: bundled rules/kernel-classification-rules.json)")
    parser.add_argument("--platform", choices=PLATFORMS, default="auto", help="Enable this platform's rules plus common; auto enables all groups")


def classify_kernel_with_reason(name: str) -> tuple[Optional[str], str]:
    """Return the stable category and audit reason using the active artifact."""
    return _DEFAULT_CLASSIFIER.classify_kernel_with_reason(name)


def classify_kernel_detail(name: str) -> dict[str, Any]:
    """Return matched rule evidence using the active classifier."""
    return _DEFAULT_CLASSIFIER.classify_detail(name)


def classify_kernel(name: str) -> Optional[str]:
    """Return the stable report category, or None for excluded markers."""
    return classify_kernel_with_reason(name)[0]


def classification_reason(name: str) -> str:
    """Return the rule/audit reason used for name."""
    return classify_kernel_with_reason(name)[1]


def should_exclude_kernel(name: str) -> bool:
    """Whether name is a non-compute trace marker."""
    return classify_kernel(name) is None
