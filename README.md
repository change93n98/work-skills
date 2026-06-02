# Work Skills

Claude Code 自定义 Skills 集合，面向 **海光 DCU (ROCm)** 平台的 GPU 性能分析工具。包含四个独立 skill：BLAS GEMM 性能对比、大模型推理 Profiling 分析、模型性能分析和 SSH Docker 远程工作流。

## 目录

- [安装](#安装)
- [Skill 1: blas-compare](#skill-1-blas-compare---gemm-性能对比)
- [Skill 2: llm-prof](#skill-2-llm-prof---大模型推理-profiling-分析)
- [Skill 3: prof-analy](#skill-3-prof-analy---模型性能分析)
- [Skill 4: ssh-docker](#skill-4-ssh-docker---远程-ssh-docker-工作流)
- [项目结构](#项目结构)
- [依赖](#依赖)

---

## 安装

将 skill 目录复制到 Claude Code 的 skills 目录下即可自动加载：

```bash
cp -r blas-compare ~/.claude/skills/
cp -r llm-prof ~/.claude/skills/
cp -r prof-analy ~/.claude/skills/
cp -r ssh-docker ~/.claude/skills/
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
50 ./rocblas-bench -f gemm_ex --transposeA N --transposeB N -m 1024 -n 1024 -k 1024 --lda 1024 --ldb 1024 --ldc 1024 --a_type f16_r --b_type f16_r --c_type f16_r --d_type f16_r --compute_type f32
```

### 输出

- `results.csv` — 结构化结果（baseline/optimized 的 GFLOPS、耗时、kernel 名称）
- `comparison_table.md` — Markdown 对比表格

### 输出示例

```markdown
| M | N | K | Kernel | Baseline GFLOPS | Optimized GFLOPS | GFLOPS Δ | Baseline Time(us) | Optimized Time(us) | Time Δ |
|---|---|---|--------|-----------------|------------------|----------|-------------------|--------------------| -------|
| 1024 | 1024 | 1024 | Cijk_Ailk_Bjlk... | 8500.23 | 9200.45 | +8.24% | 250.5 | 230.2 | -8.10% |
```

---

## Skill 2: llm-prof - 大模型推理 Profiling 分析

### 功能

针对大语言模型推理场景，自动执行多轮 profiling 并生成详细性能报告。支持 HuggingFace Transformers 和 vLLM 两种推理后端，覆盖单请求、并发、长上下文、多卡张量并行等多种场景。

### 核心特性

| 特性 | 说明 |
|------|------|
| 多后端支持 | HuggingFace Transformers（model.generate）和 vLLM（AsyncLLMEngine） |
| 自动 Profiling | 使用 PyTorch Profiler 自动采集 CPU/GPU trace，支持 dump Chrome trace |
| 性能指标 | 首 Token 延迟（TTFT）、每 Token 延迟、Token 吞吐量、峰值显存 |
| 多场景覆盖 | 单请求、并发请求、长上下文、多卡张量并行 |
| 报告生成 | 自动生成 Markdown 格式的性能报告 |

### 触发词

`大模型prof`、`llm-prof`、`推理profiling`、`transformers prof`、`vllm prof`、`大模型性能`

### 输入

1. 模型路径（HuggingFace 格式）
2. 场景配置：
   - `single` — 单请求 profiling
   - `concurrent` — 并发请求 profiling
   - `long_context` — 长上下文 profiling
   - `tensor_parallel` — 多卡张量并行 profiling
3. 推理后端：`transformers` 或 `vllm`

### 输出

- Chrome trace 文件（JSON）— 可在 chrome://tracing 或 Perfetto UI 中可视化
- 性能报告（Markdown）— 包含各阶段耗时、GPU kernel 统计、显存使用
- 原始 profiling 数据

---

## Skill 3: prof-analy - 模型性能分析

### 功能

分析 PyTorch 模型的 profiling trace 文件，自动解析算子信息，进行智能分类，生成详细的性能分析报告。支持 `.json` 和 `.json.gz` 格式的 trace 文件。

### 核心特性

| 特性 | 说明 |
|------|------|
| 智能解析 | 支持 PyTorch Profiler 生成的 trace.json 文件 |
| 自动分类 | 将算子分为 9 大类别（conv_bn、attention、norm、gemm、elementwise 等） |
| 性能统计 | 计算调用次数、总耗时、平均耗时、占比等详细指标 |
| Excel 报告 | 生成包含两个 Sheet 的详细分析报告（算子详情 + 分类汇总） |
| 优化建议 | 基于分析结果提供针对性的优化方向 |

### 触发词

`prof-analy`、`prof分析`、`trace分析`、`算子分析`、`性能分析`

### 输入

trace.json 或 trace.json.gz 文件路径

### 输出

- **Sheet1: 算子详情** — 每个算子的详细性能数据（名称、分类、调用次数、耗时、占比）
- **Sheet2: 分类汇总** — 按类别统计的性能占比（gemm、attention、conv_bn 等）
- **优化建议** — 基于分析结果的优化方向

### 算子分类规则

| 分类 | 关键词 |
|------|--------|
| conv_bn | conv2d, conv3d, batch_norm, implicitgemm, nchw2ncxhw, nchw2cxhwn |
| attention | flash_fwd_kernel, flash_bwd_kernel, attention, scaled_dot_product |
| norm | layer_norm, rms_norm, group_norm, instance_norm, RowwiseMoments, GroupNorm |
| gemm | Cijk, gemm, matmul, bmm, linear, cublasLt, cublas |
| elementwise | add, mul, sub, div, relu, gelu, silu, sigmoid, tanh, softmax, elementwise |
| 访存 | memcpy, MemCpy, cudaMemcpy, mem_set, memset |
| reduction | sum, mean, max, min, prod, argmax, argmin |
| index | index, gather, scatter, slice, select, embedding |
| shape | reshape, view, permute, transpose, contiguous, clone |
| 其他 | 其他未分类算子 |

### 验证结果

已在多个测试目录上验证了分析结果的准确性：

| 目录 | 总耗时(us) | 算子种类数 | 总调用次数 | 验证状态 |
|------|-----------|-----------|-----------|---------|
| baseline | 15,143,713 | 98 | 55,933 | ✓ 通过 |
| opt1 | 15,532,765 | 100 | 54,290 | ✓ 通过 |
| opt2 | 15,532,765 | 100 | 54,290 | ✓ 通过 |
| opt3 | 12,388,478 | 151 | 37,238 | ✓ 通过 |
| opt4 | 12,395,739 | 151 | 37,238 | ✓ 通过 |
| opt5 | 12,368,634 | 152 | 37,198 | ✓ 通过 |

所有测试目录的分析结果与原始分析高度一致，分类准确性显著提升。

### 使用示例

```bash
# 分析 trace 文件
python3 ~/.claude/skills/prof-analy/analyze.py /path/to/trace.json.gz

# 指定输出路径
python3 ~/.claude/skills/prof-analy/analyze.py /path/to/trace.json -o output.xlsx

# 作为 Claude Skill 使用
/prof-analy /path/to/trace.json.gz
```

---

## Skill 4: ssh-docker - 远程 SSH Docker 工作流

### 功能

通过 SSH + Docker exec 在远程容器中执行编译、测试、调试任务。支持从 `~/.ssh/config` 解析节点配置，自动同步本地代码到远程，适用于 GPU 服务器开发场景。

### 核心特性

| 特性 | 说明 |
|------|------|
| 节点自动识别 | 支持输入 hostname alias（从 `~/.ssh/config` 解析）或直接 IP |
| 容器交互 | 通过 `docker exec` 在目标容器内执行命令 |
| 文件同步 | 基于 SFTP 自动同步本地代码到远程服务器 |
| GPU 感知 | 自动检测 GPU 状态、内存使用，支持设备绑定 |
| 权限处理 | 自动修复容器输出文件的所有权问题 |

### 触发词

`ssh-docker`、`远程执行`、`docker exec`、`远程调试`、`GPU开发`

### 输入

调用时交互式询问：
1. **目标节点**：hostname alias 或 IP 地址
2. **Docker 容器名**：目标容器名称
3. **工作区路径**（可选）：主机和容器的挂载路径

### 典型使用流程

```powershell
# 1. 触发 skill
/ssh-docker

# 2. 交互输入
# 节点: gpu-server1  (或 10.17.176.13)
# 容器: megamoe

# 3. 自动执行
# - 解析 SSH 配置
# - 验证连接和容器状态
# - 同步代码
# - 在容器内执行任务
```

### 输出

- SSH 连接验证结果
- 容器状态和 GPU 信息
- 远程命令执行结果
- 同步状态报告

---

## 项目结构

```
work-skills/
├── README.md              # 项目说明文档
├── blas-compare/          # BLAS GEMM 性能对比 skill
│   ├── skill.md
│   ├── run_benchmark.sh
│   ├── parse_results.py
│   └── ...
├── llm-prof/              # 大模型推理 Profiling 分析 skill
│   ├── skill.md
│   ├── run_profiling.py
│   ├── generate_report.py
│   └── ...
├── prof-analy/            # 模型性能分析 skill
│   ├── skill.md           # Skill 定义文件
│   ├── analyze.py         # 核心分析脚本
│   ├── README.md          # 详细说明文档
│   ├── QUICKSTART.md      # 快速开始指南
│   ├── example.py         # 使用示例
│   └── test_prof_analy.py # 测试脚本
└── ssh-docker/            # SSH Docker 远程工作流 skill
    └── SKILL.md           # Skill 定义文件
```

## 依赖

### 通用依赖

```bash
pip install openpyxl
```

### llm-prof 额外依赖

```bash
pip install torch transformers vllm
```

### ssh-docker 依赖

- Windows: OpenSSH 客户端
- 远程节点: Docker, SSH 服务

---

## 许可证

MIT License

## 作者

Work Skills Team
