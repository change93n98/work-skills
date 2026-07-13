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
    ├── baseline/           # 基线性能测试日志（不加 TENSILE_DB）
    ├── optimized/          # 优化后性能测试日志（不加 TENSILE_DB）
    ├── baseline_kernel/    # 基线 kernel 名称提取日志（加 TENSILE_DB）
    └── optimized_kernel/   # 优化后 kernel 名称提取日志（加 TENSILE_DB）
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

**选取所有 VRAM% 和 HCU% 都为 0 的卡**，用逗号分隔记录 GPU 编号备用（如 "0,1"）。

### 0.5 检查 benchmark 可执行文件

```bash
docker exec <容器名称> ls -la /opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench
```

若无执行权限：
```bash
docker exec <容器名称> chmod +x /opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench
```

## Step 1: 创建执行脚本

根据收集的参数，在宿主机上创建脚本，通过 `docker exec` 在容器内执行。

**重要**：
1. 必须先跑全量的非优化测试，跑完之后再跑全量的优化测试（而不是每组都先跑优化和非优化）
2. 运行命令按照输入文件中的原始命令，直接使用，不要修改命令格式（不要改变 `-f gemm_ex` 为 `-f gemm` 等）
3. **性能测试时不设置 `TENSILE_DB`**（避免影响性能），设置 `HIP_VISIBLE_DEVICES`（确保使用正确的 GPU）
4. **性能测试完成后，再单独运行一次设置 `TENSILE_DB=0x8000` 的测试**，用于提取 kernel 名称
5. 所有 rocblas 输出日志都要保存

```bash
#!/bin/bash
set -euo pipefail

CONTAINER="<容器名称>"
INPUT_FILE="<输入文件路径（容器内）>"
OPT_CONFIG_DIR="<优化配置目录（容器内）>"
BENCH_BIN="/opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench"

# 输出目录 = 宿主机当前目录
OUT_DIR="/root/changhl"
LOG_BASE="${OUT_DIR}/logs"
RESULT_FILE="${OUT_DIR}/results.csv"
BASELINE_RESULT_FILE="${OUT_DIR}/baseline_results.csv"
OPTIMIZED_RESULT_FILE="${OUT_DIR}/optimized_results.csv"

# 自动查找所有空闲卡（VRAM% 和 HCU% 都为 0），用逗号分隔
GPU_IDS=$(docker exec ${CONTAINER} hy-smi | awk 'NR>1 && $6=="0%" && $7=="0.0%" {if(count>0) printf ","; printf "%s", $1; count++} END{print ""}')
if [[ -z "$GPU_IDS" ]]; then
    echo "ERROR: 没有找到空闲GPU，请检查 hy-smi 输出"
    exit 1
fi
echo "使用 GPU: $GPU_IDS"

# 在宿主机创建日志目录
mkdir -p "${LOG_BASE}/baseline" "${LOG_BASE}/optimized"
mkdir -p "${LOG_BASE}/baseline_kernel" "${LOG_BASE}/optimized_kernel"

# CSV header
BASELINE_HEADER="line,m,n,k,transA,transB,alpha,beta,lda,ldb,ldc,ldd,a_type,b_type,c_type,d_type,compute_type,baseline_kernel,baseline_gflops,baseline_us"
OPTIMIZED_HEADER="line,optimized_kernel,optimized_gflops,optimized_us"
FINAL_HEADER="line,m,n,k,transA,transB,alpha,beta,lda,ldb,ldc,ldd,a_type,b_type,c_type,d_type,compute_type,baseline_kernel,baseline_gflops,baseline_us,optimized_kernel,optimized_gflops,optimized_us,gflops_pct,us_pct"

echo "$BASELINE_HEADER" > "${BASELINE_RESULT_FILE}"
echo "$OPTIMIZED_HEADER" > "${OPTIMIZED_RESULT_FILE}"
echo "$FINAL_HEADER" > "${RESULT_FILE}"

TOTAL_LINES=$(docker exec ${CONTAINER} wc -l "${INPUT_FILE}" | awk '{print $1}')
echo "总共 ${TOTAL_LINES} 条命令"

# 提取 kernel 名称的函数
extract_kernel() {
    local output="$1"
    local kernel=$(echo "$output" | grep -oP 'Solution::\K\S+' | tail -1)
    if [[ -z "$kernel" ]]; then
        kernel=$(echo "$output" | grep -oP '\bCijk\S*|\bCij\S*' | tail -1)
    fi
    if [[ -z "$kernel" ]]; then
        kernel="N/A"
    fi
    echo "$kernel"
}

# 解析参数的函数
parse_params() {
    local cmd="$1"
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
}

# ============================================
# Phase 1: 全量非优化性能测试（不设置 TENSILE_DB）
# ============================================
echo "=========================================="
echo "Phase 1: 全量非优化性能测试（基线）"
echo "=========================================="

LINE_NUM=0
while IFS= read -r raw_line; do
    [[ -z "${raw_line// /}" ]] && continue
    LINE_NUM=$((LINE_NUM + 1))

    # 提取命令部分（跳过开头的次数，如果有）
    cmd=$(echo "$raw_line" | sed 's/^[[:space:]]*[0-9]*[[:space:]]*//')

    # 解析参数
    parse_params "$cmd"

    echo "[${LINE_NUM}/${TOTAL_LINES}] 基线性能 m=${m} n=${n} k=${k} transA=${transA} transB=${transB}"

    # 替换 ./rocblas-bench 为完整路径
    full_cmd=$(echo "$cmd" | sed "s|./rocblas-bench|${BENCH_BIN}|g")

    # 基线性能运行（不设置 ROCBLAS_TENSILE_LIBPATH，不设置 TENSILE_DB，设置 HIP_VISIBLE_DEVICES）
    baseline_log="${LOG_BASE}/baseline/line_${LINE_NUM}_m${m}_n${n}_k${k}.log"
    baseline_output=$(docker exec -e HIP_VISIBLE_DEVICES=$GPU_IDS ${CONTAINER} timeout 300 ${full_cmd} 2>&1) || true
    echo "$baseline_output" > "${baseline_log}"
    baseline_result=$(echo "$baseline_output" | grep -E '^N,|^T,' | tail -1 || echo "")
    if [[ -n "$baseline_result" ]]; then
        baseline_gflops=$(echo "$baseline_result" | awk -F',' '{print $(NF-1)}' | tr -d ' ')
        baseline_us=$(echo "$baseline_result" | awk -F',' '{print $NF}' | tr -d ' ')
    else
        baseline_gflops="N/A"; baseline_us="N/A"
    fi

    echo "  baseline=${baseline_gflops}GFLOPS/${baseline_us}us"

    # 暂时写入 baseline_kernel 为 N/A，后面会补充
    echo "${LINE_NUM},${m},${n},${k},${transA},${transB},${alpha},${beta},${lda},${ldb},${ldc},${ldd},${a_type},${b_type},${c_type},${d_type},${compute_type},N/A,${baseline_gflops},${baseline_us}" >> "${BASELINE_RESULT_FILE}"
done < <(docker exec ${CONTAINER} cat "${INPUT_FILE}")

echo ""
echo "Phase 1 完成！"
echo ""

# ============================================
# Phase 2: 全量优化性能测试（不设置 TENSILE_DB）
# ============================================
echo "=========================================="
echo "Phase 2: 全量优化性能测试"
echo "=========================================="

LINE_NUM=0
while IFS= read -r raw_line; do
    [[ -z "${raw_line// /}" ]] && continue
    LINE_NUM=$((LINE_NUM + 1))

    # 提取命令部分
    cmd=$(echo "$raw_line" | sed 's/^[[:space:]]*[0-9]*[[:space:]]*//')

    # 解析参数
    parse_params "$cmd"

    echo "[${LINE_NUM}/${TOTAL_LINES}] 优化性能 m=${m} n=${n} k=${k} transA=${transA} transB=${transB}"

    # 替换 ./rocblas-bench 为完整路径
    full_cmd=$(echo "$cmd" | sed "s|./rocblas-bench|${BENCH_BIN}|g")

    # 优化后性能运行（设置 ROCBLAS_TENSILE_LIBPATH，不设置 TENSILE_DB，设置 HIP_VISIBLE_DEVICES）
    optimized_log="${LOG_BASE}/optimized/line_${LINE_NUM}_m${m}_n${n}_k${k}.log"
    optimized_output=$(docker exec -e HIP_VISIBLE_DEVICES=$GPU_IDS -e ROCBLAS_TENSILE_LIBPATH=${OPT_CONFIG_DIR} ${CONTAINER} timeout 300 ${full_cmd} 2>&1) || true
    echo "$optimized_output" > "${optimized_log}"
    optimized_result=$(echo "$optimized_output" | grep -E '^N,|^T,' | tail -1 || echo "")
    if [[ -n "$optimized_result" ]]; then
        optimized_gflops=$(echo "$optimized_result" | awk -F',' '{print $(NF-1)}' | tr -d ' ')
        optimized_us=$(echo "$optimized_result" | awk -F',' '{print $NF}' | tr -d ' ')
    else
        optimized_gflops="N/A"; optimized_us="N/A"
    fi

    echo "  optimized=${optimized_gflops}GFLOPS/${optimized_us}us"

    # 暂时写入 optimized_kernel 为 N/A，后面会补充
    echo "${LINE_NUM},N/A,${optimized_gflops},${optimized_us}" >> "${OPTIMIZED_RESULT_FILE}"
done < <(docker exec ${CONTAINER} cat "${INPUT_FILE}")

echo ""
echo "Phase 2 完成！"
echo ""

# ============================================
# Phase 3: 提取基线 kernel 名称（设置 TENSILE_DB）
# ============================================
echo "=========================================="
echo "Phase 3: 提取基线 kernel 名称"
echo "=========================================="

# 创建 kernel 名称临时文件
BASELINE_KERNEL_FILE="${OUT_DIR}/baseline_kernel.csv"
OPTIMIZED_KERNEL_FILE="${OUT_DIR}/optimized_kernel.csv"
echo "line,kernel" > "${BASELINE_KERNEL_FILE}"
echo "line,kernel" > "${OPTIMIZED_KERNEL_FILE}"

LINE_NUM=0
while IFS= read -r raw_line; do
    [[ -z "${raw_line// /}" ]] && continue
    LINE_NUM=$((LINE_NUM + 1))

    # 提取命令部分
    cmd=$(echo "$raw_line" | sed 's/^[[:space:]]*[0-9]*[[:space:]]*//')

    # 解析参数
    parse_params "$cmd"

    echo "[${LINE_NUM}/${TOTAL_LINES}] 基线 kernel m=${m} n=${n} k=${k}"

    # 替换 ./rocblas-bench 为完整路径
    full_cmd=$(echo "$cmd" | sed "s|./rocblas-bench|${BENCH_BIN}|g")

    # 基线 kernel 提取（设置 TENSILE_DB，设置 HIP_VISIBLE_DEVICES）
    kernel_log="${LOG_BASE}/baseline_kernel/line_${LINE_NUM}_m${m}_n${n}_k${k}.log"
    kernel_output=$(docker exec -e HIP_VISIBLE_DEVICES=$GPU_IDS -e TENSILE_DB=0x8000 ${CONTAINER} timeout 300 ${full_cmd} 2>&1) || true
    echo "$kernel_output" > "${kernel_log}"
    baseline_kernel=$(extract_kernel "$kernel_output")

    echo "  baseline_kernel=${baseline_kernel}"

    echo "${LINE_NUM},${baseline_kernel}" >> "${BASELINE_KERNEL_FILE}"
done < <(docker exec ${CONTAINER} cat "${INPUT_FILE}")

echo ""
echo "Phase 3 完成！"
echo ""

# ============================================
# Phase 4: 提取优化后 kernel 名称（设置 TENSILE_DB）
# ============================================
echo "=========================================="
echo "Phase 4: 提取优化后 kernel 名称"
echo "=========================================="

LINE_NUM=0
while IFS= read -r raw_line; do
    [[ -z "${raw_line// /}" ]] && continue
    LINE_NUM=$((LINE_NUM + 1))

    # 提取命令部分
    cmd=$(echo "$raw_line" | sed 's/^[[:space:]]*[0-9]*[[:space:]]*//')

    # 解析参数
    parse_params "$cmd"

    echo "[${LINE_NUM}/${TOTAL_LINES}] 优化 kernel m=${m} n=${n} k=${k}"

    # 替换 ./rocblas-bench 为完整路径
    full_cmd=$(echo "$cmd" | sed "s|./rocblas-bench|${BENCH_BIN}|g")

    # 优化后 kernel 提取（设置 TENSILE_DB 和 ROCBLAS_TENSILE_LIBPATH，设置 HIP_VISIBLE_DEVICES）
    kernel_log="${LOG_BASE}/optimized_kernel/line_${LINE_NUM}_m${m}_n${n}_k${k}.log"
    kernel_output=$(docker exec -e HIP_VISIBLE_DEVICES=$GPU_IDS -e TENSILE_DB=0x8000 -e ROCBLAS_TENSILE_LIBPATH=${OPT_CONFIG_DIR} ${CONTAINER} timeout 300 ${full_cmd} 2>&1) || true
    echo "$kernel_output" > "${kernel_log}"
    optimized_kernel=$(extract_kernel "$kernel_output")

    echo "  optimized_kernel=${optimized_kernel}"

    echo "${LINE_NUM},${optimized_kernel}" >> "${OPTIMIZED_KERNEL_FILE}"
done < <(docker exec ${CONTAINER} cat "${INPUT_FILE}")

echo ""
echo "Phase 4 完成！"
echo ""

# ============================================
# Phase 5: 合并结果
# ============================================
echo "=========================================="
echo "Phase 5: 合并结果"
echo "=========================================="

# 使用 Python 合并结果
python3 << 'PYTHON_EOF'
import csv

BASELINE_FILE = '/root/changhl/baseline_results.csv'
OPTIMIZED_FILE = '/root/changhl/optimized_results.csv'
BASELINE_KERNEL_FILE = '/root/changhl/baseline_kernel.csv'
OPTIMIZED_KERNEL_FILE = '/root/changhl/optimized_kernel.csv'
RESULT_FILE = '/root/changhl/results.csv'

# 读取基线结果
baseline_data = {}
with open(BASELINE_FILE, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        baseline_data[row['line']] = row

# 读取优化结果
optimized_data = {}
with open(OPTIMIZED_FILE, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        optimized_data[row['line']] = row

# 读取基线 kernel 名称
baseline_kernel_data = {}
with open(BASELINE_KERNEL_FILE, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        baseline_kernel_data[row['line']] = row['kernel']

# 读取优化后 kernel 名称
optimized_kernel_data = {}
with open(OPTIMIZED_KERNEL_FILE, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        optimized_kernel_data[row['line']] = row['kernel']

# 合并并写入最终结果
with open(RESULT_FILE, 'w') as f:
    header = "line,m,n,k,transA,transB,alpha,beta,lda,ldb,ldc,ldd,a_type,b_type,c_type,d_type,compute_type,baseline_kernel,baseline_gflops,baseline_us,optimized_kernel,optimized_gflops,optimized_us,gflops_pct,us_pct"
    f.write(header + '\n')

    for line_num in sorted(baseline_data.keys(), key=int):
        b = baseline_data[line_num]
        o = optimized_data.get(line_num, {})

        baseline_gflops = b.get('baseline_gflops', 'N/A')
        baseline_us = b.get('baseline_us', 'N/A')
        optimized_gflops = o.get('optimized_gflops', 'N/A')
        optimized_us = o.get('optimized_us', 'N/A')

        # 获取 kernel 名称
        baseline_kernel = baseline_kernel_data.get(line_num, 'N/A')
        optimized_kernel = optimized_kernel_data.get(line_num, 'N/A')

        # 计算百分比
        if baseline_gflops != 'N/A' and optimized_gflops != 'N/A':
            try:
                gflops_pct = f"{float(optimized_gflops)/float(baseline_gflops)*100:.2f}%"
                us_pct = f"{float(baseline_us)/float(optimized_us)*100:.2f}%"
            except:
                gflops_pct = 'N/A'
                us_pct = 'N/A'
        else:
            gflops_pct = 'N/A'
            us_pct = 'N/A'

        row = [
            line_num,
            b.get('m', ''), b.get('n', ''), b.get('k', ''),
            b.get('transA', ''), b.get('transB', ''),
            b.get('alpha', ''), b.get('beta', ''),
            b.get('lda', ''), b.get('ldb', ''), b.get('ldc', ''), b.get('ldd', ''),
            b.get('a_type', ''), b.get('b_type', ''), b.get('c_type', ''), b.get('d_type', ''),
            b.get('compute_type', ''),
            baseline_kernel, baseline_gflops, baseline_us,
            optimized_kernel, optimized_gflops, optimized_us,
            gflops_pct, us_pct
        ]
        f.write(','.join(row) + '\n')

print("Results merged successfully!")
PYTHON_EOF

echo "Done! Results: ${RESULT_FILE}"
```

执行：`chmod +x run_benchmarks.sh && bash run_benchmarks.sh`

## Step 2: 生成对比表格

从 `results.csv` 生成 Markdown 对比表格：

```python
python3 -c "
import csv

RESULT_FILE = '/root/changhl/results.csv'
TABLE_FILE = '/root/changhl/comparison_table.md'

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
        # 截断过长的 kernel 名称
        baseline_kernel_short = r['baseline_kernel'][:50] + '...' if len(r['baseline_kernel']) > 50 else r['baseline_kernel']
        optimized_kernel_short = r['optimized_kernel'][:50] + '...' if len(r['optimized_kernel']) > 50 else r['optimized_kernel']
        lines.append(f\"| {r['m']} | {r['n']} | {r['k']} | {r['transA']} | {r['transB']} | {r['alpha']} | {r['beta']} | {r['lda']} | {r['ldb']} | {r['ldc']} | {r['ldd']} | {r['a_type']} | {r['b_type']} | {r['compute_type']} | {baseline_kernel_short} | {r['baseline_gflops']} | {r['baseline_us']} | {optimized_kernel_short} | {r['optimized_gflops']} | {r['optimized_us']} | {r['gflops_pct']} | {r['us_pct']} |\")
    lines.append('')

# 统计汇总
lines.append('## 统计汇总')
lines.append('')

gflops_values = []
improved_count = 0
regressed_count = 0

for row in rows:
    if row['gflops_pct'] != 'N/A':
        pct = float(row['gflops_pct'].replace('%', ''))
        gflops_values.append(pct)
        if pct > 100:
            improved_count += 1
        elif pct < 100:
            regressed_count += 1

if gflops_values:
    avg_gflops = sum(gflops_values) / len(gflops_values)
    max_gflops = max(gflops_values)
    min_gflops = min(gflops_values)

    lines.append(f'- **平均 GFLOPS 百分比**: {avg_gflops:.2f}%')
    lines.append(f'- **最大提升**: {max_gflops:.2f}%')
    lines.append(f'- **最大下降**: {min_gflops:.2f}%')
    lines.append(f'- **提升的 case 数**: {improved_count}')
    lines.append(f'- **下降的 case 数**: {regressed_count}')
    lines.append(f'- **无变化的 case 数**: {len(gflops_values) - improved_count - regressed_count}')

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
- **性能测试时不设置 `TENSILE_DB`**（避免影响性能），设置 `HIP_VISIBLE_DEVICES`（确保使用正确的 GPU）
- **性能测试完成后，再单独运行一次设置 `TENSILE_DB=0x8000` 的测试**，用于提取 kernel 名称
- 优化后执行通过 `-e ROCBLAS_TENSILE_LIBPATH=<优化配置目录>` 加载优化配置
- 所有 rocblas 输出日志都会保存到对应的日志目录
