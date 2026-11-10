# Prof 采集

## 准备诊断服务

按第 3 步复制本次模型的普通服务脚本。在实际 `vllm serve` 命令中加入 profiler 配置，给本次采集分配独立的挂载目录。下面是最小配置，调用栈、shape、内存等字段按本次要求和目标版本支持项填写。

```bash
--profiler-config '{"profiler":"torch","torch_profiler_dir":"/path/to/run/trace"}'
```

启动诊断实例，确认服务就绪、模型名正确、trace 目录可写。需要预热时，在开始采集前完成。输入、输出、请求数和并发按任务设置。

## 抓取和验收

用 [采集脚本](../assets/capture_prof.sh) 包住本次原生请求脚本。`server` 使用诊断实例的 `host:port`，`request_script` 是指向同一服务的请求脚本。需要传给请求脚本的参数接在其路径后面。使用 `bash -n` 检查后执行。

```bash
bash "$run_dir/capture_prof.sh" "$server" "$request_script"
```

脚本先请求 `POST /start_profile`，待本次请求结束后调用 `POST /stop_profile`。开始成功后，即使请求失败也会尝试停止采集并保留失败退出码。将采集过程输出保存到本次日志。

等待 trace 落盘，核对开始、请求和停止的状态。检查本次 trace 文件完整性和对应的 rank 或设备，记录目标请求、配置、服务日志与实际 trace 路径。只要求抓取时交付原始 trace。需要分类或选窗时使用 `llm-prof`，需要新增阶段与 Graph 标注时使用 `vllm-phase-profiler`。
