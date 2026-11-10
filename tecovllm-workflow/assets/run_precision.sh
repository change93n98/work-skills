#!/usr/bin/env bash
set -eu

mode=${1:?需要 humaneval、mmmu_pro 或 submission}
server=${2:?需要服务地址 host:port}
model=${3:?需要 served-model-name}
max_seq_len=${4:?需要服务的最大序列长度}
run_dir=${5:?需要任务输出目录的绝对路径}

case "$mode" in
  humaneval|mmmu_pro) datasets=("$mode") ;;
  submission) datasets=(longbench_v2 tool_bench mvbench) ;;
  *) printf '精度方案可选 humaneval、mmmu_pro 或 submission\n' >&2; exit 2 ;;
esac

mkdir -p "$run_dir/log_eval" "$run_dir/results"
result=0
for dataset in "${datasets[@]}"; do
  printf '评测 %s\n' "$dataset"
  python -u vllm_precision.py \
    --server_ip_port "$server" \
    --model_name "$model" \
    --dataset "$dataset" --priority p0 \
    --max_seq_len "$max_seq_len" \
    --output_dir "$run_dir/results/$dataset" > "$run_dir/log_eval/$dataset.log" 2>&1 || {
      result=$?
      printf '评测 %s 退出码 %s，日志 %s\n' "$dataset" "$result" "$run_dir/log_eval/$dataset.log" >&2
    }
done
exit "$result"
