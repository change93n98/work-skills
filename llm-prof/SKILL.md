---
name: llm-prof
description: >
  大模型推理profiling分析。启动vLLM/SGLang服务，执行bench profiling，分析trace输出prefill和decode算子耗时汇总表。
  也支持直接分析已有的trace文件（快速模式）。
  触发词：prof分析、profiling、算子耗时、推理性能、trace分析、分析trace。
---

# LLM Prof - 大模型推理算子耗时分析

## 必须收集的参数

开始前确认以下信息，缺什么问什么：

| 参数 | 说明 | 示例 |
|------|------|------|
| 推理框架 | vllm 或 sglang | vllm |
| 模型路径 | 模型权重目录 | /module/Qwen3-32B-fp8 |
| 并行方案 | TP/PP/DP | tp=4, pp=1 |
| 并发数 | max-concurrency | 24 |
| 输入长度 | random-input-len | 4000 |
| 输出长度 | random-output-len | 20（建议20，避免prof文件过大） |
| 运行目录 | 存放日志和prof文件的目录 | /home/client/aliyun/prof/qwen3-32b-0519 |

**多模态模型额外参数**（Qwen2.5-VL、InternVL 等视觉语言模型需要）：

| 参数 | 说明 | 示例 |
|------|------|------|
| 多模态类型 | image / video | image |
| 每请求图片数 | 每个请求输入的图片数量 | 10 |
| 图片分辨率 | (H, W, 帧数) | (480, 854, 1) |
| max_pixels | mm-processor-kwargs 中的图片像素上限 | 409920 |

运行目录用于存放本次运行的所有产出物，便于后续回溯：
```
<运行目录>/
├── serve.sh            # 服务启动脚本（可独立复用）
├── serve_config.txt    # 环境变量+启动命令
├── serve.log           # 服务端日志
├── serve.pid           # 服务进程ID
├── bench.log           # bench客户端日志
└── *.json.gz           # prof trace文件
```

## 环境：海光DCU（ROCm）

- 设备: `HIP_VISIBLE_DEVICES`
- 通信: RCCL
- blas: hipBLASLt

## Step 0: 查找空闲卡

启动服务前必须先确认有空闲卡，VRAM和HCU占用都为0：

```bash
hy-smi
```

输出示例：
```
HCU     Temp     AvgPwr     VRAM%      HCU%
0       40.0C    158.0W     0%         0.0%     ← 空闲
1       38.0C    160.0W     0%         0.0%     ← 空闲
6       41.0C    160.0W     91%        0.0%     ← 显存占用，不可用
```

选择VRAM%和HCU%都为0的卡，设置 `HIP_VISIBLE_DEVICES`。
如果TP>1，需要选多张连续空闲卡，如 `export HIP_VISIBLE_DEVICES=0,1,2,3`。

## Step 1: 创建运行目录并检查端口

创建运行目录，所有产出物统一存放：

```bash
RUN_DIR="<运行目录>"
mkdir -p "$RUN_DIR"
```

检查默认端口是否被占用，被占用则换一个空闲端口：

```bash
# vLLM默认8000，SGLang默认30000
DEFAULT_PORT=<默认端口>
if ss -tlnp | grep -q ":${DEFAULT_PORT} "; then
    # 找一个空闲端口
    PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('',0)); print(s.getsockname()[1]); s.close()")
    echo "端口 $DEFAULT_PORT 被占用，使用空闲端口: $PORT"
else
    PORT=$DEFAULT_PORT
    echo "端口 $PORT 可用"
fi
```

## Step 2: 启动服务

### vLLM

参考: `references/vllm-serve-example.sh`、`references/vllm-serve-h.log`

先将启动脚本写入运行目录，再执行：

```bash
# 纯文本模型
cat > "$RUN_DIR/serve.sh" << 'SCRIPT'
#!/bin/bash
set -euo pipefail

export HIP_VISIBLE_DEVICES=<gpu_ids>
export HSA_FORCE_FINE_GRAIN_PCIE=1
export NCCL_MAX_NCHANNELS=16
export NCCL_MIN_NCHANNELS=16
export ALLREDUCE_STREAM_WITH_COMPUTE=1
export VLLM_USE_PIECEWISE=0
export HIP_ALLOC_INITIALIZE=0
export GPU_MAX_HW_QUEUES=3
export VLLM_TORCH_PROFILER_DIR="$(dirname "$0")/prof"

vllm serve <model_path> \
    -tp <tp> -pp <pp> \
    --port <port> \
    --dtype auto \
    --kv-cache-dtype fp8_e4m3 \
    --profiler-config "{\"profiler\": \"torch\", \"torch_profiler_dir\": \"$(dirname "$0")/prof\", \"torch_profiler_with_stack\": true, \"torch_profiler_record_shapes\": true}"
SCRIPT
chmod +x "$RUN_DIR/serve.sh"
bash "$RUN_DIR/serve.sh" > "$RUN_DIR/serve.log" 2>&1 &
echo $! > "$RUN_DIR/serve.pid"

# 多模态模型（如 Qwen2.5-VL）额外需要：
cat > "$RUN_DIR/serve.sh" << 'SCRIPT'
#!/bin/bash
set -euo pipefail

export HIP_VISIBLE_DEVICES=<gpu_ids>
export HSA_FORCE_FINE_GRAIN_PCIE=1
export NCCL_MAX_NCHANNELS=16
export NCCL_MIN_NCHANNELS=16
export ALLREDUCE_STREAM_WITH_COMPUTE=1
export VLLM_USE_PIECEWISE=0
export HIP_ALLOC_INITIALIZE=0
export GPU_MAX_HW_QUEUES=3
export VLLM_TORCH_PROFILER_DIR="$(dirname "$0")/prof"

vllm serve <model_path> \
    -tp <tp> -pp <pp> \
    --port <port> \
    --no-enable-prefix-caching \
    --enable-chunked-prefill \
    --limit-mm-per-prompt '{"image": <n_image>, "video": 0}' \
    --mm-processor-kwargs '{"max_pixels": <max_pixels>}' \
    --profiler-config "{\"profiler\": \"torch\", \"torch_profiler_dir\": \"$(dirname "$0")/prof\", \"torch_profiler_with_stack\": true, \"torch_profiler_record_shapes\": true}"
SCRIPT
chmod +x "$RUN_DIR/serve.sh"
bash "$RUN_DIR/serve.sh" > "$RUN_DIR/serve.log" 2>&1 &
echo $! > "$RUN_DIR/serve.pid"
```

### SGLang

参考: `references/sglang-serve-example.sh`、`references/sgl-serve-h.log`

```bash
cat > "$RUN_DIR/serve.sh" << 'SCRIPT'
#!/bin/bash
set -euo pipefail

export HIP_VISIBLE_DEVICES=<gpu_ids>
export SGLANG_ENABLE_SPEC_V2=1
export USE_DCU_CUSTOM_ALLREDUCE=1
export ALLREDUCE_STREAM_WITH_COMPUTE=1
export SGLANG_KV_LAYOUT_DCU_FA=1
export SGLANG_USE_LIGHTOP=1
export SGLANG_USE_FP8_W8A8_MOE=1

sglang serve \
    --model-path <model_path> \
    --host 0.0.0.0 --port <port> \
    --trust-remote-code --dtype bfloat16 \
    --kv-cache fp8_e4m3 \
    --tp-size <tp> --pp-size <pp> \
    --mem-fraction-static 0.85 \
    --attention-backend fa3 \
    --page-size 64 \
    --cuda-graph-max-bs 512
SCRIPT
chmod +x "$RUN_DIR/serve.sh"
bash "$RUN_DIR/serve.sh" > "$RUN_DIR/serve.log" 2>&1 &
echo $! > "$RUN_DIR/serve.pid"
```

启动后保存配置到运行目录：

```bash
cat > "$RUN_DIR/serve_config.txt" << EOF
Framework: <vllm|sglang>
Model: <model_path>
TP: <tp>, PP: <pp>
Port: $PORT
GPU: $HIP_VISIBLE_DEVICES
Concurrency: <concurrency>
Input len: <input_len>
Output len: <output_len>
Multimodal: <yes|no>
  Type: <image|video>
  Items per request: <n>
  Resolution: <H>x<W>x<frames>
  max_pixels: <max_pixels>
Timestamp: $(date '+%Y-%m-%d %H:%M:%S')
EOF
```

## Step 3: 验证服务

```bash
curl -s http://localhost:$PORT/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "<model>", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 10}'
```

确认正常返回后继续。

## Step 4: 执行Profiling

### vLLM

参考: `references/vllm-bench-h.log`

**纯文本模型：**
```bash
vllm bench serve \
  --backend openai-chat \
  --model <model_path> \
  --endpoint /v1/chat/completions \
  --dataset-name random \
  --num-prompts <concurrency> \
  --max-concurrency <concurrency> \
  --random-input-len <input_len> \
  --random-output-len <output_len> \
  --ignore-eos --profile --port $PORT \
  > "$RUN_DIR/bench.log" 2>&1
```

**多模态模型（如 Qwen2.5-VL）：**
```bash
vllm bench serve \
  --backend openai-chat \
  --model <model_path> \
  --endpoint /v1/chat/completions \
  --dataset-name random-mm \
  --num-prompts <concurrency> \
  --max-concurrency <concurrency> \
  --random-input-len <input_len> \
  --random-output-len <output_len> \
  --random-mm-base-items-per-request <n_image> \
  --random-mm-limit-mm-per-prompt '{"image": <n_image>, "video": 0}' \
  --random-mm-bucket-config '{(<H>, <W>, 1): 1.0}' \
  --ignore-eos --profile --port $PORT \
  > "$RUN_DIR/bench.log" 2>&1
```

多模态参数说明：
- `--dataset-name random-mm`：使用随机多模态数据集
- `--random-mm-base-items-per-request`：每请求的图片/视频基准数量
- `--random-mm-limit-mm-per-prompt`：每请求多模态数量上限，格式同 serve 的 `--limit-mm-per-prompt`
- `--random-mm-bucket-config`：图片/视频分辨率桶配置，key 为 `(H, W, 帧数)`，value 为采样概率（需归一化）

### SGLang

参考: `references/sgl-bench-h.log`

```bash
python -m sglang.bench_serving \
  --backend sglang \
  --model <model_path> \
  --host localhost --port $PORT \
  --dataset-name random \
  --random-range-ratio 1 \
  --random-input-len <input_len> \
  --random-output-len <output_len> \
  --num-prompts <concurrency> \
  --profile --profile-output-dir "$RUN_DIR/prof" \
  > "$RUN_DIR/bench.log" 2>&1
```

## Step 5: 分析Trace

Profiling生成 `.pt.trace.json.gz` 或 `.json.gz`，在运行目录中找到并分析：

```bash
# 找到trace文件
TRACE_FILE=$(find "$RUN_DIR" -name "*.json.gz" -newer "$RUN_DIR/serve_config.txt" | head -1)

# 运行分析，结果也输出到运行目录
python3 scripts/prof_analyze.py --trace-file "$TRACE_FILE" --output-dir "$RUN_DIR" --verbose
```

分析完成后运行目录结构：
```
$RUN_DIR/
├── serve.sh                   # 服务启动脚本（可独立复用）
├── serve_config.txt           # 启动配置
├── serve.log                  # 服务端日志
├── serve.pid                  # 服务进程ID
├── bench.log                  # bench客户端日志
├── prof/                      # prof trace文件
│   └── *.json.gz
├── prof_analysis.xlsx         # 分析报告（4个子表）
├── prof_analysis_summary.txt  # 文本摘要
└── prof_analysis.json         # JSON结果
```

分析逻辑：
- 通过 `model_forward` slice划分阶段：自动检测慢/快step分界（最后一个>100ms的gap）
  - Prefill = trace开始 → 第一个快step开始（包含warmup gap）
  - Decode step N = 快step阶段的第N个step（正向索引，默认N=2）
- 算子分六类：gemm、通信、FlashAttention、Triton、其他elementwise、memcpy/memset

### XLSX输出（4个子表）

| Sheet | 内容 | 列 |
|-------|------|-----|
| Prefill详细算子 | 每个kernel的耗时明细 | 算子名称、分类、调用次数、总耗时(us)、平均耗时(us)、相对占比(%)、绝对占比(%) |
| Prefill分类汇总 | 按6大类汇总 | 分类、算子种类数、调用次数、总耗时(us)、总耗时(ms)、相对占比(%) |
| Decode-Step2详细算子 | 每个kernel的耗时明细 | 同上 |
| Decode-Step2分类汇总 | 按6大类汇总 | 同上 |

**相对占比**: 占所有kernel总耗时的百分比（不含空泡）
**绝对占比**: 占该阶段时间窗口的百分比（含空泡/GPU idle）

依赖: `pip install openpyxl`

## 输出示例

```
============================================================
  Prefill阶段算子耗时分析
============================================================
类别                  总耗时(ms)    调用次数    占比(%)
------------------------------------------------------------
gemm                      50.02        591     44.37%
通信 (comm)                 0.00          0      0.00%
FlashAttention (fa)        4.95          8      4.39%
Triton                    17.73        489     15.72%
其他elementwise            40.05        200     35.52%
memcpy/memset               0.00          0      0.00%
------------------------------------------------------------
总计                      112.74       1288    100.00%
============================================================

============================================================
  Decode阶段算子耗时分析 (Step 2)
============================================================
类别                  总耗时(ms)    调用次数    占比(%)
------------------------------------------------------------
gemm                       6.83         85     88.62%
通信 (comm)                 0.00          0      0.00%
FlashAttention (fa)        0.00          0      0.00%
Triton                      0.44         72      5.73%
其他elementwise              0.44         36      5.65%
memcpy/memset               0.00          0      0.00%
------------------------------------------------------------
总计                        7.70        193    100.00%
============================================================
```

## 快速模式：仅分析已有Trace文件

如果已经有trace文件（`.json.gz`或`.pt.trace.json.gz`），直接跳过前面所有步骤：

**需要的信息：**
- trace文件路径
- 输出目录（可选，默认与trace同目录）
- decode step编号（可选，默认2，指快decode阶段的第2个step）

**执行：**
```bash
python3 scripts/prof_analyze.py \
  --trace-file <trace.json.gz> \
  --output-dir <output_dir> \
  --decode-step 2 \
  --verbose
```

输出：
- `<output_dir>/prof_analysis.xlsx` — 4个子表的Excel报告
- `<output_dir>/prof_analysis_summary.txt` — 文本摘要
- `<output_dir>/prof_analysis.json` — JSON结果

## 参考文件（`references/`目录）

- `vllm-serve-h.log` / `sgl-serve-h.log` — serve参数帮助
- `vllm-bench-h.log` / `sgl-bench-h.log` — bench参数帮助
- `vllm-serve-example.sh` / `sglang-serve-example.sh` — 启动脚本示例
- `vllm-prof-guide.md` / `sglang-prof-guide.md` — profiling指南
- `prof算子耗时占比分析.pdf` — 分析原理
- `perfetto-sql-py工具.pdf` — Perfetto SQL工具
