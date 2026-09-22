# Work Skills

Claude Code / Codex 自定义 Skills 集合。主体面向 **海光 DCU (ROCm)** 平台的 GPU 性能分析工作流，另含远程开发与环境配置类 skill。

## 目录

| Skill | 简介 |
|-------|------|
| [blas-compare](#skill-1-blas-compare---gemm-性能对比) | 在容器内对比基线 / 优化后 rocBLAS 的 GEMM 性能，自动采集 GFLOPS 与耗时并生成对比表 |
| [blaslt-compare](blaslt-compare/SKILL.md) | hipBLASLt GEMM 性能对比：批量执行 `hipblaslt-bench`，采集 GFLOPS、耗时与 kernel 名称 |
| [cc-switch-claude-401](#skill-6-cc-switch-claude-401---claude-cli-401-排障) | 修复 cc-switch 启动的 Claude CLI 报 401 / 密钥冲突警告：定位失效 key，把 token 归位到正确的认证字段 |
| [gpu-container-lookup](#skill-8-gpu-container-lookup---加速卡占用反查) | 反查「节点 X 的物理卡 N 被哪个容器占用」：卡 → 占用进程 PID → `docker top` / cgroup 定位容器名 |
| [install-vscode-server](install-vscode-server/SKILL.md) | 在远程容器 / 服务器内快速安装 VS Code Server，绕过 Remote 连接时的慢速自动下载 |
| [llm-prof](#skill-2-llm-prof---大模型推理-profiling-分析) | 启动 vLLM / SGLang 服务跑 bench profiling，分析 trace 输出 prefill / decode 算子耗时汇总表 |
| [prof-analy](#skill-3-prof-analy---模型性能分析) | 解析 PyTorch profiling trace，按算子类别（gemm / attention / conv 等）汇总耗时并生成报告 |
| [reliable-task-execution](#skill-7-reliable-task-execution---可靠任务执行) | 按任务风险自适应选择 Quick / Standard / Extended 流程，建立可恢复计划、分层验证和基于证据的完成状态 |
| [remote-agent-config](#skill-5-remote-agent-config---远程-agent-配置同步) | 从 cc-switch 预设渲染 Claude Code / Codex 配置并推送到远程节点，直连模型 API、摆脱反向 SSH 隧道 |
| [remote-dev](#skill-9-remote-dev---远程开发容器) | SSH 到加速卡节点，检查 / 复用 / 创建并验证 Docker 开发容器（太初 / NVIDIA / 通用兜底） |
| [ssh-docker](#skill-4-ssh-docker---远程-ssh-docker-工作流) | 通过 SSH + `docker exec` 在远程容器执行编译 / 测试 / profiling，代码本地编辑再同步 |

其余章节：[安装](#安装) · [项目结构](#项目结构) · [依赖](#依赖) · [许可证](#许可证) · [作者](#作者)

---

## 安装

按使用的客户端将 skill 目录复制到对应的用户级 skills 目录：

```bash
cp -r blas-compare ~/.claude/skills/
cp -r blaslt-compare ~/.claude/skills/
cp -r cc-switch-claude-401 ~/.claude/skills/
cp -r gpu-container-lookup ~/.claude/skills/
cp -r install-vscode-server ~/.claude/skills/
cp -r llm-prof ~/.claude/skills/
cp -r prof-analy ~/.claude/skills/
cp -r ssh-docker ~/.claude/skills/
cp -r remote-agent-config ~/.claude/skills/
cp -r remote-dev ~/.claude/skills/

# Codex 用户级 skill
cp -r reliable-task-execution ~/.codex/skills/
```

安装后在对应 Agent 对话中触发关键词，或使用显式 skill 名称调用。

> `remote-agent-config` 的 `sync.py` 会被 skill 按固定路径调用，请保持它与 `SKILL.md` 平级、不要单独挪动。

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

## Skill 5: remote-agent-config - 远程 Agent 配置同步

### 功能

把 Claude Code / Codex 的模型配置推送到 `~/.ssh/config` 里的远程节点，让远程 agent **直接调用模型 API**，不再依赖指回笔记本的反向 SSH 隧道（`RemoteForward 15721`）。配置从 **cc-switch 的 provider 预设**渲染，可指定把哪一个预设同步到哪一台机器。

### 核心特性

| 特性 | 说明 |
|------|------|
| 预设可选 | 从 `~/.cc-switch/cc-switch.db` 读出全部 provider 预设，`--list-providers` 列出（`*` 标当前激活），按名字选用，唯一子串即可匹配 |
| 读预设而非生效文件 | 生效文件常被 cc-switch 本地代理改写成 `127.0.0.1:15721`；预设里存的才是真实上游 `base_url` 与凭据，这才是远程能直连的来源 |
| Codex 改写而非照搬 | 只保留可移植的键，丢掉 `[windows]` / `[projects.*]` / `[mcp_servers*]` 与 Windows 路径；紧凑 `modelCatalog` 展开为 Codex 原生模型描述格式 |
| 幂等推送 | 先比对远程已有内容（JSON 结构比较、TOML 归一化），一致则跳过且不写不备份；`--force` 强制重写 |
| 安全 | 备份到 `<file>.bak-时间戳`，`chmod 600`；`--dry-run` 输出自动脱敏；拒绝推送 loopback `base_url` 和无 `base_url` 的官方登录型预设 |

### 触发词

`remote-agent-config`、`同步配置到服务器`、`远程用 DeepSeek`、`换个渠道`、`换个 provider`、`远程 agent 掉线`

### 输入

调用时用 `question` 工具交互式询问（中文）：

1. **节点选择**：全部节点，或指定别名 / IP（逗号分隔多个）
2. **同步内容**：全部（claude + codex）/ 仅 Claude / 仅 Codex
3. **cc-switch 预设**：每个 agent 问一次，首项为「当前激活」，其后为该 agent 的其余预设

### 输出

- 远程 `~/.claude/settings.json`、`~/.codex/config.toml`、`~/.codex/auth.json`、`~/.codex/cc-switch-model-catalog.json`
- 合并写入 `~/.vscode-server/data/Machine/settings.json` 的 `claudeCode.environmentVariables`（其余键保留）
- 末行汇总：`done: N updated, M already up to date (targets)`

---

## Skill 6: cc-switch-claude-401 - Claude CLI 401 排障

### 功能

修复 cc-switch 启动的 Claude CLI 报 401（Invalid/Missing API key）或启动警告 `Both ANTHROPIC_AUTH_TOKEN and ANTHROPIC_API_KEY set`。核心是理清 Claude Code 的认证头由**变量名**决定：token 放 `ANTHROPIC_API_KEY` 发 `x-api-key: <token>`，放 `ANTHROPIC_AUTH_TOKEN` 发 `Authorization: Bearer <token>`；两变量并存时优先用 `ANTHROPIC_API_KEY` 并打警告。cc-switch 的 OpenCode 渠道（`https://opencode.ai/zen/go`）只认 `x-api-key` 头，token 放错字段即 401。

### 核心特性

| 特性 | 说明 |
|------|------|
| 报错速查 | 三种 401 场景对照病因与修法：双 key 冲突 / 认证头不对 / key 真失效 |
| 双处同步 | cc-switch.db 的 `settings_config` 与 `~/.claude/settings.json` 必须一起改；只改库不改文件，CLI 照样 401 |
| 实测优先 | 用 `curl` 分别试 `x-api-key` 与 `Bearer` 两种头，确认哪把 key 有效、该放哪个字段，不靠猜 |
| 残留清理 | 用旧 key 前缀 grep 全部 claude 配置，确认新旧 key 没有各占一个字段 |

### 报错 → 病因速查

| 报错 / 现象 | 病因 | 修法 |
|---|---|---|
| 401 "Invalid API key" + `Both ... set` 警告 | 两个变量都有值，优先用的 `ANTHROPIC_API_KEY` 是失效旧 key | 删失效 key，有效 token 归位到正确字段 |
| 401 "Missing API key"，无警告 | 只剩 `AUTH_TOKEN`，但端点只认 `x-api-key` 头 | token 移到 `ANTHROPIC_API_KEY` 字段 |
| 其他 401 且端点非 opencode zen | token 本身失效，或 `base_url` 错 | 找发 token 的渠道重新要 key |

### 触发词

`cc-switch 401`、`Claude 401`、`Invalid API key`、`Missing API key`、`Both ANTHROPIC_AUTH_TOKEN and ANTHROPIC_API_KEY set`、`密钥冲突`、`auth may not work as expected`

### 输入

报错信息或现象描述。skill 会引导检查四处：报错标题里的临时配置文件、`~/.claude/settings.json` 的 `env` 段、`~/.cc-switch/cc-switch.db` 的 `providers` 表、`curl` 实测结果。

### 输出

- 病因判定（对照速查表）
- 删失效 key / token 字段归位后的 `~/.claude/settings.json` 与 cc-switch.db（改库前需先关 cc-switch 进程，防退出时内存态覆盖）
- 验证结论：重开 CLI 无警告、对话正常

---

## Skill 7: reliable-task-execution - 可靠任务执行

### 功能

为框架/功能开发、Bug 定位修复、算子或 native 组件开发、性能优化等编码任务提供通用执行闭环：先识别独立目标并拆成 Workstream，再为每条工作流定义清晰的小目标、依赖、验收和验证；同时根据复杂度选择 Quick / Standard / Extended 模式。

### 核心特性

| 特性 | 说明 |
|------|------|
| 自适应规划 | 小任务使用微计划，普通任务使用有序任务列表，复杂任务使用可恢复 Living Plan |
| 多目标拆分 | 将可以独立成功或失败的目标拆成不同 Workstream，每条工作流有自己的步骤、验收和证据 |
| 小目标分解 | 每个 Workstream 拆成 2-5 个可独立验证的小目标，适用于功能开发、诊断修复、算子开发和优化 |
| 风险前置 | 对不可检查的 native SDK、外部 API 或版本化接口，先获取正式合同或运行最小探针 |
| 领域模式路由 | 按需加载框架开发、Bug 诊断、算子/native 开发、性能优化四类 Workstream 模式，不把某个案例当通用流程 |
| 分层验证 | 区分源码存在、聚焦测试、回归、构建、集成、运行时注册和真实目标验证 |
| 完成诚实性 | 规划使用 `PLAN_READY` / `PLANNING_BLOCKED`；实现使用 `COMPLETE` / `PARTIAL` / `BLOCKED` |
| Eval 覆盖 | 覆盖 Quick、Standard、框架功能、Bug 诊断修复、算子开发、优化对比、硬件依赖和虚假完成等场景 |

### 调用示例

```text
$reliable-task-execution

在 tecovllm 中实现一个 SDAA 自定义算子。先检查现有注册和构建模式；没有真实硬件证据时不要报告 COMPLETE。
```

---

## Skill 8: gpu-container-lookup - 加速卡占用反查

### 功能

回答「节点 X 的物理卡 N 被哪个容器占用」。思路是 **卡 → 占用进程 PID → 反查容器名**，刻意不用 `docker inspect` 的设备映射：实际节点上的容器几乎全是 privileged 且 `Devices` 为空，从映射关系根本看不出来归属。

### 核心特性

| 特性 | 说明 |
|------|------|
| 固化脚本 | `scripts/gpu-container-lookup.sh` 一次跑完：裸 IP → `~/.ssh/config` 别名、卡型探测、PID 反查、结论行 + 证据表；脚本异常时回落到 SKILL.md 的手工步骤 |
| 双卡型 | 太初（`teco-smi`）与 NVIDIA（`nvidia-smi`，用 `gpu_uuid` 把进程对回卡 index） |
| 反查双路 | `docker top` 为主，`/proc/<PID>/cgroup` 兜底（兼容 cgroup v1 / v2 / containerd）；docker 权限不足自动降级 `sudo -n` |
| 三态结论 | busy / idle（显存空）/ stuck（无进程但显存未释放），把「显存泄漏」和「真空闲」区分开 |

### 触发词

`哪张卡被占`、`卡反查容器`、`GPU 占用`、`卡的使用情况`、`物理卡 N 是谁`、`gpu-container-lookup`

### 输入

- **节点**：IP 或 ssh 别名；用户没写就用 AskUserQuestion 问一次，写了就别再问
- **卡号**：可选，Index 从 **0** 起（Index 2 = 第 3 张物理卡）。给了只查该卡，没给则扫全部

### 输出

- 结论行：`卡 N -> 容器名`（查不到容器则如实标注「宿主机进程」）
- 证据表：Index / Bus-Id / 卡显存 / Util / PID / 进程 / 进程显存 / 容器名
- 空闲与显存未释放清单 + Index 口径说明

---

## Skill 9: remote-dev - 远程开发容器

### 功能

SSH 到远程加速卡节点，**检查 / 复用 / 创建并验证 Docker 开发容器**，把「本地开发、远程容器里验证运行」的环境准备好。只负责容器就绪与验证，跑实验、同步代码不在范围内。

### 核心特性

| 特性 | 说明 |
|------|------|
| 说到就干 | 提到具体节点就连上去摸底（只读操作），不反问；只有「完全没提节点」或「新建缺镜像/挂载路径」才问，且一次性问完 |
| 三卡型分支 | 太初（`teco-smi`、`/dev/tcaicard*`、官方 tar 镜像）／NVIDIA（`--gpus`、NGC 镜像）／昇腾·寒武纪通用兜底（试验性） |
| 驱动-镜像匹配 | 按宿主 TecoDriver 版本对照兼容表选 TecoToolKit 镜像；容器与宿主驱动版本必须一致，对不上先换镜像不硬建 |
| 容内验证 | `import torch_sdaa` / `torch.cuda.is_available()` + `teco-smi -c` 卡健康；失败按排查顺序如实报卡点，不伪造「看起来成功」 |
| 边界清晰 | 到「容器就绪并验证通过」为止；卡占用反查让位给 `gpu-container-lookup`，跑实验交给下游 skill |

### 触发词

`开个开发容器`、`在 XX 节点建容器 / 进容器`、`没有容器就建一个`、`准备远程开发环境`、`XX 节点有哪些容器`、`remote-dev`

### 输入

- **节点**：从 `~/.ssh/config` 读 Host 别名（sdaa 集群 65056 端口，H100 要过跳板机），只有用户完全没提节点时才列别名问一次
- **可选**：容器名、镜像、挂载路径 —— 缺关键参数才问，且连同摸底结论（空闲卡、现成镜像、驱动版本）一起问

### 输出

- 证据表：节点 / 容器 / 镜像 / 挂载卡 / 验证结果 / 挂载路径
- 进入命令：`docker exec -it <容器名> bash`，以及 VSCode Dev Containers **Attach**（零侵入，推荐）或容器内 sshd（仅明确要求时）

---

## 项目结构

```
work-skills/
├── README.md                  # 项目说明文档
├── blas-compare/              # BLAS GEMM 性能对比 skill
│   └── SKILL.md
├── blaslt-compare/            # hipBLASLt GEMM 性能对比 skill
│   └── SKILL.md
├── cc-switch-claude-401/      # cc-switch Claude CLI 401 排障 skill
│   └── SKILL.md
├── gpu-container-lookup/      # 加速卡占用反查 skill
│   ├── SKILL.md
│   └── scripts/
│       └── gpu-container-lookup.sh
├── install-vscode-server/     # 远程快速安装 VS Code Server skill
│   └── SKILL.md
├── llm-prof/                  # 大模型推理 Profiling 分析 skill
│   ├── SKILL.md
│   ├── evals/
│   │   └── evals.json
│   ├── references/            # vLLM / SGLang 指南、示例与样例日志
│   └── scripts/
│       ├── prof_analyze.py
│       ├── prof_analyze_perfetto.py
│       └── quick_prof.sh
├── prof-analy/                # 模型性能分析 skill
│   ├── skill.md               # Skill 定义文件
│   ├── analyze.py             # 核心分析脚本
│   ├── README.md              # 详细说明文档
│   ├── QUICKSTART.md          # 快速开始指南
│   ├── example.py             # 使用示例
│   ├── test_prof_analy.py     # 测试脚本
│   └── .gitignore
├── reliable-task-execution/   # 自适应规划、执行与证据验证 skill
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── evals/evals.json
│   └── references/
├── remote-agent-config/       # 远程 Agent 配置同步 skill
│   ├── SKILL.md               # Skill 定义文件
│   └── sync.py                # 推送脚本（须与 SKILL.md 平级）
├── remote-dev/                # 远程开发容器 skill
│   └── SKILL.md
└── ssh-docker/                # SSH Docker 远程工作流 skill
    └── SKILL.md
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

### remote-agent-config 依赖

- Python 3.11+（只用标准库 `tomllib` / `sqlite3`，无需额外 pip 包）
- OpenSSH 客户端（`ssh` / `scp`）
- 本机已安装 cc-switch（读取 `~/.cc-switch/cc-switch.db` 的 `providers` 表）；没有 cc-switch 时可用 `--from-live` 直读生效文件
- 远程节点: 无需任何依赖，只落配置文件

### cc-switch-claude-401 依赖

- Python 3（标准库 `sqlite3` / `json`，无需额外 pip 包）
- `curl`（实测 key 有效性与认证头类型）
- 本机已安装 cc-switch（读写 `~/.cc-switch/cc-switch.db`；改库前须先关 cc-switch 进程）
- 仅适用 Windows 上由 cc-switch 启动的 Claude CLI

### gpu-container-lookup 依赖

- bash 4.4+（脚本用关联数组）+ OpenSSH 客户端
- 远程节点: `docker`（权限不足时脚本自动降级 `sudo -n`）、`teco-smi` 或 `nvidia-smi`
- 无 Python / pip 依赖

### remote-dev 依赖

- OpenSSH 客户端（`ssh` / `scp`）
- 远程节点: Docker；太初节点需 `/opt/tecoai/bin/teco-smi`，NVIDIA 节点需 `nvidia-smi`，用 `--gpus` 还需 nvidia-container-toolkit
- 镜像: 太初官方 tar（`jfrog.tecorigin.net/tecotp-docker/...`）或 NGC PyTorch（`nvcr.io/nvidia/pytorch:<tag>-py3`）

---

## 许可证

MIT License

## 作者

Work Skills Team
