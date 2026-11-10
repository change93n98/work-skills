# Dump size 采集

本步骤只在 T100 上执行，使用太初 SDK 和 LMK 的原生 dump 开关。

## 准备诊断服务

按第 3 步复制本次模型的普通服务脚本，核对实际版本支持的 dump 开关。普通算子 dump 使用 `TECO_ENABLE_DUMP_INFO`，LMK dump 使用 `TECOLMK_ENV_ENABLE_DUMP_INFO`，按需要开启其中一项或两项。下面以两项都开启为例。`dump_run_dir` 取容器内可写的独立挂载目录，把命令放在原有 `vllm serve` 之前。

```bash
export TECO_ENABLE_DUMP_INFO=1
export TECOLMK_ENV_ENABLE_DUMP_INFO=1
export TECO_DUMP_INFO_DIR_PATH="$dump_run_dir/dump_info"
mkdir -p "$TECO_DUMP_INFO_DIR_PATH" || exit 1
cd "$dump_run_dir" || exit 1
```

普通算子写到 `dump_info`，LMK 写到服务工作目录的 `lmk_dump`。按第 3 步启动并确认诊断服务就绪。

## 只采集正式客户端请求

1. 诊断服务就绪后，等模型加载、服务端 warmup 和 Graph 捕获结束。任务需要客户端预热时也在此时跑完，等请求和 dump 写入结束。采集期间专用实例只接收本次正式客户端请求。
2. 按第 4 步正式测试的脚本和参数复跑，将目标地址换成本次诊断实例。保留输入输出长度、BS、图片尺寸和张数。`request_script` 只执行正式请求，预热脚本在目录切换前单独执行。
3. 使用 [采集脚本](../assets/capture_dump_size.sh) 在正式请求前将 `dump_info` 和 `lmk_dump` 移入 `before_formal`，再建立空目录。`dump_run_dir` 是脚本所在环境可见的绝对路径，两个子目录与 `before_formal` 位于同一挂载内。按正式客户端要求进入工作目录，检查 `bash -n` 后执行，正式脚本参数按需接在其路径后面。

   ```bash
   bash "$run_dir/capture_dump_size.sh" "$dump_run_dir" "$request_script"
   ```

4. 核对正式请求退出状态、服务请求日志和 `request_start.txt`、`request_end.txt`。等待写入结束，确认目标算子在新目录中生成记录。采集失败时保留已写出的记录与日志，并报告缺失项。

## 去重和交付

对正式窗口的 SDK `prototxt` 使用本次 HTTP checkout 的 `teco-modeltest/lm_infer/unit/deduplicate_cases.py`。从 `dump_run_dir` 用固定相对路径调用原生工具，`teco_modeltest` 取该 checkout 的绝对路径。输出每个算子的代表文件、`cases_list.txt` 和去重日志。

```bash
(
  cd "$dump_run_dir" || exit 1
  mkdir dump_info_dedup || exit 1
  python "$teco_modeltest/lm_infer/unit/deduplicate_cases.py" \
    --input_path dump_info --output_path dump_info_dedup > deduplicate.log 2>&1
)
```

按原生工具的算子分组和测例内容去重，核对去重前后数量及代表文件。LMK YAML 按运行库的测例参数哈希归并，核对本次 `lmk_dump` 中每个测例的算子和参数。`before_formal` 单独保留，去重输入和交付结果只取正式请求目录。交付请求配置、目标算子尺寸、SDK 去重前后数量、LMK 唯一测例数、日志，以及宿主和容器中的结果路径。
