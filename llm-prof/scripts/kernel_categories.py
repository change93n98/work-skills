#!/usr/bin/env python3
"""Cross-platform kernel classification for LLM profiling traces.

The six report buckets are intentionally stable for existing consumers:
``gemm``, ``通信 (comm)``, ``FlashAttention (fa)``, ``Triton``,
``其他elementwise`` and ``memcpy/memset``.

Important design rule: a kernel name is evidence, not a complete semantic
contract.  Rules therefore use explicit vendor/library/operator markers,
ordered from the most specific semantics to the broad fallback.  The public
``classify_kernel`` API remains compatible, while ``classify_kernel_with_reason``
exposes the matched rule for audits and regression tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional


CATEGORIES = (
    "gemm",
    "通信 (comm)",
    "FlashAttention (fa)",
    "Triton",
    "其他elementwise",
    "memcpy/memset",
)

# Kept as a public compatibility mapping.  Unlike the old implementation,
# matching is performed by the ordered regex rules below, not by iterating this
# broad list with ``pattern in name``.
OP_CATEGORIES = {
    "gemm": [
        "gemm", "hgemm", "matmul", "nvjet_", "cublas", "rocblas", "hipblaslt",
        "CKGemm", "DeviceGemm", "GroupedGemm", "SplitkGemm", "StreamkGemm",
        "Cijk", "slave_gemm", "slave_mm_", "GemmWrapArgs", "linear_kernel",
    ],
    "通信 (comm)": [
        "tccl", "nccl", "rccl", "allreduce", "all_reduce", "allgather",
        "all_gather", "reduce_scatter", "two_shot", "one_shot",
        "cross_device_reduce", "mnnvl", "CustomAllReduce",
    ],
    "FlashAttention (fa)": [
        "flash::", "flash_attn", "FlashAttention", "FlashDecoding", "fmha",
        "mha_fwd", "mha_bwd", "paged_attention", "page_attention",
        "fused_block_attention", "block_attention", "teco_slave_flash_attention",
    ],
    "Triton": ["triton"],
    "其他elementwise": [
        "fused_qk_gemma_norm_mrope", "fused_norm", "layernorm", "rmsnorm",
        "ffn_layer_general", "causal_conv1d", "delta_rule", "gdn_gating",
        "softmax", "gelu", "silu", "rope", "mrope", "sampling",
    ],
    "memcpy/memset": [
        "memcpy", "memset", "copy_stride_dma", "set_tensor", "dma_2d", "dma_3d",
    ],
}


@dataclass(frozen=True)
class _Rule:
    category: Optional[str]
    reason: str
    patterns: tuple[re.Pattern[str], ...]


def _rule(category: Optional[str], reason: str, *patterns: str) -> _Rule:
    return _Rule(category, reason, tuple(re.compile(p, re.IGNORECASE) for p in patterns))


# Ordered semantic rules.  Do not move broad vendor fallbacks above explicit
# operator rules: CUTLASS contains both GEMM and FlashAttention/DeltaRule.
_RULES = (
    # Runtime/profiler markers are excluded from GPU busy time.  WAIT is an
    # exact trace marker; do not exclude arbitrary names merely containing
    # ``wait``.
    _rule(None, "runtime:WAIT/SET", r"^\s*(?:WAIT|SET)\s*$"),
    _rule(None, "runtime:profiler", r"(?:^|[_.:])profiler(?:$|[_.:])", r"ProfilerStep", r"torch\.autograd", r"autograd"),

    # Communication must be explicit.  Generic ``broadcast`` is deliberately
    # absent because T100 tecodnn broadcast_add/no_broadcast_* are local
    # elementwise kernels, not inter-device collectives.
    _rule("通信 (comm)", "collective:TCCL/NCCL/RCCL", r"\b(?:tccl|nccl|rccl)(?:[A-Za-z0-9_]|::)*"),
    _rule("通信 (comm)", "collective:all-reduce/gather/scatter", r"(?:all[_]?reduce|all[_]?gather|reduce[_]?scatter|custom[_]?allreduce)"),
    _rule("通信 (comm)", "collective:multi-device/fused", r"(?:cross[_]?device[_]?reduce|two[_]?shot|one[_]?shot|mnnvl|trtllm_mnnvl)"),

    # Explicit transfer/DMA names precede generic copy/elementwise names.
    _rule("memcpy/memset", "memory:CUDA/HIP transfer", r"(?:memcpy|memset|hipmem|hipmemcpy|asyncmemcpy|memcpyasync)"),
    _rule("memcpy/memset", "memory:T100 DMA/copy", r"(?:sdaart::sdaamemcpy|copy[_]?stride[_]?dma|teco_slave_(?:copy_stride|set_tensor|memset)|(?:^|[_.:])dma[_]?(?:2d|3d)(?:$|[_.:])|batch_memcpy|memcpy32|memcpy_p2p)"),
    _rule("memcpy/memset", "memory:directional transfer", r"(?:^|\s)(?:d2h|h2d|h2h|d2d)(?:$|\s|[()])"),

    # Attention-specific kernels precede CUTLASS/vendor fallbacks.
    _rule("FlashAttention (fa)", "attention:T100 flash/block attention", r"(?:teco_slave_flash_attention|fused_block_attention|block_attention)"),
    _rule("FlashAttention (fa)", "attention:CUDA/ROCm flash/fmha", r"(?:flash::|flash[_]?attn|flashattention|flash[_]?decoding|fmha|mha[_]?(?:fwd|bwd)|paged?[_]?attention|page[_]?attention)"),

    # Triton is an implementation backend and is unambiguous when it is an
    # actual kernel prefix/namespace.  Keep it before elementwise fallback.
    _rule("Triton", "backend:Triton", r"(?:^|[_.:])triton(?:$|[_.:])"),

    # T100/local knowledge and CUDA fused operators that are not GEMM.
    # ``gemma`` is intentionally handled here before the GEMM rule: the local
    # tecovllm op fused_qk_gemma_norm_mrope is norm/rope, not matrix multiply.
    _rule("其他elementwise", "fused:T100 qk-gemma norm/mrope", r"fused[_]?qk[_]?gemma[_]?norm[_]?mrope", r"fused[_]?qk.*norm.*(?:rope|mrope)"),
    _rule("其他elementwise", "fused:T100 norm/activation/FFN", r"(?:fused[_]?norm|layernorm|rmsnorm|ffn[_]?layer[_]?general|fused[_]?ffn|activation|gelu|silu|relu)"),
    _rule("其他elementwise", "fused:T100 DeltaRule/GDN/conv", r"(?:delta[_]?rule|deltarule|gated[_]?delta|fused[_]?recurrent|gdn[_]?gating|compute[_]v[_]?new|compute[_]o(?:_|$)|compute[_]decay|fused[_]?sigmoid[_]?gating|causal[_]?conv1d)"),
    _rule("其他elementwise", "fused:T100 layout/cache/index", r"(?:tecolmk_slave_(?:prefill_cache|block_kv_gather|src_kind.*permute)|reshape_and_cache|compute_slot_mapping|index[_]?tensor|cast[_]?tensor|reduce[_]?tensor|concat|permute|transpose|rotary|mrope|rope|embedding|top[_]?k|sampling|sample[_]?recovered|rejection_random|eagle_prepare_inputs|scatter_num_accepted)"),
    _rule("其他elementwise", "elementwise:CUDA/ROCm/T100", r"(?:elementwise|vectorized|unrolled_elementwise|softmax|scatter_gather|index_elementwise|index_put|catarray|direct_copy_kernel|binaryfunctor|fillfunctor|clamp_tensor|arg_max|(?:^|[_:.])reduce_kernel(?:$|[_:.])|(?:^|[_:.])unary(?:$|[_:.])|(?:^|[_:.])binary(?:$|[_:.])|(?:^|[_:.])ternary(?:$|[_:.])|tecodnn::ual::slave::teco_slave_(?:broadcast|no_broadcast|masked_fill|activation|gelu|softmax|embedding)|fused_post_conv|postprocess_mamba|teco_fused_add_bitwise|tecorand::|philox|xorwow|arange|linspace|gather_elements|scatter_out|expand_(?:impl|kernel)|bilinear_pos_embed|zero_kv_blocks|eagle_(?:set_inputs|prepare)|update_num_computed_tokens|fill_reverse_indices|radix_sort|device_scan|device_sort|scan_kernel|sort_kernel|teco_slave_cast|indexSelectSmallIndex|at::native::.*reduce_kernel|cub::detail::scan|DeviceScan|scan::)"),

    # GEMM rules use word/operator boundaries so ``gemma`` cannot match.
    _rule("gemm", "gemm:T100 GEMM/BLAS", r"(?:teco_slave_gemm|slave_gemm|slave_mm_|GemmWrapArgs|Gemm[MNK]|(?:^|[_.:])gemm(?:$|[_.:]))"),
    _rule("gemm", "gemm:CUDA/ROCm library", r"(?:nvjet_[a-z0-9_]+|cublas(?:lt)?|hipblaslt|rocblas|ckgemm|devicegemm|groupedgemm|splitkgemm|streamkgemm|cijk(?:_|$)|splitkreduce_kernel|linear_kernel)"),
    _rule("gemm", "gemm:CUTLASS non-attention", r"cutlass::"),
)


def classify_kernel_with_reason(name: str) -> tuple[Optional[str], str]:
    """Classify ``name`` and return ``(category, rule)``.

    ``None`` means the event is a runtime/profiler marker and must be excluded
    from kernel busy time.  Unknown valid GPU kernels intentionally fall back
    to ``其他elementwise`` for backward-compatible reports, but carry the
    ``fallback:unknown`` reason so audits can surface them.
    """
    text = str(name)
    for rule in _RULES:
        if any(pattern.search(text) for pattern in rule.patterns):
            return rule.category, rule.reason
    return "其他elementwise", "fallback:unknown"


def classify_kernel(name: str) -> Optional[str]:
    """Return the stable report category, or ``None`` for excluded markers."""
    return classify_kernel_with_reason(name)[0]


def classification_reason(name: str) -> str:
    """Return the rule/audit reason used for ``name``."""
    return classify_kernel_with_reason(name)[1]


def should_exclude_kernel(name: str) -> bool:
    """Whether ``name`` is a non-compute trace marker."""
    return classify_kernel(name) is None


# Compatibility list for callers that only need a human-readable exclusion
# hint.  Matching itself uses the explicit regex rules above.
EXCLUDE_PATTERNS = ["WAIT", "profiler", "ProfilerStep", "torch.autograd", "autograd"]
