---
name: codex-ssh-proxy
description: 配置或检查远程 Codex CLI、VS Code Codex 扩展经 SSH 反向隧道使用本地 v2rayN/HTTP 代理。用户说“给远程节点配置 Codex SSH代理”“远程 Codex 走本地代理”“检查 SSH 代理”时使用。不是 CC Switch 的 API 转发、供应商切换或远程独立 Xray 部署。
---

# Codex SSH 代理

在运行本地 HTTP 代理的电脑执行本技能，通过 SSH 自动配置远程 Linux。
入口是 `scripts/set_codex_ssh_proxy.py`，不依赖 PowerShell，不需要用户把脚本上传服务器。
本地需要 Python 3.8+ 和 OpenSSH，远程需要 Python 3.8+、curl，以及已安装的 Codex CLI 或远程扩展。

## 选择节点和操作

先用 `--list` 读取当前用户的 SSH config，按实际别名解析用户提到的 IP 或节点简称。
不维护固定节点清单；简称存在多个候选时才询问。
指定节点只操作那些节点；用户明确要求全部时才传 `--all`。未指定目标则列出别名让用户选择。
用户问“检查/是否可用/是否重连”使用 `--check-only`，不能顺便修改配置。

在本技能目录下运行（解释器按本机可用路径选择，`dev-node` 替换成实际 SSH 别名）：

```bash
python scripts/set_codex_ssh_proxy.py --list
python scripts/set_codex_ssh_proxy.py --nodes dev-node
python scripts/set_codex_ssh_proxy.py --nodes dev-node --check-only
python scripts/set_codex_ssh_proxy.py --all
```

参数：
- `--nodes ALIAS [ALIAS ...]`：SSH Host 别名，保留其 User、Port、IdentityFile、ProxyJump。
- `--all`：当前配置中所有明确的单别名 Host；不要从简单提及“远程”推断为全部。
- `--local-proxy-port`：默认 10808，本地 HTTP 代理必须正在运行。
- `--remote-proxy-port`：默认 18080，只绑定远程 127.0.0.1。
- `--ssh-config`：默认当前用户 `~/.ssh/config`。
- `--check-only`：验证现有配置、代理认证网页、WebSocket 端点的代理/直连对照、CLI 登录状态和运行中 Codex 的代理环境；不写配置文件，不发送模型请求或复制凭据。
- `--dry-run`：仅显示选中节点及本地 SSH 配置是否需要变更，不连接远程。

## 修改内容与边界

脚本备份并更新本地 SSH Host 中的 RemoteForward、保活参数和 ExitOnForwardFailure。
通过 SSH 先检查远程代理认证端点，再更新：
- `~/.config/codex-proxy-hosts/<hostname>.json`：SSH 模式及代理地址。
- `~/.local/bin/codex-proxy` 和 Bash 中有标记的 `codex` 函数：仅为启动的 Codex 设置代理环境。
- 远程 VS Code `data/Machine/settings.json` 中的 `http.proxy`。
- 若该节点记录了此前创建的 `xray-codex-*` 用户服务，验证它属于该主机后停用并取消自启动。

已有授权覆盖用户明确请求的配置动作，不再重复询问确认。
不复制登录令牌或代理订阅，不改模型供应商、API Key、TLS 校验或 SSH 认证，不安装 CLI。
保留旧 Xray 文件和 linger，避免影响其他后台服务。
共享 HOME 的节点共享 VS Code Machine 设置；逐台建立隧道，运行脚本时顺序处理。
Include 不展开，通配符/多别名/重复 Host 块不自动改写；需要时做针对性的配置整理，不能盲目扩大范围。
远程 settings.json 当前要求严格 JSON；解析失败时停止该节点并报告，不能覆盖原文件。

## 验证和交付

代理配置通过必须有每个目标节点的 HTTP 200、CLI 版本，以及旧受管 Xray 的停用状态。`CHECK_OK` 只表示这些配置检查通过。
`--check-only` 还输出下列诊断，不能省略失败或未验证项：
- `WS_PROXY_ROUTE` / `WS_DIRECT_ROUTE`：不带凭据的 TLS/Upgrade 请求。HTTP 401 是到达服务端认证关卡的预期结果；不是鉴权成功、WebSocket 会话建立或模型推理成功。403 或网络异常不能算通过。
- `CLI_LOGIN`：CLI 自身是否登录；桌面客户端可能按请求注入凭据，因此 CLI 未登录不能直接判定桌面远程会话不可用。
- `RUNNING_CODEX`：同用户进程的代理环境是否匹配。`missing` 是进一步排查线索，不单独证明断连；CLI 的 Bash 函数和 VS Code 的 `http.proxy` 不证明其他入口启动的 Rust 后台进程继承了代理。
- `MODEL_NOT_TESTED`：连接诊断未调用模型；只有另行用该入口的既有授权完成模型请求，才能宣称推理可用。不要为验证方便把本机登录令牌复制到远程。

出现重连时，先核对该入口的日志是否为 WebSocket 连接失败、是否随后 `falling back to HTTP`，再对照实际代理环境。Linux 的 CLI 启动器已显式设置代理环境；不要因 Windows 上的复现就给所有远程节点关闭 WebSocket。
只有证明该节点的 WebSocket 路径失败而 HTTP 路径成功后，才针对选定入口配置 `supports_websockets=false`，保留原模型、供应商和认证。内置供应商 ID `openai` 不能直接覆盖；检查当前版本和配置后处理，不照搬整个本机配置。
侧栏需重新连接 Remote-SSH 并重载窗口，不能把 CLI 测试当作实际侧栏 UI 验证。
若有失败，报告具体节点，检查原因后只重试该节点；不要反复原样重试。

说明：配置脚本的测试 SSH 连接会结束，不留下额外后台隧道。
以后正常 SSH/Remote-SSH 连接根据 config 自动建立转发。本地代理、电脑和承载转发的 SSH 连接必须在线。
已有连接可能仍持有旧端口转发；修改端口后需断开旧连接再重连，保活参数不会自动重连。

## 维护验证

修改脚本后，从本技能目录运行 `python -m unittest discover -s tests -p 'test_*.py' -v`。
再对选定节点运行 `--check-only`；回归测试不能替代远程连接验证或实际入口的模型请求。
