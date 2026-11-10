# 准备 TecovLLM 开发容器

TecovLLM 主仓库默认走 HTTP。内网 GitLab 的 `git@10.10.30.109:` 来源用命令级 `insteadOf` 转成同项目的 HTTP 地址。先核对 `origin` 和 `.gitmodules`，其他主机或地址格式按实际项目的 HTTP 地址处理。

## 2A 从源码构建并创建 T100 容器

1. 在目标宿主机选一个新的任务目录，执行克隆。

   ```bash
   git clone http://10.10.30.109/tecoap/tecovllm.git &&
     cd tecovllm
   ```

   进入仓库后切到指定分支或 commit，再初始化子模块。未指定版本时记录远端默认分支实际取到的 commit。

   ```bash
   git -c 'url.http://10.10.30.109/.insteadOf=git@10.10.30.109:' submodule update --init --recursive &&
     git log -1 &&
     git -C 3rdparty/vllm log -1
   ```

2. 核对当前版本的 `scripts/build-docker.sh` 和 `docker/Dockerfile.ubuntu.dev`。给开发镜像的 `docker build` 加 `--network=host`，在 `VLLM_SDAA_VERSION` 的原默认值后拼接 TecovLLM 的短 commit。`BASE_SDAA_VERSION` 取 JFrog 上与本次构建匹配的基础镜像版本。下面以原默认版本 `4.0.0` 为例。

   ```bash
   VLLM_SDAA_VERSION=${VLLM_SDAA_VERSION:-4.0.0-$(git rev-parse --short HEAD)}
   docker build . -f docker/Dockerfile.ubuntu.dev --target dev --network=host \
     --build-arg "BASE_SDAA_VERSION=${BASE_SDAA_VERSION}" \
     -t "vllm:${VLLM_SDAA_VERSION}" --progress=plain
   ```

   执行 `bash scripts/build-docker.sh`，保留构建日志并核对成功退出。有环境变量覆盖 `VLLM_SDAA_VERSION` 时，确认实际 tag 也带本次短 commit。用 `docker image inspect` 记录镜像 tag 和 ID。把本次构建脚本的两处差异记录到任务目录，再从 checkout 撤销这两处临时改动，便于以后在同一 checkout 换分支。

3. 用 `remote-dev` 的 `references/create-containers.md` 中「创建 T100 容器」命令，将容器名和镜像替换为本次值，按宿主实际目录挂载。源码必须在容器里可访问。用 `docker inspect` 核对容器 ID、镜像与挂载。

4. 在容器实际执行用户的 `~/.bashrc` 里，确认 Conda 初始化之后有一条有效的 `conda activate torch_env_py312`。缺少时追加一次，在交互式 Bash 中 `source ~/.bashrc`，再用新的 `bash -ic` 验证。进入挂载的 TecovLLM 根目录，完成下方「安装与验收」。

## 2B 在已有容器内换版

1. 使用第 1 步核对过的容器。已停止的容器按 `remote-dev` 启动，确认待更新的服务或任务已结束。通过 `bash -ic` 进入 `torch_env_py312`，必要时按下文登记 Git 安全目录。记录当前 TecovLLM 和 vLLM commit、安装来源、系统包版本和挂载路径。用 `git -c 'url.http://10.10.30.109/.insteadOf=git@10.10.30.109:' fetch origin` 确认目标 ref 可取，再检查主仓库和子模块的修改情况。

   上次安装可能已经把旧 `vllm.patch` 应用到 vLLM。确认子模块的完整差异只包含该补丁时，先用旧 checkout 中的补丁执行 `git apply --reverse --check`，通过后再在子模块中反向应用。遇到其他本地修改、暂存或未跟踪内容时，保留原目录，另准备挂载可见的干净 checkout。本地目标分支领先或分叉时，也使用独立 checkout。

2. 在同一个 Python 环境内卸载，再切换和拉取。下面是跟随远端分支的命令，`branch` 取用户指定值。指定 commit 时检出该 commit 后同步并更新子模块。

   ```bash
   python -m pip uninstall -y vllm tecovllm &&
     git switch "$branch" &&
     git -c 'url.http://10.10.30.109/.insteadOf=git@10.10.30.109:' pull --ff-only origin "$branch" &&
     git submodule sync --recursive &&
     git -c 'url.http://10.10.30.109/.insteadOf=git@10.10.30.109:' submodule update --init --recursive
   ```

   核对 TecovLLM 的 HEAD 与目标 ref 一致，vLLM 的 HEAD 与主仓库记录的子模块 commit 一致。

3. 对照**新 checkout** 的 `docker/Dockerfile.ubuntu.dev`，用 `dpkg-query -W` 查容器当前系统包版本。对 TCCL、DNN、Custom、LMK 等实际声明的依赖，用 `dpkg-deb -f` 核对目标 `.deb` 的包名、完整版本和架构，再用 `dpkg --compare-versions` 判断。低于目标版本或缺失的必需包使用对应发行版和架构的 `.deb`，按依赖关系用 `dpkg -i` 安装。版本相同的包直接复用，较新版本记录实际差异。安装后用 `dpkg-query` 复核，发现依赖冲突先解决再继续。

4. 进入「安装与验收」，按与 2A 相同的顺序重新安装两套 Python 包。

## 安装与验收

用 `remote-dev` 的 `bash -ic` 进入容器，核对 `CONDA_DEFAULT_ENV` 为 `torch_env_py312` 且 `python` 和 `pip` 来自该环境。进入实际用于本次安装的 TecovLLM 根目录。需要登记 Git 安全目录时，逐个登记主仓库和 vLLM 子模块的实际绝对路径。

```bash
repo="$(pwd -P)"
git config --global --get-all safe.directory | grep -Fxq "$repo" ||
  git config --global --add safe.directory "$repo"
git config --global --get-all safe.directory | grep -Fxq "$repo/3rdparty/vllm" ||
  git config --global --add safe.directory "$repo/3rdparty/vllm"
```

检查 `build-vllm.sh` 对 `vllm.patch` 的处理。脚本会应用补丁的版本应从干净子模块开始，安装中断后重跑时先核对补丁状态。

```bash
bash -e scripts/build-vllm.sh &&
  bash -e scripts/build-vllm_teco.sh &&
  python -c 'import sys, vllm, vllm_sdaa; print(sys.executable); print(vllm.__file__); print(vllm_sdaa.__file__)'
```

用实际输出核对两个模块分别来自本次 checkout 的 `3rdparty/vllm` 和 `vllm_sdaa`。确认容器在运行、T100 设备可见、任务需要的路径可读，记录两个 commit、包版本和日志。第 2 步在这些检查通过后完成。
