# Work Skills

Claude Code 自定义 skills 集合，用于 GPU 性能分析和 benchmark 对比。

## Skills

### blas-compare

BLAS GEMM 单测性能对比。从 CSV 文件读取 `rocblas-bench` 命令，在空闲 GPU 上分别执行基线和优化后的 rocBLAS 库，自动采集 GFLOPS、耗时和 gemm kernel 全称，生成对比表格。

- 自动查找空闲 GPU（VRAM% 和 HCU% 都为 0）
- 通过 `TENSILE_DB=0x8000` 提取 gemm kernel 完整名称
- 输出 results.csv 和 Markdown 对比表格

触发词：`blas对比`、`blas-compare`、`gemm性能对比`、`rocblas对比`、`blas测试`

### llm-prof

大模型推理 profiling 分析。启动 vLLM/SGLang 服务，执行 bench profiling，分析 trace 输出 prefill 和 decode 算子耗时汇总表。也支持直接分析已有的 trace 文件（快速模式）。

- 支持 vLLM 和 SGLang 两种推理框架
- 自动解析 Chrome trace 格式
- 按 prefill/decode 阶段分组统计算子耗时

触发词：`prof分析`、`profiling`、`算子耗时`、`推理性能`、`trace分析`、`分析trace`

## 使用方式

将 skill 目录复制到 `~/.claude/skills/` 下，Claude Code 会自动加载。在对话中触发对应关键词即可调用。
