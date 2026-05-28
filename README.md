# Work Skills

Claude Code 自定义 Skills 集合，面向 **海光 DCU (ROCm)** 平台的 GPU 性能分析工具。包含三个独立 skill：BLAS GEMM 性能对比、hipBLASLt GEMM 性能对比和大模型推理 Profiling 分析。

## 目录

- [安装](#安装)
- [Skill 1: blas-compare](#skill-1-blas-compare---gemm-性能对比)
- [Skill 2: blaslt-compare](#skill-2-blaslt-compare---hipblaslt-gemm-性能对比)
- [Skill 3: llm-prof](#skill-3-llm-prof---大模型推理-profiling-分析)
- [项目结构](#项目结构)
- [依赖](#依赖)

---

## 安装

将 skill 目录复制到 Claude Code 的 skills 目录下即可自动加载：

```bash
cp -r blas-compare ~/.claude/skills/
cp -r blaslt-compare ~/.claude/skills/
cp -r llm-prof ~/.claude/skills/
```

安装后在 Claude Code 对话中触发对应关键词即可调用。

---

## Skill 1: blas-compare - GEMM 性能对比

### 功能

从 CSV 文件批量读取 `rocblas-bench` 命令，在同一张 DCU 上分别执行**基线**和**优化后**的 rocBLAS 库，自动采集 GFLOPS 和耗时，生成对比表格。用于验证自编译 rocBLAS 的 kernel 优化效果。

### 核心特性

| 特性 | 说明 |
|------|------|
| 自动选卡 | 通过 `hy-smi` 查找 VRAM% 和 HCU% 都为 0 的空闲 GPU，无需手动指定 |
| Kernel 识别 | 通过 `TENSILE_DB=0x8000` 环境变量启用 Tensile 调试输出，提取 gemm kernel 完整名称（如 `Cijk_Ailk_Bjlk_BH...`） |
| 参数解析 | 自动从 CSV 命令中解析 m、n、k、transpose、data type 等全部 GEMM 参数 |
| 结果汇总 | 输出 `results.csv`（结构化数据）和 `comparison_table.md`（Markdown 表格），并计算 GFLOPS 和耗时的百分比变化 |

### 触发词

`blas对比`、`blas-compare`、`gemm性能对比`、`rocblas对比`、`blas测试`

### 输入

CSV 文件，每行格式为 `<次数> ./rocblas-bench -f gemm_ex --transposeA N ...`，示例：

```csv
16320 ./rocblas-bench -f gemm_ex --transposeA N --transposeB N -m 8192 -n 1 -k 7392 --alpha 1 --a_type bf16_r --lda 8192 --b_type bf16_r --ldb 7392 --beta 0 --c_type bf16_r --ldc 8192 --d_type bf16_r --ldd 8192 --compute_type f32_r --algo 0 --solution_index 0 --flags 0
```

开头的数字是次数元数据，执行时会被忽略。

### 输出

```
<输出目录>/
├── run_benchmarks.sh       # 执行脚本（可独立复用）
├── results.csv             # 汇总结果（含所有参数和性能数据）
├── comparison_table.md     # Markdown 对比表格
└── logs/
    ├── baseline/           # 基线执行日志
    └── optimized/          # 优化后执行日志
```

### 输出字段

| 字段 | 含义 |
|------|------|
| `baseline_kernel` / `optimized_kernel` | gemm kernel 全称（从 TENSILE_DB 调试输出解析） |
| `baseline_gflops` / `optimized_gflops` | 吞吐量 (GFLOPS) |
| `baseline_us` / `optimized_us` | 耗时 (微秒) |
| `gflops_pct` | 优化后 / 基线 GFLOPS × 100%（>100% 表示吞吐提升） |
| `us_pct` | 基线 / 优化后耗时 × 100%（>100% 表示耗时缩短） |

### 使用流程

1. 准备包含 `rocblas-bench` 命令的 CSV 文件
2. 提供自编译的优化后 rocBLAS 库路径（`librocblas.so` 所在目录）
3. 在 Claude Code 中说"blas对比"或类似关键词
4. Skill 自动查找空闲 GPU、执行 benchmark、生成对比表格

### 注意事项

- 每条命令执行约 10-30 秒，15 条命令全流程约 10 分钟
- 需要 `rocblas-bench` 可执行权限：`chmod +x /opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench`
- 超时默认 300 秒，可在脚本中调整

---

## Skill 2: blaslt-compare - hipBLASLt GEMM 性能对比

### 功能

从命令文件批量读取 `hipblaslt-bench` 命令，在同一张 DCU 上分别执行**基线**和**优化后**的 hipBLASLt 库，自动采集 GFLOPS、耗时和 kernel 名称，生成 `results.csv`。用于验证自编译 hipBLASLt 的 kernel 优化效果（W8A8 等量化 GEMM 场景）。

### 核心特性

| 特性 | 说明 |
|------|------|
| 自动选卡 | 通过 `hy-smi` 查找 VRAM% 和 HCU% 都为 0 的空闲 GPU，无需手动指定 |
| Kernel 识别 | 通过 `--print_kernel_info` 参数获取选定的 kernel 全称（如 `Cijk_Alik_Bljk_F8BS_MT16x16x64_...`） |
| 参数解析 | 自动从命令中解析 m、n、k、transA、transB、data type、bias、scale 等全部参数 |
| 限流重试 | 内置指数退避重试机制，自动处理 DCU 集群的 rate limit 错误 |
| 结果汇总 | 输出 `results.csv`，包含基线/优化后的 kernel 名称、GFLOPS、耗时及百分比变化 |

### 触发词

`blaslt对比`、`blaslt-compare`、`hipblaslt对比`、`blaslt测试`、`blaslt性能对比`

### 输入

命令文件，每行一条完整的 `hipblaslt-bench` 命令，示例：

```
hipblaslt-bench --api_method c -m 10240 -n 1 -k 8192 --lda 8192 --ldb 8192 --ldc 10240 --ldd 10240 --stride_a 0 --stride_b 0 --stride_c 0 --stride_d 0 --alpha 1.000000 --beta 0.000000 --transA T --transB N --batch_count 1 --scaleA 2 --scaleB 2 --bias_vector --bias_source d --a_type f8_r --b_type f8_r --c_type bf16_r --d_type bf16_r --scale_type f32_r --bias_type f16_r --compute_type f32_r --activation_type none
```

### 输出

```
<输出目录>/
├── run_benchmarks.sh       # 执行脚本（可独立复用）
├── results.csv             # 汇总结果（含kernel名称、GFLOPS、耗时、百分比）
└── logs/
    ├── baseline/           # 基线执行日志
    └── optimized/          # 优化后执行日志
```

### 输出字段

| 字段 | 含义 |
|------|------|
| `baseline_kernel` / `optimized_kernel` | gemm kernel 全称（从 `--print_kernel_info` 输出解析） |
| `baseline_gflops` / `optimized_gflops` | 吞吐量 (GFLOPS) |
| `baseline_us` / `optimized_us` | 耗时 (微秒) |
| `gflops_pct` | 优化后 / 基线 GFLOPS × 100%（>100% 表示吞吐提升） |
| `us_pct` | 基线 / 优化后耗时 × 100%（>100% 表示耗时缩短） |

### 使用流程

1. 准备包含 `hipblaslt-bench` 命令的文件（每行一条命令）
2. 提供自编译的优化后 hipBLASLt 库路径（`libhipblaslt.so` 所在目录）
3. 在 Claude Code 中说"blaslt对比"或类似关键词
4. Skill 自动查找空闲 GPU、执行 benchmark、生成 results.csv

### 注意事项

- 每条命令执行约 3-10 秒，24 条命令全流程约 5-10 分钟
- 需要 `hipblaslt-bench` 可执行权限：`chmod +x /opt/dtk/lib/hipblaslt/benchmark_tool/hipblaslt-bench`
- 优化库通过 `LD_LIBRARY_PATH` 注入，不影响系统默认库
- 脚本内置重试机制，自动处理 DCU 集群限流（rate limit）错误
- 超时默认 300 秒，可在脚本中调整

---

## Skill 3: llm-prof - 大模型推理 Profiling 分析

### 功能

端到端的大模型推理性能分析工具。支持两种模式：

1. **完整模式**：启动 vLLM/SGLang 推理服务 → 执行 bench profiling → 分析 trace 文件 → 输出算子耗时报告
2. **快速模式**：直接分析已有的 trace 文件（跳过服务启动和 bench 步骤）

### 核心特性

| 特性 | 说明 |
|------|------|
| 双框架支持 | 同时支持 vLLM 和 SGLang 推理框架 |
| 多模态支持 | 支持 Qwen2.5-VL、InternVL 等视觉语言模型的 profiling |
| 阶段划分 | 自动区分 Prefill 和 Decode 阶段，按 step 粒度分析 |
| 算子分类 | 将 kernel 归为 6 大类：gemm、通信、FlashAttention、Triton、其他 elementwise、memcpy/memset |
| 多格式输出 | Excel 报告（4 个子表）、文本摘要、JSON 结构化数据 |
| 空泡分析 | 区分"相对占比"（仅 kernel 时间）和"绝对占比"（含 GPU idle） |

### 触发词

`prof分析`、`profiling`、`算子耗时`、`推理性能`、`trace分析`、`分析trace`

### 运行目录结构

每次 profiling 运行的所有产出物统一存放在运行目录下，便于回溯：

```
<运行目录>/
├── serve.sh                   # 服务启动脚本（可独立复用）
├── serve_config.txt           # 环境变量 + 启动命令记录
├── serve.log                  # 服务端日志
├── serve.pid                  # 服务进程 ID
├── bench.log                  # bench 客户端日志
├── prof/                      # prof trace 文件目录
│   └── *.json.gz
├── prof_analysis.xlsx         # 分析报告（4 个子表）
├── prof_analysis_summary.txt  # 文本摘要
└── prof_analysis.json         # JSON 结果
```

### 分析输出

#### Excel 报告（4 个子表）

| Sheet | 内容 | 关键列 |
|-------|------|--------|
| Prefill 详细算子 | 每个 kernel 的耗时明细 | 算子名称、分类、调用次数、总耗时(us)、平均耗时(us)、相对占比(%)、绝对占比(%) |
| Prefill 分类汇总 | 按 6 大类汇总 | 分类、算子种类数、调用次数、总耗时(ms)、相对占比(%) |
| Decode-Step2 详细算子 | 每个 kernel 的耗时明细 | 同上 |
| Decode-Step2 分类汇总 | 按 6 大类汇总 | 同上 |

#### 终端输出示例

```
============================================================
  Prefill阶段算子耗时分析
============================================================
类别                  总耗时(ms)    调用次数    占比(%)
------------------------------------------------------------
gemm                      50.02        591     44.37%
通信 (comm)                 0.00          0      0.00%
FlashAttention (fa)        4.95          8      4.39%
Triton                    17.73        489     15.72%
其他elementwise            40.05        200     35.52%
memcpy/memset               0.00          0      0.00%
------------------------------------------------------------
总计                      112.74       1288    100.00%
============================================================
```

### 快速模式

如果已有 trace 文件，可跳过服务启动和 bench 步骤，直接分析：

```bash
python3 scripts/prof_analyze.py \
  --trace-file <trace.json.gz> \
  --output-dir <output_dir> \
  --decode-step 2 \
  --verbose
```

### 脚本说明

| 脚本 | 用途 |
|------|------|
| `scripts/prof_analyze.py` | 主分析脚本，解析 Chrome trace JSON，输出 XLSX/TXT/JSON |
| `scripts/prof_analyze_perfetto.py` | 基于 Perfetto trace_processor 的备选分析器（`pip install perfetto`） |
| `scripts/quick_prof.sh` | 一键 profiling 脚本，自动完成服务启动 → bench → 分析全流程 |

### 参考文件（`references/` 目录）

| 文件 | 内容 |
|------|------|
| `vllm-serve-h.log` / `sgl-serve-h.log` | serve 命令参数帮助 |
| `vllm-bench-h.log` / `sgl-bench-h.log` | bench 命令参数帮助 |
| `vllm-serve-example.sh` / `sglang-serve-example.sh` | 启动脚本示例 |
| `vllm-prof-guide.md` / `sglang-prof-guide.md` | 各框架 profiling 指南 |
| `prof算子耗时占比分析.pdf` | 分析原理文档 |
| `perfetto-sql-py工具.pdf` | Perfetto SQL 工具使用说明 |

---

## 项目结构

```
work-skills/
├── README.md
├── blas-compare/
│   └── SKILL.md                          # blas-compare skill 定义（rocBLAS GEMM 对比）
├── blaslt-compare/
│   └── SKILL.md                          # blaslt-compare skill 定义（hipBLASLt GEMM 对比）
└── llm-prof/
    ├── SKILL.md                          # llm-prof skill 定义（含完整执行流程）
    ├── scripts/
    │   ├── prof_analyze.py               # 主分析脚本（Chrome trace → XLSX/TXT/JSON）
    │   ├── prof_analyze_perfetto.py      # Perfetto 版分析器
    │   └── quick_prof.sh                 # 一键 profiling 脚本
    ├── references/                       # 参考文档和示例
    │   ├── vllm-serve-example.sh
    │   ├── sglang-serve-example.sh
    │   ├── vllm-serve-h.log
    │   ├── vllm-bench-h.log
    │   ├── sgl-serve-h.log
    │   ├── sgl-bench-h.log
    │   ├── vllm-prof-guide.md
    │   ├── sglang-prof-guide.md
    │   ├── prof算子耗时占比分析.pdf
    │   └── perfetto-sql-py工具.pdf
    └── evals/
        └── evals.json                    # Skill 测试用例
```

### Skill 文件说明

每个 skill 由一个 `SKILL.md` 文件定义，包含：

- **元信息**：名称、描述、触发词
- **参数表**：需要向用户收集的输入参数
- **执行步骤**：完整的 step-by-step 流程（含可直接复用的代码片段）
- **输出格式**：预期产出物和字段说明
- **注意事项**：边界条件和常见问题

Claude Code 加载 skill 后，会根据 `SKILL.md` 中的指令自动编排执行流程。

---

## 依赖

### 环境要求

- 海光 DCU 环境（ROCm/HIP）
- `hy-smi` 命令（DCU 状态查询）
- Python 3

### Python 包

| 包 | 用于 | 安装 |
|----|------|------|
| `openpyxl` | llm-prof Excel 报告生成 | `pip install openpyxl` |
| `perfetto` | llm-prof Perfetto 版分析器（可选） | `pip install perfetto` |

### 系统工具

| 工具 | 用于 | 说明 |
|------|------|------|
| `rocblas-bench` | blas-compare benchmark 执行 | 默认路径 `/opt/dtk/lib/rocblas/benchmark_tool/rocblas-bench` |
| `hipblaslt-bench` | blaslt-compare benchmark 执行 | 默认路径 `/opt/dtk/lib/hipblaslt/benchmark_tool/hipblaslt-bench` |
| `vllm` | llm-prof vLLM 推理服务 | `pip install vllm` |
| `sglang` | llm-prof SGLang 推理服务 | `pip install sglang` |
