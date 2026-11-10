#!/usr/bin/env bash
set -eu

server=${1:?需要服务地址 host:port}
model=${2:?需要 served-model-name}
tokenizer=${3:?需要 tokenizer 路径}
run_dir=${4:?需要任务输出目录的绝对路径}

mkdir -p "$run_dir/warmup"
exec python -u vllm_requests.py \
  --server_ip_port "$server" \
  --model_name "$model" \
  --tokenizer_path "$tokenizer" \
  --model_type mllm --batch 1 --request_nums 1 \
  --seqlen 1024,1024 --image_size '4096*4096*1' \
  --output_dir "$run_dir/warmup" > "$run_dir/warmup/client.log" 2>&1
