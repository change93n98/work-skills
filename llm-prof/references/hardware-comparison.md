# 跨硬件性能对比模板

两侧各用一份 `llm-prof` 分类 JSON。每份 JSON 对应一个已选窗口和一个 rank 或设备范围。分开输出 BS1、BS32 或不同阶段的对比，按需把成品放在两份分类结果的共同上级目录。

```bash
python3 scripts/prof.py compare \
  --left T100-BS1-prefill.json --right H100-BS1-prefill.json \
  --left-name T100 --right-name H100 \
  --title "Qwen3.6-35B 纯文本 BS1 Prefill 性能对比" \
  --workload-verified --workload-note "FP16，rank 0，实际 4106 token，T100 TP8，H100 TP2" \
  --output BS1-prefill-comparison.xlsx
```

左右标签填写实际硬件名称，右侧为性能比基准。XLSX 使用与分类导出相同的 Artifact Tool 环境，可显式传 `--node` 和 `--node-modules`。只在确实更新已有对比表时加 `--overwrite`，分类输入保持只读。

## 读表口径

- 主表沿用分类顺序及样式。每侧耗时为该窗口设备事件 dur 之和，显示毫秒。主类别合计排除 WAIT/SET，设备调用合计包含 WAIT/SET。覆盖按设备事件区间并集，空泡等于窗口总时间减去覆盖。聚合分类没有逐事件覆盖数据时，相关字段显示 `n.a.`。
- 耗时比为左侧耗时除以右侧耗时。观测性能比取倒数，以右侧为 100%。用完整精度计算后显示百分比，耗时为零或缺少归因时显示 `n.a.`。
- 先核对模型、精度、阶段、rank/设备范围、Graph 模式和实际工作量，再加 `--workload-verified`。用 `--workload-note` 记录 TP/EP、输入和实际 token 数等影响解读的条件。模板会在已知阶段、rank、分类规则或实际工作量不一致，以及混合轮次时保留观测耗时比并禁用性能比。纯 Prefill 的 chunk 数可以因调度而不同，以实际 token 数核对；不同 TP 下的比例仍是两套配置的观测结果。
- GDN 分项按 [逻辑阶段](gdn-classification.md#t100-与-h100-对比) 对齐，标签使用「中文（英文算子）」。卷积后准备可把一侧的 QKV 重排、门控和归一化对应到另一侧的融合核。分项不重复计入主类合计。一侧未单独归因、实现辅助、元数据，以及 graph 候选导致的 GDN 整体已确认子集不填性能比。旧分类 JSON 如保留 GDN 语义明细，可从现有归因恢复分项。
- 工作量区读取报告中保存的实际 token、轮次和 Decode annotation。缺失值保持 `n.a.`，用 `--workload-note` 补充已有证据。导出后核对各侧 GDN 分项之和、WAIT/SET 及时间核算，并确认分类文件和窗口来源。
