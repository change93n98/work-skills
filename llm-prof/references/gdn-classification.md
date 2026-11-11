# GDN 分类和跨卡对齐

`GDN` 是独立主类别，放在 FlashAttention 后。Prefill、Decode 和 XLSX 重新分类的汇总页均把已确认的算子明细放在 GDN 主行下方并默认折叠。点击行号左侧「+」或「−」切换。展开后可见调用次数、核名种类、耗时和 GDN 内占比。主类合计只计一次 GDN。

| 算子汇总行 | 归因依据 | 计入的设备调用 |
| --- | --- | --- |
| `causal_conv1d` | GDN 内的 `causal_conv1d_fn` | 卷积核和该调用内部关联到的布局或搬运 |
| `causal_conv1d_update` | GDN 内的 `causal_conv1d_update` | Decode 卷积状态更新及该调用内部的设备事件 |
| `rearrange_mixed_qkv` | GDN 内同名 Python scope | 拆分后连续化、拼接等布局转换产生的核 |
| `fused_gdn_gating` | GDN 门控 Python/CPU scope 或已验证的专用核名 | 门控主核和该调用内部关联到的转换等辅助核 |
| Q/K L2 Norm | GDN 内的 `l2norm` scope 或明确的 CPU Norm 模式 | T100 的 chunk 封装中对 Q、K 各执行一次的归一化 |
| QKV 重排、门控与 Q/K 归一化融合 | H100 GDN 核心内的 `_fused_post_conv_kernel` | 一次调用产出卷积后整理的 Q/K/V、归一化后的 Q/K 和门控 g/β |
| `chunk_gated_delta_rule_fwd` | T100 同名 CPU 算子或 H100 FlashInfer 分块实现 | T100 的 `compute_decay_mask_u_w`、`compute_v_new_last_state`、`compute_o`，或 H100 的 T/MN Precompute、Prefill、FixupSimt。可归因到该调用内部的辅助核也计入 |
| `fused_recurrent_gated_delta_rule_fwd` | T100 专用 `FusedRecurrentGatedDeltaRuleArgs` 核名或同名 GDN 源码调用 | Decode 逐 token 更新 recurrent state 并产出结果。已验证的 T100 路径在核内做 Q/K L2 Norm |
| 门控与递推融合 | H100 `fused_sigmoid_gating_delta_rule_update_kernel` | 门控与递推一起发射。Qwen 的已验证调用启用核内 Q/K L2 Norm |
| Packed QKV、门控与递推融合 | vLLM `fused_recurrent_gated_delta_rule_packed_decode_kernel` | 从 packed QKV 直接读取各 head，执行门控与递推。Q/K L2 Norm 由调用配置决定 |

Q/K 的两次 L2 Norm 在 T100 的 chunk Python 封装内执行，先于 `_C_sdaa::chunk_gated_delta_rule_fwd`。统计时两次 L2 合为一行，随后 CPU 算子发射的核心核合为另一行。Kernel 明细继续显示各核和预计算、状态更新、输出等语义。输入与输出投影的 GEMM 继续按 GEMM 规则处理。

对原生 trace，`scripts/gdn_context.py` 使用 GDN CPU scope、同线程包含关系和 flow/correlation 逐次识别共享核。T100 的卷积前向和状态更新可以共用 `teco_slave_causal_conv1d_perf`，须结合调用 scope 区分。通用 Norm 同时检查 GDN scope 和 CPU Norm 模式，输出门控 Norm 要有已验证的输出 scope。融合核时长整笔计入。

T100 旧交付分支的核心 CPU 算子可记录为 `vllm::gdn_attention_core`，QKV 重排来自 `layers/mamba/gdn_linear_attn.py`。主分支可记录为 `vllm::qwen_gdn_attention_core`，QKV 重排来自 `mamba/gdn/qwen_gdn_linear_attn.py`。两种路径均通过同一套调用关联归因，通用核仍需落在已确认的 GDN scope 内。

Decode 图回放中，专用核名仍可确认语义，例如 T100 递推、独立门控与 `gdn_prepare_cudagraph_impl`，以及 H100 的融合递推。`cudaGraphLaunch`、`sdaaGraphLaunch` 等只表明 replay 所属。若窗口内已有 GDN 递推证据，关联到 replay 的通用卷积、T100 通用 Norm 或已知 AOT 输出符号沿用原类别，在明细标 GDN 候选，在 JSON `gdn_comparison.graph_candidates` 记录候选调用次数、耗时和依据。需要补充归因时使用 [graph 双 trace 映射](graph-source-mapping.md)，确认源调用证据与映射歧义后再汇总。仅有 XLSX 时只用专用核名规则。

## T100 与 H100 对比

对比表读 `gdn_comparison.rows` 的 `group` 和 `total_duration_us`。每次设备调用只进入一个对齐条目。`semantic_types` 可回查单卡明细。总耗时对比使用 `summary` 的 GDN 主类行。

| 阶段 | 对齐条目 | 对齐方式 |
| --- | --- | --- |
| Prefill | 卷积 | 两侧 `causal_conv1d` |
| Prefill | 卷积后准备 | T100 的 QKV 重排、门控、Q/K L2 Norm 合计，对 H100 的 `_fused_post_conv_kernel` |
| Prefill | Chunk 主计算 | TecoLMK 与 FlashInfer 的完整分块调用，各自内部辅助核按已确认归因计入 |
| Decode | 卷积状态更新 | 两侧已确认的 `causal_conv1d_update` 设备调用 |
| Decode | 卷积后准备与递推 | T100 已归因的 QKV 整理、独立门控、可独立量到的 Q/K L2 和递推合计。H100 取对应准备和融合递推。融合部分不拆耗时 |

输出门控及布局、元数据和实现辅助单列。只在一侧确认的条目，另一侧填「未单独归因」，性能比留空。已知覆盖不一致的 GDN 整体耗时标为「已确认子集」，性能比留空。工作量核对同模型、相同 Prefill token 数或 Decode 请求及 token 数、并行配置和可比的 graph 模式，匹配后才按 `H100 耗时 / T100 耗时` 填 T100 性能百分比。

`scope=mixed-or-stage-mismatch` 表示窗口包含混合 annotation、同时观测到两阶段的核，或分类证据与窗口标签冲突。保留窗口统计，避免用它生成纯阶段性能比。要选纯 Decode Step 2，可用 `step --stage decode --step 2 --annotation-regex '^execute_context_0\(0\)_generation_[1-9]'`。仅有聚合 XLSX 或未标阶段的选区输出 `scope=unknown`，需要另核对工作量与阶段。

同名调用跨类别或子项时，Kernel 明细保留按名字聚合的 SQL 六列，分类分项记录实际调用次数和耗时。主类核名种类在类别内去重。只有 XLSX 或仅按名字的入口应用专用核名规则。新版 schema3 声明 GDN 类别，旧 schema1、schema2 分类文件仍可加载。

证据来自 2026-10-28 Qwen3.6-35B 的 T100/H100 rank0 trace、对应的 TecoLMK 调用路径和 vLLM 的 [Prefill 卷积后融合](https://github.com/vllm-project/vllm/blob/main/vllm/third_party/flash_linear_attention/ops/fused_gdn_prefill_post_conv.py) 与 [Decode packed 递推](https://github.com/vllm-project/vllm/blob/main/vllm/third_party/flash_linear_attention/ops/fused_recurrent.py) 源码。专用核名和语义 ID 在 `rules/kernel-classification-rules.json`。明细行名和对齐条目映射在 `assets/report-layout.json`。
