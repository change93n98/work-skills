---
name: blas-compare
description: >
  blas gemm 单测性能对比。
  从CSV文件读取rocblas-bench命令，在指定GPU上分别执行基线和优化后的rocBLAS库，自动采集GFLOPS和耗时，生成对比表格。
  触发词：blas对比、blas-compare、gemm性能对比、rocblas对比、blas测试。
---

# BLAS Compare - GEMM 单测性能对比

## 必须收集的参数

开始前确认以下信息，缺什么问什么：

| 参数 | 说明 | 示例 |
|------|------|------|
| CSV文件路径 | 包含rocblas-bench命令的CSV | /path/to/commands.csv |
| 优化后rocBLAS库路径 | 自编译的rocblas .so 所在lib目录 | /path/to/rocblas-install/lib |
| 输出目录 | 存放日志和结果的目录 | /path/to/output/ |
| rocblas-bench路径 | benchmark可执行文件（默认 `/opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench`） | /opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench |

> GPU编号不需要用户指定，脚本会自动查找空闲卡。

## CSV输入格式

每行格式：`<次数> ./rocblas-bench -f gemm_ex --transposeA N --transposeB N -m <M> -n <N> -k <K> ...`

示例：
```
  16320 ./rocblas-bench -f gemm_ex --transposeA N --transposeB N -m 8192 -n 1 -k 7392 --alpha 1 --a_type bf16_r --lda 8192 --b_type bf16_r --ldb 7392 --beta 0 --c_type bf16_r --ldc 8192 --d_type bf16_r --ldd 8192 --compute_type f32_r --algo 0 --solution_index 0 --flags 0
```

第一个数字是次数元数据，实际执行时忽略，只取 `./rocblas-bench` 及之后的命令部分。

## 输出目录结构

```
<输出目录>/
├── run_benchmarks.sh       # 执行脚本
├── gen_table.sh            # 表格生成脚本
├── results.csv             # 汇总结果（含所有参数和性能数据）
├── comparison_table.md     # Markdown对比表格
└── logs/
    ├── baseline/           # 基线执行日志
    │   ├── line_1_m8192_n1_k7392.log
    │   └── ...
    └── optimized/          # 优化后执行日志
        ├── line_1_m8192_n1_k7392.log
        └── ...
```

## Step 0: 查找空闲卡并确认环境

Benchmark 单测只需一张空闲卡，自动查找 VRAM 和 HCU 占用都为 0 的卡：

```bash
hy-smi
```

输出示例：
```
HCU     Temp     AvgPwr     VRAM%      HCU%
0       40.0C    158.0W     0%         0.0%     ← 空闲
1       38.0C    160.0W     0%         0.0%     ← 空闲
6       41.0C    160.0W     91%        0.0%     ← 显存占用，不可用
```

选取第一张 VRAM% 和 HCU% 都为 0 的卡，记录 GPU 编号备用。

同时确认 benchmark 可执行文件和优化库存在：

```bash
# 检查benchmark可执行文件，若无权限则加
ls -la /opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench || chmod +x /opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench

# 检查优化库
ls <优化库路径>/librocblas.so*
```

## Step 1: 创建执行脚本

在输出目录下创建 `run_benchmarks.sh`，脚本逻辑：

```bash
#!/bin/bash
set -euo pipefail

CSV_FILE="<CSV文件路径>"
BENCH_BIN="/opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench"
ROCBLAS_OPT="<优化库路径>"
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

# 启用 TENSILE_DB 以输出 gemm kernel 全称
export TENSILE_DB=0x8000

mkdir -p "${LOG_BASE}/baseline" "${LOG_BASE}/optimized"

# CSV header（含 kernel 列）
echo "line,m,n,k,transA,transB,alpha,beta,lda,ldb,ldc,ldd,a_type,b_type,c_type,d_type,compute_type,baseline_kernel,baseline_gflops,baseline_us,optimized_kernel,optimized_gflops,optimized_us,gflops_pct,us_pct" > "${RESULT_FILE}"

LINE_NUM=0
while IFS= read -r raw_line; do
    [[ -z "${raw_line// /}" ]] && continue
    LINE_NUM=$((LINE_NUM + 1))

    # 提取命令部分（跳过开头的次数）
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

    # 基线运行（不加载优化库）
    baseline_log="${LOG_BASE}/baseline/line_${LINE_NUM}_m${m}_n${n}_k${k}.log"
    baseline_output=$(HIP_VISIBLE_DEVICES=$GPU_ID timeout 300 ${full_cmd} 2>&1) || true
    echo "$baseline_output" > "${baseline_log}"
    baseline_kernel=$(extract_kernel "$baseline_output")
    baseline_result=$(echo "$baseline_output" | grep -E '^N,|^T,' | tail -1 || echo "")
    if [[ -n "$baseline_result" ]]; then
        baseline_gflops=$(echo "$baseline_result" | awk -F',' '{print $(NF-1)}' | tr -d ' ')
        baseline_us=$(echo "$baseline_result" | awk -F',' '{print $NF}' | tr -d ' ')
    else
        baseline_gflops="N/A"; baseline_us="N/A"
    fi

    # 优化后运行（加载优化库）
    optimized_log="${LOG_BASE}/optimized/line_${LINE_NUM}_m${m}_n${n}_k${k}.log"
    optimized_output=$(HIP_VISIBLE_DEVICES=$GPU_ID LD_LIBRARY_PATH="${ROCBLAS_OPT}:${LD_LIBRARY_PATH:-}" timeout 300 ${full_cmd} 2>&1) || true
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
done < "${CSV_FILE}"

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

lines = ['# GEMM 性能对比', '', '## 测试环境', '- **GPU**: <GPU型号>', '- **优化库**: <优化库路径>', '']

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
2. 总结统计：平均加速比、最大/最小加速比、提升明显的case数量
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
| `gflops_pct` | 优化后GFLOPS / 基线GFLOPS × 100%（>100%表示提升） |
| `us_pct` | 基线us / 优化后us × 100%（>100%表示耗时缩短） |

## 注意事项

- 每条命令执行约需10-30秒，15条命令全流程约10分钟
- 若命令较多或超时，可适当调整 timeout 值
- `./rocblas-bench` 需替换为完整路径 `/opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench`
- 确保benchmark可执行文件有执行权限：`chmod +x /opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench`
- 脚本通过 `export TENSILE_DB=0x8000` 启用 Tensile 调试输出，用于提取 gemm kernel 全称
