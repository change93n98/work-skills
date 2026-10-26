# Codex → Kylin 远程文件跳转

目标是保留 Codex 的远程会话，通过自定义编辑器把主机、文件、行列号转交给已连接的 Kylin 窗口。
在运行 Codex 桌面端的 Windows 电脑执行配置；远程只部署用户目录内的 Python 小脚本。
本地生成器及测试使用 Python 3.11+；远端 helper 使用 Python 3.8+。

## 先确认入口

1. 从当前电脑的 SSH config 解析用户指定别名，使用 `ssh -G` 确认 hostname/user/port，保留跳板、密钥和自定义端口。没有指定节点才询问；不要使用技能中的示例主机。
2. 通过该别名探测远端 HOME、CPU/ABI、`~/.kylin-ide-server/server/bin/remote-cli/kylin-ide-server`。该版本的 IPC 发现依赖 Linux `/proc`、`ss -xlpn` 和同用户可读进程。
3. 需要先用 Remote - Dev 连接节点并打开项目。多个同用户 Kylin 会话会被明确拒绝，避免把文件打开到错误窗口；不要通过杀进程解决歧义。
4. 查看本地 `~/.codex/config.toml` 的 `desktop.custom_file_handlers` 和现有打开脚本，只输出必要字段，保留其他主机和本地编辑器的路由。

仅检查请求保持只读，不重新部署、打开文件或顺便改模型代理。遇到 `UnsupportedArch`、Node 启动断言或旧 ABI 兼容层崩溃时，先读 [ABI 与运行前提](kylin-prerequisites.md)，不把编辑器错误当成 SSH/API 代理错误。

## 配置

读取 [配置与验证](editor-configuration.md)。源码不保存节点 IP、用户名、HOME 或凭据；按探测结果生成每个节点的独立实例：

```text
python scripts/kylin/render_bridge.py --host <resolved-hostname> --user <resolved-user> --remote-home <remote-home> --output-dir <private-local-bin-dir> --handler-id <unique-handler-id>
```

生成的 `open_in_kylin.py` 接收 Codex `json_stdin`，经 SSH 将 JSON 输入发送到 `open_remote.py`。文件路径不进入远程 shell 命令，保留空格、中文、引号；行列号从 1 开始，拒绝非正整数。

部署前备份要修改的脚本及用户 TOML，只添加本节点的编辑器入口，不覆盖已有 `desktop` 配置。现有打开脚本若需要热接入，只在已确认的自定义 handler 中添加本节点分流，不能替换系统 VS Code 协议处理程序。首次执行前核对别名解析结果与生成实例的 hostname/user 一致。

不得复制 ChatGPT 登录令牌、API key、SSH 私钥、Remote - Dev 证书或浏览器凭据；不关闭 TLS 校验、不改模型供应商、不重新部署代理。不要自动重启当前运行对话的 Codex 桌面端。

## 验证与结论

- 先运行 `python scripts/kylin/test_render_bridge.py`，再验证生成脚本、TOML 片段和参数传递。
- 在用户授权的真实文件上验证完整 SSH → Kylin 路由，要求打开正确文件，并核对编辑器状态栏的行、列。
- 从 Codex 的实际文件路径菜单点击一次，核对本地 `~/.codex/logs/kylin-open.log` 中主机、路径、行列号及远端退出码。
- Python 直接调用成功、IPC 返回成功、文件打开成功、非默认行号的真实点击成功是不同证据；不能互相替代。不能操作 Codex UI 时，由用户完成点击，然后读取日志并核对 Kylin；遵守当前可用工具的界面限制。
- 新菜单名称可能需要重启桌面端才显示。已有首选 handler 的脚本分流可立即用于该入口，但不证明新菜单已被运行中的客户端加载。

技能交付不等于已经完成某个节点的配置；新节点只有在真实文件/行号测试通过后才报告跳转完成。记录未验证项和恢复所需动作。
