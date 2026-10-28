#!/bin/bash
# Run the whole script with nohup for background execution.
# LongBench v2 -> ToolBench -> MVBench, sequentially on one service.
source /root/miniconda3/etc/profile.d/conda.sh || exit 1
# Match this environment to the EvalScope version required by the checkout.
conda activate evalscope_py312_1_11_1 || exit 1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TS="$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)_$$"
mkdir -p "$SCRIPT_DIR/log_eval" "$SCRIPT_DIR/results" || exit 1
cd /data/application/changhl/work/35b-opt/teco-modeltest/lm_infer/unit || exit 1

# LongBench v2: full dataset.
nohup python vllm_precision.py \
  --server_ip_port 0.0.0.0:8031 --model_name Qwen3.6-35B-A3B \
  --dataset longbench_v2 --priority p0 --max_seq_len 262144 \
  --output_dir "$SCRIPT_DIR/results/Qwen3.6-35B-A3B_mtp1_${TS}/longbench_v2" \
  > "$SCRIPT_DIR/log_eval/longbench_v2_${TS}.log" 2>&1 < /dev/null

# ToolBench: run after LongBench exits.
nohup python vllm_precision.py \
  --server_ip_port 0.0.0.0:8031 --model_name Qwen3.6-35B-A3B \
  --dataset tool_bench --priority p0 --max_seq_len 262144 \
  --output_dir "$SCRIPT_DIR/results/Qwen3.6-35B-A3B_mtp1_${TS}/tool_bench" \
  > "$SCRIPT_DIR/log_eval/tool_bench_${TS}.log" 2>&1 < /dev/null

# MVBench: run after ToolBench exits; p0 selects 1000 samples in total.
nohup python vllm_precision.py \
  --server_ip_port 0.0.0.0:8031 --model_name Qwen3.6-35B-A3B \
  --dataset mvbench --priority p0 --max_seq_len 262144 \
  --output_dir "$SCRIPT_DIR/results/Qwen3.6-35B-A3B_mtp1_${TS}/mvbench" \
  > "$SCRIPT_DIR/log_eval/mvbench_${TS}.log" 2>&1 < /dev/null
