---
name: llm-prof
description: >
  大模型推理 profiling 与 kernel 分类。支持三种入口：抓取 prof 并分析、已有 Perfetto 导出 XLSX 分类、
  trace 路径加 Perfetto 开始/结束时间直接生成分类表。支持 NVIDIA、DCU、太初 T100，
  以及 graph-off 来源映射与 graph-on 耗时分析。触发词：prof分析、profiling、算子耗时、trace分析、片选区域分类。
---

# LLM Prof

## 先选入口

按用户已提供的输入直接进入对应模式，不需要每次展示菜单或让用户重新选。输入不明确时只询问缺少的模式或关键参数。

| 模式 | 用户提供 | 执行方式 |
| --- | --- | --- |
| 1. 抓取 prof 并分类 | 需要启动服务/运行 profiling | 读取 [抓取与自动阶段分析](references/capture-and-auto-analysis.md)，仅此模式收集模型、框架、并行、负载、节点/容器等启动参数 |
| 2. 已有 XLSX 分类 | Perfetto 导出的 XLSX，或已有分类表 | `scripts/prof.py xlsx`，保留旧列，在新文件追加分类列和最新汇总 |
| 3. trace 指定窗口分类 | trace 文件/目录、阶段、开始和结束时间 | `scripts/prof.py window`，直接执行 Perfetto SQL，生成 XLSX、CSV、JSON、SQL，无需打开 UI |

用户给 trace 但没有时间、希望自动找 prefill/decode 时，仍可使用 [自动阶段分析](references/capture-and-auto-analysis.md) 的快速模式。只有要求 Python/CPU 来源时才额外读取 [graph 双 trace 映射](references/graph-source-mapping.md)，不必为分类采集双 trace。

## 模式 3：trace 加时间窗口

```bash
python3 scripts/prof.py window \
  --trace <trace.json.gz或目录> \
  --start-us 34860750.232 --end-us 34936572.312 \
  --stage decode --label decode-step2 \
  --platform teco --output-dir <output_dir>
```

- 时间默认单位 µs，原点是 **Perfetto 的 `trace_bounds.start_ts`**，与相对 trace 起点的 UI 时间/用户 SQL 一致。不是 JSON 中的绝对 `ts`。用户给 ns/ms 时先明确换算，禁止凭最早 kernel 推算原点。
- `stage` 是用户标签，不自动更改窗口。`decode-step2` 由用户确认，不能从任意片段猜测步数。
- 与原 SQL 一致：只选 `ts >= start` 且 `ts < end` 的 `kernel/gpu_memcpy/gpu_memset`，按 name 分组，保留完整 dur，包括跨越窗口终点的事件。默认不裁剪、不按结束时间筛除。
- 目录只有一个支持的 trace 才自动选取；多个文件必须分别指定，不能默认取第一个或合并不同 rank。
- 默认选该 trace 的全部设备 track，与原 SQL 相同；用户要选某个设备时先查看 track/device 元数据，用重复 `--track-id` 限定，不能把所有 track 当同一张卡。国产 exporter 的其他明确设备类别可用重复 `--device-category` 补充，不能包含 CPU/runtime 类别。
- 实现使用原生 Perfetto Trace Processor，不以 JSON 最小时间近似替代。依赖与完整参数见 [指定窗口与 XLSX 入口](references/window-and-xlsx.md)。

## 模式 2：XLSX 加分类

```bash
python3 scripts/prof.py xlsx \
  --xlsx <perfetto-export.xlsx> \
  --platform teco --label reclassified --output-dir <output_dir>
```

识别第一行含 `name`、`record_count`、`total_duration_us` 的数据页；多个候选用 `--sheet` 选择。保留原文件、所有旧列与旧汇总，追加“最新分类结果”和独立的“最新分类汇总”；已有同名列/页则使用数字后缀，不能覆盖以前的版本。详细匹配证据和歧义写入同名 JSON。只读输入，输出文件必须与源文件不同。

## 三个模式共用的分类和统计约定

- 平台用 `--platform nv|dcu|teco|auto`，已知硬件时明确选择；规则统一来自 `rules/kernel-classification-rules.json`，可用 `--kernel-rules <JSON>` 覆盖。记录规则版本、SHA256、平台、输入文件及窗口。
- 模式3数据页前六列保持用户 SQL：`name, record_count, total_duration_us, avg_duration_us, kernel_relative_pct, window_absolute_pct`。模式2完整保留输入列。原始 SQL 相对占比包括被 exporter 标为设备事件的 WAIT/SET，便于与原 SQL 对账。
- 分类汇总的六类为 GEMM、通信、FlashAttention、Triton、其他elementwise、memcpy/memset；精确 WAIT/SET 等规则排除项单列，不进入六类相对占比的分母。不能直接把明细已四舍五入的百分比当精确分类占比。
- 不用“窗口减去所有 dur 之和”推算空泡。多流/多设备可重叠，相加占比可能超过100%；类别窗口占比不代表利用率。XLSX 只有舍入后的窗口占比时不能恢复精确窗口/空泡。
- 分类仍依据名字；保留 rule ID、semantic_type、confidence、evidence、ambiguity_reasons 和候选类别。`fallback:unknown` 不代表语义已确认，按耗时报告未知/歧义项，不能用泛厂商前缀消除 unknown。
- “其他elementwise”是兼容桶，包含归约、布局、卷积、采样等，不能全部描述为逐元素。融合 FFN GEMM 与 activation helper 分开；已实测的 TecoBLAS NN/NT FP16 GEMM allReduce 是 GEMM，未验证变体仍标 unknown。

分类规则 API 和优先级见 [独立分类产物](references/kernel-classification.md)。T100 证据见 [API/源码依据](references/tecovllm-t100-kernel-knowledge.md)、[逐核审阅](references/teco-kernel-review-20261012.md)、[allReduce 实测复核](references/t100-allreduce-deep-review-20261012.md)。

## 验证与交付

1. 对齐时间原点、单位、设备范围和 SQL 入窗方式。空结果或越界应明确报错，不自动扩大窗口。
2. 核对原始调用次数/总耗时、六类合计与排除项守恒；高耗时 unknown/歧义项保留待确认状态。
3. XLSX 用 artifact-tool 导出，检查汇总与明细并回读。已有表格追加分类时核对旧值/公式/格式，不能只验证文件存在。
4. 交付 XLSX 与简洁分类结果，说明窗口、分母和未知项。JSON/SQL 留在输出目录便于复核。

新入口不替换原自动阶段/双 trace 分析器；其输出文件和命令保持兼容。
