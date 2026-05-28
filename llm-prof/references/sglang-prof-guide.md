# SGLang Profiling 指南

## 环境变量

### 必需环境变量
```bash
export HIP_VISIBLE_DEVICES=<gpu_ids>  # DCU设备
export SGLANG_ENABLE_SPEC_V2=1
export USE_DCU_CUSTOM_ALLREDUCE=1
export ALLREDUCE_STREAM_WITH_COMPUTE=1
export SGLANG_KV_LAYOUT_DCU_FA=1
```

### 性能优化环境变量
```bash
export SGLANG_USE_LIGHTOP=1
export SGLANG_USE_FP8_W8A8_MOE=1
export SGLANG_USE_FUSED_TOPK_SOFTMAX=1
export NCCL_MIN_NCHANNELS=16
export NCCL_MAX_NCHANNELS=16
export HSA_ENABLE_COREDUMP=1
export GLIBC_TUNABLES=glibc.rtld.optional_static_tls=0x40000
export HIP_KERNEL_BATCH_CEILING=100
export GPU_FORCE_BLIT_COPY_SIZE=16
export HSA_KERNARG_POOL_SIZE=8388608
export ROC_AQL_QUEUE_SIZE=131072
```

## Serve启动

```bash
sglang serve \
    --model-path <model_path> \
    --host 0.0.0.0 \
    --port <port> \
    --trust-remote-code \
    --dtype bfloat16 \
    --kv-cache fp8_e4m3 \
    --tp-size <tp_size> \
    --pp-size <pp_size> \
    --mem-fraction-static 0.85 \
    --attention-backend fa3 \
    --page-size 64 \
    --disable-radix-cache \
    --cuda-graph-max-bs 512
```

## Bench Profiling

```bash
python -m sglang.bench_serving \
  --backend sglang \
  --model <model_path> \
  --host <host> \
  --port <port> \
  --dataset-name random \
  --random-range-ratio 1 \
  --random-input-len 4000 \
  --random-output-len 20 \
  --num-prompts 8 \
  --profile \
  --profile-output-dir <output_dir>
```

### 关键参数
- `--random-output-len 20`: decode步数设为20
- `--profile`: 启用profiling
- `--profile-output-dir`: trace输出目录
- `--num-prompts`: 请求总数

## 输出文件

Profiling完成后在`--profile-output-dir`目录下生成:
- `*.json.gz` - Chrome trace格式的profiling数据

## 参考脚本
- `sglang-serve-example.sh` (本skill目录下)
