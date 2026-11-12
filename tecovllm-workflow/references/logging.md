# 任务日志

开始执行前建立本次任务目录 `run_dir`，将 [日志脚本](../assets/log_step.sh) 放在执行环境可读的位置。`log_step` 取脚本的绝对路径，`log_dir` 默认取该环境下的 `$run_dir/logs`。阶段命令通过日志脚本运行，标准输出和错误输出同时显示并追加到对应文件。日志记录命令的开始、结束和退出码，失败时保留已写出的内容。

第 1 步在发起端记录 SSH 检查输出，便于回查连接失败。下面的 `probe_script` 是本次节点检查命令文件，`ssh_target` 使用已解析的目标别名。

```bash
bash "$log_step" "$log_dir/01-node.log" ssh "$ssh_target" bash -s < "$probe_script"
```

| 阶段 | 日志文件 | 回溯内容 |
| --- | --- | --- |
| 1 检查节点 | `01-node.log` | SSH 目标、实际主机、GPU 型号和占用、Docker 与挂载检查 |
| 2 准备容器 | `02-container.log` | 镜像和容器、GPU 映射、源码版本、构建或换版输出、依赖与验收结果 |
| 3 启动服务 | `03-service.log` | 启动脚本路径、进程、服务地址和就绪验证，服务 stdout 和 stderr 另存 `serve.log` |
| 4 性能测试 | `04-performance.log` | 客户端 commit、测试矩阵、预热和正式脚本退出状态，以及 `warmup`、`formal` 明细路径 |
| 5 精度测试 | `05-precision.log` | 客户端 commit、评测环境和数据集，另保留 `log_eval` 和 `results` |
| 6 Dump size | `06-dump-size.log` | 正式请求区间、采集和去重状态、`deduplicate.log` 和结果路径 |
| 7 抓 prof | `07-prof.log` | profiler 配置、预热、正式请求、开始和停止采集的输出，以及实际 trace 路径 |

构建、安装、启动或测试由多条命令完成时，把各条命令的输出追加到同一阶段日志，或先写成本次执行脚本再交给日志脚本。后台运行批处理时把日志脚本放在后台命令内部，记录实际任务退出结果。服务就绪、产物核对等后续检查也写入对应阶段日志，最后记录阶段状态和产物路径。

容器内日志和产物写到宿主可回查的挂载目录。不同节点或本机与远端目录各自保存时，交付时标明节点、容器内路径和宿主绝对路径。重试继续追加阶段日志，可能覆盖的原生明细写入新的尝试目录，并记录该目录。保存本次使用的脚本和脱敏后的配置摘要，凭据通过原有认证渠道传入。

## 查看远端文件

远端生成的脚本、日志和结果默认保留在节点上。交付时写明 SSH 别名和宿主机绝对路径。容器内文件先通过挂载关系确认宿主路径，再交付可打开的路径。

在本地会话中，以代码格式展示远端路径，并提供 VS Code Remote-SSH 打开命令。`ssh_target` 是已配置的 SSH 别名，`host_file` 是确认可读的宿主机文件路径。 [VS Code Remote-SSH 命令行](https://code.visualstudio.com/docs/remote/troubleshooting#_connect-to-a-remote-host-from-the-terminal)

```bash
code --remote "ssh-remote+$ssh_target" "$host_file"
```

需要在对话里看内容时，通过 `ssh-skill` 只读查看远端文件。只有用户明确要求下载时才保存本地副本。
