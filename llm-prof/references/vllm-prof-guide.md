# vLLM Profiling 指南

## 环境变量

### 必需环境变量
```bash
export HIP_VISIBLE_DEVICES=<gpu_ids>  # DCU设备
export HSA_FORCE_FINE_GRAIN_PCIE=1
export NCCL_MAX_NCHANNELS=16
export NCCL_MIN_NCHANNELS=16
```

### Profiling相关环境变量
```bash
export VLLM_TORCH_PROFILER_DIR=<output_dir>  # trace输出目录
```

### 性能优化环境变量
```bash
export ALLREDUCE_STREAM_WITH_COMPUTE=1
export VLLM_USE_PIECEWISE=0
export HIP_ALLOC_INITIALIZE=0
export GPU_MAX_HW_QUEUES=3
export VLLM_ZERO_OVERHEAD=1
export VLLM_ZERO_NO_THREAD=1
export VLLM_ENABLE_TBO=1
export VLLM_TBO_REQ_DELAY_MS=100
```

## Serve启动

```bash
vllm serve <model_path> \
    -tp <tp_size> \
    -pp <pp_size> \
    --port <port> \
    --dtype auto \
    --kv-cache-dtype fp8_e4m3 \
    --profiler-config '{"profiler": "torch", "torch_profiler_dir": "<dir>", "torch_profiler_with_stack": true, "torch_profiler_record_shapes": true}'
```

## Bench Profiling

```bash
vllm bench serve \
  --model <model_path> \
  --dataset-name random \
  --num-prompts 24 \
  --max-concurrency 24 \
  --random-input-len 4000 \
  --random-output-len 20 \
  --profile \
  --trust-remote-code \
  --port <port>
```

### 关键参数
- `--random-output-len 20`: decode步数设为20，避免prof文件过大
- `--profile`: 启用profiling
- `--num-prompts`: 请求总数
- `--max-concurrency`: 最大并发数

## 输出文件

Profiling完成后在`VLLM_TORCH_PROFILER_DIR`目录下生成:
- `*.pt.trace.json.gz` - Chrome trace格式的profiling数据

## 参考脚本
- `vllm-serve-example.sh` (本skill目录下)
