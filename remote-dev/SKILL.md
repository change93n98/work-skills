---
name: remote-dev
description: SSH 到远程加速卡节点，检查/复用/创建并验证 Docker 开发容器。当用户说"开个开发容器"、"在XX节点建容器/进容器"、"没有容器就建一个"、"准备远程开发环境"、"XX节点有哪些容器/开发容器"时使用；用户一提到具体节点就直接连上去摸底执行，不要反问等确认；支持太初卡节点（teco-smi，/dev/tcaicard*，官方 tar 镜像）、NVIDIA 节点（nvidia-smi，NGC 镜像，--gpus）和未识别卡型的通用兜底；节点信息从 ~/.ssh/config 读取，只有用户完全没提节点时才列别名让用户选。只负责容器环境就绪与验证，不负责跑实验。
---

# 节点开发容器：检查 / 创建 / 进入

目标：把"本地开发、远程容器里验证运行"的环境准备好——在指定节点上确保有一个
可用的开发容器（有则复用/启动，没有则创建），并在容器内验证加速卡可用。
思路：拿到节点就连接 → 摸底（卡型/驱动/docker/现有容器/空闲卡）→ 选容器
或建容器 → 容器内验证 → 给出进入方式。

不要靠 `docker inspect` 的设备映射判断卡的归属——实际节点上的容器几乎全是
privileged 且 `Devices` 为空；查占用关系请用 gpu-container-lookup skill。

## 1. 执行原则：说到就干

- **用户提到具体节点 → 直接连上去执行**，不要反问"要连吗/查什么"。摸底全是
  只读操作，先把事实拿回来再汇报；执行动作（建容器、启停容器）只影响用户
  自己目标的资源，默认直接做，做完如实汇报。
- 只有两种情况才提问：
  1. 用户完全没提节点 → 从 `~/.ssh/config` 列 Host 别名问一次（AskUserQuestion
     最多 4 个选项，别名多时在消息里列全表让用户挑）。
  2. 要**新建**容器但缺关键参数（镜像、挂载路径）→ 把摸底结论（空闲卡、现成
     镜像、驱动版本）连同默认建议一起，**一次性**问完，让用户能直接确认。
- 容器名/类型不用开局就问：摸底结果里通常能对出来；卡号口径：监控工具的
  Index 从 **0** 开始（teco-smi 的 Index 1 = 第二张物理卡），回答时同时给出
  Bus-Id 和 Index 避免歧义。

## 2. 连接节点

1. 先在 `~/.ssh/config` 里 grep 该 IP 找 Host 块，用**别名**连接（别名自动携带
   Port/ProxyJump/IdentityFile；sdaa 集群端口是 65056，H100 节点要经跳板机，裸 IP 直连会失败）。
2. 找不到别名才用 `ssh -o BatchMode=yes -o ConnectTimeout=15 <ip>` 兜底。
3. 若 `~/.ssh/config` 仍保留 `RemoteForward 15721`，stderr 可能出现
   `Warning: remote port forwarding failed for listen port 15721`，属正常，忽略即可。

## 3. 摸底节点

一条命令探完卡型、docker、现有容器：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> '
  echo "=== 卡型探测 ==="; command -v nvidia-smi; command -v teco-smi; ls /opt/tecoai/bin/teco-smi 2>/dev/null
  echo "=== docker ==="; docker --version 2>&1
  echo "=== 现有容器 ==="; docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}" 2>&1 | head -40
'
```

- `docker ps` 报 `permission denied` → 改用 `sudo -n docker ...` 重试，后续所有
  docker 命令都带 `sudo -n`。
- 节点没装 docker → 属宿主机管理操作，报告并停止，不要代装。

再按卡型查占用概览（给用户建议空闲卡）：

**太初节点**：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> '/opt/tecoai/bin/teco-smi 2>&1 | head -80'
```

Permission denied 再试 `sudo -n`。记下各卡显存占用（低占用的卡即空闲）。
同时查宿主 TecoDriver 版本（后面选镜像要用）：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> '/opt/tecoai/bin/teco-smi --query-device driver_version --format csv -i 0 2>&1; dpkg -l 2>/dev/null | grep tecodriver || rpm -qa 2>/dev/null | grep tecodriver'
```

**NVIDIA 节点**：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'nvidia-smi --query-gpu=index,name,memory.used,memory.total,driver_version --format=csv,noheader; docker info 2>/dev/null | grep -i nvidia; command -v nvidia-ctk'
```

`docker info` 输出里能看到 nvidia runtime 才说明 toolkit 就绪；没有则记下来，
走创建分支时处理。

## 4. 选容器或新建

- **用户指名容器**：`docker inspect -f "{{.State.Status}}" <容器名>` 查状态。
  `running` → 直接跳到第 8 节验证；`exited`/`created` → `docker start <容器名>`；
  查无此容器 → 走创建分支。
- **未指名**：先看用户意图。查询类（"有哪些容器/XX的容器在哪"）→ 把第 3 节的
  `docker ps -a` 结果整理后**直接回答，不问**。要环境类（"给我个容器/准备开发
  环境"）→ 给出推荐方案并直接创建：空闲卡 + 按驱动匹配的现成镜像 + 命名
  `<用户名>-<卡型>-dev`（如 `alice-teco-dev`），创建完汇报用了哪些卡和镜像；
  推荐不了或参数缺失才回到第 1 节的提问路径。不要动别人的容器，重名冲突就换名。

## 5. 创建容器：太初分支

依据：太初官方文档（pytorch2.12 v3.3.0「构建 Docker 容器」、transfer v2.0.0
Docker 环境实践），在线来源 https://docs.tecorigin.com/release/pytorch2.12/v3.3.0/。

**镜像匹配**——先看节点上有什么：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'docker images --format "{{.Repository}}:{{.Tag}}" | grep -iE "tecotp-docker|torch_sdaa|paddle|vllm|teco" | head -20'
```

- 镜像 tag 形态：`jfrog.tecorigin.net/tecotp-docker/release/<os>/<arch>/<产品>:<版本>`。
- 按宿主 TecoDriver 版本对照兼容性选镜像（来源：compatibility v3.3.0 手册）：

| 宿主 TecoDriver | 可用的 TecoToolKit（即镜像内版本） |
| --- | --- |
| ≥ 2.3.0 | v3.0.0 ~ v3.3.0（前向兼容） |
| ≥ 2.1.0 | v2.x |
| 更早 | 区间约束，需对照 compatibility 手册核对 |

- 框架版本与 TecoToolKit 版本一一对应（TecoPyTorch v3.3.0 ↔ ToolKit v3.3.0）。
  候选有多个且不确定时，把候选列出来问用户，不要替用户猜。

**缺镜像**——问用户要 tar 包路径或下载 URL，然后：

```bash
# URL 在节点上直接下（wb.tecorigin.com 是太初内网源）
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'wget -O /tmp/<tar名> "<URL>" && md5sum /tmp/<tar名>'
# 或用户本地有 tar，从 Windows scp 上去
scp -o BatchMode=yes -o ConnectTimeout=15 "<本地路径>/<tar名>" <别名>:/tmp/
# 校验 md5 与官方一致后导入
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'docker load < /tmp/<tar名> && docker images | grep -i teco'
```

导入失败或 md5 对不上 → 把差异报给用户，不要硬装。

**创建**（官方模板，逐卡映射，默认走这个）：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'DEVS=""; for i in <卡号列表，如 0 1 2 3>; do DEVS="$DEVS --device=/dev/tcaicard$i"; done
docker run -itd --name=<容器名> --net=host --ipc=host $DEVS \
  --cap-add SYS_PTRACE --cap-add SYS_ADMIN --shm-size 64g \
  -v <宿主工作路径>:<容器内路径> <镜像> /bin/bash'
```

- `-itd` 后台常驻；`--device=/dev/tcaicardN` 挂载指定 SDAA 设备（SPA）；
  `--shm-size` 建议 64G 及以上（训练场景 128g）。
- **全卡/大量卡场景**可用 transfer 实践模板（多卡训练/大模型微调实测）：
  `-e TECO_VISIBLE_DEVICES=all --net=host --ipc=host --privileged=true --ulimit memlock=-1 --shm-size=128g`，
  不逐卡映射。取舍：逐卡映射权限面小、能卡级隔离，对比实验默认用；privileged
  全通只在明确要全部卡时用。
- 卡号映射口径：容器挂了 tcaicard4~7 时，容器内 `SDAA_VISIBLE_DEVICES=0`
  对应物理卡 4；对比实验要独占某几张卡时，只映射那几张。
- 挂载注意：`-v` 的容器内路径不要落在 `/mnt` 下（官方文档提醒会影响数据集路径）。
- **容器与宿主机 TecoDriver 版本必须一致**（transfer 文档原文），版本对不上时
  先按上面兼容表换镜像，不要强行创建。

## 6. 创建容器：NVIDIA 分支

**runtime 检查**：第 3 节若发现 `docker info` 里没有 nvidia runtime：

```bash
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

这些是宿主机改动，输出给用户/管理员执行，**agent 不代装**；装完回本 skill 继续。

**镜像**：默认 NGC PyTorch（`nvcr.io/nvidia/pytorch:<tag>-py3`，tag 问用户，
或沿用节点上已有镜像的版本风格）。节点上没有：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'docker pull nvcr.io/nvidia/pytorch:<tag>-py3'
```

pull 失败（多半是集群无外网）→ 问用户：有没有现成 tar（scp 上去 `docker load`），
或从另一台有网机器 `docker save -o <名>.tar <镜像>` 后 scp 过来 `docker load`。

**创建**：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'docker run -itd --name=<容器名> --gpus all --ipc=host \
  --shm-size 64g -v /home:/home -u "$(id -u):$(id -g)" <镜像> bash'
```

- 只用部分卡时把 `--gpus all` 换成 `--gpus "device=0,1"`（在整段单引号命令内直接
  用双引号包裹即可，不要嵌套单引号——`'"device=0,1"'` 的单引号三明治会截断外层引号）。
- `-u $(id -u):$(id -g)` 保住容器内产出文件的属主是你，避免 root 落盘；NGC 容器
  进去时提示 `I have no name!` 属正常。
- NGC 镜像默认不带 sshd，走 VSCode attach 路线（第 9 节）即可，不要改镜像。

## 7. 创建容器：通用兜底分支（昇腾/寒武纪等其他卡，试验性）

先探测设备节点和厂商运行时：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'ls /dev | grep -iE "davinci|cambricon|mlu|npu|ascend"; ls /usr/local 2>/dev/null | grep -iE "ascend|neuware|cambricon"; docker info 2>/dev/null | grep -iE "ascend|nvidia"'
```

- 有 **ascend docker runtime**（`docker info` 可见 ascend）→ 优先官方插件写法：
  `docker run -itd --name=<容器名> -e ASCEND_VISIBLE_DEVICES=<卡号> --net=host --ipc=host --shm-size 64g -v <路径>:<路径> <镜像> bash`，
  不手动 `--device /dev/davinci*`。
- 识别不出 runtime 插件 → 兜底形态（各家通用）：`--privileged=true --net=host
  --ipc=host --shm-size 64g` + 按用户给的设备名 `--device` 映射。
- 镜像从哪来：同第 5 节"缺镜像"流程（tar 路径/URL 问用户）。
- 此分支验证手段弱：容器内只确认设备节点可见 + 用户指定框架能 import；跑不通
  就停下，以该卡型官方文档为准，如实报告卡在哪一步。

## 8. 容器内验证

**太初容器**：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'docker exec <容器名> bash -c "source /opt/tecoai/setvars.sh; python -c \"import torch_sdaa\" && echo PYTORCH_OK"'
```

import 失败先看容器内 conda 环境（不同镜像默认环境不同）：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'docker exec <容器名> bash -c "source /opt/tecoai/setvars.sh; conda env list"'
```

按镜像类型对应激活再验：TecoPyTorch → `conda activate torch27_env_py310` +
`import torch_sdaa`；Teco-vLLM → `conda activate vllm_env_py312` + `import vllm`；
TecoPaddle → `conda activate paddle_env_py310` + `import paddle_sdaa`。

卡健康：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'docker exec <容器名> teco-smi -c 2>&1 | head -30'
```

Health 列全 OK 即通过。**容器内 `teco-smi -c` 显示的进程 PID 是宿主机 PID，与容器
内 `ps` 看到的不一致，属正常**（官方 FAQ），不是环境问题。

**NVIDIA 容器**：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'docker exec <容器名> nvidia-smi; docker exec <容器名> python -c "import torch; print(torch.cuda.is_available(), torch.cuda.device_count())"'
```

验证失败时的排查顺序：镜像内框架版本 vs 宿主驱动版本（对照第 5/6 节兼容表）→
设备是否真映射进容器 → 报告卡点，不要伪造"看起来成功"。

## 9. 输出格式与进入方式

直接给结论 + 一张证据表：

| 项目 | 值 |
| --- | --- |
| 节点 | sdaa-192.167.252.35（太初，宿主 TecoDriver 2.3.0） |
| 容器 | alice-teco-dev（running） |
| 镜像 | jfrog.tecorigin.net/tecotp-docker/release/ubuntu22.04/x86_64/torch_sdaa:... |
| 挂载卡 | tcaicard0~3（容器内 SDAA_VISIBLE_DEVICES 0~3） |
| 验证 | import torch_sdaa OK；teco-smi -c 全 OK |
| 挂载路径 | /home/alice/work:/work |

进入命令（直接可用）：

```bash
ssh <别名>
docker exec -it <容器名> bash
```

VSCode 两条路线（默认推荐 A）：

- **A. Attach（零侵入，推荐）**：本地 VSCode Remote-SSH 连上节点 → 装官方
  Dev Containers 扩展 → F1 → "Dev Containers: Attach to Running Container..." →
  选容器。attach 与容器怎么启动的无关，容器重启后重新 attach 即可；扩展等
  attach 配置可保存复用。
- **B. 容器内 sshd**：体验与普通 SSH 服务器一致，但要维护镜像内 sshd 和端口
  分配，容器重建后 IP/端口会变。仅用户明确要求时再给要点，默认不展开。

边界声明：本 skill 到"容器就绪并验证通过"为止。跑实验、同步代码不在范围内；
后续 remote-run 类 skill 应引用本 skill 的输出（节点别名 + 容器名 + 挂载路径）。
