# 通过调用关联选择设备 step 窗口

适用于用户给 step 编号而不给 Perfetto 起止时间。自动边界是“本步首关联设备事件”到“下一步首关联设备事件”；时间单位和原点沿用 native Perfetto。该间隔是设备迭代周期，包含等待/空隙，不等于本步 kernel dur 之和或忙碌时间。

## 任意 step

```bash
python3 scripts/prof.py step --trace rank0.pt.trace.json.gz \
  --stage decode --step 3 --platform teco --label decode-step3-device --output-dir output
```

`--step N` 是从1开始的序号。默认 decode 匹配 `execute_context..._generation_<正整数>(...)`；prefill 匹配 context 数大于0的 execute_context。它们是本库已验证的导出命名，其他框架应显式提供例如 `--annotation-regex '^model_forward'`。自定义 regex 按匹配的 user_annotation 排序编号，不自行判断首次是否 prefill。不要把同一调用的嵌套 annotation 数成不同步。

如需跨阶段边界（例如最后一个 prefill 到第一个 decode），或已经知道两个 slice ID：

```bash
python3 scripts/prof.py step --trace rank0.json.gz --stage prefill \
  --annotation-id 123 --next-annotation-id 456 --platform teco --output-dir output
```

此时两个 ID 必须是同一原生主机线程上正向、不重叠的 user_annotation；没有原生线程身份时要求同一显示 track。ID 是当前 trace 的局部值，不得跨 trace 复制。最后一个 step 没有下一步时，不能输出首到首周期；明确报错，不能用本步最后一个事件结束时间冒充下一步开始。

## 关联依据

1. 从 `descendant_slice(annotation_id)` 找嵌套 runtime/driver。带 Python stack 的 Chrome trace 可能让 Perfetto 把同一线程拆为 execution/overlapping 多条显示 track；此时通过 `thread_track.utid` 确认是同一原生线程，再用 annotation 时间完整包含 runtime 的关系补充，并记录 `same-host-thread-enclosure` 依据。不能仅凭显示 track 不同丢弃调用，也不能跨原生线程按时间强行关联。
2. 读取设备事件与 runtime 的 correlation，以及原生 `flow.slice_out/slice_in`。有 flow 和 correlation 时求一致候选；flow 缺失可用唯一 correlation 补充；flow 可缩小复用 correlation 的候选范围。
3. 同一个 graph launch 对应的全部节点都纳入候选。包含三类设备事件 kernel/gpu_memcpy/gpu_memset，额外后端类别可用 `--device-category`；**不按名字排除 WAIT/SET，不排除零耗时 SET**。主机 runtime 本身不作设备边界。
4. 在确定归属的候选中取最小设备 `ts`。同一最小时间戳的多个事件全部记录，不声称其中某一个在时间上更早。
5. 复用 ID 或冲突使更早候选可能属于本步时失败，不随意挑一个。没有任何确定关联、跨设备或时钟顺序矛盾也失败；没有按最近时间匹配或 CPU 边界回退。

边界确定只覆盖 trace 中记录到的关联。annotation 只覆盖同一原生线程的嵌套/包含调用，后台线程没有可追踪父子关系时不能凭时间补归属。首事件之前若存在无关联的设备事件，保留 `nearby-unlinked-events` 状态，表示当前值只是首个已确认关联事件，不能宣称关联完整。JSON还记录全 trace 未关联数量、后续有歧义候选数、首时间戳并列事件和 launch 详情。

多设备时使用 `--device-id`，多 host track 时用 `--host-track-id`；必要时用多个 `--track-id` 显式限定 stream/track。track 不等同于物理卡，设备 ID 是 exporter 的逻辑 ID。按 rank 分文件分析，不能把不同 rank 的 correlation 或时钟直接混合。

## 窗口统计与调用归属

确定边界后仍使用原 SQL 的 `[start,end)` 开始时间筛选和完整 dur，分类并保留六个原始统计列。统计对象是时间窗内的全部所选设备事件，**不是按归属过滤的本步事件集合**。这是与原 Perfetto 片选表一致的口径。

报告另外记录本步关联事件跨过窗口末尾的数量、窗口内不能确认由本步调用的事件数量。多流交错时这些数值可能非零，不能把窗口内所有事件强制归属本步。WAIT/SET 始终保留在原始明细，类别汇总单列等待/同步；六类计算相对占比的分母仍排除这类标记。

窗口总时间单列，等于设备选窗两端之差。覆盖时间使用同一窗口的逐次设备事件（含 WAIT/SET）合并重叠、裁剪窗口边缘，并补入窗口开始前发起但仍在执行的部分；空泡=窗口−覆盖。分类加总保留原 SQL 口径，必要时用“重叠/边界调整”衔接到覆盖时间：调用加总+调整+空泡=窗口。当前空泡是所选设备轨迹没有事件覆盖的时间，不将 WAIT 内部时长再次算为空泡。只有按 name 汇总的 XLSX 缺少区间信息，不能假定所有 dur 不重叠。

XLSX 的“选窗依据”页显示两个 annotation、首设备事件名字/category/时间、device/stream、correlation、关联方式及置信状态。完整证据在同名 JSON 的 `metadata.device_step` 中。`.sql` 保存由设备边界生成、可在 Perfetto 执行的查询。

默认只导出选定 step，decode 为 step2；任意 N 是可选能力，不是要求默认枚举全部 N。子表1只汇总子表2中这一个选区的数据，不能另加全 trace/prefill/其他 decode 时间片。每个 rank 单独统计，旧报告另存。用户明确要求多窗口时，每份 trace 复用一个 `DeviceStepIndex`，各汇总公式引用对应的明细块；最后一步缺少下一步则记录不可形成周期，不能补造边界。

## 已验证示例

lx-fulldecode decode 第2步与第3步最早关联事件均为 `Memcpy HtoD (Pinned->Device)`，偏移为34860874.392和34936696.472 µs，周期75822.080 µs。此值包含 WAIT/SET 的候选筛选；不能因为时长与另一手选窗口相同，就认定它们起止位置相同。

原生机制参考：[Perfetto descendant/flow](https://perfetto.dev/docs/analysis/perfetto-sql-getting-started#descendant-slice)。
