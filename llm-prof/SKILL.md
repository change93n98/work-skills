---
name: llm-prof
description: >
  大模型推理 profiling 与 kernel 分类。支持三种入口：抓取 prof 并分析、已有 Perfetto 导出 XLSX 分类、
  trace 路径加起止时间或 step 编号直接生成分类表，支持通过调用关联定位首设备事件。
  支持 NVIDIA、DCU、太初 T100，
  以及 graph-off 来源映射与 graph-on 耗时分析。触发词：prof分析、profiling、算子耗时、trace分析、片选区域分类。
---

# LLM Prof

## 先选入口

按用户已提供的输入直接进入对应模式，不需要每次展示菜单或让用户重新选。输入不明确时只询问缺少的模式或关键参数。

| 模式 | 用户提供 | 执行方式 |
| --- | --- | --- |
| 1. 抓取 prof 并分类 | 需要启动服务/运行 profiling | 读取 [抓取与自动阶段分析](references/capture-and-auto-analysis.md)，仅此模式收集模型、框架、并行、负载、节点/容器等启动参数 |
| 2. 已有 XLSX 分类 | Perfetto 导出的 XLSX，或已有分类表 | `scripts/prof.py xlsx`，保留旧列，在新文件追加分类列和最新汇总 |
| 3. trace 选窗分类 | trace 文件/目录，加起止时间或 step 编号 | 手工时间用 `scripts/prof.py window`；按关联自动选 step 用 `scripts/prof.py step`，无需打开 UI |

用户给 trace 但没有时间时先检查阶段标记，decode 默认选关联设备边界的 step2，并说明编号和依据；prefill 总范围可显式选择首个 prefill 与首个 decode 的 annotation。旧的 [自动阶段分析](references/capture-and-auto-analysis.md) 保留给明确需要原有主机阶段口径的任务，不作为关联失败时的静默回退。只有要求 Python/CPU 来源时才额外读取 [graph 双 trace 映射](references/graph-source-mapping.md)，不必为分类采集双 trace。

默认每份分类表只导出用户选定的一个时间窗，decode 为 step2。子表1“分类汇总”仅按子表2“Kernel明细/数据”的这份数据汇总，选窗证据放在子表3。支持其他 step 不等于默认导出全部 step：未经要求，不混入全 trace、prefill、其他 decode 或另一个手选窗口。多 rank 仍分开汇总，不跨卡相加。只有用户明确要求多个窗口时才增加相应报告。

当前表格样式已经用户认可，后续新生成分类表固定复用 [分类表模板 v1](references/report-layout.md)：通过 `scripts/export_prof_report.mjs` 调用 `scripts/report_template.mjs`，使用 `assets/report-layout.json` 的列顺序、字体、颜色、列宽、数字格式、条纹表格和冻结行，不临时重新排版。表1必须保留空泡、设备覆盖和窗口总时间；只有用户明确要求时才改样式。已有XLSX源表保持原样，新增汇总使用同版配色和精度；缺少逐事件区间时空泡标不可计算。

## 模式 3：trace 加时间窗口

用户只给 step 时，默认按关联到的首设备事件选窗，而不是用 CPU annotation 的起止时间：

```bash
python3 scripts/prof.py step \
  --trace <trace.json.gz或目录> --stage decode --step 2 \
  --platform teco --label decode-step2-device --output-dir <output_dir>
```

`--step N` 从1开始计数，窗口为第N步关联首设备事件的 ts 到第N+1步关联首设备事件的 ts。通过 annotation 的 descendant runtime（同一原生线程被拆成多个显示 track 时可补充同线程包含关系），结合 trace 内 correlation/flow 找设备事件；包含 memcpy 和 WAIT/SET，零耗时 SET 也可作边界。graph replay 的一次 launch 可对应多个节点，不能只取一条 flow，也不能拿 CPU 起点附近的第一个事件代替关联。没有下一步或关联冲突时明确失败，不回退主机边界。

任意模型的 annotation 命名可用 `--annotation-regex`，明确的两段可用 `--annotation-id` / `--next-annotation-id`。阶段默认识别已验证的 execute_context generation/context 标记，不用耗时长短猜阶段。多 rank/设备明确选文件和 `--device-id`、`--host-track-id`、`--track-id`。关联不足、首时间戳并列、未关联事件、跨步重叠和两个首设备事件都要记录；XLSX 的“选窗依据”页提供核对。完整语义见 [设备 step 关联选窗](references/device-step-window.md)。

用户明确给定时间时继续沿用原手工窗口：

```bash
python3 scripts/prof.py window \
  --trace <trace.json.gz或目录> \
  --start-us 34860750.232 --end-us 34936572.312 \
  --stage decode --label decode-step2 \
  --platform teco --output-dir <output_dir>
```

- 时间默认单位 µs，原点是 **Perfetto 的 `trace_bounds.start_ts`**，与相对 trace 起点的 UI 时间/用户 SQL 一致。不是 JSON 中的绝对 `ts`。用户给 ns/ms 时先明确换算，禁止凭最早 kernel 推算原点。
- 手工 window 的 `stage` 是用户标签，不自动更改窗口；step 模式按匹配 annotation 序列编号，并记录实际两个 annotation。
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
- 模式3数据页前六列保持用户 SQL：`name, record_count, total_duration_us, avg_duration_us, kernel_relative_pct, window_absolute_pct`。模式2完整保留输入列。边界确定后仍按时间窗统计，不代表其中所有事件都由本步 annotation 调用；JSON记录窗口内不能确认归属本步的事件数。原始 SQL 相对占比包含 WAIT/SET，便于对账。
- 分类汇总的六类为 GEMM、通信、FlashAttention、Triton、其他elementwise、memcpy/memset；精确 WAIT/SET 等规则排除项单列，不进入六类相对占比的分母。不能直接把明细已四舍五入的百分比当精确分类占比。
- 明确显示“窗口总时间”和“空泡”。总时间等于片选窗口长度；空泡等于窗口减去设备事件区间并集，包含 WAIT/SET，跨窗口事件裁剪后计入覆盖。分类 dur 仍按子表2加总；有多流重叠时另列“重叠/边界调整”，不能重复扣减。当前空泡指所选设备轨迹未覆盖的时间，等待标记内部时间仍单列。仅有聚合 XLSX 而无逐事件 ts/dur 时不能计算精确去重空泡。
- 分类仍依据名字；保留 rule ID、semantic_type、confidence、evidence、ambiguity_reasons 和候选类别。`fallback:unknown` 不代表语义已确认，按耗时报告未知/歧义项，不能用泛厂商前缀消除 unknown。
- “其他elementwise”是兼容桶，包含归约、布局、卷积、采样等，不能全部描述为逐元素。融合 FFN GEMM 与 activation helper 分开；已实测的 TecoBLAS NN/NT FP16 GEMM allReduce 是 GEMM，未验证变体仍标 unknown。

分类规则 API 和优先级见 [独立分类产物](references/kernel-classification.md)。T100 证据见 [API/源码依据](references/tecovllm-t100-kernel-knowledge.md)、[逐核审阅](references/teco-kernel-review-20261012.md)、[allReduce 实测复核](references/t100-allreduce-deep-review-20261012.md)。

## 验证与交付

1. 对齐时间原点、单位、设备范围和 SQL 入窗方式。空结果或越界应明确报错，不自动扩大窗口。
2. 核对原始调用次数/总耗时、六类合计与排除项守恒；高耗时 unknown/歧义项保留待确认状态。
3. XLSX 用 artifact-tool 导出，检查汇总与明细并回读。已有表格追加分类时核对旧值/公式/格式，不能只验证文件存在。
4. 交付 XLSX 与简洁分类结果，说明窗口、分母和未知项。JSON/SQL 留在输出目录便于复核。

新入口不替换原自动阶段/双 trace 分析器；其输出文件和命令保持兼容。
