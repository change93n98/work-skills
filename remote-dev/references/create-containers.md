# 建容器：三套模板（由探测结果选，不由节点名选）

先按 SKILL.md 第 2 节摸底，拿到**卡型 + 驱动版本 + 现成镜像 + 空闲卡**再回来。
分支选择只看探测结果：`teco-smi` 存在 → 太初分支；`nvidia-smi` 存在 → NVIDIA 分支；
都不存在或识别出其他加速卡 → 兜底分支。

通用约定：

- 以下外层 SSH 从发起机器连接执行节点，`<别名>` 使用发起机器的 SSH 配置与已有跳板路由。
  Docker 创建、镜像查询、设备探测及宿主挂载路径均属于执行节点，不能用发起节点的信息替代。
- 容器命名 `<用户名>-<卡型>-dev`（用户名取摸底时的 `whoami`，不要预设）。
- `-v` 的容器内路径**不要落在 `/mnt` 下**（太初官方文档提醒会影响数据集路径）。
- 容器内执行首选 `bash -ic`，由 `.bashrc` 初始化环境（见 SKILL.md 第 5 节）。
  长命令优先用 heredoc 形态下发，避免 ssh → docker → bash 三层引号嵌套：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'docker exec -i <容器名> bash -ic "source /dev/stdin"' <<'EOF'
<要执行的命令>
EOF
```

---

## 一、太初分支

依据：太初官方文档（pytorch2.12 v3.3.0「构建 Docker 容器」、transfer v2.0.0 Docker 环境实践），
在线来源 https://docs.tecorigin.com/release/pytorch2.12/v3.3.0/

### 镜像匹配

先看节点上有什么：

```bash
ssh <别名> 'docker images --format "{{.Repository}}:{{.Tag}}" | grep -iE "tecotp-docker|torch_sdaa|paddle|vllm|teco" | head -20'
```

- 镜像 tag 形态：`jfrog.tecorigin.net/tecotp-docker/release/<os>/<arch>/<产品>:<版本>`。
- 按**宿主 TecoDriver 版本**对照兼容性选镜像（来源：compatibility v3.3.0 手册）：

| 宿主 TecoDriver | 可用的 TecoToolKit（即镜像内版本） |
| --- | --- |
| ≥ 2.3.0 | v3.0.0 ~ v3.3.0（前向兼容） |
| ≥ 2.1.0 | v2.x |
| 更早 | 区间约束，需对照 compatibility 手册核对 |

- 框架版本与 TecoToolKit 版本一一对应（TecoPyTorch v3.3.0 ↔ ToolKit v3.3.0）。
- 候选有多个且不确定时，**把候选列出来问用户，不要替用户猜**。
- **容器与宿主机 TecoDriver 版本必须一致**（transfer 文档原文）。版本对不上时先按上表换镜像，
  不要强行创建。

### 缺镜像

问用户要 tar 包路径或下载 URL，然后：

```bash
# URL 在节点上直接下（wb.tecorigin.com 是太初内网源）
ssh <别名> 'wget -O /tmp/<tar名> "<URL>" && md5sum /tmp/<tar名>'
# 或用户本地有 tar，从本机 scp 上去
scp -o BatchMode=yes -o ConnectTimeout=15 "<本地路径>/<tar名>" <别名>:/tmp/
# 校验 md5 与官方一致后导入
ssh <别名> 'docker load < /tmp/<tar名> && docker images | grep -i teco'
```

导入失败或 md5 对不上 → 把差异报给用户，不要硬装。

### 创建（官方模板，逐卡映射，默认走这个）

```bash
ssh <别名> 'DEVS=""; for i in <卡号列表，如 0 1 2 3>; do DEVS="$DEVS --device=/dev/tcaicard$i"; done
docker run -itd --name=<容器名> --net=host --ipc=host $DEVS \
  --cap-add SYS_PTRACE --cap-add SYS_ADMIN --shm-size 64g \
  -v <宿主工作路径>:<容器内路径> <镜像> /bin/bash'
```

- `-itd` 后台常驻；`--device=/dev/tcaicardN` 挂载指定 SDAA 设备（SPA）。
- `--shm-size` 建议 64G 及以上（训练场景 128g）。

**全卡/大量卡场景**可用 transfer 实践模板（多卡训练/大模型微调实测）：

```bash
-e TECO_VISIBLE_DEVICES=all --net=host --ipc=host --privileged=true \
--ulimit memlock=-1 --shm-size=128g
```

不逐卡映射。取舍：逐卡映射权限面小、能卡级隔离，对比实验默认用；privileged 全通只在
明确要全部卡时用。

### 卡号映射口径

容器挂了 `tcaicard4~7` 时，容器内 `SDAA_VISIBLE_DEVICES=0` 对应**物理卡 4**。
对比实验要独占某几张卡时，只映射那几张。

### 容器内验证 / conda 环境

先在 `bash -ic` 中验证框架；若 `.bashrc` 已激活合适环境，直接执行，不再重复激活。
不同镜像默认环境不同，import 失败先查 `command -v python`、`CONDA_DEFAULT_ENV` 与
`conda env list`。下表仅是排查时的候选，以当前容器实际环境为准：

| 镜像类型 | 激活 | 验证 |
| --- | --- | --- |
| TecoPyTorch | `conda activate torch27_env_py310` | `import torch_sdaa` |
| Teco-vLLM | `conda activate vllm_env_py312` | `import vllm` |
| TecoPaddle | `conda activate paddle_env_py310` | `import paddle_sdaa` |

```bash
ssh <别名> 'docker exec <容器名> bash -ic "python -c \"import torch_sdaa\" && echo PYTORCH_OK"'
ssh <别名> 'docker exec <容器名> teco-smi -c 2>&1 | head -30'   # Health 列全 OK 即通过
```

仅确认 `.bashrc` 未初始化所需环境时，才补充实际 conda 安装下的初始化脚本、
`conda activate <实际环境>` 或 `/opt/tecoai/setvars.sh`。

容器内 `teco-smi -c` 显示的进程 PID 是宿主机 PID，与容器内 `ps` 不一致，属正常（官方 FAQ）。

---

## 二、NVIDIA 分支

### runtime 检查

摸底时 `docker info | grep -i nvidia` 没看到 nvidia runtime，说明 toolkit 未就绪：

```bash
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

这些是**宿主机改动，输出给用户/管理员执行，agent 不代装**；装完回本流程继续。

### 镜像

默认 NGC PyTorch（`nvcr.io/nvidia/pytorch:<tag>-py3`，tag 问用户，或沿用节点上已有镜像的版本风格）。
节点上没有：

```bash
ssh <别名> 'docker pull nvcr.io/nvidia/pytorch:<tag>-py3'
```

pull 失败（多半是集群无外网）→ 问用户：有没有现成 tar（scp 上去 `docker load`），
或从另一台有网机器 `docker save -o <名>.tar <镜像>` 后 scp 过来 `docker load`。

### 创建

```bash
ssh <别名> 'docker run -itd --name=<容器名> --gpus all --ipc=host \
  --shm-size 64g -v /home:/home -u "$(id -u):$(id -g)" <镜像> bash'
```

- 只用部分卡：把 `--gpus all` 换成 `--gpus "device=0,1"`。在整段单引号命令内直接用双引号包裹即可，
  **不要嵌套单引号**——`'"device=0,1"'` 这种单引号三明治会截断外层引号。
- `-u $(id -u):$(id -g)` 保住容器内产出文件的属主是当前用户，避免 root 落盘；
  进 NGC 容器时提示 `I have no name!` 属正常。
- NGC 镜像默认不带 sshd，走 VS Code attach 路线（SKILL.md 第 8 节）即可，不要改镜像。

---

## 三、通用兜底分支（昇腾/寒武纪等其他卡，试验性）

先探测设备节点和厂商运行时：

```bash
ssh <别名> 'ls /dev | grep -iE "davinci|cambricon|mlu|npu|ascend"; ls /usr/local 2>/dev/null | grep -iE "ascend|neuware|cambricon"; docker info 2>/dev/null | grep -iE "ascend|nvidia"'
```

- 有 **ascend docker runtime**（`docker info` 可见 ascend）→ 优先官方插件写法：

```bash
docker run -itd --name=<容器名> -e ASCEND_VISIBLE_DEVICES=<卡号> \
  --net=host --ipc=host --shm-size 64g -v <路径>:<路径> <镜像> bash
```

  不要手动 `--device /dev/davinci*`。

- 识别不出 runtime 插件 → 兜底形态（各家通用）：`--privileged=true --net=host --ipc=host
  --shm-size 64g` + 按用户给的设备名 `--device` 映射。
- 镜像从哪来：同太初分支"缺镜像"流程（tar 路径/URL 问用户）。

此分支验证手段弱：容器内只确认设备节点可见 + 用户指定框架能 import；跑不通就停下，
以该卡型官方文档为准，**如实报告卡在哪一步**。
