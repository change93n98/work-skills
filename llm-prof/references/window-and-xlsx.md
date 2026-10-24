# 指定窗口与 XLSX 入口

`scripts/prof.py` 有 `window`、`xlsx` 两个子命令；抓取服务仍由 capture 流程负责，避免把服务启动参数混进离线分类。支持单个 JSON(.gz) 或 Perfetto 原生 trace，目录内多个 trace 明确报错。

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

- `.xlsx`：window 为“分类汇总”和“数据”两页；XLSX 输入保留旧页并追加最新汇总。
- `.csv`：前六列原始统计、类别、规则、confidence、歧义。
- `.json`：完整窗口基准、track 范围、规则版本/哈希、证据和候选类别、raw/busy/excluded 总耗时。
- `.sql`：window 使用的可在 Perfetto UI 直接执行的查询。
- `.txt`：类别耗时摘要。

默认拒绝覆盖已有报告；使用新 label/目录，或明确 `--overwrite`。即使 overwrite 也不允许原地覆盖输入 XLSX。交付前另用 artifact-tool 渲染并查看汇总/明细，不将交互预览的生命周期混入批量导出。

两种分母不可混用：原始相对占比包括所选 SQL 设备类别的全部事件（可含 WAIT/SET），分类相对占比只包括规则允许的六类设备事件。raw_total = busy_total + excluded_total。多流时 dur 相加可能超过墙钟时长，不自动生成空泡/利用率。

原生 API 与时间单位参考：[Perfetto Python API](https://perfetto.dev/docs/analysis/trace-processor-python)、[Perfetto SQL](https://perfetto.dev/docs/analysis/perfetto-sql-getting-started)。
