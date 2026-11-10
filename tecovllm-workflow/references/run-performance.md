# 性能客户端与固定预热

## 准备客户端

按 [任务日志](logging.md) 将客户端准备、预热、正式运行和结果核对记入 `04-performance.log`。

使用第 3 步已验收的普通服务，或按 [启动配置检查](start-service.md#按用途选择服务) 核对现有实例。确认服务端实际启动参数里没有 `--profiler-config` 及其等号或点分形式，再执行预热和正式测试。核对服务地址、`served-model-name` 和 tokenizer 路径，确认客户端可访问且服务支持图文请求。服务仅支持文本时，先说明固定图文预热的前置条件。

每次实际执行性能任务前，在客户端可访问的新任务目录 `run_dir` 通过 HTTP 获取 `teco-modeltest` 的 `vllm` 分支最新提交。复用已有 checkout 时，先核对 HTTP 来源、分支和工作区状态，再执行 `git pull --ff-only origin vllm` 并确认 HEAD 与远端分支一致。有本地改动、领先提交或分叉时，在新目录克隆。记录本次实际 commit，整轮预热与正式测试使用同一份源码。

```bash
cd "$run_dir" &&
  git clone --branch vllm --single-branch \
    http://10.10.30.109/tecoap/teco-modeltest.git teco-modeltest &&
  git -C teco-modeltest rev-parse HEAD
```

按本次 checkout 核对依赖、`lm_infer/unit/vllm_requests.py` 参数和客户端 Python 环境。优先用用户指定的正式脚本，确认其调用本次 checkout 的原生客户端。也可复制 [正式性能模板](../assets/run_performance.sh)，用 `simple-test-scripts` 按任务填写文本或图文输入、输出长度、BS 和请求数。模板里的纯文本矩阵用于示范。图文正式测试按本次配置设置 `--model_type mllm` 和 `--image_size`。只要求写脚本时，交付脚本和静态检查结果。

## 固定图文预热

每次正式客户端脚本执行前，向同一服务发 **一次** 预热请求。固定为 BS 1、请求数 1、1024 文本输入 token、目标输出 1024 token、1 张 4096×4096 图片。预热独立于正式矩阵，结果保存在 `warmup` 目录。

将 [预热脚本](../assets/warmup_performance.sh) 和本次正式脚本放到 `run_dir`，分别通过 `bash -n` 检查后再开始预热。两个脚本从同一 checkout 的 `lm_infer/unit` 执行。`server` 使用 `host:port`，`model` 使用服务的 `served-model-name`，`tokenizer` 使用客户端可读的 tokenizer 路径，`run_dir` 使用绝对路径。

```bash
cd "$run_dir/teco-modeltest/lm_infer/unit" &&
  bash "$log_step" "$log_dir/04-performance.log" \
    bash "$run_dir/warmup_performance.sh" "$server" "$model" "$tokenizer" "$run_dir"
```

核对退出状态和 `warmup/client.log` 中的原生请求结果。预热成功后从同一目录执行正式客户端脚本，预热失败时保留日志并停在预热阶段。用已有 checkout 时将上面 `cd` 的目录改为本次确认的客户端源码路径。

## 执行与结果

使用本 Skill 的模板时，用下面的命令启动正式测试。用户指定的正式脚本沿用其调用方式。

```bash
bash "$log_step" "$log_dir/04-performance.log" \
  bash "$run_dir/run_performance.sh" "$server" "$model" "$tokenizer" "$run_dir"
```

正式脚本每组在 `formal` 下保存独立的原生结果和日志。性能和精度共用服务时串行执行。对照测试使用同一套正式请求、固定预热和统计口径。

记录本次客户端 commit、服务地址、模型名、测试矩阵和日志路径。按原生结果报告成功请求数、实际输出长度、首 token 延迟、TPOT 和吞吐。预热结果单独保存，正式指标只取正式测试。
