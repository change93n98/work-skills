#!/usr/bin/env python3
"""Focused regression tests for DCU, NVIDIA and Taichu T100 classification.

The negative/ambiguous cases are intentional: they protect against the broad
substring mistakes found in real T100/H100 tables.
"""

from kernel_categories import classification_reason, classify_kernel, classify_kernel_with_reason


CASES = {
    # Taichu T100: GEMM/BLAS
    "void slave_gemm_m8n256k128_fp16<1536u, false, false>(GemmM8N256K128Args)": "gemm",
    "tecoblas::ual::slave::teco_slave_gemm_NN_Afp16_Bfp16_Cfp16_N256_NOPAD(GemmWrapArgs)": "gemm",
    "void slave_mm_dequantize_v3<1536u>(void const*, void const*, void*, int, int, int)": "gemm",
    # T100 collective
    "void tccl_move_data_list<8192ul>(tcclMove)": "通信 (comm)",
    "tecoblas::ual::slave::teco_slave_gemm_NT_Afp16_Bfp16_Cfp16_allReduce(GemmWrapArgs)": "通信 (comm)",
    # T100 attention
    "tecocustom::ual::kernel::teco_slave_flash_attention_forward_8_4_64_false_general_hd256(Args)": "FlashAttention (fa)",
    "void tecolmk_slave_fused_block_attention_decode_v2<256u, 32u>(BlockAttentionLayerArgs)": "FlashAttention (fa)",
    # T100 non-attention fused ops
    "void tecolmk_slave_fused_norm<2, 1>(FusedNormArgs)": "其他elementwise",
    "void tecolmk_slave_compute_v_new_last_state<1>(ChunkGatedDeltaRuleArgs)": "其他elementwise",
    "tecodnn::ual::slave::teco_slave_broadcast_add(tecodnn::ual::ops::BroadcastArgs)": "其他elementwise",
    "tecodnn::ual::slave::teco_slave_no_broadcast_mul(tecodnn::ual::ops::NoBroadcastArgs)": "其他elementwise",
    "tecolmk_slave_prefill_cache(BlockAttentionLayerArgs)": "其他elementwise",
    "_Z42tecolmk_slave_fused_qk_gemma_norm_mrope_kernel_impl(Args)": "其他elementwise",
    # T100 transfer
    "tecodnn::ual::slave::teco_slave_copy_stride_dma_2D<unsigned short>(CopyStrideArgs)": "memcpy/memset",
    "sdaart::sdaaMemcpyAsyncH2D": "memcpy/memset",
    "WAIT": None,
    # NVIDIA
    "nvjet_sm90_tst_192x8_64x8_4x1_v_bz_TNT": "gemm",
    "void cublasLt::splitKreduce_kernel<32, 16>(Params)": "gemm",
    "void cutlass::device_kernel<flash::FlashAttnFwdSm90<...>>(Params)": "FlashAttention (fa)",
    "void cutlass::device_kernel<flat::kernel::FlatKernelTmaWarpSpecializedDeltaRule<...>>(Params)": "其他elementwise",
    "void ncclKernel_AllReduce_RING_LL()": "通信 (comm)",
    "triton_poi_fused_add_mul_0": "Triton",
    # ROCm / DCU
    "Cijk_Alik_Bljk_F8BS_MT16x16x64": "gemm",
    "void CKFmhaFwdKernel<...>()": "FlashAttention (fa)",
    "rcclAllReduceRingKernel": "通信 (comm)",
    "hipMemcpyAsync": "memcpy/memset",
}


def main():
    failures = []
    for name, expected in CASES.items():
        actual, reason = classify_kernel_with_reason(name)
        if actual != expected:
            failures.append((name, expected, actual, reason))
    if failures:
        for name, expected, actual, reason in failures:
            print(f"FAIL expected={expected!r} actual={actual!r} rule={reason!r}: {name}")
        raise SystemExit(1)

    # Guard the public wrapper and the two most important false-positive fixes.
    assert classify_kernel("WAIT") is None
    assert classify_kernel("gemma_norm_kernel") == "其他elementwise"
    assert classification_reason("tecodnn::ual::slave::teco_slave_broadcast_add(Args)") == "elementwise:CUDA/ROCm/T100"
    print(f"PASS: {len(CASES)} DCU/NVIDIA/T100 classification cases with reasons")


if __name__ == "__main__":
    main()
