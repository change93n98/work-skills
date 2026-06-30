---
name: install-vscode-server
description: 在远程容器/服务器内通过 code tunnel 快速安装 VS Code Server，解决 VS Code Remote 连接时自动下载慢的问题
---

# Install VS Code Server（via code tunnel）

在远程容器或服务器内通过 `code tunnel` 快速安装 VS Code Server，无需获取本地 commit 版本，一次创建，不同版本自动复用。

## 使用场景

- VS Code Remote-SSH / Dev Containers 连接远程机器时，vscode-server 下载极慢或超时
- 需要提前在远程机器上预装 vscode-server，实现秒连

## 使用方式

用户会提供一个远程连接信息（SSH host 或容器名称），按以下步骤操作：

### Step 1: 确定远程机器信息

从用户的 SSH config（`~/.ssh/config`）中获取连接方式，或从用户提供的容器/Docker 信息中获取。

### Step 2: 在远程机器上执行 code tunnel

**无需获取本地 VS Code 版本和 commit hash**，直接在远程机器上运行 `code tunnel`，它会自动下载与本地 VS Code 匹配的 server。

#### 对于 SSH 主机：

```bash
# 1. 先将 code CLI 传到远程（如果远程没有）
# 检查远程是否已有 code
ssh <host> "which code || test -f ~/.vscode-cli/code"

# 如果没有，下载并安装 code CLI
ssh <host> 'curl -fsSL "https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64" | tar xz -C /tmp && mv /tmp/code ~/.vscode-cli/code && chmod +x ~/.vscode-cli/code'

# 2. 运行 code tunnel（首次运行会提示登录或使用 token）
ssh <host> "~/.vscode-cli/code tunnel --accept-server-license-terms"
```

#### 对于 Docker 容器：

```bash
# 1. 将 code CLI 拷贝到容器内
# 方法A: 从宿主机拷贝（如果宿主机有 code）
docker cp $(which code) <container>:/usr/local/bin/code

# 方法B: 在容器内下载
docker exec <container> bash -c '
  curl -fsSL "https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64" \
  | tar xz -C /tmp && mv /tmp/code /usr/local/bin/code && chmod +x /usr/local/bin/code
'

# 2. 在容器内运行 code tunnel
docker exec -it <container> code tunnel --accept-server-license-terms
```

### Step 3: 首次运行认证

首次运行 `code tunnel` 时需要认证：

1. 终端会显示一个 URL 和 device code
2. 在本地浏览器中打开该 URL，输入 device code 完成认证
3. 认证成功后 tunnel 建立，可以通过 vscode.dev 或本地 VS Code 连接

### Step 4: 连接

- **方式一**：通过 vscode.dev 连接 — 打开 `https://vscode.dev/tunnel/<tunnel-name>`
- **方式二**：在本地 VS Code 中使用 Command Palette → `Remote-Tunnels: Connect to Tunnel`

### 加速下载备选方案

如果 `code tunnel` 下载 vscode-server 仍然很慢，可以手动预下载：

```bash
# 获取需要的版本信息（在远程机器上运行）
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  ARCH="x64" ;;
    aarch64) ARCH="arm64" ;;
esac

# 手动下载 vscode-server tar.gz 到 ~/.vscode-server/bin/<commit>/
# commit hash 从 code tunnel 的日志输出中获取
mkdir -p ~/.vscode-server/bin/<COMMIT>
curl -fSL "https://vscode.cdn.azure.cn/stable/<COMMIT>/vscode-server-linux-${ARCH}.tar.gz" \
  | tar xz --strip-components=1 -C ~/.vscode-server/bin/<COMMIT>/
```

### 注意事项

- `code tunnel` 会自动处理版本匹配，**不需要**手动获取本地 VS Code 的 commit hash
- 首次认证后会保存凭据，后续连接无需重复认证
- 如果 VS Code 更新了版本，`code tunnel` 会自动更新 server
- 对于没有网络访问权限的离线环境，需要手动下载 vscode-server tar.gz 并放到 `~/.vscode-server/bin/<commit>/` 目录
