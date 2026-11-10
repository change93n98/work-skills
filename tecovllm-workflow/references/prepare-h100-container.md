# 准备 H100 容器

## 核对设备和镜像

在目标宿主机按 `remote-dev` 的 NVIDIA 分支检查 Docker、NVIDIA runtime 和 GPU 占用。用 `nvidia-smi` 确认卡型、物理编号和 UUID，按本次任务选择 H100 设备。已有指定容器时，通过 `docker inspect` 核对镜像、GPU 映射、端口和挂载，再做下面的容器验收。

新建时选择用户指定或节点已有、已确认包含 vLLM 的 CUDA 镜像。先用 `docker image inspect` 核对镜像 ID、平台、入口和默认命令。镜像不在节点时，按用户指定的镜像来源获取。需要换版本时选已有的对应镜像并创建新容器。

## 从已有镜像创建

用本次核对过的容器名、镜像和挂载创建容器。下面在宿主机 Bash 运行，`gpu_devices` 是已选宿主 GPU 的编号或 UUID 列表，例如 `0,2`。多卡的 `device=` 值作为一个带引号的 CSV 字段传给 Docker。示例使用宿主网络，模型目录和任务目录分别以只读和可写方式挂载到同名路径。 [Docker GPU 参数](https://docs.docker.com/engine/containers/gpu/#expose-gpus-for-use)

```bash
docker run -dit --name "$container" --pull never \
  --gpus "\"device=$gpu_devices\"" --network host --ipc host \
  --mount "type=bind,source=$model_dir,target=$model_dir,readonly" \
  --mount "type=bind,source=$run_dir,target=$run_dir" \
  --workdir "$run_dir" --entrypoint /bin/bash "$image"
```

示例用 `/bin/bash` 覆盖默认直接启动服务的入口，服务由第 3 步启动。镜像需要初始化脚本时，按该镜像的实际入口进入它提供的 vLLM 环境。 [Docker 入口规则](https://docs.docker.com/engine/containers/run/#default-entrypoint)

## 容器验收

核对容器内 GPU UUID 与宿主分配一致。使用第 3 步实际采用的 Python 检查 CUDA 和 vLLM。下面以镜像 PATH 中的 `python` 为例。

```bash
docker exec "$container" nvidia-smi --query-gpu=index,uuid,name --format=csv,noheader &&
  docker exec "$container" bash -ic 'python -c "import sys, torch, vllm; assert torch.cuda.is_available(); print(sys.executable, vllm.__version__, vllm.__file__, torch.version.cuda, torch.cuda.device_count())"'
```

确认 CUDA 可见卡数符合本次任务、模型目录可读、任务目录可写。记录镜像 ID、GPU 映射、Python 和 vLLM 版本及加载路径，交给第 3 步。
