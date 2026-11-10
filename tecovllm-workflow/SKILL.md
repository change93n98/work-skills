---
name: tecovllm-workflow
description: 在远程 T100 节点按阶段准备 TecovLLM 环境、启动模型服务、跑性能或精度测试、dump size 和抓 prof。用于构建或更新容器，以及编写或执行简洁的 vllm serve 和 teco-modeltest 客户端脚本。
---

# TecovLLM 工作流

按用户指定的阶段执行，并检查该阶段用到的前置条件。准备环境时执行第 1、2 步。已有容器时可直接调用第 3 步。已有符合用途的就绪服务时，可单独调用第 4 至第 7 步。

第 4、5 步使用未配置 `--profiler-config` 的普通服务。第 6、7 步分别使用对应的诊断服务。已有服务按 [启动配置检查](references/start-service.md#按用途选择服务) 验证后再复用。

各阶段获取仓库默认使用 HTTP(S) Git 地址，包括 clone、fetch、pull 和子模块。内网 GitLab 凭据通过 Git 的认证渠道传入，仓库 URL 和脚本只写项目地址。

## 1. 检查节点

- 用 `remote-dev` 从发起机器的 SSH 配置解析目标节点和跳板。登录后核对宿主 `hostname`、Docker 权限、T100 设备与驱动。容器和挂载信息都在执行节点查询。
- **2A 新建**需要确定宿主任务目录、源码版本和新容器名。未指定版本时取远端默认分支。沿用 `remote-dev` 的命名规则补齐未指定的容器名，按目标节点核对构建目录、磁盘空间和任务需要的挂载。
- **2B 换版**需要已有容器名和目标分支或 commit。通过 `docker inspect` 核对容器身份、镜像和挂载。定位容器实际使用的源码目录，确认没有正在使用待更新环境的服务或任务。
- 查询 T100 的物理卡和占用。容器可用后核对物理卡与容器内逻辑设备的对应关系。提供了模型路径或服务端口时，核对挂载和宿主端口。起服务前再确认一次资源状态。

用户要求先看计划时，做到只读检查，输出选定的分支、容器和源码目录。执行时按实际结果补齐关键参数。

## 2. 准备容器

新建走 **2A**，在指定的已有容器内更新走 **2B**。按 [容器准备命令](references/prepare-container.md) 执行。

构建和安装任一步失败时停在该步骤，保留日志和实际状态。换版中断时说明旧包是否已卸载、哪些系统包已变更，以及从哪里恢复。

验收通过后给出执行节点、容器名、镜像 tag 或 ID、宿主与容器内源码路径、TecovLLM 和 vLLM 的 commit、Python 环境、实际加载路径、系统包变更和日志位置。

## 3. 启动模型服务

用 `simple-test-scripts` 选择或编写本次的服务端脚本。优先用用户指定的命令或脚本。需要从历史找参考时，按实际权重、容器版本和场景匹配。同一模型的不同配置分别保留为短脚本。按 [服务端脚本与启动验收](references/start-service.md) 执行。

只要求写脚本或先看方案时，交付脚本和静态校验结果。用户要求启动时，用 `remote-dev` 在目标容器运行，并在验收后交付服务地址、模型名、脚本和日志位置。

## 4. 跑性能测试

按 [性能客户端与固定预热](references/run-performance.md) 执行。使用本次通过 HTTP 获取的 `teco-modeltest` 最新 `vllm` 分支，直接调用原生 `vllm_requests.py`。每次正式客户端脚本执行前，对同一服务先跑一次固定图文预热，再执行本次测试矩阵。

## 5. 跑精度测试

按 [精度客户端与数据集](references/run-precision.md) 执行。使用本次通过 HTTP 获取的 `teco-modeltest` 最新 `vllm` 分支。简单验证跑 HumanEval，多模态验证跑 MMMU-Pro，提测依次跑 LongBench v2、ToolBench、MVBench。按实际 checkout 确认原生入口和依赖。

## 6. Dump size

按 [Dump size 采集](references/dump-size.md) 执行。在诊断服务上复跑正式客户端请求，先隔离服务启动和所有预热产生的 dump，再对正式请求的尺寸记录去重。

## 7. 抓 prof

按 [Prof 采集](references/capture-prof.md) 执行。使用带 `--profiler-config` 的诊断服务，以 `start_profile`、目标请求、`stop_profile` 的顺序抓 trace。需要分析 trace 时按任务使用 `llm-prof`。
