# 抓取 prof 与自动阶段分析

仅模式 1 或用户明确要求自动识别阶段时读取；已有 XLSX 或指定时间窗口不需要补齐启动服务参数。

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

如果 decode 使用 CUDA/HIP/SDAA graph，且需要 CPU 算子或 Python 来源，读取 [graph 双 trace 流程](graph-source-mapping.md)，使用 `scripts/prof_graph_analyze.py`。先采集 graph-off 建立来源映射，再采集真实 graph-on replay 统计设备耗时；单份 graph-on trace 的 `with_stack` 不能恢复未执行的逐算子 host 调用链。需要确认两次运行的配置、实际 graph 开关、阶段窗口及 rank/设备一致。

```bash
python3 scripts/prof_graph_analyze.py \
  --mapping-trace <graph-off-decode.json.gz> \
  --formal-trace <graph-on-decode.json.gz> \
  --stage decode --output-dir <output_dir>
```

这个入口只从 graph-on 的明确设备事件取 dur，不把 cpu_op 当设备耗时；不依赖 model_forward 阶段标记。输出 JSON/CSV/文本及可选 XLSX，标记 `match_basis`、每个候选的 `attribution_basis`、`source_status`、`ambiguity_reasons`。多来源不强选唯一位置，无法关联则保留未知。跨 trace 只按完整/有限规范化符号匹配，不使用两次运行的关联 ID；类别仍按名字分类。详细采集、国产卡后端开关验证、窗口选择和配置审计见上述参考。

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
- dense 算子分原六类：gemm、通信、FlashAttention、Triton、其他elementwise、memcpy/memset；MoE 专家矩阵乘另列 group gemm。旧 JSON 分析器按名字分类，通用符号的专家角色需要 native window/step 调用关联确认。
- 分类兼容 DCU、NVIDIA 和太初 T100；T100 的 `WAIT` 运行时等待标记不计入 kernel busy time，而计入 bubble/idle
- 分类规则同时输出 `classification_rule`；`fallback:unknown` 必须通过 audit 脚本检查，不允许静默认为分类正确
- 明细保留 `semantic_type`、`classification_confidence`、`classification_ambiguity` 和候选类别；“其他elementwise”是兼容桶，不等于全部逐元素。FFN 融合 GEMM 与激活 helper 分开。已由单设备纯矩阵乘实测确认的 TecoBLAS NN/NT fp16 allReduce 归 GEMM；未验证变体仍报告 unknown，不能按 allReduce 字样认定通信。

### XLSX输出（4个子表）

| Sheet | 内容 | 列 |
|-------|------|-----|
| Prefill详细算子 | 每个kernel的耗时明细 | 算子名称、分类、分类规则、调用次数、总耗时(us)、平均耗时(us)、相对占比(%)、绝对占比(%) |
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

## 分类审计（推荐在新硬件/新版本上执行）

先审计，再把汇总表用于性能结论：

```bash
python3 scripts/audit_kernel_categories.py \
  <trace.json.gz 或 kernel明细.xlsx> \
  --output kernel_classification_audit.json
```

审计报告按分类规则统计调用次数和耗时，并列出 `fallback:unknown` 的 kernel。
新硬件的完成标准不是“所有名字都命中某个字符串”，而是：

1. 通信、内存、attention、GEMM 等高影响类别没有明显语义冲突；
2. fallback 未知项按耗时从高到低人工检查；
3. 对新增稳定算子模式补充回归测试；
4. 重新运行真实 trace，确认 kernel 总耗时守恒，WAIT/profiler marker 不进入 busy kernel。

`--fail-on-fallback` 只适合规则收敛阶段；未知 kernel 在探索新平台时可以先报告、再确认，不能直接把 fallback 当作正确证据。

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
