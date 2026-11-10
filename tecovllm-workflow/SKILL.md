---
name: tecovllm-workflow
description: 在远程 T100 或 H100 节点按平台准备容器、启动 vLLM 服务、跑性能或精度测试及抓 prof。支持构建或更新 T100 TecovLLM 容器、使用已有镜像创建 H100 容器，以及在 T100 采集 dump size。
---

# TecovLLM 工作流

按用户指定的阶段执行，并检查该阶段用到的前置条件。准备环境时执行第 1、2 步。已有容器时可直接调用第 3 步。已有符合用途的就绪服务时，可单独调用第 4 至第 7 步。

第 1～3 步按实际设备选择 T100 或 H100 流程。第 4、5 步共用客户端和测试口径，使用未配置 `--profiler-config` 的普通服务。第 6 步只在 T100 执行，第 7 步使用支持对应采集接口的诊断服务。已有服务按 [启动配置检查](references/start-service.md#按用途选择服务) 验证后再复用。

各阶段获取仓库默认使用 HTTP(S) Git 地址，包括 clone、fetch、pull 和子模块。内网 GitLab 凭据通过 Git 的认证渠道传入，仓库 URL 和脚本只写项目地址。

## 1. 检查节点

- 用 `remote-dev` 解析 SSH 目标和跳板。登录后核对宿主 `hostname`、Docker 权限和实际 GPU 型号。T100 用 `teco-smi` 检查设备、驱动和占用，H100 用 `nvidia-smi` 并核对 Docker 的 NVIDIA runtime。按本次选定的实际设备走对应分支。
- **T100** 核对任务目录、源码版本、容器名、磁盘空间和挂载。源码未指定版本时取远端默认分支。换版时通过 `docker inspect` 核对已有容器、镜像、挂载和实际源码，确认待更新环境的服务和任务已结束。
- **H100** 核对已确认的 vLLM 镜像或已有容器、GPU 编号与 UUID、模型目录、任务目录和挂载。
- 新建时按 `remote-dev` 的命名规则补齐容器名。容器可用后核对物理卡与容器内逻辑设备的对应关系。提供了模型路径或服务端口时，在执行节点核对挂载和端口。起服务前再确认一次资源状态。

用户要求先看计划时，做到只读检查，输出平台、节点、容器和选定的源码版本或镜像。执行时按实际结果补齐关键参数。

## 2. 准备容器

- **T100** 新建走 **2A**，在指定的已有容器内换版走 **2B**。按 [T100 容器准备命令](references/prepare-container.md) 构建、安装和验收。失败时保留日志和实际状态，换版中断时记录卸载、系统包变更和恢复位置。
- **H100** 按 [H100 容器准备命令](references/prepare-h100-container.md) 从已有 vLLM 镜像新建容器，或验证已有容器后复用。使用镜像内的 vLLM、PyTorch 和 CUDA 运行环境。

验收后记录节点、平台、容器、镜像、卡映射、挂载、Python 环境、vLLM 版本及日志位置。T100 构建或换版时同时记录源码路径、commit 和系统包变更。

## 3. 启动模型服务

用 `simple-test-scripts` 选择或编写本次的服务端脚本。优先用用户指定的命令或脚本。按平台、实际权重、容器版本和场景匹配参考。同一模型的不同配置分别保留为短脚本。按 [服务端脚本与启动验收](references/start-service.md) 执行。

只要求写脚本或先看方案时，交付脚本和静态校验结果。用户要求启动时，用 `remote-dev` 在目标容器运行，并在验收后交付服务地址、模型名、脚本和日志位置。

## 4. 跑性能测试

按 [性能客户端与固定预热](references/run-performance.md) 执行。使用本次通过 HTTP 获取的 `teco-modeltest` 最新 `vllm` 分支，直接调用原生 `vllm_requests.py`。每次正式客户端脚本执行前，对同一服务先跑一次固定图文预热，再执行本次测试矩阵。

## 5. 跑精度测试

按 [精度客户端与数据集](references/run-precision.md) 执行。使用本次通过 HTTP 获取的 `teco-modeltest` 最新 `vllm` 分支。简单验证跑 HumanEval，多模态验证跑 MMMU-Pro，提测依次跑 LongBench v2、ToolBench、MVBench。按实际 checkout 确认原生入口和依赖。

## 6. Dump size

仅在 T100 上按 [Dump size 采集](references/dump-size.md) 执行。在诊断服务上复跑正式客户端请求，先隔离服务启动和所有预热产生的 dump，再对正式请求的尺寸记录去重。

## 7. 抓 prof

按 [Prof 采集](references/capture-prof.md) 执行。使用带 `--profiler-config` 的诊断服务，以 `start_profile`、目标请求、`stop_profile` 的顺序抓 trace。需要分析 trace 时按任务使用 `llm-prof`。
