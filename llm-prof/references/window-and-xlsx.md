# 指定窗口与 XLSX 入口

`scripts/prof.py` 有 `window`（手工时间）、`step`（关联首设备事件）、`xlsx` 三个子命令；抓取服务仍由 capture 流程负责。只给 step 编号时读取 [设备 step 关联选窗](device-step-window.md)，无需手工导出或提供起止时间。支持单个 JSON(.gz) 或 Perfetto 原生 trace，目录内多个 trace 明确报错。

## 运行环境

Python 依赖：`perfetto`（window）、`openpyxl`（XLSX 只读）。XLSX 由 Node.js `@oai/artifact-tool` 导出，默认查找本机 bundled runtime 的 `~/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/`。

可显式提供 `--node <node-executable>` 与 `--node-modules <absolute-node_modules-directory>`。没有 XLSX 运行环境时明确提示，`--no-xlsx` 仅导出 JSON/CSV/文本，不能声称已经交付 XLSX。运行脚本不修改依赖目录、不安装全局包。原生 Trace Processor 可用 `--trace-processor <trace_processor_shell>` 指定；首次使用 Perfetto SDK 可能下载其原生程序。

## window 参数与时间

```bash
python3 scripts/prof.py window \
  --trace /data/rank0.pt.trace.json.gz \
  --start-us 34860750.232 --end-us 34936572.312 \
  --stage decode --label decode-step2 --platform teco \
  --output-dir /data/outputs/decode-step2
```

精确换算：start_offset_ns=34860750232，end_offset_ns=34936572312，duration=75822.080 µs。偏移用 Decimal 解析为整数 ns，再与原生 `trace_bounds.start_ts` 做整数加法，避免 epoch 时间经浮点运算丢失边界精度。JSON `displayTimeUnit` 不用于推测 SQL 原点。

筛选与用户原 SQL 相同：`category IN ('kernel','gpu_memcpy','gpu_memset')`，`ts >= trace_bounds.start_ts + start_offset_ns`、`ts < trace_bounds.start_ts + end_offset_ns`；按 name 聚合完整 dur。不会计入开始在窗口之前的跨入事件，也不会裁剪开始在窗口内、结束在窗口外的事件。报告记录跨出事件数。需要 overlap/clipping 口径时应另选明确选项/实现，不能静默更换。

默认全部设备 track。`--track-id 3 --track-id 4` 可限定已核实的 track；track 是 stream/线程等存储单位，不能直接等同逻辑/物理设备。`--device-category sdaa_kernel` 可加 exporter 的明确设备类别；调用者应先核对元数据。不加 CPU op/runtime 类别。stage 仅标签，不猜测所选区间是第几个 decode。

原始相对占比、窗口占比的舍入和平均值沿用原 SQL，包括 `SUM(dur)/COUNT(*)/1000.0` 的整数 ns 除法次序。分类窗口占比另外直接按未舍入耗时与窗口计算，不累加四舍五入后的百分比。

## xlsx 参数与保留策略

```bash
python3 scripts/prof.py xlsx --xlsx exported.xlsx --sheet 数据 \
  --platform teco --label classified --output-dir output
```

数据页第一行需要 `name/record_count/total_duration_us`；其余原始列可缺失，缺失值保持不可用。多个数据页必须指定 `--sheet`。原文件不变，新文件完整导入原工作簿，只在所选数据页追加一个分类列和一页最新汇总；不重排/覆盖旧列和旧汇总。重复分类使用列/页数字后缀。

不能从已舍入的百分比可靠恢复精确时间窗口。该模式分类汇总中的窗口占比仅汇总输入的已有 `window_absolute_pct`；缺失时显示 n.a.。分类相对占比用原始总耗时重新计算，排除运行时标记。需要精确窗口值时使用 window 模式。

## 输出与审计

以 `--label` 为前缀：

- `.xlsx`：window/step 固定为“分类汇总”“Kernel明细”“选窗依据”三页；dense 六类，已确认专家 group gemm 的 MoE 七类。XLSX 输入保留旧页并追加最新汇总。
- `.csv`：前六列原始统计、类别、规则、confidence、歧义。
- `.json`：完整窗口基准、track 范围、规则版本/哈希、证据和候选类别、raw/busy/excluded 总耗时。
- `.sql`：window 使用的可在 Perfetto UI 直接执行的查询。
- `.txt`：类别耗时摘要。

默认拒绝覆盖已有报告；使用新 label/目录，或明确 `--overwrite`。即使 overwrite 也不允许原地覆盖输入 XLSX。交付前另用 artifact-tool 渲染并查看汇总/明细，不将交互预览的生命周期混入批量导出。

两种分母不可混用：原始相对占比包括所选 SQL 设备类别的全部事件（可含 WAIT/SET），分类相对占比只包括规则允许的六/七类设备事件；group gemm 独立计入分母，不与 gemm 重复。raw_total = busy_total + excluded_total。window/step 模式另以原始逐事件区间计算 `metadata.window_coverage`：同一窗口内合并重叠、裁剪边缘并补入跨入覆盖，空泡=窗口−覆盖；不是直接用窗口减 dur 之和。WAIT/SET覆盖仍保留。仅有聚合XLSX缺少逐事件区间时，不声称能得到精确去重空泡。

## 交付目录整理

每组实验、rank 或独立 trace 使用各自的交付目录。请求同时分析 decode 和 prefill 时，最终结构为：

```text
<本组目录>/
├── <原始trace>.pt.trace.json.gz
├── <最新decode分类表>.xlsx
├── <最新prefill分类表>.xlsx
└── 分析辅助资料/
    ├── <分类结果>.json / .csv / .sql / .txt
    ├── <选窗、多流、重叠、空泡等核验记录>
    ├── <抓取日志、脚本、配置和来源信息>
    └── <旧版分类表及其他辅助文件>
```

- 顶层只保留原始 trace 和两份最新分类表，名称应能区分阶段及所选 step/窗口；“最新”指本次已成功核验的结果，不能仅凭修改时间选表。原始 trace 保持名称和内容不变，格式也可为其他受支持的 trace 格式。
- 现有 `prof.py` 会把所有产物写到 `--output-dir`，不会自动整理目录。新分析优先将该参数设为 `<本组目录>/分析辅助资料`，完成导出、回读及核验后，只将最新 XLSX 移到本组顶层。直接调用 XLSX 导出器时，可以从辅助目录中的 JSON 读取并指定顶层 XLSX 路径；导出器的输入、输出参数保持兼容。
- 对已有交付目录，先明确保留的原始 trace 和两份最新表，再把其他普通文件移入辅助目录，包括旧版 XLSX、核验 CSV/JSON、SQL、文本、日志、脚本、配置、额外报告和压缩包。旧表归档保存；用户明确要求删除时才删除。采集、服务或导出仍在使用的脚本、日志、PID 等待任务结束后再整理，不能移动活动运行目录中的文件。
- 整理前核实绝对路径均在本组交付目录内，不递归处理上级目录或其他组。辅助目录存在同名文件时不覆盖，使用清晰版本后缀或归档子目录；新表成功核验前保留上次有效表。文件占用时另存清晰版本并说明，不能声称整理已完成。移动后核对顶层清单、归档数量及文件哈希，确认没有丢失或改写内容。
- 只要求 decode、prefill 或一个手选窗口时，顶层只保留原始 trace 与已要求阶段的最新分类表，不额外分析其他窗口。多个 rank/trace 分目录，graph-off 映射 trace 等额外来源材料归入辅助目录并保留有效来源路径；跨组汇总表和总压缩包放在各组目录的共同上级目录。
- 仅有 XLSX 输入时，交付目录顶层保留本次最新分类表，辅助产物仍放入“分析辅助资料”；原始输入 XLSX 保持原位，不移动或覆盖，不创建不存在的 trace 或另一阶段报告。仅交付 JSON/CSV 的 `--no-xlsx` 任务同样不伪造两份表格。

原生 API 与时间单位参考：[Perfetto Python API](https://perfetto.dev/docs/analysis/trace-processor-python)、[Perfetto SQL](https://perfetto.dev/docs/analysis/perfetto-sql-getting-started)。
