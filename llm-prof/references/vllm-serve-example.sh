# export CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7
# export CUDA_VISIBLE_DEVICES=7
export HIP_VISIBLE_DEVICES=7
export HSA_FORCE_FINE_GRAIN_PCIE=1
export NCCL_MAX_NCHANNELS=16
export NCCL_MIN_NCHANNELS=16
export NCCL_P2P_LEVEL=SYS
export NCCL_LAUNCH_MODE=GROUP
export ALLREDUCE_STREAM_WITH_COMPUTE=1
# export ROCBLAS_COMPUTETYPE_FP16R=0

export VLLM_RPC_TIMEOUT=1800000

# 零消耗
export VLLM_ZERO_OVERHEAD=1
export VLLM_ZERO_NO_THREAD=1
# tbo
export VLLM_ENABLE_TBO=1
export VLLM_TBO_REQ_DELAY_MS=100
# NUMA
export VLLM_NUMA_BIND=1
export VLLM_RANK0_NUMA=3
export VLLM_RANK1_NUMA=1
export VLLM_RANK2_NUMA=1
export VLLM_RANK3_NUMA=0
export VLLM_RANK4_NUMA=7
export VLLM_RANK5_NUMA=5
export VLLM_RANK6_NUMA=5
export VLLM_RANK7_NUMA=4

# export VLLM_USE_FUSED_RMS_ROPE=0
#prof
# export VLLM_TORCH_PROFILER_DIR=./prof/qwen35-397b
# export ROCBLAS_TENSILE_GEMM_OVERRIDE_PATH=/home/client/aliyun/rocblas-25042-gemm-tune/qwen3-14b.log

model_path=/home/client/aliyun/quant/Qwen3-32B-channelwise-fp8
data_type="bfloat16"
tp=1
pp=1
dp=1
ep=1
# request_rate=3

# gemm
# export ROCBLAS_LAYER=4
# export ROCBLAS_LOG_PROFILE_PATH=./qwen3-32b-tp1-gemmsize.log

# blaslt
# export HIPBLASLT_LOG_MASK=32 
# export HIPBLASLT_LOG_FILE=./hipblaslt-32b-tp1.log
# export HIPBLASLT_LOG_LEVEL=4
# export HIPBLASLT_TUNING_OVERRIDE_FILE=/home/client/aliyun/public/shells/vllm/hipblaslt-32b-tp1.config
export LD_LIBRARY_PATH=/home/client/aliyun/public/shells/vllm/hipblaslt-install/lib:$LD_LIBRARY_PATH
export VLLM_USE_PIECEWISE=0
export HIP_ALLOC_INITIALIZE=0
export GPU_MAX_HW_QUEUES=3


vllm serve ${model_path} \
    -tp $tp \
    -pp $pp \
    --no-enable-prefix-caching \
    --enable-chunked-prefill \
    -q slimquant_marlin \
    --dtype auto \
    --kv-cache-dtype fp8_e4m3 \
    --port 8000 \
    --profiler-config '{"profiler": "torch", "torch_profiler_dir": "/home/client/aliyun/public/prof/260518/32b-tp1", "torch_profiler_with_stack": true, "torch_profiler_record_shapes": true}' > /home/client/aliyun/public/shells/server-log/260519/qwen3-32b-fp8-tp1.log 2>&1