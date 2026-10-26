# Kylin 与龙芯 ABI

官方 VS Code Remote-SSH 的 CPU 架构支持，与现有 Kylin/Code-OSS 远程编辑器的文件打开机制是两件事。此 skill 使用已经可工作的 Kylin remote CLI，不尝试让微软 Remote-SSH 下载一个不匹配的服务包。

先观察 `uname -m`、系统发行版、`getconf GNU_LIBC_VERSION`，并对**实际使用的 Node** 运行 `file`、`readelf -h/-l`、`ldd` 和最小启动检查。不能仅凭主机名、下载文件名或 uname 中的 `loongarch64` 判断新旧 ABI。

初始案例中，旧 Node 是 `OBJ-v0`，解释器 `/lib64/ld.so.1` 实际进入系统的旧兼容层，`rt_sigprocmask` 出现 `EINVAL` 并导致初始化断言。适配系统的新包 Node 是 `OBJ-v1`，使用原生 `/lib64/ld-linux-loongarch-lp64d.so.1`。包名 `loongarch64` 与 `loong64` 在该发行包里代表不同构建，不能套用到所有供应方。

需要更换服务包时，核对当时官方发布资源与二进制 ABI，备份用户自己的 `server` 目录，保留 `data` 和扩展，不替换系统 glibc、不覆盖系统 loader、不杀其他人的 IDE 进程。此步骤超出单纯文件跳转检查，只有用户授权修复编辑器环境时才执行。

发行资源：[Kylin IDE Server](https://gitee.com/mcy-kylin/kylin-ide-server/releases)。版本和构建必须以实测为准。
