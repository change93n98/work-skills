# 独立 kernel 分类规则产物

唯一规则产物是 `rules/kernel-classification-rules.json`。Python 加载器只负责读取、校验和匹配，不维护另一份硬编码正则表。JSON 可单独复制、版本管理或由其他分类程序读取。

## 选择文件和平台

四个入口 `prof_analyze.py`、`prof_analyze_perfetto.py`、`prof_graph_analyze.py`、`audit_kernel_categories.py` 共用参数：

```bash
python3 scripts/prof_analyze.py \
  --trace-file trace.json.gz --output-dir analysis \
  --kernel-rules rules/kernel-classification-rules.json --platform teco
```

- nv：通用 + NVIDIA。
- dcu：通用 + DCU/ROCm。
- teco：通用 + 太初/SDAA。
- auto（默认）：全部分组，兼容混合名字；不探测设备厂商。

省略文件参数时按脚本位置读取 skill 的 JSON，与当前工作目录无关。platform 是规则分组开关，不是厂商名字过滤器；通用词也可能匹配其他平台。已知设备时明确选平台。

其他代码复用加载器（先将 skill 的 scripts 目录加入 Python 导入路径）：

```python
from kernel_categories import KernelClassifier
classifier = KernelClassifier("/path/kernel-classification-rules.json", platform="teco")
result = classifier.classify_detail(kernel_name)
```

修改文件后新建 classifier 或调用 configure_classifier；不会在分析途中静默重载。所有报告记录文件路径、SHA256、version、platform。

## 结构与解释

顶层含 schema_version、version、categories、fallback、platforms，以及仅供展示的 compatibility_keywords / exclude_hints。新版 schema2 的类别契约为 gemm、group gemm、通信 (comm)、FlashAttention (fa)、Triton、其他elementwise、memcpy/memset；平台分组仍须含 common、nv、dcu、teco。加载器兼容 schema1 的原六类覆盖文件，不静默改写用户的旧规则或分类语义。

| 字段 | 含义 |
| --- | --- |
| id / reason | 唯一规则 ID / 匹配原因 |
| priority | 数字越小越先匹配；同值按文件的分组与规则顺序 |
| patterns | 大小写不敏感的 Python 正则数组，任一命中 |
| category | schema2 七类中的一类；schema1 保留原六类。null 表示运行时/profiler 排除 |
| semantic_type | fused_ffn、kv_cache_layout、linear_attention_state_update 等语义细分 |
| evidence | 审阅过的源码/API/知识库或快照 |
| confidence | high/medium/low/unknown，证据强度，不是概率 |
| ambiguity_reasons | 未决语义和命名歧义 |
| category_candidates | 可选的其他候选桶 |
| notes | 限制、版本和预期但未观察到的家族 |
| match_on | 默认 kernel_name；cpu_op 表示 native 专家来源规则，不参与普通核名匹配 |
| source_categories | cpu_op 规则当前只能声明 [gemm]，并将已确认的调用归 group gemm；其他辅助核不迁移 |

默认分类依据核名；native window/step 还能通过明确的专家 CPU API 及同 trace 发射关联确认通用 GEMM 的角色，见 MoE 参考。静态 evidence 不是当前 invocation 的调用栈证明，逐次确认另记 context_evidence。错误 JSON、重复 key/ID、非法类别和正则明确失败，不回退旧规则。

dense 报告保留原六类布局；观察到已确认的 MoE 专家分组矩阵乘时新增 `group gemm` 行，使用七类合计。自动判断来自分类结果，不凭模型名把普通 GEMM 全部迁移。`active_categories` 提供统一顺序，所有统计入口共用；比例分母包含新增类且不能重复计入 gemm。“其他elementwise”仍是包含归约、卷积、采样、cache/layout、DeltaRule 的兼容桶。普通 GEMV、融合 dense/shared FFN GEMM 继续归 gemm。具体模式、源码及未验证家族见 [MoE group GEMM](moe-group-gemm.md)。

fallback:unknown 保留其他桶、confidence=unknown。词法全命中不等于语义全验证。源码明确的厂商例外、通信/内存/attention、明确 GEMM 家族应先于泛 activation/layout；以 JSON priority 为准。

## 重要例外

- Teco ffn_layer_general_fused_for_small 是双投影 GEMM+激活；ffn_layer_general_activation 是激活 helper。
- vLLM fused_moe_kernel 是按专家权重执行的矩阵乘；Triton 是实现后端，该核按运算语义归 group gemm。TecoLMK 专家 grouped-batched 矩阵乘同样单列。普通 batched GEMM、attention QK/PV、通用 CUTLASS/BLAS 命名不能仅凭 batch/group 字样迁移。
- prepare_for_group_gemm 是指针/offset 准备，weight_permute 是布局；moe_reduce 是本地专家结果加权汇总。
- TecoBLAS NN/NT fp16 gemm_*allReduce 已由单设备、无通信组、无 graph 的 torch.mm/F.linear 实测确认属于小 M/N GEMM 局部归约算法，归 GEMM。单次矩阵乘可只发射这个核，不能把它简单称为前一个 GEMM 的后处理。仅放行已验证变体，其他变体显式 unknown。
- 精确 WAIT/SET 排除，哪怕 exporter 标为 gpu_memset；tcclStreamWaitFlagKernel 保留通信同步。
- gemma 不是 GEMM；KV cache helper 不是 attention 主计算。
- CK/CUTLASS 明确 GEMM 类型的 ReLU/GELU/LayerNorm 是 epilogue；hipblasLtMatrixTransform 是布局辅助。
- 库名不证明 GEMM；不把任意 cutlass:: 或 BLAS namespace 当矩阵乘。

Teco 依据见 [知识参考](tecovllm-t100-kernel-knowledge.md) 和 [此次审阅](teco-kernel-review-20261012.md)。
新增实验与逐核证据等级见 [T100 深度复核](t100-allreduce-deep-review-20261012.md)。

## 验证

先检查 trace、API 和实现，再加入稳定模式，不硬编码一次模板实例，不为消除 fallback 使用泛厂商前缀。

```bash
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/test_kernel_categories.py
python3 scripts/audit_kernel_categories.py trace.json.gz \
  --platform teco --kernel-rules rules/kernel-classification-rules.json --output audit.json
```

audit 也支持 XLSX/TSV/CSV。按耗时检查 low、歧义和 unknown；fail-on-fallback 只查未命中，不证明语义。修改后同时跑旧平台和新例外用例，核对设备耗时总和。
