# 精度客户端与数据集

使用第 3 步已验收的普通服务，或按 [启动配置检查](start-service.md#按用途选择服务) 核对现有实例。确认服务端实际启动参数里没有 `--profiler-config` 及其等号或点分形式，再核对 `host:port`、`served-model-name` 和最大序列长度。性能与精度共用服务时串行执行。

| 任务 | 脚本模式 | 原生数据集 |
| --- | --- | --- |
| 简单精度验证 | `humaneval` | `humaneval` |
| 多模态精度验证 | `mmmu_pro` | `mmmu_pro` |
| 精度提测 | `submission` | `longbench_v2` → `tool_bench` → `mvbench` |

## 准备客户端

实际评测前，通过 HTTP 获取 `teco-modeltest` 的 `vllm` 分支最新提交，记录本次使用的 commit。复用本次任务已确认的 checkout 时，从它的 `lm_infer/unit` 执行。新建 checkout 时在客户端可访问的任务目录运行。

```bash
cd "$run_dir" &&
  git clone --branch vllm --single-branch \
    http://10.10.30.109/tecoap/teco-modeltest.git teco-modeltest &&
  git -C teco-modeltest rev-parse HEAD
```

用 `simple-test-scripts` 的 [精度环境准备](../../simple-test-scripts/references/precision-submission-baseline.md#精度测试前准备环境) 核对实际 checkout 的依赖，使用独立的 Python 3.12 评测环境。EvalScope 版本跟随仓库声明。HumanEval 会执行生成的代码，使用普通权限的独立评测容器，挂载评测所需的源码、数据和结果目录。

案例中的 `qa_precision_eval.py` 对应当前仓库的 `lm_infer/unit/vllm_precision.py`。用本次 checkout 的 `--help` 核对参数和数据集配置。脚本用 `--priority p0`，保持仓库的样本和生成参数口径。提测时 LongBench v2 跑全量，ToolBench 单独跑，MVBench 按 `p0` 选择样本。已核对的版本中 MVBench 是 20 个子集各 50 条，目标合计 1000 条。每次按实际 checkout 确认配置，完成后按原生报告核对有效样本数。

## 运行与交付

将 [精度脚本](../assets/run_precision.sh) 放到本次任务目录 `run_dir`，先用 `bash -n` 核对脚本。进入已激活的评测环境和本次 checkout 的 `lm_infer/unit`。`mode` 从上表选择，`max_seq_len` 取实际模型服务的最大序列长度，`run_dir` 使用绝对路径。

```bash
bash "$run_dir/run_precision.sh" "$mode" "$server" "$model" "$max_seq_len" "$run_dir"
```

提测各数据集依次执行，单项失败时保留日志并继续，脚本最终返回非零。需要后台执行时，用 `remote-dev` 的方式启动整份脚本。`log_eval` 按数据集保存客户端日志，`results` 按数据集保存原生结果。核对每项完成状态、分数、有效样本数及报告路径，并记录客户端 commit、评测环境和服务配置。
