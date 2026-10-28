---
name: vllm-phase-profiler
description: "在 vLLM/SDAA 的独立诊断副本中添加 PHASE_GRAPH profiler scope，显示每轮 prefill/decode/mixed、token 数及实际 PIECEWISE/FULL/NONE 模式，并核验 trace。适用于用户要看短 prefill 是否误用 decode graph、原生 trace 缺少 mode 标注或希望复用阶段标注；普通吞吐测试和仅做算子分类不需要此技能。"
---

# vLLM 阶段与 Graph 标注

目标：让真实模型 forward 在 trace 中显示类似下面的 `user_annotation`，用实际选图结果回答“本轮到底走什么图”，不根据 token 数或 GraphLaunch 是否出现来猜。

```text
PHASE_GRAPH step=27 phase=prefill tokens=2 padded=2 mode=PIECEWISE computed=[33841] prompt=[83008]
```

## 按用户请求选择操作

- 只要求总结、脚本或配置：交付说明/文件，不启动服务、占卡或发请求。
- 已有 trace：先检查是否已有阶段、token 数及 mode；不为解释已有证据重新部署。
- 要求采集或补齐 mode 标注：核对环境后，准备诊断副本并执行用户授权的采集。
- 用户只开了 `detailed_trace_annotation`，却仍搜不到 `PHASE_GRAPH`：说明原生开关只扩展 context/generation 等信息；精确的自定义名称和 mode 需要代码中的 `record_function()`。

## 找准执行位置

复用会话已知的节点、容器、模型、并行度、输入输出、可见卡及原生客户端。缺少会改变实验含义的参数才询问，不把历史示例固化为默认值。

1. 核对安装模式、`__file__`/`inspect.getsourcefile()`、Git 状态和实际 runner。继承路径及 V1/V2、模型自定义入口会随版本变化。
2. 找到真实请求的 `execute_model()`、最终 graph 分发结果以及实际 forward；不要仅按文件名或补丁行号定位。
3. 阶段来自请求状态或该 runner 的阶段字段。检查字段语义；仅凭 query 长度无法区分短 prefill 和 speculative decode。
4. 选图前保存本轮状态，选图后读取最终 `cudagraph_mode`，scope 包住真实 forward 和 replay。[标注模板](references/annotation-template.md) 说明插入位置及边界。

## 使用独立诊断副本

复制实际 Python 包到本次运行目录，再修改副本；涉及相对导入时保留完整包结构，不能只复制一个模块就假定 `PYTHONPATH` 有效。原生扩展、包资源和其他模块仍须可加载。

服务启动脚本显式通过 `PYTHONPATH` 加载副本。启动前/后确认诊断模块的实际路径；保存源码差异、启动命令及原文件校验值。仅增加标注和必要的加载路径，保留模型、dtype、缓存、MTP、编译、并发等实验设置。

不为了获得期望标签改变 graph 选择逻辑，不把 `PIECEWISE` 写死在标签中。用户未要求时不修改正式安装、不重装包、不提交或推送。

## 采集

需要节点/容器操作时使用现有 `remote-dev` 工作流；启动服务前确认目标卡空闲及端口可用，不停止其他任务。已有原生性能脚本时直接复用，保持脚本简洁。

配置可保留用户原参数。例如：

```json
{
  "profiler": "torch",
  "torch_profiler_dir": "./trace",
  "torch_profiler_with_stack": false,
  "torch_profiler_record_shapes": true,
  "torch_profiler_with_memory": false,
  "torch_profiler_dump_cuda_time_total": false,
  "detailed_trace_annotation": true
}
```

字段以当前版本定义为准。`detailed_trace_annotation` 可选，不是生成 `PHASE_GRAPH` 的开关；stack/shapes 也不能自动输出 mode。

服务健康后，按约定预热；用 `curl -X POST /start_profile` → 原生测试请求 → `curl -X POST /stop_profile` 采集。保证完成请求后再 stop，异常清理也避免重复 stop；新 trace 使用独立目录。输出长度及请求次数遵守用户要求，不擅自改为历史的五图/10 tokens。

## 核验与交付

- 检查请求退出码、实际完成状态、开始/停止采集 HTTP 状态和 trace 文件完整性。
- 使用运行环境中的 `scripts/inspect_phase_trace.py TRACE --output RESULT.json` 检查 scope 及同线程、同范围内的 graph launch。脚本需要 `ijson`，支持 PyTorch JSON / gzip trace；不修改原 trace，也不执行模型。
- 检查 `computed`/`prompt` 或对应阶段字段与标签一致；mode 应是实际分发值。没有命中相关用例就如实报告，不假定一定出现 2-token prefill。
- `PHASE_GRAPH` 只包主模型时，范围内计数不包括随后 MTP 草稿；原生 execute scope 可能包含二者。launch 数量随模型变化，不把 65、66 或 1 当作通用判据。
- 明确区分实际模式与 trace 特征推断。大块 prefill 可能为 NONE；不能推断所有 prefill 都该 PIECEWISE，或所有 decode 都该 FULL。
- 诊断开销不计入正式性能结论。记录生产源码校验结果、trace 路径、可搜索的真实名称、采集配置和日志；step 可能包含预热，不要求固定编号。
- 用户无继续运行需求时，停止本次服务并核对卡释放。停服后的 EngineDeadError 与采集过程错误分开记录，不删日志或笼统声称“没有错误”。
