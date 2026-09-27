---
name: remote-dev
description: 在 ~/.ssh/config 里的任意远程节点上准备/复用 Docker 开发容器，并在容器内执行任务、盯进度、取结果状态。当用户说"开个开发容器"、"XX节点建容器/进容器"、"准备远程开发环境"、"XX节点有哪些容器/我的容器"、"在XX节点跑/起个任务"、"看下任务进度/跑到哪了/完成了没"、"结果在哪/精度多少"、"VS Code 怎么连这个节点/远程开发"时使用；用户提到节点就直接连上去摸底执行，不要反问等确认；节点从 ~/.ssh/config 动态读取，不维护固定清单，只有用户完全没提节点时才列别名让用户选。
---

# 远程节点：容器准备 / 执行 / 盯进度

目标：本机 agent 一路走到底——在用户指定的节点上准备好容器（有则复用/启动，没有则建），
在容器内把任务跑起来，盯住进度，给出结果与状态。
**节点上绝大多数任务都在 docker 内跑**，所以一切以容器为单位，宿主只做摸底与 docker 操作。

两条硬规则：

1. **不写死节点**。节点清单的唯一来源是 `~/.ssh/config`；卡型、驱动、docker、挂载、
   存储共享关系全部连上去现探。skill 里不保存任何节点名、端口、跳板机、路径、用户名的既定事实。
2. **探测驱动分支**。太初 / NVIDIA / 其他兜底三套建容器模板由摸底结果决定用哪套，
   不是由节点叫什么决定。

分册（按需读，不要一开始全读）：

- 建容器三套模板、镜像匹配与导入、容器内验证细节：`references/create-containers.md`
- 执行/监控命令集、进度判定表、增量测速、结果读取实例：`references/exec-and-monitor.md`

## 0. 执行原则：说到就干

- 用户提到节点 → 直接连上去执行，不要反问"要连吗/查什么"。摸底全是只读操作，先把事实拿回来再汇报。
- 执行类动作（起任务、建容器、启停容器）只影响用户自己的目标资源，默认直接做，做完如实汇报。
- 只在两种情况提问：① 用户完全没提节点；② 要新建容器但缺关键参数（镜像、挂载路径）——
  把摸底结论（空闲卡、现成镜像、驱动版本）连同默认建议**一次性**问完。
- 容器名/类型不用开局就问：摸底结果里通常能对出来。

## 1. 解析节点（不写死）

唯一来源 `~/.ssh/config`。枚举别名（跳过注释行与通配符）：

```bash
grep -iE "^[[:space:]]*Host[[:space:]]+" ~/.ssh/config \
  | awk '{for(i=2;i<=NF;i++) print $i}' | grep -v '[*?]'
```

- 用户给了 IP 或别名 → 先在 config 里找对应 Host 块，**用别名连接**。别名自动携带
  Port / ProxyJump / IdentityFile；裸 IP 直连会漏掉端口与跳板机。
- 找不到别名才兜底：`ssh -o BatchMode=yes -o ConnectTimeout=15 <ip>`。
- 用户完全没给节点 → 把别名列成文本表让用户挑。**用文本列出，不要用四选项弹窗**：
  节点数常超过 4 个，弹窗还会挡住对话。
- 需要复核有效参数：`ssh -G <别名> | grep -iE "^(hostname|port|user|proxyjump)"`。
- 连接时 stderr 若出现 `Warning: remote port forwarding failed for listen port 15721`，
  属正常（config 里残留的 `RemoteForward` 所致），忽略即可，不要当成连接失败。

## 2. 摸底节点（一条命令拿全）

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> '
  echo "=== 卡型 ==="; command -v nvidia-smi; command -v teco-smi; ls /opt/tecoai/bin/teco-smi 2>/dev/null
  echo "=== docker ==="; docker --version 2>&1
  echo "=== 身份 ==="; whoami; echo "$HOME"
  echo "=== 容器 ==="; docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}" 2>&1 | head -40
  echo "=== 宿主在跑的重活 ==="; ps -eo pid,etime,pcpu,args --sort=-pcpu 2>/dev/null | head -12
'
```

- `whoami` / `$HOME` 用于后面拼路径和判断归属，**不要预设用户名**。
- `docker ps` 报 `permission denied` → 改 `sudo -n docker ...`，后续都带 `sudo -n`。
- 节点没装 docker → 属宿主机管理操作，报告并停止，不要代装。

再按探测到的卡型查占用与驱动（挑一个分支，别两个都跑）：

```bash
# 太初系（teco-smi 存在时）
ssh <别名> '/opt/tecoai/bin/teco-smi 2>&1 | head -80'
ssh <别名> '/opt/tecoai/bin/teco-smi --query-device driver_version --format csv -i 0 2>&1; dpkg -l 2>/dev/null | grep -i tecodriver || rpm -qa 2>/dev/null | grep -i tecodriver'

# NVIDIA（nvidia-smi 存在时）
ssh <别名> 'nvidia-smi --query-gpu=index,name,memory.used,memory.total,driver_version --format=csv,noheader; docker info 2>/dev/null | grep -i nvidia; command -v nvidia-ctk'
```

卡号口径：监控工具 Index 从 **0** 开始（teco-smi 的 Index 1 = 第二张物理卡），
回答时同时给 Bus-Id 和 Index 避免歧义。

**挂载与归属**（用到时再查，不需要每次都查）：

```bash
# 容器内路径 ↔ 宿主路径——汇报路径时必须两边都给
docker inspect -f '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}' <容器名>

# "哪些容器是我的"——docker 不记录创建者，靠两处对齐推断：
#   a) 容器名带用户名前缀   b) 挂载路径落在该用户目录下（$HOME 或集群的用户目录）
for c in $(docker ps -a --format '{{.Names}}'); do
  printf '%-28s %s\n' "$c" "$(docker inspect -f '{{range .Mounts}}{{.Source}} {{end}}' $c \
    | tr ' ' '\n' | grep -oE "/(home|data|mnt|sdata|nfsdata)/[a-z0-9_.-]+" | sort -u | tr '\n' ',')"
done
```

归属结论要标注是**推断**（命名前缀 + 挂载点两处对上才可信），不要当成 docker 记录的创建者。

**存储是否跨节点共享**（决定"这个路径能不能在别的节点上直接看"）：

```bash
ssh <别名> 'df -h <路径>; findmnt -no SOURCE,FSTYPE <路径>; hostname'
```

同一路径在多台节点上落在同一个文件系统（gpfs/nfs/ceph 等）时，**同一路径在多节点可见**——
那就不能用路径推断结果出自哪台节点，要用 `hostname` 确认。

## 3. 选容器或新建

- **用户指名容器**：`docker inspect -f '{{.State.Status}}' <容器名>`。
  `running` → 跳到第 4 节验证；`exited`/`created` → `docker start <容器名>`；
  查无此容器 → 走创建分支。
- **未指名**：查询类（"有哪些容器/XX 的容器在哪"）→ 把第 2 节结果整理后**直接回答，不问**。
  要环境类（"给我个容器/准备开发环境"）→ 按探测结果直接创建：空闲卡 + 与驱动版本匹配的
  现成镜像 + 命名 `<用户名>-<卡型>-dev`，建完汇报用了哪些卡和镜像。推荐不了或参数缺失才提问。
- 不要动别人的容器（按第 2 节归属判断）；重名冲突就换名。
- 创建模板见 `references/create-containers.md`（太初 / NVIDIA / 兜底三套）。

## 4. 验证容器

容器内确认设备可见 + 框架能 import，才算就绪：

```bash
# 太初系
ssh <别名> 'docker exec <容器名> bash -c "source /opt/tecoai/setvars.sh; python -c \"import torch_sdaa\" && echo PYTORCH_OK"'
ssh <别名> 'docker exec <容器名> teco-smi -c 2>&1 | head -30'   # Health 列全 OK 即通过

# NVIDIA
ssh <别名> 'docker exec <容器名> nvidia-smi'
ssh <别名> 'docker exec <容器名> python -c "import torch; print(torch.cuda.is_available(), torch.cuda.device_count())"'
```

- import 失败先看容器内 conda 环境（不同镜像默认环境不同，映射见 `references/create-containers.md`）。
- 容器内 `teco-smi -c` 显示的进程 PID 是**宿主机 PID**，与容器内 `ps` 不一致，属正常，不是环境问题。
- 验证失败排查顺序：镜像内框架版本 vs 宿主驱动版本 → 设备是否真映射进容器 → 报告卡点。
  **不要伪造"看起来成功"**。

## 5. 容器内执行任务

长任务一律**后台 + 日志落盘 + 打印 pid**；前台阻塞会把 agent 挂住。

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'docker exec -i <容器名> bash -s' <<'EOF'
cd <容器内工作目录>
nohup bash <启动脚本> > <容器内日志路径> 2>&1 &
echo "pid=$!"
EOF
```

- **用 `docker exec -i ... bash -s` + heredoc**，不要 `ssh '<别名>' 'docker exec <容器> bash -c "..."'`：
  后者是 ssh → docker → bash 三层引号嵌套，命令里再有一个引号就会解析错。
  实测 heredoc 形态稳；命令里含引号时优先用它。
- 日志与产物必须落在**容器挂载目录内**（否则容器重建即丢）。先查第 2 节的挂载映射，
  汇报时给容器内和宿主两个路径。
- 只动用户自己的容器/进程。要 kill 别人或不确定归属的进程，先问。
- 需要"先起服务再跑客户端"的任务（推理服务 + 压测/评测），服务起完等就绪再起客户端，
  不要盲等固定秒数——轮询端口/健康检查。

## 6. 盯进度

四步，**从粗到细，先判断"在不在动"再谈"到哪了"**：

1. **进程还在不在**：`docker exec <容器> ps -eo pid,ppid,etime,pcpu,args --sort=-pcpu | head`
   看 `etime`（跑了多久）、有没有 `<defunct>`（僵尸不算在跑）。
2. **日志尾部**：`docker exec <容器> tail -n 25 <日志路径>`。看最后一行是"在推进"还是"在等"。
3. **产物目录**：`docker exec <容器> ls -lt <输出目录>`，看新的 run 目录/文件有没有在长。
4. **增量测速**（对下载、写盘、生成类任务最有效——**看增量，不看瞬时**）：

```bash
ssh <别名> 'docker exec -i <容器> bash -s' <<'EOF'
F=<被观察的文件>
a=$(stat -c %s "$F"); sleep 20; b=$(stat -c %s "$F")
echo "$(( (b-a)/20/1024 )) KB/s  当前 $(( b/1048576 )) MB  增量 $(( b-a )) B"
EOF
```

判定表：

| 现象 | 判定 |
| --- | --- |
| 进程在 + 日志/产物持续增长 | **running**，按增量算 ETA |
| 进程在 + 产物长时间（几分钟）零增量 | **卡住或等待**（等下载/等锁/等对端）→ 把日志最后一行贴出来，别只说"还在跑" |
| 进程消失 + 日志有完成标记 / `rc=0` | **完成**，去读结果文件 |
| 进程消失 + 无完成标记 | **失败或被 OOM/外力杀掉**（`Exited (137)` = SIGKILL），查日志尾部与 rc |

- 汇报进度必须带**已跑时长 + 当前阶段 + 依据**（进程/日志/文件大小），不要只复述用户的描述。
- 别在节点上跑 `find /` 全盘扫描——会拖慢正在跑的任务（尤其正在下载/写盘的）。
  自己用完临时进程要清理；发现别人（或历史会话）留下的残留重进程，报告给用户，不要擅自 kill。
- 结果读取：评测类产物通常在 `<输出目录>/<数据集>/<数据集>/<时间戳>/reports/`，
  里面 `*.json` 是结构化指标、`report.html` 是给人看的。取指标用 `jq` 或 python 解析，
  实例见 `references/exec-and-monitor.md`。

## 7. 汇报契约

给结论 + 一张证据表。固定包含这几项，缺的写"unknown"而不是猜：

| 项目 | 值 |
| --- | --- |
| 节点 | 别名 + `hostname`（多节点共享存储时必须给，用于区分结果来源） |
| 容器 | 名字 + running/exited |
| 镜像 / 卡 | 镜像 tag；占用卡号（Bus-Id + Index） |
| 任务 | 启动脚本 + 计算位置（容器内路径） |
| 日志 | 容器内路径（必要时附宿主路径） |
| 进度 | 已跑时长 + 当前阶段 + 依据（进程/日志/产物） |
| 状态 | running / 卡住 / 完成 / 失败（+ rc） |
| 结果 | 产物目录 + 关键指标（有则给） |

后续别的 skill 要接手时，移交这三样就够：**节点别名 + 容器名 + 容器内工作路径**。

## 8. VS Code / 远程开发接入

- VS Code 的 Remote-SSH **直接读 `~/.ssh/config`**，所以 config 里每个 Host 都是可连接节点；
  本 skill 不维护节点清单，也就不存在"某个节点没被支持"这回事。
- **路线 A（推荐，零侵入）：Attach。** 本地 VS Code Remote-SSH 连上节点 → 装官方
  Dev Containers 扩展 → F1 → "Dev Containers: Attach to Running Container..." → 选容器。
  attach 与容器怎么启动的无关；容器重启后重新 attach 即可。
- **路线 B：容器内 sshd。** 体验与普通 SSH 服务器一致，但要维护镜像内 sshd 和端口分配，
  容器重建后 IP/端口会变。仅用户明确要求时再展开。
- 远端 VS Code 扩展 / agent 需要直连模型 API 时，用 `remote-agent-config` skill 渲染配置，
  **不要依赖反向 SSH 隧道**（隧道一断，远端 agent 就跟着死）。

## 9. 陷阱与边界

- **别按标签推断事实**。节点名、卡型、"哪个集群"都不算证据——卡型看 `command -v`，
  驱动看 `*-smi`，身份看 `whoami`/`hostname`。同一台机器的内网名和外部名可能完全不同。
- **共享存储上的路径会骗人**。多节点共享同一文件系统时，路径到处都能看到，
  不代表结果出自那台——用 `hostname` 和"服务监听地址"一起判断（`127.0.0.1:8010` 说明服务在本机）。
- **卡 → 容器占用反查**用 `who-use-gpu` skill（不是 `gpu-container-lookup`，那个名字不存在）。
- **不要用 `docker inspect` 的设备映射判断卡归属**：实际节点上的容器几乎全是 privileged 且
  `Devices` 为空。查占用关系走上面的 skill。
- **残留进程**：历史会话可能留下长时间空转的命令（全盘 `find`、`tail -f`），
  它们会抢 I/O 并污染后来的进度判断。摸底时留意，报告但不擅自动手。

边界：本 skill 到"任务跑起来、盯到状态、给出结果位置"为止。写实验脚本、代码同步策略
不属于这里（`ssh-docker` 有编译/测试/调试模板）。本 skill 的输出（节点别名 + 容器名 +
工作路径）供后续 skill 接手引用。
