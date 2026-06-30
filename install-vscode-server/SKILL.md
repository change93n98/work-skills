---
name: install-vscode-server
description: 在远程容器/服务器内快速安装 VS Code Server，解决 VS Code Remote 连接时自动下载慢的问题
---

# Install VS Code Server

在远程容器或服务器内快速安装 VS Code Server，替代 VS Code Remote 连接时的慢速自动下载。

## 使用场景

- VS Code Remote-SSH / Dev Containers 连接远程机器时，vscode-server 下载极慢或超时
- 需要提前在远程机器上预装 vscode-server，实现秒连

## 使用方式

用户会提供一个远程连接信息（SSH host 或容器名称），按以下步骤操作：

### Step 1: 确定远程机器信息

从用户的 SSH config（`~/.ssh/config`）中获取连接方式，或从用户提供的容器/Docker 信息中获取。

### Step 2: 获取本地 VS Code commit hash

在本地运行 `code --version`，取第二行作为 COMMIT hash。例如：
```
1.126.0
7e7950df89d055b5a378379db9ee14290772148a   ← 这就是 COMMIT
x64
```

### Step 3: 在远程机器上安装 VS Code Server

将以下脚本发送到远程机器执行，**自动清理残留目录**（VS Code 下载超时会留下空的带时间戳目录）：

```bash
#!/bin/bash
set -e

COMMIT="{{COMMIT_HASH}}"  # 替换为实际 commit hash

# 检测架构
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  ARCH="x64" ;;
    aarch64) ARCH="arm64" ;;
    armv7l)  ARCH="armhf" ;;
    *)       echo "[ERROR] 不支持的架构: $ARCH"; exit 1 ;;
esac

INSTALL_DIR="$HOME/.vscode-server/bin/${COMMIT}"

# 检查标准目录是否已存在且有内容
if [ -d "$INSTALL_DIR" ] && [ -f "$INSTALL_DIR/bin/code-server" ]; then
    echo "[OK] VS Code Server 已安装: $INSTALL_DIR"
    exit 0
fi

# 清理残留的带时间戳空目录（VS Code 下载超时留下的）
echo "[1/4] 清理残留目录..."
rm -rf "$HOME/.vscode-server/bin/${COMMIT}"_*

# 创建标准目录
mkdir -p "$INSTALL_DIR"

# 下载
echo "[2/4] 下载 vscode-server (commit: $COMMIT, arch: $ARCH)..."
curl -fSL --connect-timeout 15 --max-time 600 \
  "https://update.code.visualstudio.com/commit:${COMMIT}/server-linux-${ARCH}/stable" \
  -o /tmp/vscode-server.tar.gz

# 解压
echo "[3/4] 解压中..."
tar -xzf /tmp/vscode-server.tar.gz --strip-components=1 -C "$INSTALL_DIR"
rm -f /tmp/vscode-server.tar.gz

# 验证
echo "[4/4] 验证安装..."
if [ -f "$INSTALL_DIR/bin/code-server" ]; then
    echo "[OK] VS Code Server 安装成功！"
    echo "     路径: $INSTALL_DIR"
    ls "$INSTALL_DIR/bin/"
else
    echo "[ERROR] 安装失败"
    exit 1
fi
```

### Step 4: 执行流程

对于用户给的 SSH host 或容器：

1. **获取本地 commit hash**：`code --version` 取第二行
2. **替换脚本中的 `{{COMMIT_HASH}}`**
3. **通过 SSH 执行脚本**：
   - SSH 主机: `ssh <host> 'bash -s' < script.sh`
   - Docker 容器: `docker exec -i <container> bash < script.sh`
4. **确认安装成功后，用户重新用 VS Code 连接即可秒连**

### 加速下载备选方案

如果官方源下载慢，可以用国内镜像替换 curl 的 URL：
- Azure CDN: `https://vscode.cdn.azure.cn/stable/${COMMIT}/vscode-server-linux-${ARCH}.tar.gz`
- npmmirror: `https://npmmirror.com/mirrors/vscode-server/${COMMIT}/vscode-server-linux-${ARCH}.tar.gz`

### 注意事项

- **自动清理残留**：VS Code 连接超时会留下带时间戳的空目录（如 `commit_1782790979867`），脚本会自动清理
- 安装后 VS Code Remote 连接时会检测到已安装的 server，跳过下载
- 如果 VS Code 更新了版本，需要重新执行此 skill 更新 server
- 对于 Docker 容器，确保宿主机能访问 `update.code.visualstudio.com`
