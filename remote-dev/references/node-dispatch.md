# 节点间派发：发起机器 → 执行节点 → 容器

用于“从 A 节点给 B 节点的容器起任务”，配合 SKILL.md 第 0–7 节。
A、B 都是运行时解析的角色，不保存某个集群的固定地址或网络拓扑。

## 路由与登录验证

agent 已在 A 上时，直接在 A 读取 `~/.ssh/config` 及其 `Include`，解析 B 的别名。
agent 在电脑上而用户指定从 A 发起时，先 SSH 到 A，再在 A 执行下面的命令；
多行内容以 stdin 原样传递，不在电脑上提前展开 `$HOME`、`$!` 或容器命令。

```bash
# 在发起机器 A 上执行；有效配置可能包含 ProxyJump 或 ProxyCommand
ssh -G <执行节点别名> | grep -iE '^(hostname|port|user|proxyjump|proxycommand|identityfile) '
ssh -o BatchMode=yes -o ConnectTimeout=15 -o ClearAllForwardings=yes <执行节点别名> \
  'hostname && whoami && docker ps -q >/dev/null && echo DOCKER_ACCESS_OK'
```

确认返回的宿主机身份属于目标 B，并确认 Docker 可访问，再按主文件选择容器。
若当前任务依赖 SSH 配置中的端口转发，保留所需转发，省略 `ClearAllForwardings=yes`。

- **端口可达**只说明网络连接成功；**SSH 命令成功并返回宿主机身份**才说明可以登录执行命令。
  回答“是否直连”时同时说明使用的端口与有无跳板，不能把跳板登录成功称作网络直连。
- **直连超时**时先检查配置中的跳板路由；经跳板成功则继续，不需要另建直连通道。
- **认证失败或主机密钥校验失败**时如实报告。电脑能登录 B，并不证明 A 拥有相同的凭据；
  不自动复制私钥、开启 agent 转发或关闭主机密钥校验。
- 没有可用路由时，报告发起位置、目标、失败阶段与必要的缺失参数；
  只有用户要求排查多节点互通时才扩大探测范围，不默认扫描所有节点。

## 在 B 的容器内执行与检查

在 A 发起下面的环境检查；`.bashrc` 初始化在 B 的容器里完成：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 -o ClearAllForwardings=yes <执行节点别名> \
  'docker exec -i <容器名> bash -ic "source /dev/stdin"' <<'EOF'
cd <容器内工作目录> || exit 1
pwd
command -v python
printf 'conda_env=%s\n' "${CONDA_DEFAULT_ENV:-unknown}"
EOF
```

环境确认后，用主文件第 5 节模板在同一容器内启动后台任务，记录容器 PID、日志及产物路径。
SSH 返回成功或打印 PID 仅证明启动命令执行了；任务完成仍需在 B 检查进程、日志和退出状态。
后续监控继续由 A 沿同一路由连接 B，参照 `exec-and-monitor.md`。

路径和 PID 按所在机器解释：B 的宿主路径对应 B 的挂载，容器路径对应 B 的目标容器；
A 的同名路径或共享存储中的同名结果不能证明任务在 A 或 B 执行。
交接时附发起机器、执行节点别名及宿主机 hostname、有效路由、容器和工作路径。

此流程派发的是程序或脚本。把任务交给 B 上另一个 agent 自主完成，需要另行使用 agent 协调机制。
