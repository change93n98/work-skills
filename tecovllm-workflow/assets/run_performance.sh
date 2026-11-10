#!/usr/bin/env bash
set -eu

server=${1:?需要服务地址 host:port}
model=${2:?需要 served-model-name}
tokenizer=${3:?需要 tokenizer 路径}
run_dir=${4:?需要任务输出目录的绝对路径}

# 纯文本示例。复制后按本次测试修改长度、BS、请求数和模型类型。
output_len=1024
for input_len in 1024 4096; do
  for batch in 1 32; do
    case_dir="$run_dir/formal/in${input_len}_out${output_len}_bs${batch}"
    mkdir -p "$case_dir"
    printf '运行 %s\n' "$case_dir"
    python -u vllm_requests.py \
      --server_ip_port "$server" \
      --model_name "$model" \
      --tokenizer_path "$tokenizer" \
      --model_type llm --batch "$batch" --request_nums "$batch" \
      --seqlen "$input_len,$output_len" \
      --output_dir "$case_dir" > "$case_dir/client.log" 2>&1
  done
done
