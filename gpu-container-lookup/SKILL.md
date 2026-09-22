---
name: gpu-container-lookup
description: 查询远程节点上"哪张加速卡被哪个容器占用"。当用户问"XX节点占用物理卡N的容器叫什么"、"谁占用了某张卡"、"GPU/卡 反查容器"、"某节点卡的使用情况/哪张卡在用"时使用；支持太初卡节点（teco-smi，/dev/tcaicard*）和 NVIDIA 节点（nvidia-smi）两类，自动 SSH、按卡找进程 PID、用 docker top 反查容器名。用户没给节点 IP 时必须先询问节点 IP。
---

# 查询占用加速卡的容器

目标：回答"节点 X 的物理卡 N 被哪个容器占用"。思路是卡 → 占用进程 PID → 反查容器名。
不要靠容器 inspect 的设备映射判断——实际节点上的容器几乎全是 privileged 且
`HostConfig.Devices`/`DeviceRequests` 为空，看不出来；只能按进程反查。

## 0. 优先跑脚本

本技能已固化为脚本。**脚本路径要相对本 SKILL.md 所在目录解析**，不要写
`scripts/gpu-container-lookup.sh` 这种相对当前工作目录的路径——技能被调用时
CWD 是用户项目目录，那样写必然找不到文件：

```bash
S="<本 SKILL.md 所在目录>"   # 如 ~/.claude/skills/gpu-container-lookup
bash "$S/scripts/gpu-container-lookup.sh" <节点IP或ssh别名> [卡Index ...]
```

脚本自动完成：裸 IP 匹配 ~/.ssh/config 别名、探测卡型（teco/nvidia）、按卡找进程
PID、docker top + /proc/<PID>/cgroup 反查容器名，并输出结论行和证据表。
节点没写时仍按 §1 先用 AskUserQuestion 问一次再调脚本；
脚本失败或输出异常时，再按下述步骤手工执行并核对。

## 1. 确认参数

- 节点：IP 或 ssh 别名（如 `192.167.252.35`、`sdaa-192.167.252.35`、`172.16.240.15`）。**用户请求里没写节点时，用 AskUserQuestion 问一次**；已写明则不要再问。
- 卡号：可选。给了就只查该卡；没给或问法是"哪些卡在用/使用情况"，则扫全部卡输出完整映射。
- 卡号口径：监控工具的 Index 从 **0** 开始（teco-smi 的 Index 1 = 第二张物理卡）。回答时同时给出 Bus-Id 和 Index，避免歧义。

## 2. 连接节点

1. 先在 `~/.ssh/config` 里 `grep` 该 IP 找对应的 Host 块，用**别名**连接（别名自动携带 Port/ProxyJump/IdentityFile；sdaa 集群端口是 65056，H100 节点要经跳板机，裸 IP 直连会失败）。
2. 找不到别名时才用 `ssh -o BatchMode=yes <ip>` 兜底。
3. 若 `~/.ssh/config` 仍保留 `RemoteForward 15721`，stderr 可能出现 `Warning: remote port forwarding failed for listen port 15721`，属正常，忽略即可。

## 3. 找占用卡的进程

先探测卡类型：

```bash
ssh -o BatchMode=yes <别名> 'command -v nvidia-smi; ls /opt/tecoai/bin/teco-smi 2>/dev/null; command -v sdaa-smi'
```

**太初卡节点**（有 /opt/tecoai/bin/teco-smi）：

```bash
ssh -o BatchMode=yes <别名> '/opt/tecoai/bin/teco-smi 2>&1 | head -80'
```

解析输出两段：上半段是各卡 Index/BusId/显存总量，下半段 `Processes:` 表是
`Device | PID | Process name | Memory Usage`——Device 即卡 Index。若 `Permission denied`
再试 `sudo -n /opt/tecoai/bin/teco-smi`。

**NVIDIA 节点**：

```bash
ssh -o BatchMode=yes <别名> 'nvidia-smi --query-gpu=index,gpu_uuid --format=csv,noheader; nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader'
```

用 gpu_uuid 把进程对回卡 index。

目标卡没有任何进程（或 0MB）→ 直接回答"无占用"并列出各卡占用概览，到此结束，不必查容器。

## 4. PID 反查容器名

对每个 PID（注意嵌套引号，整段单引号包住，内部 awk 用转义）：

```bash
ssh -o BatchMode=yes <别名> 'PID=<目标PID>; for c in $(docker ps -q); do n=$(docker inspect -f "{{.Name}}" $c | sed "s#^/##"); docker top $c 2>/dev/null | awk -v P=$PID "{print \$2}" | grep -qx "$P" && echo "$n"; done'
```

一个 PID 通常只属于一个容器。`docker top` 不可用时的兜底：`grep -o "docker[-/].*" /proc/<PID>/cgroup`，
从 cgroup 路径取容器 ID，再 `docker ps --no-trunc | grep <容器ID前12位>` 得到名字。

`docker ps` / `docker top` 报 `permission denied` → 整段改用 `sudo -n docker ...`
重试（同 remote-dev 的约定）。不重试会把容器内进程误判成"宿主机进程"：cgroup
兜底也依赖 `docker ps` 把容器 ID 映射成名字。

查不到所属容器 → 这是宿主机进程，回答时如实标注"宿主机进程，不属于容器"。

## 5. 回答格式

直接给结论 + 一张证据表，例如：

| 卡 Index | Bus-Id | 显存占用 | PID | 进程 | 容器名 |
|---|---|---|---|---|---|
| 1 | 00000000:34:00.0 | 14318MB | 3730222 | VLLM | vllm0251-alice-dev |

其余卡 0MB 的可以一句话带过（"其余卡均为空"）。同卡多进程、多容器共卡时逐行列出。
最后附一句口径说明（Index 0 起）以消除"物理卡 1"的歧义。
