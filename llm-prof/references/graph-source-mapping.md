# Graph-off 源码映射 / Graph-on 真实设备耗时

适用于 CUDA Graph、DCU/ROCm HIP Graph，以及太初 T100/SDAA/PrivateUse1 等设备 graph 的 Chrome/Kineto JSON trace。源码映射属于跨运行推断，不是 replay 中恢复出来的逐次调用链。设备 graph 实现是否能导出 kernel、关联 ID 和 Python frame，需要在目标环境检查。

## 采集两份可比 trace

1. 保存本次实际的服务启动命令、环境变量、框架/插件/编译器版本和 graph 设置。使用同一个模型、精度、TP/PP/DP、rank、设备、attention backend、并发、输入/输出长度和请求数据。记录 graph capture 的 batch bucket/padding；关闭 graph 后实际 batch shape 可能变化。
2. **Mapping / graph-off**：关闭目标后端的 graph，开启 CPU + 设备 profiling、Python 调用栈（`with_stack`）；必要时开启 shapes。先 warmup 再采集，确认 trace 有 `cpu_op`、`python_function` 或 Call stack，以及设备 kernel 与 host 的 `External id` / `correlation` 关联信息。
3. **Formal / graph-on**：恢复真实运行的 graph、融合和编译配置，完成 warmup/capture 后只采集稳定的 replay。保留设备 kernel 事件、设备编号和 stream。这里的 kernel `dur` 是性能报告唯一的耗时输入。
4. 优先分别采集 prefill、decode workload。两次采集的时间戳和关联 ID 不需要相同，也**不能跨 trace 用 ID 直接关联**。每次选同一 rank/设备；混合 trace 必须分别确认两个 trace 的阶段时间窗口。

不要同时启动两个会争抢同一设备的服务。不要把初始化、graph capture 或 warmup kernel 混入正式 decode replay 窗口。`--stage decode` 是用户确认的阶段标签，不会自动证明 trace 中全是 decode。

### 各平台的 graph 开关

| 环境 | Mapping | Formal | 验证 |
| --- | --- | --- | --- |
| 上游 SGLang CUDA | 常见开关 `--disable-cuda-graph` | 恢复实际 graph 配置 | 检查当前 `--help`、启动日志和 replay trace |
| 上游 vLLM CUDA | 常见开关 `--enforce-eager` | 恢复实际 graph 配置 | eager 可能同时关闭 torch.compile，记录由此产生的 kernel/融合变化 |
| DCU / ROCm HIP Graph | 使用安装版本/厂商 fork 的真实开关 | 恢复实际 HIP Graph 配置 | 不仅凭参数名含 cuda 判断；检查 HIP capture/replay 路径与日志 |
| T100 / SDAA graph | 读取本地 tecovllm/框架插件的 graph runner、配置定义和 `--help` 后确定 | 恢复真实 SDAA graph 配置 | 不臆造 `--disable-sdaa-graph` 等参数；核实 capture/replay 路径 |

国产卡只要导出相同结构的 trace，就使用同一分析器，不要求 runtime 名称以 CUDA 开头。`privateuse1_runtime`（真实 T100 导出类别）、`sdaa_runtime`、`hip_runtime`、`cuda_runtime` 和 driver 类别中的 correlation 均可参与映射。

参考：[SGLang 官方双 trace 工作流](https://github.com/sgl-project/sglang/tree/main/.agents/skills/llm-torch-profiler-analysis)、[vLLM eager 与编译的关系](https://docs.vllm.ai/en/latest/design/debug_vllm_compile/)。启动参数以目标版本为准。

## 执行分析

使用独立入口，它不依赖 `model_forward` 标记，也不会把 CPU 算子耗时当设备耗时：

```bash
python3 scripts/prof_graph_analyze.py \
  --mapping-trace /run/mapping/decode/rank0.trace.json.gz \
  --formal-trace /run/formal/decode/rank0.trace.json.gz \
  --stage decode --output-dir /run/analysis/decode \
  --run-configs /run/pair-configs.json
```

`--run-configs` 可选；缺失时输出 `unverified` 和配置未验证警告，不能宣称两次执行配置已被脚本核实。配置文件使用以下结构，补齐实际影响调用路径的字段：

```json
{
  "mapping": {
    "graph_enabled": false,
    "platform": "T100", "model": "/models/Qwen", "dtype": "bf16",
    "tp": 1, "pp": 1, "dp": 1, "rank": 0,
    "batch_size": 1, "input_len": 1024, "output_len": 20,
    "framework_version": "实际版本", "attention_backend": "实际后端"
  },
  "formal": {
    "graph_enabled": true,
    "platform": "T100", "model": "/models/Qwen", "dtype": "bf16",
    "tp": 1, "pp": 1, "dp": 1, "rank": 0,
    "batch_size": 1, "input_len": 1024, "output_len": 20,
    "framework_version": "实际版本", "attention_backend": "实际后端"
  }
}
```

脚本比较提供的字段（除 `graph_enabled`）；差异写入报告，已有来源候选标记为 ambiguous。相同的元数据是使用者声明，仍应检查运行日志和 graph-on kernel 序列是否可比。

混合 trace 的窗口使用各自 trace 的绝对微秒时间戳：

```bash
python3 scripts/prof_graph_analyze.py \
  --mapping-trace mapping.json.gz --formal-trace formal.json.gz \
  --mapping-window 100000:200000 --formal-window 300000:400000 \
  --mapping-device 0 --formal-device 0 \
  --stage decode --output-dir analysis
```

窗口只纳入完整落在窗口内的事件，务必检查起止边界不会切断 kernel。多设备/多 rank 合并 trace 默认报错；用 `--mapping-pid` / `--formal-pid`、`--mapping-device` / `--formal-device` 明确选设备轨道。两次运行 pid 不需要相同。不要直接把主机进程 pid 当设备轨道 pid。

默认设备类别：`kernel`、`gpu_kernel`、`cuda_kernel`、`hip_kernel`、`sdaa_kernel`、`device_kernel`、`gpu_memcpy`、`gpu_memset`。如果厂商使用不同类别，先确认该事件代表**设备执行时间**，再用可重复的 `--device-category 厂商类别` 加入。`cpu_op`、runtime 和 Python scope 不允许用作设备类别。没有设备事件时停止并报错。

## 匹配与歧义

在 mapping trace 内建立关联：

- `external-id`：kernel 的 External id 对应 CPU op；有 launch 时同时检查 host 线程和时间包围。
- `correlation+launch-external-id`：kernel → 同 correlation 的 runtime/driver 事件 → CPU op。
- `correlation+host-thread-enclosure`：通过发射事件的主机 pid/tid 和时间，找最内层 CPU op；这是时间包围证据，弱于直接 ID。
- `correlation+python-frame`：找到了发射处 Python scope，但没有 CPU op。只报告已有部分。

关联字段兼容 `External id` / `external_id`、`correlation` / `correlation_id` 等大小写/分隔符变体。不会猜测未知厂商 ID 的含义。只有 graph launch/replay scope 时标记 `graph-launch-only`，不能将其当原始算子来源。

跨 trace 的 `match_basis`：

- `name:exact`：完整 kernel 名字相同。
- `name:normalized`：仅移除 `void` 前缀、空白、地址差异和末尾参数签名。保留模板参数、数字后缀和大小写。
- `none`：无符号匹配。不会用泛前缀/名字相似度强行转移来源，也不会假设两次 kernel 顺序一一对应。

`source_status`：

| 状态 | 含义 |
| --- | --- |
| `mapped` | 当前映射中唯一、完整的 host 来源候选；仍不是逐 replay 实例的证明 |
| `partial` | 只找到 CPU op 或 Python 位置中的一部分 |
| `ambiguous` | 多个符号/来源、部分 mapping 调用缺失来源，或运行配置不同 |
| `unresolved` | 无名字匹配或没有可靠 host 关联 |

同名 kernel 的不同来源保留全部候选；不选“耗时最多的一层”当唯一来源。多个模型层可能执行相同代码行，trace 未标记层身份时，唯一源码位置也不能证明唯一模型层。`source_candidates` 含 mapping 符号、CPU op、Python 位置/短调用栈、host pid/tid、关联依据和观测次数。观测次数只描述 graph-off 样本，不能分摊 graph-on 的耗时。类别仍使用现有 kernel 名字分类，源码候选不会自动覆盖类别。

## 产出与检查

- `graph_analysis.json`：完整报告、输入选择、配置差异、所有候选和歧义原因。
- `graph_kernel_sources.csv`：按 graph-on 耗时降序，包含类别、来源状态、匹配依据、候选。
- `graph_analysis.xlsx`：明细、类别汇总和 Provenance（安装 openpyxl 时生成）。超长单元格提示查看完整 JSON。
- `graph_analysis_summary.txt`：来源状态覆盖率、graph-on 总耗时及警告。

检查 `formal_total_duration_us` 等于选中 graph-on 设备事件的 dur 总和，以及各类别、各来源状态的耗时之和。WAIT/SET/profiler marker 排除；mapping 的 kernel、CPU op、graph launch 耗时不进入统计。多 stream 的 kernel 可能重叠，因此 dur 总和不是阶段墙钟耗时，本入口不据此计算 idle/bubble 或设备利用率。

`graph_evidence` 汇报选中 kernel 的 correlation 是否能关联到 runtime/driver graph launch。Mapping 仍有 replay 链接时提示核查 graph-off；Formal 没有链接时提示从日志/导出器确认 graph-on，不能把没有导出关联信息等同于没有启用 graph。

分类未知项继续使用 `audit_kernel_categories.py graph_analysis.xlsx` 审计（或查看 JSON 的 `classification_rule`）；按 graph-on 耗时优先核实 ambiguous/unresolved 项。只有 graph-on trace 时仍可用原分析器做名字分类，但不能宣称已经完成 graph-off 源码映射。
