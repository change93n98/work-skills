#!/bin/bash
# Quick profiling script for vLLM/SGLang on DCU
# Usage: ./quick_prof.sh <framework> <model_path> [port] [num_prompts] [input_len]
# Example: ./quick_prof.sh vllm /path/to/model 8000 24 4000

set -e

FRAMEWORK=${1:? "Usage: $0 <vllm|sglang> <model_path> [port] [num_prompts] [input_len]"}
MODEL_PATH=${2:? "Please provide model path"}
PORT=${3:-8000}
NUM_PROMPTS=${4:-24}
INPUT_LEN=${5:-4000}
OUTPUT_LEN=20
TIMESTAMP=$(date +%y%m%d_%H%M%S)
MODEL_NAME=$(basename "$MODEL_PATH")
PROF_DIR="${PROF_OUTPUT_DIR:-./prof}/${FRAMEWORK}-${MODEL_NAME}-${TIMESTAMP}"

mkdir -p "$PROF_DIR"

echo "=========================================="
echo "  Profiling Configuration"
echo "=========================================="
echo "Framework: $FRAMEWORK"
echo "Model: $MODEL_PATH"
echo "Port: $PORT"
echo "Num prompts: $NUM_PROMPTS"
echo "Input len: $INPUT_LEN"
echo "Output len: $OUTPUT_LEN"
echo "Prof dir: $PROF_DIR"
echo "=========================================="

# Save config
cat > "$PROF_DIR/serve_config.txt" << EOF
Framework: $FRAMEWORK
Model: $MODEL_PATH
Port: $PORT
Num prompts: $NUM_PROMPTS
Input len: $INPUT_LEN
Output len: $OUTPUT_LEN
Timestamp: $TIMESTAMP
EOF

# Common env
export HIP_VISIBLE_DEVICES=${HIP_VISIBLE_DEVICES:-0}
export HSA_FORCE_FINE_GRAIN_PCIE=1
export NCCL_MAX_NCHANNELS=16
export NCCL_MIN_NCHANNELS=16

if [ "$FRAMEWORK" = "vllm" ]; then
    # vLLM specific env
    export ALLREDUCE_STREAM_WITH_COMPUTE=1
    export VLLM_USE_PIECEWISE=0
    export HIP_ALLOC_INITIALIZE=0
    export GPU_MAX_HW_QUEUES=3

    echo "[1/4] Starting vLLM serve..."
    vllm serve "$MODEL_PATH" \
        --port "$PORT" \
        --dtype auto \
        --kv-cache-dtype fp8_e4m3 \
        --profiler-config "{\"profiler\": \"torch\", \"torch_profiler_dir\": \"$PROF_DIR\", \"torch_profiler_with_stack\": true, \"torch_profiler_record_shapes\": true}" \
        > "$PROF_DIR/serve.log" 2>&1 &
    SERVER_PID=$!

elif [ "$FRAMEWORK" = "sglang" ]; then
    # SGLang specific env
    export SGLANG_ENABLE_SPEC_V2=1
    export USE_DCU_CUSTOM_ALLREDUCE=1
    export ALLREDUCE_STREAM_WITH_COMPUTE=1
    export SGLANG_KV_LAYOUT_DCU_FA=1
    export SGLANG_USE_LIGHTOP=1
    export SGLANG_USE_FP8_W8A8_MOE=1

    echo "[1/4] Starting SGLang serve..."
    sglang serve \
        --model-path "$MODEL_PATH" \
        --host 0.0.0.0 \
        --port "$PORT" \
        --trust-remote-code \
        --dtype bfloat16 \
        --kv-cache fp8_e4m3 \
        --mem-fraction-static 0.85 \
        --attention-backend fa3 \
        --page-size 64 \
        --disable-radix-cache \
        --cuda-graph-max-bs 512 \
        > "$PROF_DIR/serve.log" 2>&1 &
    SERVER_PID=$!
else
    echo "Unknown framework: $FRAMEWORK (use 'vllm' or 'sglang')"
    exit 1
fi

echo "Server PID: $SERVER_PID"
echo "$SERVER_PID" > "$PROF_DIR/server.pid"

# Wait for server
echo "[2/4] Waiting for server to be ready..."
for i in $(seq 1 120); do
    if curl -s "http://localhost:$PORT/v1/models" > /dev/null 2>&1; then
        echo "Server ready after ${i}s"
        break
    fi
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo "ERROR: Server process died. Check $PROF_DIR/serve.log"
        exit 1
    fi
    sleep 2
done

# Verify
echo "[3/4] Verifying service..."
RESPONSE=$(curl -s "http://localhost:$PORT/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d "{
        \"model\": \"$MODEL_NAME\",
        \"messages\": [{\"role\": \"user\", \"content\": \"Hello\"}],
        \"max_tokens\": 10
    }")

if echo "$RESPONSE" | grep -q "choices"; then
    echo "Service verification passed"
    echo "$RESPONSE" > "$PROF_DIR/verify_response.json"
else
    echo "WARNING: Service verification may have issues"
    echo "$RESPONSE" > "$PROF_DIR/verify_response.json"
fi

# Run profiling
echo "[4/4] Running profiling..."
if [ "$FRAMEWORK" = "vllm" ]; then
    vllm bench serve \
        --model "$MODEL_PATH" \
        --dataset-name random \
        --num-prompts "$NUM_PROMPTS" \
        --max-concurrency "$NUM_PROMPTS" \
        --random-input-len "$INPUT_LEN" \
        --random-output-len "$OUTPUT_LEN" \
        --profile \
        --trust-remote-code \
        --port "$PORT" \
        > "$PROF_DIR/bench.log" 2>&1
elif [ "$FRAMEWORK" = "sglang" ]; then
    python -m sglang.bench_serving \
        --backend sglang \
        --model "$MODEL_PATH" \
        --host localhost \
        --port "$PORT" \
        --dataset-name random \
        --random-range-ratio 1 \
        --random-input-len "$INPUT_LEN" \
        --random-output-len "$OUTPUT_LEN" \
        --num-prompts "$NUM_PROMPTS" \
        --profile \
        --profile-output-dir "$PROF_DIR" \
        > "$PROF_DIR/bench.log" 2>&1
fi

echo "=========================================="
echo "  Profiling complete!"
echo "  Output directory: $PROF_DIR"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Find trace file: find $PROF_DIR -name '*.json.gz'"
echo "  2. Run analysis: python3 $(dirname "$0")/prof_analyze.py --trace-file <trace_file>"
echo ""

# Cleanup server
if [ -f "$PROF_DIR/server.pid" ]; then
    kill $(cat "$PROF_DIR/server.pid") 2>/dev/null || true
fi
