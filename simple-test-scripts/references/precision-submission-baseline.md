# 提测基准精度测试脚本

用户于 2026-10-26 确认的客户端基准保存在 [precision_submission_baseline.sh](../assets/precision_submission_baseline.sh)。其来源为 `/data/application/changhl/work/35b-opt/precision_mtp1/run_precision_35b_mtp1.sh`；后续生成脚本时读取 skill 内副本，不只依赖可能被再次编辑的工作目录文件。

## 保持的执行语义

- 使用指定 teco-modeltest 仓库的原生 `python vllm_precision.py`，不增加适配层或修改评测库。
- 在同一个模型服务上，依次执行 `longbench_v2`、`tool_bench`、`mvbench`。前一项退出后才启动后一项；一项评测失败仍继续下一项，错误保留在各自客户端日志。
- 参数按基准保留 `--server_ip_port`、`--model_name`、`--dataset`、`--priority p0`、`--max_seq_len`、`--output_dir`。
- 不额外传 `--batch`、`--max_tokens`、`--model_type`、`--limits`，使用指定版本评测入口的原生默认行为。日志名里的 max_tokens、thinking、版本标签不代表实际设置；不要据此添加参数或改库。
- 基准是 Qwen3.6-35B-A3B 的示例，地址为 0.0.0.0:8031、上下文为 262144；模型、服务地址、上下文长度、Conda 安装位置及仓库/结果路径按当前任务调整。MTP 由服务端配置，客户端目录中的 mtp1 标签不会开启 MTP。
- 日志分数据集保存在 log_eval/；原生结果保存在 results/，同一轮使用同一时间戳。脚本内三条命令都不加 `&`；需要后台运行时将整份脚本放到后台。

本基准对应的原生入口曾采用 LongBench v2 输出上限 16384、ToolBench/MVBench 为 8192；默认 batch=2，LongBench 实际并发为 1。版本变更时读取实际源码确认，不把这些数值强行写进调用命令。

## 测试仓库与分支更新

精度提测默认来源：

- 仓库：`http://10.10.30.109/tecoap/teco-modeltest.git`。
- 分支：`vllm`，对应页面为 [teco-modeltest / vllm](http://10.10.30.109/tecoap/teco-modeltest/-/tree/vllm)。
- 实际评测前获取该分支最新 commit，用本次检出版本完成依赖检查和初始精度测试环境配置。用户当前指定其他版本或固定 commit 时以当前要求为准。

首次准备时，在目标执行环境的任务目录中，例如：

```bash
cd /path/to/eval-workdir
git clone --branch vllm --single-branch \
  http://10.10.30.109/tecoap/teco-modeltest.git teco-modeltest
cd teco-modeltest
git branch --show-current
git log -1 --format="%H %s"
```

已有目录时先检查远端、分支和 `git status --short`。确认来源一致、当前分支为 vllm 且无本地修改后，可用 `git pull --ff-only origin vllm` 更新；存在本地修改或分叉时另 clone 到新目录，不覆盖已有代码。记录实际使用的 commit，正式评测开始后保持该 checkout 不再更新。

检查最新 commit 的 README、依赖声明及 `lm_infer/unit/vllm_precision.py`，确认原生参数和默认配置。生成客户端时，将工作目录改为本次 checkout 的 `lm_infer/unit/`，不继续指向其他分支或旧目录。以该 checkout 的依赖声明确定 EvalScope 和相关依赖版本，安装到下面的独立评测环境。若 README 与 requirements/setup.py 不一致，优先核对实际安装声明；用户明确指定版本时，以用户当前要求为准并说明冲突。

网络或鉴权失败时保留错误，不默认为其他分支或历史 checkout 也满足本次“最新分支”要求。只更新 skill 或生成脚本时仅保存这些准备说明，不执行 clone、pull 或安装。

## 精度测试前准备环境

采用本基准时，先读取本次 checkout 的 `requirements/common.txt`、`requirements/evalscope.txt` 和 `setup.py`，确定精度入口需要的依赖。**版本跟随本次仓库，不再固定 EvalScope 1.8.1。** 使用 Python 3.12 的独立 Conda 环境，名称采用 `evalscope_py312_<版本号下划线形式>`；例如要求 `evalscope==1.11.1` 时为 `evalscope_py312_1_11_1`。

- 已存在且解释器、框架和所需依赖符合本次声明：复用，不重复创建。
- 仓库要求变化时使用对应的新环境，不覆盖旧评测环境或推理环境。客户端模板中的激活环境名也要同步修改。
- 安装所选数据集及原生远程 API 入口实际需要的依赖，保留仓库的版本约束；RAG、OCR、本地推理或音频等可选依赖按任务需要安装，不把整个 requirements 文件不加区分地装进推理环境。
- pip 安装优先使用清华源 `https://pypi.tuna.tsinghua.edu.cn/simple`，可用阿里云源作为国内备用；使用命令级 `-i`，不修改全局 pip 配置。更换镜像只影响下载来源，不改变仓库版本约束。
- 安装后记录 checkout commit、Python、EvalScope 版本，执行原生入口 `--help` 验证导入；安装或导入失败时解决实际错误，不悄悄改用其他框架版本。
- 只要求生成脚本或更新 skill 时，仅准备说明与文件；已授权执行测试或准备环境时才实际安装。

下面以仓库声明 EvalScope 1.11.1 为例；版本、附加依赖及 Conda 路径须先与实际 checkout 核对：

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda env list
# 仅在该环境不存在时创建。
conda create -n evalscope_py312_1_11_1 python=3.12 -y
conda activate evalscope_py312_1_11_1

# 在本次 teco-modeltest checkout 中执行；按实际声明调整版本。
python -m pip install -r requirements/common.txt \
  evalscope==1.11.1 transformers==4.57.3 \
  -i https://pypi.tuna.tsinghua.edu.cn/simple

python -c "import sys; from importlib.metadata import version; print(sys.executable); print(sys.version); print(version('evalscope'))"
cd lm_infer/unit
python vllm_precision.py --help
```

模板展示的是本次远程 API 精度入口所需安装范围；其他任务应按实际声明和入口补充对应依赖，而不是永远照抄示例版本或 extras。

## 后台执行

模型服务由独立的服务端脚本启动，确认服务就绪后再执行客户端。运行后台任务时，例如：

```bash
nohup bash /path/to/run_precision.sh \
  > /path/to/precision_all.log 2>&1 < /dev/null &
```

这是启动方式示例，不是读取 skill 或生成脚本时的执行指令。
