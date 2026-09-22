# Reliable Task Execution 使用指南

`reliable-task-execution` 是一个通用编码任务执行 Skill。它不会替代框架、语言或硬件领域知识，而是统一控制任务如何被理解、拆分、执行、验证和报告。

适用场景包括：

- 框架和功能开发；
- Bug 定位与修复；
- 算子、Kernel、Native 扩展和设备后端开发；
- 性能优化和优化前后对比；
- 跨模块、跨仓库、跨会话或依赖真实环境的长任务。

## 安装

从 `work-skills` 仓库复制到 Codex 用户级 Skills 目录：

```bash
mkdir -p ~/.codex/skills
cp -r reliable-task-execution ~/.codex/skills/
```

开发时也可以使用符号链接，使源码修改立即生效：

```bash
ln -s /path/to/work-skills/reliable-task-execution \
  ~/.codex/skills/reliable-task-execution
```

如果同名目录已经存在，请先确认它是否是需要保留的版本，不要直接覆盖。

安装后可在 Codex CLI 或 IDE 扩展中运行：

```text
/skills
```

也可以输入 `$`，确认候选列表中存在：

```text
reliable-task-execution
```

Codex 通常会自动检测 Skill 变更；如果没有出现，请重启 Codex。

## 调用方式

### 显式调用（推荐）

在任务开头加入：

```text
$reliable-task-execution
```

例如：

```text
$reliable-task-execution

为当前项目增加一个新的配置校验功能，补充回归测试，并运行相关集成测试。
```

显式调用最可靠，适合重要、长时间或需要严格验证的任务。

### 隐式调用

直接描述符合 Skill 用途的任务时，Codex 也可能根据 `description` 自动选择该 Skill，例如：

```text
定位这个偶发超时的根因，完成最小修复，并提供可以证明修复有效的回归测试。
```

如果必须确保 Skill 被使用，请使用显式调用。

## 推荐提示格式

不需要把所有字段都写全，但以下结构最容易得到稳定结果：

```text
$reliable-task-execution

目标：
<希望最终得到的用户可观察结果>

约束：
- <不能修改的范围>
- <兼容性要求>
- <权限、成本、硬件或时间边界>

验收：
- <必须通过的行为或测试>
- <必须运行的构建、集成或真实环境验证>

补充：
- <计划位置、目标节点、设备、模型、数据等>
```

## Skill 如何组织任务

### 任务模式

Skill 会根据范围和风险选择最轻但足够可靠的模式：

| 模式 | 适用情况 | 计划形式 |
| --- | --- | --- |
| Quick | 明确、局部、低风险、易回滚 | Outcome / Change / Verify 微计划 |
| Standard | 多步骤行为变更，通常一个会话完成 | 有序任务或紧凑 Workstream |
| Extended | 高风险、跨模块、硬件依赖、多会话或实现方向不确定 | 可恢复的 Living Plan |

任务模式不按文件数量机械判断。一个单文件权限修改可能是 Extended；一个多文件机械改名可能只是 Standard。

### Workstream

当请求包含多个可以独立成功或失败的目标时，Skill 会拆成不同 Workstream。

例如：

```text
优化算子，并给出优化前后性能对比
```

会拆成：

```text
Workstream 1：优化实现
Workstream 2：性能评估
Integration：正确性通过后，使用冻结的 Benchmark 合同完成 after 测量
```

每个 Workstream 都应包含：

- Goal；
- 小目标步骤；
- Dependencies；
- Acceptance；
- Verification。

格式化、提交等普通机械动作不会被单独包装成 Workstream，除非它们本身就是用户要求的交付物。

## 使用示例

### 1. 框架或功能开发

```text
$reliable-task-execution

在当前推理框架中增加一个可插拔调度后端。

约束：
- 保留旧配置兼容性；
- 遵循现有 Backend 扩展模式；
- 不重构无关调度逻辑。

验收：
- 从真实配置入口选择新 Backend；
- 新旧 Backend 集成测试通过；
- 旧配置行为不变。
```

预期拆分方向：

```text
现有架构和扩展点
→ 接口与兼容合同
→ 最小端到端薄链路
→ 必要功能扩展
→ 跨模块集成与兼容验证
```

### 2. Bug 定位和修复

```text
$reliable-task-execution

定位并修复偶发请求超时。目前只有线上日志，没有稳定复现。
不要直接重写整个调度器。
```

预期可能拆成：

```text
Workstream 1：诊断
- 建立失败信号
- 缩小复现条件
- 排列原因假设
- 增加窄范围观测
- 获得根因证据

Workstream 2：修复
- 增加回归测试
- 实现最小修复
- 验证原始现象
- 运行受影响回归
```

诊断尚未得到证据时，不应直接进入大规模重写。

### 3. 算子或 Native 组件开发

```text
$reliable-task-execution

开发一个 SDAA 归一化算子：
- 定义 Python 接口；
- 实现 native kernel；
- 完成注册和构建；
- 增加 reference、非法输入、边界和真实设备测试。

没有要求性能优化。
```

预期拆分方向：

```text
语义合同
→ SDK/API probe
→ 最小正确 Kernel
→ 注册与构建集成
→ 分层测试
→ 真实设备证据
```

因为没有要求性能优化，不应创建多余的 Benchmark Workstream。

### 4. 性能优化和对比

```text
$reliable-task-execution

优化 teco-matmul，并提供可信的优化前后性能数据。
优化方向包括 tile、数据搬运和双缓冲；在远程 SDAA 节点验证。
```

预期拆成：

```text
Workstream 1：优化实现
1. 冻结正确性和支持范围
2. 定位瓶颈并提出优化假设
3. 调整 tile 并验证
4. 改善搬运/复用并验证
5. 增加重叠或双缓冲并验证

Workstream 2：性能评估
1. 冻结设备、shape、dtype、构建、warmup、次数和计时边界
2. 在优化前保存 baseline 原始样本
3. 正确性通过后采集 after 样本
4. 计算 median、mean、min/max、吞吐和 speedup
5. 报告噪声、回退、不支持情况和结论边界
```

性能变快不能替代正确性；正确但没有受控测量，也不能完成性能评估 Workstream。

### 5. 只生成计划，不修改代码

```text
$reliable-task-execution

只规划，不修改任何文件。

为下面的任务生成可执行计划：
<任务描述>

要求：
- 检查真实仓库；
- 拆分独立 Workstream；
- 每个 Workstream 给出小目标、依赖、验收和验证；
- 最终使用 PLAN_READY 或 PLANNING_BLOCKED。
```

### 6. 继续已有长任务

```text
$reliable-task-execution

读取 plans/2026-09-22-example.md，从 Resume Snapshot 继续。
开始前核对工作树、计划和上次验证是否仍有效。
完成步骤后更新 Progress、Discoveries、Verification Matrix 和下一动作。
```

### 7. 只做完成验收

```text
$reliable-task-execution

不要修改代码。对当前工作树执行完成验收：
- 对照原始请求；
- 检查实际 diff；
- 检查每个 Workstream 的验收和证据；
- 检查构建、集成和真实目标验证；
- 判断总体是 COMPLETE、PARTIAL 还是 BLOCKED。
```

## 状态说明

### 规划状态

| 状态 | 含义 |
| --- | --- |
| PLAN_READY | 计划已具备可执行的小目标、依赖和验证 |
| PLANNING_BLOCKED | 缺少会改变方向、风险或授权的关键信息 |

### 实现状态

| 状态 | 含义 |
| --- | --- |
| COMPLETE | 所有必需 Workstream 和集成 Gate 都有新鲜证据 |
| PARTIAL | 已完成部分有价值结果，但仍有必需目标或证据缺失 |
| BLOCKED | 由于环境、权限、硬件、外部服务或方向问题无法继续 |

关键原则：

```text
代码存在 != 已验证
测试通过 != 真实目标完整交付
一个 Workstream 完成 != 整个请求完成
```

## 什么时候不应该使用

通常不需要显式调用本 Skill 的情况：

- 纯概念解释；
- 普通翻译或文案改写；
- 不涉及仓库变更的简单问答；
- 用户只需要一条无需验证的临时命令。

明显的一行低风险修改仍可以使用，但 Skill 应选择 Quick，而不是生成大型 Living Plan。

## 文件结构

```text
reliable-task-execution/
├── SKILL.md
├── README.md
├── agents/
│   └── openai.yaml
├── evals/
│   └── evals.json
└── references/
    ├── execution-plan-template.md
    ├── task-modes.md
    ├── verification-contract.md
    └── workstream-patterns.md
```

`README.md` 面向使用者；`SKILL.md` 和 `references/` 才是 Codex 执行时使用的指令。
