# 2026-10-12 Teco 分类审阅范围

此次结合官方 tecorigin-kb、两份本地 tecovllm 源码、34 节点实际安装版本和已有 trace，没有启动新 workload。逐名报告和完整证据位于此次机器的 `D:/learn/work/outputs/llm-prof-rules-20261012/`；可复用规则是 `rules/kernel-classification-rules.json`。

## 实际观察

SSH 配置解析节点为 `sdaa-192.167.252.34`，宿主 `tczc-tc34`，SDAA driver/runtime 3.3.0；用户挂载 `/data/application/changhl -> /workspace`。检查了 vllm330、vllm331、vllmmain、qwen35-clean-1010 用户容器。各容器 torch_sdaa/tecolmk/框架版本不同，历史采集容器身份未保存，不能把 Oct9 trace 归给 Oct10 创建的 clean 容器。

近期 trace 位于 `/workspace/work/release330/prof_2card_20261009_0935/{bs1_4images_i10o10,bs4_4images_i10o10}/vllm_profile/` 的 rank0 文件。各有 104/109 个 kernel 名称、16066/22614 次 kernel，25/35 次 sdaaGraphLaunch。合计 113 个 kernel 名称、122 个设备事件身份（包含传输/同步标签）。这是特定 Qwen workload 覆盖，不是全部 T100 算子。

vllm_profile_readable 仅修复同次 capture 的 Python 栈 UTF-8，设备名字、次数、耗时一致；它不是 graph-off。raw 有 13/9 个 Python 名字替换字符，设备名字无替换字符。审阅不把 raw/readable 两份计数相加。

补充历史 T100 1024/4096 prefill/decode 表后，共审阅 134 个不同设备名字。闭源 TecoBLAS/TecoDNN/TecoLMK 的内部实现并未全部开放：中置信度项明确基于库/算子名字和 API 依据，不把全部规则命中宣称为内部实现全验证。

## 关键修正与未决项

| 家族 | 六类桶 / 语义 | 依据 |
| --- | --- | --- |
| ffn_layer_general_fused_for_small | GEMM / fused_ffn | csrc/lmk/ffn.cc:125 双投影+激活；KB 注册模型:749 |
| ffn_layer_general_activation | 其他 / activation | FFN 激活子阶段，不能用整层 FFN 的 GEMM 标签 |
| prepare_for_group_gemm | 其他 / gemm_metadata_prepare | csrc/scpp/prepare_for_group_gemm.scpp:7 指针和 offset |
| DeltaRule | 其他 / linear_attention_state_update | recurrent/chunk API 与 q/k/v、state 输入输出 |
| moe_reduce/local_reduce_fused | 其他 / moe_weighted_reduce | csrc/scpp/moe_reduce.scpp:19-56,474-501,552,562，本地加权累加 |
| WAIT/SET | 排除 | 实际 exporter 标为 gpu_memset；精确名字语义优先 |
| TCCL wait flag | 通信 / sync | collective stream 等待，不是精确 WAIT 标记 |

最初的 BLAS gemm_*allReduce 样例只关联到 sdaaGraphLaunch（1889 事件/23 名字），不足以确定语义。后续单算子深度复核已经确认 NN/NT fp16 变体：单设备、无通信组、无 graph 的 torch.mm/F.linear 各在四个小 M/N 形状下只发射这个计算核，CPU 数值校验通过。因此规则2026-10-12.3改归 GEMM，小矩阵局部归约算法；此前暂定通信的结论已被实验证据替代。

历史 eager trace 的 NT 变体由 tecoblasHgemm -> mm.out -> aten::linear 调用；真实两物理卡 TCCL 对照发射 TCCL 通信核，没有测试到 BLAS GEMM allReduce。邻接顺序不能证明该核是前一 GEMM 的后处理。详见 [深度复核](t100-allreduce-deep-review-20261012.md)。

## 预期 capture 的操作

当前 clean 容器检查到 94 个 API 调用位置，是预期来源，不是已捕获的 kernel 名字。

- ffnv2、weight_only_linear、unified_linear：gemm/融合线性。group_gemm_v2 的专家 grouped-batched 核自2026-10-28单列 group gemm，见 [MoE复核](moe-group-gemm.md)；API 的 bias、activation、布局 helper 单独分类。
- moe_routing、moe_reduce：本地路由和专家结果加权汇总；DP token 数量元数据不表示通信，交换由 TCCL/TecoEP 路径承担。
- DeltaRule、causal_conv1d：线性 attention 状态更新、卷积状态更新；保留非 elementwise 语义。
- weight_permute、独立 GGML 解量化：布局/解量化，不是量化 GEMM。weight_permute_model_quant 选择 CPU runtime，当前 GGUF fallback 也可在 CPU 执行，不据此预测 decode 设备 kernel。
- qkv_gemm_fp8、project_gemm_fp8：量化 projection；部分 csrc/quant.cc 的 static/dynamic FP8 接口报不支持，注册不等于设备 kernel 存在。

新名字继续报告 unknown，核对实际实现/API/可靠来源后扩展，不能只从预期 API 推断它的每个子 kernel。

本地参考 commits 为 989a50ef7c5fc4b67816bde3f1865533dd533cf2 和 00d47293e632f1a6a37aa47c9fd36fdbff3f675f。节点旧 version.json 与真实库软链接不一致，分别记录包版本、库版本、代码 commit 和 capture 信息；不把过时字段当唯一版本证据。
