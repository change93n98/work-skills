# 配置与验证

## 文件分工

| 位置 | 作用 |
| --- | --- |
| Windows `~/.codex/config.toml` | 注册 SSH 自定义编辑器，保留原有设置 |
| Windows 私有 bin 目录的 `open_in_kylin.py` | 校验目标主机/用户，提取文件和行号，经 OpenSSH 发送 JSON |
| 远端 `~/.local/lib/codex-kylin-open/open_remote.py` | 查找当前用户的活跃 Kylin extensionHost IPC，调用原生 remote CLI |
| Windows `~/.codex/logs/kylin-open.log` | 记录路由、文件、行列号、结果；不记录完整 hostConfig 或凭据 |

这些是操作系统用户配置，不是容器内的工作负载。文件只能打开在该 SSH 用户可见的路径；容器独有路径应先确认宿主挂载映射，不能直接当作宿主文件。

## 探测与生成

先用 `ssh -G <alias>` 解析 hostname/user，远端 Python 获取 HOME；不要把 PowerShell 的 `$HOME` 误展开成本机目录。

在 skill 目录运行 `scripts/kylin/render_bridge.py`，输出目录选择用户私有、持久的位置，如 `~/.codex/bin/kylin-<node-id>/`。它只生成配置实例和 TOML 片段，不连接主机、不修改用户配置；已有输出文件默认拒绝覆盖，确需覆盖时先备份再传 `--force`。

`--handler-id` 应为每个节点单独的 ID。`--python` 可指定桌面端实际可用的 Python 绝对路径；默认使用当前解释器，旁边有 `pythonw.exe` 时使用它。不要把只在某个终端 PATH 中可见的解释器当成桌面端可用。

将生成的 `open_remote.py` 经既有 SSH 连接部署到远端对应 HOME 的 `.local/lib/codex-kylin-open/open_remote.py`，设置为仅该用户可读写/执行。远程创建目录和部署脚本前应有用户配置授权。

## Codex 自定义编辑器

将生成的 `handler.toml` 合并到本地用户级配置，逐项保留其余配置。官方字段为：

```toml
[desktop.custom_file_handlers.kylin-example]
label = "龙芯远程编辑器（Kylin）"
icon = "apps/vscode.png"
command = "C:/absolute/path/to/pythonw.exe"
args = ["-X", "utf8", "C:/absolute/private/bin/open_in_kylin.py"]
input = "json_stdin"
supports_ssh = true
```

示例路径必须替换成生成实例的实际值。配置解析通过后，桌面端的新菜单入口按官方说明需重启后确认。不要为显示新名称而终止当前对话；若已有可用自定义 handler，可把目标节点转交生成实例的 `is_target_request()`/`open_request()`，使当前入口立即走 Kylin。多节点实例放在独立目录，通过唯一模块名加载，不能让同名脚本覆盖另一节点。

源：[官方自定义编辑器配置](https://learn.chatgpt.com/docs/config-file/config-advanced#add-custom-file-handlers)。部署前核对当时客户端支持的字段。

## JSON 输入与测试

真实 `json_stdin` 包含 `target/path/appPath/location/hostConfig/remoteWorkspaceRoot/remotePath`；示例输入只可用于脚本测试：

```json
{
  "target": "custom:kylin-example",
  "path": "/home/dev/project/main.py",
  "location": {"line": 20, "column": 3},
  "hostConfig": {"kind": "ssh", "sshAlias": "dev-node"},
  "remoteWorkspaceRoot": "/home/dev/project",
  "remotePath": "/home/dev/project/main.py"
}
```

`--dry-run` 只解析本机 SSH config 并显示命令及 JSON，不打开远端文件。实际运行发送 JSON 到固定 Python helper，路径永远不拼接进 shell 代码。对其他节点、错误用户、相对路径、控制字符或非正行列号应明确失败；不能静默打开本地同名文件。

## 已有实例的验证边界

2026-10-26 的初始案例已验证：真实 SSH remote CLI 可打开文件并定位非默认行号；通过 Codex 真实点击可以打开远程文件（该次请求位置为 1:1）；桥接脚本收到非默认行列号并返回成功。用户停止界面操作后，**尚未完成该次 Codex 非默认行号点击的画面核验**。这不是对其他节点或未来实例的通用通过结论。

配置备份可能包含用户原有敏感字段，保留在本机，不放入 skill 仓库。仓库只保留模板、生成器、测试和说明，不保存实例、日志、连接令牌、历史截图或备份。
