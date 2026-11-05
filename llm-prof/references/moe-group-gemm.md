# MoE 专家 group GEMM

仅将已确认执行专家分组矩阵乘的 kernel 归 `group gemm`；普通投影、router 的打分线性层、共享 FFN 的普通 dense GEMM 继续归 `gemm`。专家路由、排序、padding、指针/offset 准备、量化布局和本地专家结果求和不是专家矩阵乘。`prepare_for_group_gemm` 和普通 batched attention 矩阵乘不能因包含 gemm/batched 被迁入新类。

分类先按独立 JSON 的核名规则执行；native trace 还可用同一文件的专家 CPU API 来源规则核实通用 GEMM。来源依赖同 trace 的 runtime flow/correlation 与 CPU op descendant/同原生线程包含关系，不按时间最近匹配，也不使用主机耗时替代设备 dur。确认专家核、专家来源或 MoE helper 时显示七类；dense 保持原六类，调用方无需额外传模型名。

## 通用 GEMM 符号的专家来源

T100 prefill 的 `group_gemm_v2` 可能发射 `slave_gemm_m1n32k32_fp16` 等通用名称。`moe_context.py` 逐次检查这些 GEMM 的同 trace 来源。全部调用均确认属于专家 API 时，按名字聚合的整行归 group gemm。来源算法版本为 `moe-source-attribution-v2`，与核名规则版本分别记录。

flow 与 correlation 发生冲突时，核查两者候选的并集。每个候选必须属于同一次专家 CPU scope、同一原生线程和同一来源规则，且 launch 时间有效、早于设备事件。满足这些条件时，类别可归 group gemm，精确 launch 继续保留歧义；缺少候选来源、候选跨 scope 或类别不同均保持未决。不修改 DeviceStepIndex 的原始关联和严格选窗结果。

同名调用的来源混用或仅部分已确认时，原始 SQL 行保留原值和候选歧义。`classification.allocations` 记录分项调用数、整数 duration_ns 和逐次 event_ids；`category_parts` 是供汇总与导出的实测分项。已确认专家部分归 group gemm，残余调用保留 gemm 的名字分类并标记专家角色 unknown，避免将缺少专家证据解释为普通来源已确认。每次设备事件仅计一次，分项次数和耗时必须与原始行守恒。

有分项时，“Kernel明细”上方的原SQL六列及名字汇总保留，下方同样式的“分类分项”成为表1的唯一统计来源。JSON 保存逐次 event_ids；CSV 附加 category_parts。普通报告沿用原三表和样式。仅有聚合 XLSX 时按已有名字规则分类，不补造逐次来源。旧 schema1 覆盖文件继续服从自己的规则。

类别和精确 launch 的置信度分别记为 category_confidence、launch_confidence。关联冲突记录在 context_evidence.launch_conflicts，含设备事件 ID、候选 launch 及其 correlation、专家 scope ID 和设备 dur。“选窗依据”同时显示这些冲突，类别已确定的事件仍可保留 launch 歧义。

已复核的 T100 4096 多模态例子中，两个设备事件的 flow/correlation 分别指向两个相邻 launch，各候选都落在同一个 group_gemm_v2 scope。两个事件耗时为11.015和21.128µs，可确定专家类别。该例的事件 ID 只用于核验，不写入分类规则。

## 已验证家族

| 平台/实现 | 名称 | 分类及依据 |
|---|---|---|
| vLLM Triton 通用实现 | 精确 `fused_moe_kernel`、`fused_moe_kernel_gptq_awq` | group gemm；按 expert_ids 取专家 B 权重并用 tl.dot 做 token A × B。按运算语义优先于 Triton 后端分类。common 组可用于各平台的同名实现，不表示已采集所有后端变体。 |
| T100 TecoLMK | `tecolmk_slave_gemm_grouped_batched...`，已观察 v2_weight_half 的 `<3,64>`、`<4,64>` | group gemm；expert_stats 驱动每专家 group 的 w1/w2 矩阵乘。优先于旧通用 GEMM 规则。 |
| NVIDIA MoE helper | `moe_align_block_size_kernel`、`count_and_sort_expert_tokens_kernel`、`moe_sum_vec_kernel` | 其他elementwise；分别为对齐、排序和本地求和。安装 Python API 已核对，CUDA helper 源码未随 wheel 提供，保留 medium 与证据限制。 |

不为没有来源证据的 CK/Tensile/其他厂商变体增加宽泛规则。普通 batched_gemm、任意 cutlass:: 或 BLAS namespace 不是专家分组语义证明；新增家族需检查实现或可信 API/实验。

## 本次核对来源

- H100 安装 vLLM0.29.0：`vllm/model_executor/layers/fused_moe/fused_moe.py:299,539-563`，量化实现`:65,276`。SHA256 `7072eb06237be9d33dcb0ef7101410f886a6363c98cbee70a014c68b70f639cb`。`:1854-1857` 在专家计算后调用 `ops.moe_sum`。
- 同版本 `moe_align_block_size.py:11-45,90` 描述 token/expert 分组、排序、按 block 对齐以供后续矩阵乘。SHA256 `c3f7fc2087836f0160a32ab99ceb1d8f6e87c793679da34dd672e225cb7fa31b`。
- T100 `tecovllm/csrc/lmk/group_gemm_v2.cc:4-28,111-127`：expert_stats/expert count 与每组 N/K/权重传入 `tecolmkGemmGroupedBatchedExV2`。SHA256 `0d4c9b4ba09776bad698ee42d2c670cb9d56af9aba7f1e4f0717b72876355247`。
- T100 `tecovllm/vllm_sdaa/layers/fused_moe/experts/sdaa_moe.py:26-53,275-285,333-343`：按 expert_stats 执行 w1/w2 group_gemm_v2。SHA256 `5988cb91762dfa2ccff72d54047f9a1e843413bd019deb27c4d2819fd1d95f85`。

以上为2026-10-28实际安装/源码快照，跨版本扩展前重新核对。完整模板参数不硬编码进规则。

## 统计与兼容

七类顺序为 gemm、group gemm、通信、FlashAttention、Triton、其他elementwise、memcpy/memset；没有 MoE 证据时省略新行，原 dense 顺序及13行时间块保持不变。MoE 每 rank 为14行。分母包括全部六/七类，WAIT/SET 单列；原始 SQL 前六列、设备事件数、选窗、去重覆盖、空泡均不随分类拆分而变化。

schema2 声明七类；schema1 的旧六类覆盖文件继续加载并服从自身规则。旧覆盖文件若将 fused_moe_kernel 明确归 gemm，不会被代码暗中覆盖；需要迁移到新版默认规则或显式更新覆盖文件。

验证入口：`test_group_gemm.py`、`test_moe_context.py`、`test_report_time_accounting.py` 与已有回归。覆盖 dense 六类不变、专家乘法与 helpers 分离、同名混用/跨线程/无关联不强迁移、七类比例守恒、多 rank 行偏移、旧 XLSX 既有分类/格式保留及现有分析入口。JSON旧分析器与跨运行 graph 映射仍按名字归类，逐次专家来源需使用 native window/step。
