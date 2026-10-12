# 太初 T100 kernel 语义知识库

规则产物位于 `rules/kernel-classification-rules.json` 的 teco 分组。本参考从知识库、`tecovllm` 注册/API/实现和实际 trace 提炼稳定语义，不按一次完整模板实例硬编码。闭源库的中置信度命名依据与源码已验证家族分开；未知项或未决项通过 audit 明示。此次范围见 `teco-kernel-review-20261012.md`。

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
| 明确 `tccl_*`、`nccl*`、`rccl*` collective、`all_gather`、`reduce_scatter` | `通信 (comm)` | 跨设备通信；BLAS allReduce 例外见下行 |
| `tecoblas::*gemm_{NN,NT}_Afp16_Bfp16_Cfp16_allReduce(GemmWrapArgs)` | `gemm` / gemm_small_mn_local_reduce | 单设备 torch.mm/F.linear 已复现同名核并通过 CPU 数值校验，无通信组、无 graph；属于小 M/N GEMM 算法 |
| `teco_slave_flash_attention*`、`fused_block_attention*`、`block_attention*` | `FlashAttention (fa)` | TecoLMK attention API |
| `tecolmk_slave_ffn_layer_general_fused_for_small*` | `gemm` / fused_ffn | FFN API 接收双投影权重与激活，知识库确认 linear+activation 融合 |
| `tecolmk_slave_ffn_layer_general_activation*` | `其他elementwise` / activation | FFN 的激活 helper，不能按整个 FFN 分类 |
| `tecolmk_slave_fused_norm*`、`causal_conv1d*`、`DeltaRule`、`gdn_gating`、`fused_qk_gemma_norm_mrope` | `其他elementwise`，另记语义细分 | norm/激活/卷积/线性 attention 状态更新/rope，并非全部逐元素 |
| `prepare_for_group_gemm`、`weight_permute`、`moe_routing`、`moe_reduce` | `其他elementwise` / 元数据、布局、本地路由与加权归约 | 不因为 GEMM/reduce 字样归矩阵乘/通信 |
| `tecodnn::*broadcast_add`、`no_broadcast_*`、`masked_fill_*` | `其他elementwise` | 单卡 DNN 广播/逐元素操作，不是通信 |
| `tecolmk_slave_prefill_cache*`、`reshape_and_cache_flash*`、`block_kv_gather*` | `其他elementwise` | KV cache/layout；不是 attention |
| `sdaart::sdaaMemcpy*`、`copy_stride_dma*`、`set_tensor`、`MEMCPY_P2P` | `memcpy/memset` | DMA/显存传输 |
| 精确 `WAIT` / `SET` | 排除 | runtime 标记，即使 exporter 标为 gpu_memset 也不计入 busy |
| `tcclStreamWaitFlagKernel` | `通信 (comm)` / sync | 通信同步，与精确 WAIT 区分 |

## 不能使用的宽泛规则

- 不能用普通字符串 `"gemm" in name.lower()`：会把 `gemma` 误判为 GEMM。使用单词/算子边界或显式 `GemmWrapArgs`。
- 不能把所有 `broadcast` 都当通信：T100 `tecodnn` 的 broadcast_add/no_broadcast/masked_fill 是本地逐元素 kernel。
- 不能把所有 `cutlass::` 都当 GEMM：CUTLASS FlashAttention 要先匹配 attention，CUTLASS DeltaRule 要先匹配 DeltaRule。
- 不能把 `prefill_cache`、`reshape_and_cache` 当 FlashAttention：它们是 cache/layout。
- 不能把任意包含 `wait` 的名字排除；只有精确 `WAIT` 或明确 profiler marker 才排除。
- 不能把所有 FFN helper 归 elementwise：双投影 fused_for_small 是 GEMM，activation helper 单独分类。
- 不能只看 allReduce 后缀认定跨卡通信；已验证的 TecoBLAS NN/NT fp16 变体归 GEMM，其他未验证变体仍显式 unknown。精确算法内部的工作划分未解码，不把它表述为已证明的独立后处理 helper。

## 审计原则

分类器返回 `classification_reason`。`fallback:unknown` 不代表一定错误，但必须在审计报告中列出，按耗时从高到低人工确认；确认后只添加稳定的语义模式，不添加一次实例化产生的完整模板名。
