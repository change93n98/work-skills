# Prof 采集

## 准备诊断服务

按第 3 步复制本次模型的普通服务脚本，在 `vllm serve` 中加入 profiler 配置，给本次采集分配独立的挂载目录。默认记录算子耗时、shape、调用栈和内存事件。已指定参考配置时，按本次目标和镜像支持项调整。

```bash
--profiler-config '{
  "profiler": "torch",
  "torch_profiler_dir": "/path/to/run/trace",
  "torch_profiler_record_shapes": true,
  "torch_profiler_with_stack": true,
  "torch_profiler_with_memory": true,
  "torch_profiler_use_gzip": true
}'
```

按实际镜像中的 `ProfilerConfig` 核对可用字段。 [vLLM ProfilerConfig](https://docs.vllm.ai/en/latest/api/vllm/config/profiler/)

| 目的 | 参数 |
| --- | --- |
| 查调用来源 | `torch_profiler_with_stack=true`，记录调用栈 |
| 查内存分配 | `torch_profiler_with_memory=true`，记录内存事件 |
| 统计计算量 | `torch_profiler_with_flops=true`，估算支持的算子的 FLOPs |
| CUDA 耗时汇总 | `torch_profiler_dump_cuda_time_total`，控制 CUDA 耗时汇总 |
| 只看 worker | `ignore_frontend=true`，关闭 AsyncLLM 前端采集 |
| 跳过或截取 worker 迭代 | `delay_iterations` 跳过开始后的若干迭代，`max_iterations` 限制采集迭代数，`0` 表示不设上限 |
| 使用 profiler 内部调度 | `wait_iterations`、`warmup_iterations` 和 `active_iterations` 控制等待、内部预热和正式记录的迭代数 |
| 增加原生阶段标注 | `detailed_trace_annotation=true`，按版本确认支持 |

常规抓请求使用 `start_profile` 和 `stop_profile` 定界。只有需要分析服务启动时的 Graph 捕获，才核对目标版本的 `capture_torch_profiler` 实现并单独采集。

## 抓取和验收

确认诊断服务就绪、模型名正确、trace 目录可写。准备两份原生请求脚本，指向同一个诊断实例。预热脚本按目标用例选取有代表性的输入类型、长度、图片尺寸和并发，把参数写在脚本里。预热请求应完整结束，失败时返回非零。客户端预热在采集开始前完成，与 profiler 内部的 `warmup_iterations` 分开。

用 [采集脚本](../assets/capture_prof.sh) 依次执行预热和正式采集。`server` 使用诊断实例的 `host:port`，`warmup_script` 为预热脚本，`request_script` 为正式请求脚本。正式脚本的参数接在其路径后。使用 `bash -n` 检查后执行。

```bash
bash "$run_dir/capture_prof.sh" "$server" "$warmup_script" "$request_script"
```

脚本先跑预热。预热成功退出后调用 `POST /start_profile`，待正式请求结束后调用 `POST /stop_profile`。正式请求失败时也会尝试停止采集，并保留失败退出码。预热日志和正式请求日志分别保存。

等待 trace 落盘，核对开始、请求和停止的状态。检查本次 trace 文件完整性和对应的 rank 或设备，记录目标请求、配置、服务日志与实际 trace 路径。只要求抓取时交付原始 trace。需要分类或选窗时使用 `llm-prof`，需要新增阶段与 Graph 标注时使用 `vllm-phase-profiler`。
