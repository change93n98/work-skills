# T100 allReduce 与逐 kernel 深度复核

## 结论与直接证据

`tecoblas::ual::slave::teco_slave_gemm_{NN,NT}_Afp16_Bfp16_Cfp16_allReduce(GemmWrapArgs)` 是小 M/N、大 K 的 GEMM 局部归约算法，归 `gemm`，不是跨卡 collective。它可以独自完成矩阵乘，不能仅凭原 trace 的邻接顺序把它称为上一 GEMM 的后处理 helper。具体闭源工作划分未解码，避免宣称已还原完整 split-K 实现。

在34节点用户容器 vllm330、TecoBLAS3.3.0、torch_sdaa3.3.0 上：

- 只开放逻辑设备24（本节点对应物理卡6的一个逻辑设备），无 distributed process group，不使用 graph。
- `torch.mm` 复现 NN，`F.linear` 复现 NT；每种操作测试 M/N/K 为 1/32/5120、1/64/5120、1/16/5120、4/32/17408。
- 每形状 profiling 3 次矩阵乘，只出现对应 allReduce 计算核；CPU FP32 reference 对比通过（FP16容差 rtol=.03, atol=.003，实际最大绝对误差约1.1e-4）。
- CPU profiler 包含 aten::mm、sdaa::mm.out、tecoblasHgemm，后者记录 m/n/k、alpha=1、beta=0、NN/NT 与 dtype。
- 真实两物理卡6/7的 TCCL all_reduce/all_gather/reduce_scatter 对照，分别测试512/5120/65536个FP16元素，两个rank共18个案例正确。发射 tccl_move_data、tccl_all_reduce_oneproc、tccl_move_data_list、tccl_reduce，未出现 BLAS GEMM allReduce。
- 库的 GemmNN/NT::findAlgoImplKai 调用 allReduce 算法分支；历史 eager NT trace 的发射点位于 tecoblasHgemm 的主机时间区间内。

实测库 SHA256：`33d74409c22f31e28f18020e809c329a5d8bbeb776369f44d51785dfe0df2072`。仅更新已验证 NN/NT fp16 变体；未验证 BLAS reduce 变体由专门规则标 unknown，不能让通用 allReduce 关键词抢归通信。其他版本仍应记录版本/哈希并复核。

## 每个 kernel 的复核范围

134个历史/近期T100名字全部有逐名记录：当前完整分类、语义、执行域、历史类别、规则ID、证据等级、精确单算子复现、来源和剩余限制。

证据层级分开：41个精确单算子复现、60个源码或明确API语义依据、33个库符号与参数类型依据。后者没有被宣称已读取全部闭源 kernel body。47个本地 tensor API 探针均成功，37个历史名字精确匹配；加上 GEMM/TCCL 对照，增强了类别证据。

共享 activation/unary 核可按 runtime mode 实现不同数学函数；历史 mode 缺失时只能确定激活/逐元素类别，不能把所有历史调用强制标为本次探针复现的 SiLU 或标量加法。fused_norm 也不能仅凭名字指定 RMSNorm。

新增稳定语义例外：`no_broadcast_float_between_half` 是 dtype 转换，`broadcast_expand_2d/last_dim` 是广播布局展开。它们仍在历史兼容的其他elementwise桶，但子类型已纠正。GDN/DeltaRule、卷积、cache/layout、scan、sum/argmax、采样等继续使用独立语义标签。

MEMCPY_P2P 是 peer 内存传输，是否跨物理卡应读源/目的设备；它不直接等同集合通信。精确 WAIT/SET 排除，TCCL wait flag 属通信同步。

## 实验位置与编号口径

执行节点为 tczc-tc34；容器挂载 `/workspace -> /data/application/changhl`。本次远程产物在 `/workspace/work/t100-deep-review-20261012/`，宿主路径 `/data/application/changhl/work/t100-deep-review-20261012/`；本机证据在 `D:/learn/work/outputs/t100-deep-review-20261012/`。关键文件为 allreduce-proof.json、t100-kernel-deep-review.json/csv/md，以及原始单算子 traces。

本节点每物理卡4个逻辑SDAA设备。早期诊断设置逻辑6，实际为物理卡1，原 metadata 的物理编号已在复核报告更正。决定分类的 NN/NT 实验使用逻辑24/物理6；两卡通信对照使用逻辑24和28/物理6和7。探针结束后释放资源，没有改动原推理服务，也没有覆盖已有1012工作簿列。
