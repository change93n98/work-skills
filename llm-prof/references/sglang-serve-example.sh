#!/bin/bash

# Model config
export HIP_VISIBLE_DEVICES=0,1,2,3,4,5,6,7
# export HIP_VISIBLE_DEVICES=4,5,6,7
model_path=/module/Qwen3.5-397B-A17B-Channel-FP8
model=${model_path##*/}
tp=4
pp=1
dp=2

# Network config
host_ip=$(hostname -I | awk '{print $1}')
hostname=$(hostname)
master_ip=$host_ip

# Log config
logpath="/home/client/aliyun/public/shells/server-log/260511/$model-tp$tp-dp$dp-$hostname"
if [ ! -d ${logpath} ]; then
    mkdir -p ${logpath}
fi
time=$(date "+%m%d-%H%M")

echo "---- Current Env Variables Setup ------"
env_vars=(
    # NCCL settings
    "NCCL_MIN_NCHANNELS=16"
    "NCCL_MAX_NCHANNELS=16"
    
    # Core settings
    "SGLANG_ENABLE_SPEC_V2=1"
    "HSA_ENABLE_COREDUMP=1"
    "USE_DCU_CUSTOM_ALLREDUCE=1" # default using vllm allreduce, if set to 1, ALLREDUCE_STREAM_WITH_COMPUTE has to be set to 1, optimize for graph mode
    "ALLREDUCE_STREAM_WITH_COMPUTE"
    "HIP_KERNEL_EVENT_SYSTENFENCE=1" # default using vllm allreduce, optimize for egar mode
    "SGL_CHUNKED_PREFIX_CACHE_THRESHOLD=0" # default stay
    "GLIBC_TUNABLES=glibc.rtld.optional_static_tls=0x40000" # default stay
    "HIP_KERNEL_BATCH_CEILING=100" # default stay
    "GPU_FORCE_BLIT_COPY_SIZE=16" # default stay
    "HSA_KERNARG_POOL_SIZE=8388608" # default stay
    "ROC_AQL_QUEUE_SIZE=131072" # default stay
    "SGLANG_KV_LAYOUT_DCU_FA=1" # default enable, using optimized PA layout
    
    # Lightop kernels
    "SGLANG_USE_LIGHTOP=1" # enable lightop rope and topk kernel
    "SGLANG_USE_FP8_W8A8_MOE=1" # using lightop fp8 moe kernel
    "SGLANG_USE_FUSED_TOPK_SOFTMAX=1" # Specially for topk of Qwen-model and bailing

    "SGLANG_USE_CAUSAL_CONV1D=1"
    "SGLANG_USE_AITER_LINEAR_ATTN=1"
  )

for kv in "${env_vars[@]}"; do
    export "$kv"
    echo "export $kv"
done

sysctl -w kernel.numa_balancing=0

echo "---- Current Running Cmd ------"
DEFAULT_ARGS=(
    --model-path $model_path
    --host 0.0.0.0
    --port 30001
    --trust-remote-code
    --dtype bfloat16
    --kv-cache fp8_e4m3
    --tp-size $tp
    --pp-size $pp
    --dp-size $dp
    --mem-fraction-static 0.85
    --attention-backend fa3
    --page-size 64
    --disable-radix-cache
    --cuda-graph-max-bs 512
)

FINAL_ARGS=("${DEFAULT_ARGS[@]}")

# Print command
printf '%s\n' "sglang serve \\"
i=0
while [[ $i -lt ${#FINAL_ARGS[@]} ]]; do
  arg="${FINAL_ARGS[$i]}"
  if [[ "$arg" == --* ]]; then
    next=$((i + 1))
    if [[ $next -lt ${#FINAL_ARGS[@]} && "${FINAL_ARGS[$next]}" != --* ]]; then
      printf '  %s %s \\\n' "$arg" "${FINAL_ARGS[$next]}"
      i=$((i + 2))
    else
      printf '  %s \\\n' "$arg"
      i=$((i + 1))
    fi
  else
    printf '  %s \\\n' "$arg"
    i=$((i + 1))
  fi
done
printf '%s\n' " > ${logpath}/$time.log 2>&1"
printf '%s\n' "--------------------------------"

# Start server
sglang serve "${FINAL_ARGS[@]}" > ${logpath}/$time.log 2>&1
