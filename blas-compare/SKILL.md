---
name: blas-compare
description: >
  blas gemm 单测性能对比（容器版）。
  在指定容器内分别执行基线和优化后的rocBLAS库，自动采集GFLOPS和耗时，生成对比表格。
  优化后通过 ROCBLAS_TENSILE_LIBPATH 环境变量加载优化配置。
  触发词：blas对比、blas-compare、gemm性能对比、rocblas对比、blas测试。
---

# BLAS Compare - GEMM 单测性能对比（容器版）

## 必须收集的参数

开始前确认以下信息，缺什么问什么：

| 参数 | 说明 | 示例 |
|------|------|------|
| 容器名称 | Docker 容器名或 ID | ch_vllm018_0707 |
| 输入文件路径（容器内） | 包含 rocblas-bench 命令的文件（rocblas-layer3 格式） | /home/auto_select_test/commands.log |
| 优化配置目录（容器内） | 用于设置 ROCBLAS_TENSILE_LIBPATH 的目录 | /home/auto_select_test/auto_select_tools/optimization_configs/new/config/library_gpu5 |

> 输出目录自动设为输入文件所在目录。
> GPU 编号不需要用户指定，脚本会自动查找空闲卡。

## 输入文件格式

rocblas-layer3 格式，每行包含一条 rocblas-bench 命令，示例：

```
./rocblas-bench -f gemm_ex --transposeA N --transposeB N -m 8192 -n 1 -k 7392 --alpha 1 --a_type bf16_r --lda 8192 --b_type bf16_r --ldb 7392 --beta 0 --c_type bf16_r --ldc 8192 --d_type bf16_r --ldd 8192 --compute_type f32_r --algo 0 --solution_index 0 --flags 0
```

或者带次数前缀的格式也支持：
```
16320 ./rocblas-bench -f gemm_ex --transposeA N --transposeB N -m 8192 -n 1 -k 7392 ...
```

脚本会自动识别并提取 `./rocblas-bench` 及之后的命令部分。

## 输出目录结构

```
<输入文件所在目录>/
├── run_benchmarks.sh       # 执行脚本
├── results.csv             # 汇总结果（含所有参数和性能数据）
├── comparison_table.md     # Markdown 对比表格
└── logs/
    ├── baseline/           # 基线执行日志
    │   ├── line_1_m8192_n1_k7392.log
    │   └── ...
    └── optimized/          # 优化后执行日志
        ├── line_1_m8192_n1_k7392.log
        └── ...
```

## Step 0: 确认环境

### 0.1 检查容器是否存在且运行中

```bash
docker ps --filter "name=<容器名称>" --format "{{.Names}} {{.Status}}"
```

确认容器状态为 Up。

### 0.2 检查输入文件是否存在

```bash
docker exec <容器名称> ls -la <输入文件路径>
```

### 0.3 检查优化配置目录是否存在

```bash
docker exec <容器名称> ls -la <优化配置目录>/
```

### 0.4 查找空闲卡

```bash
docker exec <容器名称> hy-smi
```

输出示例：
```
HCU     Temp     AvgPwr     VRAM%      HCU%
0       40.0C    158.0W     0%         0.0%     ← 空闲
1       38.0C    160.0W     0%         0.0%     ← 空闲
6       41.0C    160.0W     91%        0.0%     ← 显存占用，不可用
```

选取第一张 VRAM% 和 HCU% 都为 0 的卡，记录 GPU 编号备用。

### 0.5 检查 benchmark 可执行文件

```bash
docker exec <容器名称> ls -la /opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench
```

若无执行权限：
```bash
docker exec <容器名称> chmod +x /opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench
```

## Step 1: 创建执行脚本

根据收集的参数，在宿主机上创建脚本，通过 `docker exec` 在容器内执行：

```bash
#!/bin/bash
set -euo pipefail

CONTAINER="<容器名称>"
INPUT_FILE="<输入文件路径（容器内）>"
OPT_CONFIG_DIR="<优化配置目录（容器内）>"
BENCH_BIN="/opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench"

# 输出目录 = 输入文件所在目录
OUT_DIR=$(dirname "${INPUT_FILE}")
LOG_BASE="${OUT_DIR}/logs"
RESULT_FILE="${OUT_DIR}/results.csv"

# 自动查找空闲卡（VRAM% 和 HCU% 都为 0）
GPU_ID=$(docker exec ${CONTAINER} hy-smi | awk 'NR>1 && $6=="0%" && $7=="0.0%" {print $1; exit}')
if [[ -z "$GPU_ID" ]]; then
    echo "ERROR: 没有找到空闲GPU，请检查 hy-smi 输出"
    exit 1
fi
echo "使用 GPU: $GPU_ID"

# 在容器内创建日志目录
docker exec ${CONTAINER} mkdir -p "${LOG_BASE}/baseline" "${LOG_BASE}/optimized"

# CSV header（含 kernel 列）
echo "line,m,n,k,transA,transB,alpha,beta,lda,ldb,ldc,ldd,a_type,b_type,c_type,d_type,compute_type,baseline_kernel,baseline_gflops,baseline_us,optimized_kernel,optimized_gflops,optimized_us,gflops_pct,us_pct" > "${RESULT_FILE}"

LINE_NUM=0
while IFS= read -r raw_line; do
    [[ -z "${raw_line// /}" ]] && continue
    LINE_NUM=$((LINE_NUM + 1))

    # 提取命令部分（跳过开头的次数，如果有）
    cmd=$(echo "$raw_line" | sed 's/^[[:space:]]*[0-9]*[[:space:]]*//')

    # 解析参数
    m=$(echo "$cmd" | grep -oP '(?<=-m )\S+')
    n=$(echo "$cmd" | grep -oP '(?<=-n )\S+')
    k=$(echo "$cmd" | grep -oP '(?<=-k )\S+')
    transA=$(echo "$cmd" | grep -oP '(?<=--transposeA )\S+')
    transB=$(echo "$cmd" | grep -oP '(?<=--transposeB )\S+')
    alpha=$(echo "$cmd" | grep -oP '(?<=--alpha )\S+')
    beta=$(echo "$cmd" | grep -oP '(?<=--beta )\S+')
    lda=$(echo "$cmd" | grep -oP '(?<=--lda )\S+')
    ldb=$(echo "$cmd" | grep -oP '(?<=--ldb )\S+')
    ldc=$(echo "$cmd" | grep -oP '(?<=--ldc )\S+')
    ldd=$(echo "$cmd" | grep -oP '(?<=--ldd )\S+')
    a_type=$(echo "$cmd" | grep -oP '(?<=--a_type )\S+')
    b_type=$(echo "$cmd" | grep -oP '(?<=--b_type )\S+')
    c_type=$(echo "$cmd" | grep -oP '(?<=--c_type )\S+')
    d_type=$(echo "$cmd" | grep -oP '(?<=--d_type )\S+')
    compute_type=$(echo "$cmd" | grep -oP '(?<=--compute_type )\S+')

    echo "[${LINE_NUM}] m=${m} n=${n} k=${k} transA=${transA} transB=${transB}"

    # 替换 ./rocblas-bench 为完整路径
    full_cmd=$(echo "$cmd" | sed "s|./rocblas-bench|${BENCH_BIN}|g")

    # 提取 kernel 名称的函数（从 TENSILE_DB 调试输出中解析）
    extract_kernel() {
        local output="$1"
        # 优先匹配 Tensile Solution 名称（如 Cijk_Ailk_Bjlk_BH_...）
        local kernel=$(echo "$output" | grep -oP 'Solution::\K\S+' | tail -1)
        if [[ -z "$kernel" ]]; then
            # 回退：匹配包含 Cijk/Cij 的行中的完整 kernel 标识
            kernel=$(echo "$output" | grep -oP '\bCijk\S*|\bCij\S*' | tail -1)
        fi
        if [[ -z "$kernel" ]]; then
            kernel="N/A"
        fi
        echo "$kernel"
    }

    # 基线运行（不设置 ROCBLAS_TENSILE_LIBPATH）
    baseline_log="${LOG_BASE}/baseline/line_${LINE_NUM}_m${m}_n${n}_k${k}.log"
    baseline_output=$(docker exec -e HIP_VISIBLE_DEVICES=$GPU_ID -e TENSILE_DB=0x8000 ${CONTAINER} timeout 300 ${full_cmd} 2>&1) || true
    echo "$baseline_output" > "${baseline_log}"
    baseline_kernel=$(extract_kernel "$baseline_output")
    baseline_result=$(echo "$baseline_output" | grep -E '^N,|^T,' | tail -1 || echo "")
    if [[ -n "$baseline_result" ]]; then
        baseline_gflops=$(echo "$baseline_result" | awk -F',' '{print $(NF-1)}' | tr -d ' ')
        baseline_us=$(echo "$baseline_result" | awk -F',' '{print $NF}' | tr -d ' ')
    else
        baseline_gflops="N/A"; baseline_us="N/A"
    fi

    # 优化后运行（设置 ROCBLAS_TENSILE_LIBPATH 指向优化配置目录）
    optimized_log="${LOG_BASE}/optimized/line_${LINE_NUM}_m${m}_n${n}_k${k}.log"
    optimized_output=$(docker exec -e HIP_VISIBLE_DEVICES=$GPU_ID -e TENSILE_DB=0x8000 -e ROCBLAS_TENSILE_LIBPATH=${OPT_CONFIG_DIR} ${CONTAINER} timeout 300 ${full_cmd} 2>&1) || true
    echo "$optimized_output" > "${optimized_log}"
    optimized_kernel=$(extract_kernel "$optimized_output")
    optimized_result=$(echo "$optimized_output" | grep -E '^N,|^T,' | tail -1 || echo "")
    if [[ -n "$optimized_result" ]]; then
        optimized_gflops=$(echo "$optimized_result" | awk -F',' '{print $(NF-1)}' | tr -d ' ')
        optimized_us=$(echo "$optimized_result" | awk -F',' '{print $NF}' | tr -d ' ')
    else
        optimized_gflops="N/A"; optimized_us="N/A"
    fi

    # 计算百分比
    if [[ "$baseline_gflops" != "N/A" && "$optimized_gflops" != "N/A" ]]; then
        gflops_pct=$(python3 -c "print(f'{${optimized_gflops}/${baseline_gflops}*100:.2f}%')")
        us_pct=$(python3 -c "print(f'{${baseline_us}/${optimized_us}*100:.2f}%')")
    else
        gflops_pct="N/A"; us_pct="N/A"
    fi

    echo "  baseline=${baseline_gflops}GFLOPS/${baseline_us}us  optimized=${optimized_gflops}GFLOPS/${optimized_us}us  gflops=${gflops_pct}  us=${us_pct}"
    echo "  baseline_kernel=${baseline_kernel}  optimized_kernel=${optimized_kernel}"

    echo "${LINE_NUM},${m},${n},${k},${transA},${transB},${alpha},${beta},${lda},${ldb},${ldc},${ldd},${a_type},${b_type},${c_type},${d_type},${compute_type},${baseline_kernel},${baseline_gflops},${baseline_us},${optimized_kernel},${optimized_gflops},${optimized_us},${gflops_pct},${us_pct}" >> "${RESULT_FILE}"
done < <(docker exec ${CONTAINER} cat "${INPUT_FILE}")

echo "Done! Results: ${RESULT_FILE}"
```

执行：`chmod +x run_benchmarks.sh && bash run_benchmarks.sh`

## Step 2: 生成对比表格

从 `results.csv` 生成 Markdown 对比表格：

```python
python3 -c "
import csv

RESULT_FILE = '<输出目录>/results.csv'
TABLE_FILE = '<输出目录>/comparison_table.md'

with open(RESULT_FILE, 'r') as f:
    rows = list(csv.DictReader(f))

lines = ['# GEMM 性能对比', '', '## 测试环境', '- **容器**: <容器名称>', '- **优化配置目录**: <优化配置目录>', '']

# 按 (transA, transB, n) 分组
groups = {}
for row in rows:
    if row['transA'] == 'T':
        key = 'TransA=T, TransB=N'
    else:
        key = f\"TransA=N, TransB=N, n={row['n']}\"
    groups.setdefault(key, []).append(row)

for gname, grows in groups.items():
    lines.append(f'### {gname}')
    lines.append('')
    lines.append('| m | n | k | transA | transB | alpha | beta | lda | ldb | ldc | ldd | a_type | b_type | compute_type | 基线 kernel | 基线 GFLOPS | 基线 us | 优化后 kernel | 优化后 GFLOPS | 优化后 us | GFLOPS% | us% |')
    lines.append('|---|---|---|--------|--------|-------|------|-----|-----|-----|-----|--------|--------|-------------|-----------|-----------|--------|-------------|-------------|----------|---------|-----|')
    for r in grows:
        lines.append(f\"| {r['m']} | {r['n']} | {r['k']} | {r['transA']} | {r['transB']} | {r['alpha']} | {r['beta']} | {r['lda']} | {r['ldb']} | {r['ldc']} | {r['ldd']} | {r['a_type']} | {r['b_type']} | {r['compute_type']} | {r['baseline_kernel']} | {r['baseline_gflops']} | {r['baseline_us']} | {r['optimized_kernel']} | {r['optimized_gflops']} | {r['optimized_us']} | {r['gflops_pct']} | {r['us_pct']} |\")
    lines.append('')

with open(TABLE_FILE, 'w') as f:
    f.write('\n'.join(lines))
print(f'Table: {TABLE_FILE}')
"
```

## Step 3: 汇报结果

向用户展示：
1. 完整的对比表格（按分组）
2. 总结统计：平均加速比、最大/最小加速比、提升明显的 case 数量
3. 文件位置：results.csv、comparison_table.md、logs/

## 输出字段说明

| 字段 | 含义 |
|------|------|
| `baseline_kernel` | 基线 gemm kernel 全称（TENSILE_DB=0x8000 输出） |
| `baseline_gflops` | 基线吞吐量 (GFLOPS) |
| `baseline_us` | 基线耗时 (微秒) |
| `optimized_kernel` | 优化后 gemm kernel 全称（TENSILE_DB=0x8000 输出） |
| `optimized_gflops` | 优化后吞吐量 (GFLOPS) |
| `optimized_us` | 优化后耗时 (微秒) |
| `gflops_pct` | 优化后GFLOPS / 基线GFLOPS × 100%（>100% 表示提升） |
| `us_pct` | 基线us / 优化后us × 100%（>100% 表示耗时缩短） |

## 注意事项

- 每条命令执行约需 10-30 秒，命令较多时全流程可能需要较长时间
- 若命令较多或超时，可适当调整 timeout 值
- 确保容器内 benchmark 可执行文件有执行权限：`docker exec <容器名> chmod +x /opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench`
- 脚本通过 `-e TENSILE_DB=0x8000` 启用 Tensile 调试输出，用于提取 gemm kernel 全称
- 优化后执行通过 `-e ROCBLAS_TENSILE_LIBPATH=<优化配置目录>` 加载优化配置
