# 太初 T100 kernel 语义知识库

本参考不是按一次 trace 的完整模板实例名硬编码，而是从本地 `tecovllm` 的算子注册、C++ 实现和 TCCL 调用关系抽取稳定语义。使用时优先匹配算子/库/命名空间，最后才回退到 `其他elementwise`，并通过 audit 报告发现未知项。

## 证据来源

以下路径来自本地 `tecovllm` 仓库：

- `csrc/pybind.cc`：注册 `block_attention`、`flash_attention`、`group_gemm`/`group_gemm_v2`、`fused_norm`、`fused_gdn_gating`、`fused_recurrent_gated_delta_rule_fwd`、`causal_conv1d_fn/update`、`reshape_and_cache_flash` 等算子。
- `csrc/lmk/block_attention.cc`：调用 TecoLMK Transformer Block Attention；kernel 名带 `teco_slave_*block_attention*` 属于 attention。
- `csrc/lmk/flash_attention.cc`：实现 T100 FlashAttention；kernel 名带 `teco_slave_flash_attention*` 属于 attention。
- `csrc/cache_ops.cc` 和 `csrc/scpp/cache_kernels.scpp`：`reshape_and_cache_flash`/`prefill_cache` 是 KV cache/layout 操作，不是 FlashAttention；在六类兼容输出中归入 `其他elementwise`。
- `csrc/fused_qk_gemma_norm_mrope.cc` 和 `csrc/scpp/fused_qk_gemma_norm_mrope_kernel.scpp`：`fused_qk_gemma_norm_mrope` 是 norm/rope 融合算子；`gemma` 不能按 `gemm` 子串匹配。
- `csrc/lmk/fused_norm.cc`、`fused_gdn_gating.cc`、`fused_recurrent_gated_delta_rule_fwd.cc`、`causal_conv1d_fn.cc`：对应 T100 norm、GDN/DeltaRule、causal conv 融合算子，归入 `其他elementwise`。
- `csrc/lmk/group_gemm.cc`、`group_gemm_v2.cc`、`group_gemm_ffn` 注册：`teco_slave_gemm*`、`GemmWrapArgs`、`slave_gemm*` 是 GEMM；`slave_mm_dequantize*` 是 GEMM/量化矩阵乘路径。
- `vllm_sdaa/distributed/device_communicators/sdaa_communicator.py`、`pytccl.py`、`pytccl_wrapper.py`：T100 跨卡通信通过 TCCL 的 all-reduce/all-gather/reduce-scatter 等原语；`tccl_*` 和明确 collective 名属于通信。

## T100 规则

| trace 名称/模式 | 六类报告分类 | 依据 |
|---|---|---|
| `teco_slave_gemm*`、`slave_gemm*`、`slave_mm_*`、`GemmWrapArgs` | `gemm` | TecoBLAS/group GEMM/量化矩阵乘 |
| `tccl_*`、`nccl*`、`rccl*`、`all_reduce`、`all_gather`、`reduce_scatter`、`two_shot`/`one_shot` | `通信 (comm)` | 跨设备 collective |
| `teco_slave_flash_attention*`、`fused_block_attention*`、`block_attention*` | `FlashAttention (fa)` | TecoLMK attention API |
| `tecolmk_slave_fused_norm*`、`ffn_layer_general*`、`causal_conv1d*`、`DeltaRule`、`gdn_gating`、`fused_qk_gemma_norm_mrope` | `其他elementwise` | 融合 norm/激活/状态更新/rope |
| `tecodnn::*broadcast_add`、`no_broadcast_*`、`masked_fill_*` | `其他elementwise` | 单卡 DNN 广播/逐元素操作，不是通信 |
| `tecolmk_slave_prefill_cache*`、`reshape_and_cache_flash*`、`block_kv_gather*` | `其他elementwise` | KV cache/layout；不是 attention |
| `sdaart::sdaaMemcpy*`、`copy_stride_dma*`、`set_tensor`、`MEMCPY_P2P` | `memcpy/memset` | DMA/显存传输 |
| 精确 `WAIT` | 排除 | runtime wait，计入 phase bubble 而不是 GPU kernel busy |

## 不能使用的宽泛规则

- 不能用普通字符串 `"gemm" in name.lower()`：会把 `gemma` 误判为 GEMM。使用单词/算子边界或显式 `GemmWrapArgs`。
- 不能把所有 `broadcast` 都当通信：T100 `tecodnn` 的 broadcast_add/no_broadcast/masked_fill 是本地逐元素 kernel。
- 不能把所有 `cutlass::` 都当 GEMM：CUTLASS FlashAttention 要先匹配 attention，CUTLASS DeltaRule 要先匹配 DeltaRule。
- 不能把 `prefill_cache`、`reshape_and_cache` 当 FlashAttention：它们是 cache/layout。
- 不能把任意包含 `wait` 的名字排除；只有精确 `WAIT` 或明确 profiler marker 才排除。

## 审计原则

分类器返回 `classification_reason`。`fallback:unknown` 不代表一定错误，但必须在审计报告中列出，按耗时从高到低人工确认；确认后只添加稳定的语义模式，不添加一次实例化产生的完整模板名。
