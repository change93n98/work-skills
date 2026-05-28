---
name: blaslt-compare
description: >
  hipBLASLt gemm 单测性能对比。
  从命令文件读取hipblaslt-bench命令，在指定GPU上分别执行基线和优化后的hipBLASLt库，自动采集GFLOPS、耗时和kernel名称，生成results.csv。
  触发词：blaslt对比、blaslt-compare、hipblaslt对比、blaslt测试、blaslt性能对比。
---

# BLASLt Compare - hipBLASLt GEMM 单测性能对比

## 必须收集的参数

开始前确认以下信息，缺什么问什么：

| 参数 | 说明 | 示例 |
|------|------|------|
| 命令文件路径 | 包含hipblaslt-bench命令的文件（每行一条命令） | /path/to/commands.sh |
| 优化后hipBLASLt库路径 | 自编译的hipblaslt .so 所在lib目录 | /path/to/hipblaslt-install/lib |
| 输出目录 | 存放日志和结果的目录 | /path/to/output/ |
| hipblaslt-bench路径 | benchmark可执行文件（默认 `/opt/dtk/lib/hipblaslt/benchmark_tool/hipblaslt-bench`） | /opt/dtk/lib/hipblaslt/benchmark_tool/hipblaslt-bench |

> GPU编号不需要用户指定，脚本会自动查找空闲卡。

## 命令文件输入格式

每行一条完整的 `hipblaslt-bench` 命令，示例：
```
hipblaslt-bench --api_method c -m 10240 -n 1 -k 8192 --lda 8192 --ldb 8192 --ldc 10240 --ldd 10240 --stride_a 0 --stride_b 0 --stride_c 0 --stride_d 0 --alpha 1.000000 --beta 0.000000 --transA T --transB N --batch_count 1 --scaleA 2 --scaleB 2 --bias_vector --bias_source d --a_type f8_r --b_type f8_r --c_type bf16_r --d_type bf16_r --scale_type f32_r --bias_type f16_r --compute_type f32_r --activation_type none
```

## hipblaslt-bench 输出格式

使用 `--print_kernel_info` 参数可获取 kernel 名称：

```
hipBLASLt version: 1000
...
[0]:transA,transB,grouped_gemm,batch_count,m,n,k,alpha,lda,stride_a,beta,ldb,stride_b,ldc,stride_c,ldd,stride_d,a_type,b_type,c_type,d_type,compute_type,scaleA,scaleB,scaleC,scaleD,amaxD,activation_type,bias_vector,bias_type,hipblaslt-Gflops,us
    T,N,0,1,128,1,128,1,128,16384,0,128,128,128,128,128,128,f8_r,f8_r,bf16_r,bf16_r,f32_r,2,2,0,0,0,none,0,f16_r,4.48877,7.3
    --Solution index: 4993
    --Solution name:  Cijk_Alik_Bljk_F8BS_MT16x16x64_TT2_2_WG8_8_1_MFWGS64_WGM1_bias_channelwise
    --kernel name:    Cijk_Alik_Bljk_F8BS_MT16x16x64_TT2_2_WG8_8_1_MFWGS64_WGM1_bias_channelwise
```

- 头部行以 `[0]:` 开头，后接逗号分隔的列名
- 数据行以空格开头，逗号分隔，最后两个字段为 `hipblaslt-Gflops` 和 `us`
- `--kernel name:` 行包含选定的 kernel 全称

## 输出目录结构

```
<输出目录>/
├── run_benchmarks.sh       # 执行脚本
├── results.csv             # 汇总结果（含kernel名称、GFLOPS、耗时、百分比）
└── logs/
    ├── baseline/           # 基线执行日志
    │   ├── line_1_m10240_n1_k8192.log
    │   └── ...
    └── optimized/          # 优化后执行日志
        ├── line_1_m10240_n1_k8192.log
        └── ...
```

## Step 0: 查找空闲卡并确认环境

Benchmark 单测只需一张空闲卡，自动查找 VRAM 和 HCU 占用都为 0 的卡：

```bash
hy-smi
```

输出示例：
```
HCU     Temp     AvgPwr     Perf     PwrCap     VRAM%      HCU%
0       38.0C    158.0W     manual   800.0W     0%         0.0%     ← 空闲
7       68.0C    560.0W     manual   800.0W     39%        100.0%   ← 不可用
```

选取第一张 VRAM% 和 HCU% 都为 0 的卡，记录 GPU 编号备用。

同时确认 benchmark 可执行文件和优化库存在：

```bash
# 检查benchmark可执行文件，若无权限则加
ls -la /opt/dtk/lib/hipblaslt/benchmark_tool/hipblaslt-bench || chmod +x /opt/dtk/lib/hipblaslt/benchmark_tool/hipblaslt-bench

# 检查优化库
ls <优化库路径>/libhipblaslt.so*
```

## Step 1: 创建执行脚本

在输出目录下创建 `run_benchmarks.sh`，脚本逻辑：

```bash
#!/bin/bash
set -euo pipefail

CMD_FILE="<命令文件路径>"
BENCH_BIN="/opt/dtk/lib/hipblaslt/benchmark_tool/hipblaslt-bench"
HIPBLASLT_OPT="<优化库路径>"
OUT_DIR="<输出目录>"
LOG_BASE="${OUT_DIR}/logs"
RESULT_FILE="${OUT_DIR}/results.csv"

# 自动查找空闲卡（VRAM% 和 HCU% 都为 0）
GPU_ID=$(hy-smi | awk 'NR>1 && $6=="0%" && $7=="0.0%" {print $1; exit}')
if [[ -z "$GPU_ID" ]]; then
    echo "ERROR: 没有找到空闲GPU，请检查 hy-smi 输出"
    exit 1
fi
echo "使用 GPU: $GPU_ID"

mkdir -p "${LOG_BASE}/baseline" "${LOG_BASE}/optimized"

# CSV header
echo "line,m,n,k,transA,transB,batch_count,a_type,b_type,c_type,d_type,compute_type,activation_type,bias_vector,scaleA,scaleB,baseline_kernel,baseline_gflops,baseline_us,optimized_kernel,optimized_gflops,optimized_us,gflops_pct,us_pct" > "${RESULT_FILE}"

LINE_NUM=0
while IFS= read -r raw_line; do
    [[ -z "${raw_line// /}" ]] && continue
    [[ "${raw_line}" =~ ^[[:space:]]*# ]] && continue
    LINE_NUM=$((LINE_NUM + 1))

    cmd="${raw_line}"

    # 解析参数
    m=$(echo "$cmd" | grep -oP '(?<=-m )\S+')
    n=$(echo "$cmd" | grep -oP '(?<=-n )\S+')
    k=$(echo "$cmd" | grep -oP '(?<=-k )\S+')
    transA=$(echo "$cmd" | grep -oP '(?<=--transA )\S+')
    transB=$(echo "$cmd" | grep -oP '(?<=--transB )\S+')
    batch_count=$(echo "$cmd" | grep -oP '(?<=--batch_count )\S+' || echo "1")
    a_type=$(echo "$cmd" | grep -oP '(?<=--a_type )\S+')
    b_type=$(echo "$cmd" | grep -oP '(?<=--b_type )\S+')
    c_type=$(echo "$cmd" | grep -oP '(?<=--c_type )\S+')
    d_type=$(echo "$cmd" | grep -oP '(?<=--d_type )\S+')
    compute_type=$(echo "$cmd" | grep -oP '(?<=--compute_type )\S+')
    activation_type=$(echo "$cmd" | grep -oP '(?<=--activation_type )\S+' || echo "none")
    bias_vector=$(echo "$cmd" | grep -qP '\-\-bias_vector' && echo "1" || echo "0")
    scaleA=$(echo "$cmd" | grep -oP '(?<=--scaleA )\S+' || echo "0")
    scaleB=$(echo "$cmd" | grep -oP '(?<=--scaleB )\S+' || echo "0")

    echo "[${LINE_NUM}] m=${m} n=${n} k=${k} transA=${transA} transB=${transB} batch=${batch_count} ${a_type}*${b_type}->${d_type}"

    # 替换 hipblaslt-bench 为完整路径，并加上 --print_kernel_info
    full_cmd=$(echo "$cmd" | sed "s|hipblaslt-bench|${BENCH_BIN} --print_kernel_info|g")

    # 从输出中提取 GFLOPS 和 us
    extract_perf() {
        local output="$1"
        local data_line=$(echo "$output" | grep -E '^\s+[A-Z],' | tail -1)
        if [[ -n "$data_line" ]]; then
            local gflops=$(echo "$data_line" | awk -F',' '{print $(NF-1)}' | tr -d ' ')
            local us=$(echo "$data_line" | awk -F',' '{print $NF}' | tr -d ' ')
            echo "${gflops} ${us}"
        else
            echo "N/A N/A"
        fi
    }

    # 从输出中提取 kernel 名称
    extract_kernel() {
        local output="$1"
        local kernel=$(echo "$output" | grep 'kernel name:' | tail -1 | sed 's/.*kernel name:\s*//' | awk '{print $1}')
        if [[ -z "$kernel" ]]; then
            kernel="N/A"
        fi
        echo "$kernel"
    }

    # 带重试的执行函数（处理集群限流）
    run_with_retry() {
        local log_file="$1"
        shift
        local max_retries=5
        local delay=3
        local attempt=1
        local output=""
        while [[ $attempt -le $max_retries ]]; do
            output=$(timeout 300 "$@" 2>&1) && break
            echo "$output" > "${log_file}"
            if echo "$output" | grep -qi "rate limit\|400\|Cluster"; then
                echo "    [RETRY ${attempt}/${max_retries}] 集群限流，等待 ${delay}s 后重试..."
                sleep $delay
                delay=$((delay * 2))
                attempt=$((attempt + 1))
            else
                break
            fi
        done
        echo "$output"
    }

    # 基线运行（不加载优化库）
    baseline_log="${LOG_BASE}/baseline/line_${LINE_NUM}_m${m}_n${n}_k${k}.log"
    baseline_output=$(HIP_VISIBLE_DEVICES=$GPU_ID run_with_retry "${baseline_log}" ${full_cmd}) || true
    echo "$baseline_output" > "${baseline_log}"
    read baseline_gflops baseline_us <<< $(extract_perf "$baseline_output")
    baseline_kernel=$(extract_kernel "$baseline_output")

    sleep 2

    # 优化后运行（加载优化库）
    optimized_log="${LOG_BASE}/optimized/line_${LINE_NUM}_m${m}_n${n}_k${k}.log"
    optimized_output=$(HIP_VISIBLE_DEVICES=$GPU_ID LD_LIBRARY_PATH="${HIPBLASLT_OPT}:${LD_LIBRARY_PATH:-}" run_with_retry "${optimized_log}" ${full_cmd}) || true
    echo "$optimized_output" > "${optimized_log}"
    read optimized_gflops optimized_us <<< $(extract_perf "$optimized_output")
    optimized_kernel=$(extract_kernel "$optimized_output")

    sleep 2

    # 计算百分比
    if [[ "$baseline_gflops" != "N/A" && "$optimized_gflops" != "N/A" ]]; then
        gflops_pct=$(python3 -c "print(f'{${optimized_gflops}/${baseline_gflops}*100:.2f}%')")
        us_pct=$(python3 -c "print(f'{${baseline_us}/${optimized_us}*100:.2f}%')")
    else
        gflops_pct="N/A"; us_pct="N/A"
    fi

    echo "  baseline=${baseline_gflops}GFLOPS/${baseline_us}us  optimized=${optimized_gflops}GFLOPS/${optimized_us}us  gflops=${gflops_pct}  us=${us_pct}"
    echo "  baseline_kernel=${baseline_kernel}  optimized_kernel=${optimized_kernel}"

    echo "${LINE_NUM},${m},${n},${k},${transA},${transB},${batch_count},${a_type},${b_type},${c_type},${d_type},${compute_type},${activation_type},${bias_vector},${scaleA},${scaleB},${baseline_kernel},${baseline_gflops},${baseline_us},${optimized_kernel},${optimized_gflops},${optimized_us},${gflops_pct},${us_pct}" >> "${RESULT_FILE}"
done < "${CMD_FILE}"

echo "Done! Results: ${RESULT_FILE}"
```

执行：`chmod +x run_benchmarks.sh && bash run_benchmarks.sh`

## Step 2: 汇报结果

测试完成后向用户展示：
1. results.csv 的内容摘要
2. 总结统计：平均加速比、最大/最小加速比、提升/下降的case数量
3. 文件位置：results.csv、logs/

## 输出字段说明

| 字段 | 含义 |
|------|------|
| `baseline_kernel` | 基线 gemm kernel 全称（--print_kernel_info 输出） |
| `baseline_gflops` | 基线吞吐量 (GFLOPS) |
| `baseline_us` | 基线耗时 (微秒) |
| `optimized_kernel` | 优化后 gemm kernel 全称（--print_kernel_info 输出） |
| `optimized_gflops` | 优化后吞吐量 (GFLOPS) |
| `optimized_us` | 优化后耗时 (微秒) |
| `gflops_pct` | 优化后GFLOPS / 基线GFLOPS × 100%（>100%表示提升） |
| `us_pct` | 基线us / 优化后us × 100%（>100%表示耗时缩短） |

## 注意事项

- 每条命令执行约需3-10秒，24条命令全流程约5-10分钟
- 若命令较多或超时，可适当调整 timeout 值
- `hipblaslt-bench` 需确保有执行权限：`chmod +x /opt/dtk/lib/hipblaslt/benchmark_tool/hipblaslt-bench`
- 优化库通过 `LD_LIBRARY_PATH` 注入，不影响系统默认库
- 脚本内置重试机制，自动处理 DCU 集群限流（rate limit）错误
- kernel 名称通过 `--print_kernel_info` 参数获取，用于对比优化前后是否选择了不同的 kernel
