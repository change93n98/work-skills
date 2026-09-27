# 执行任务与盯进度：命令集

配合 SKILL.md 第 5–7 节使用。所有命令都在**容器内**执行，节点名一律用 `<别名>` 占位——
别名从 `~/.ssh/config` 现取，不要抄某个具体节点。

## 一、先找到"任务是什么"

用户说"有个任务在跑，看下进度"时，先别猜，按这条链找：

```bash
# 1) 容器内在跑什么
ssh <别名> 'docker exec <容器> ps -eo pid,ppid,etime,pcpu,args --sort=-pcpu | head -25'

# 2) 通常能看到：驱动脚本 / 客户端脚本 / 遗留的 <defunct> 僵尸
#    从命令行里认出驱动脚本路径（例：bash .../run_xxx_datasets.sh），读它
ssh <别名> 'docker exec <容器> cat <驱动脚本路径>'

# 3) 驱动脚本里一般写着：日志路径、输出目录、执行顺序（这些是判断进度的关键）
```

驱动脚本里常见的三类"进度锚点"，找到它们比看进程更有用：

| 锚点 | 用途 |
| --- | --- |
| 总控日志（每次阶段 START/END + rc） | 判断"第几个数据集/阶段"、"上一个成功没" |
| 阶段日志（每个子任务一个 log） | 判断当前阶段在干什么、最后一行是什么 |
| 输出目录（run 目录带时间戳） | 判断产物是否落地、有几个已完成 |

```bash
ssh <别名> 'docker exec <容器> cat <总控日志>'                  # START/END 行
ssh <别名> 'docker exec <容器> ls -lt <输出目录> | head -20'     # 各阶段的产物
ssh <别名> 'docker exec <容器> tail -n 25 <当前阶段日志>'
```

## 二、进度四步与增量测速

四步（进程 → 日志 → 产物 → 增量）见 SKILL.md 第 6 节。增量测速模板（可直接用）：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 <别名> 'docker exec -i <容器> bash -s' <<'EOF'
F=<被观察的文件>
TOTAL=<预期总大小，字节；不知道就不填>
a=$(stat -c %s "$F" 2>/dev/null) || { echo "文件不存在: $F"; exit 1; }
sleep 20
b=$(stat -c %s "$F")
rate=$(( (b-a)/20 ))                       # B/s
echo "速率 $(( rate/1024 )) KB/s | 当前 $(( b/1048576 )) MB | 增量 $(( b-a )) B/20s"
if [ -n "$TOTAL" ] && [ "$rate" -gt 0 ]; then
  echo "剩余 $(( (TOTAL-b)/rate/60 )) 分钟（按当前速率）"
fi
EOF
```

要点：

- **看增量，不看瞬时**。单次 `ls -l` 看不出"是否在动"，两次采样只差才说明。
- 速率算出来的 ETA 是**线性外推**，只在剩余阶段性质相同（同一批下载/同一批推理）时可信；
  跨阶段（下载完转推理）要重新采样。
- 多文件并发增长时，对目录取总大小：`du -sb <目录>` 同样两次采样。

## 三、状态判定细节

| 现象 | 判定 | 下一步 |
| --- | --- | --- |
| 进程在 + 日志/产物增长 | running | 报当前阶段 + 增量 ETA |
| 进程在 + 长时间零增量 | 卡住/等待 | 贴日志最后一行；查是否等下载、等对端服务、等锁 |
| 无主进程，只剩 `<defunct>` | 已结束（僵尸不占 CPU） | 看 rc |
| 日志出现 `END ... rc=0` / `Done` / 完成行 | 成功 | 读结果 |
| 日志无完成行、容器 `Exited (137)` | 被 SIGKILL（常见 OOM/外力） | 查日志尾部与 dmesg |

判定 OOM 与资源竞争时的辅助信息：

```bash
ssh <别名> 'docker ps -a --format "{{.Names}}\t{{.Status}}" | head -20'   # 看 Exited 码
ssh <别名> 'docker exec <容器> tail -n 40 <日志> | grep -iE "error|oom|killed|traceback|timeout"'
```

## 四、读结果

评测/跑分类任务的结果目录通常是：

```
<输出目录>/<数据集>/<数据集>/<时间戳>/
├── logs/        eval_log.log（含完整任务配置：模型、数据集、参数）
├── configs/     task_config.yaml
├── predictions/ 逐条预测 jsonl
├── reviews/
└── reports/     结构化 json + report.html
```

取结构化指标：

```bash
# jq 存在时（不一定有，先 command -v jq）
ssh <别名> 'docker exec <容器> jq -c "{score,num,metrics:[.metrics[]|{name,score,num}]}" <reports 目录>/<模型名>/<数据集>.json'

# jq 不存在时用 python3——注意 heredoc 形态，别嵌引号
ssh <别名> 'docker exec -i <容器> bash -s' <<'EOF'
python3 - <<'PY'
import json, glob
for p in glob.glob('<reports 目录>/*/*.json'):
    d = json.load(open(p))
    print(p, '-> score', d.get('score'), 'num', d.get('num'))
PY
EOF
```

- `perf_metrics.throughput` 里的 `avg_output_tps` / `avg_req_ps` **不是聚合吞吐**：
  它们等于 `1/平均延迟` 和 `输出token均值/平均延迟`（单请求口径）。
  要聚合吞吐用挂钟时间自己算：`总样本数 ÷ 端到端秒数`。
- 汇总多个阶段的精度/性能做对比时，**从各自的 report json 读原值**，不要从终端输出里抄数字。

## 五、常见"看起来在跑其实卡住"的形态

- **惰性下载**：评测框架按子集/样本现用现下数据集（下载器只在需要时触发）。表现为
  "进程在、CPU 不高、日志停在进度条"。这类任务的前半程完全不在推理——先确认"现在是在下载还是在算"，
  再谈 ETA，否则给出的时间会差一个量级。
- **等对端服务**：客户端起来了但推理服务还没 ready，或反过来。轮询服务端口/健康检查，别盲等。
- **共享资源争抢**：同一节点上别人的任务在抢 I/O 或卡。摸底时的"宿主重活"和 `who-use-gpu`
  能看出来。
- **前台阻塞**：任务被以非后台方式起在容器里，agent 自己的 `ssh`/`docker exec` 会一直挂着。
  发现这种情况不要二次 `docker exec` 硬等，先用另开的命令看进程和日志。

## 六、不要做

- 不要在节点上跑 `find /` 全盘扫描或递归 `du`（拖慢正在跑的任务，尤其正在写盘/下载的）。
  要定位文件用已知路径 + `ls`，或限制在具体目录内并加 `-maxdepth`。
- 不要用 `tail -f` 这类不会返回的命令（会挂住会话）。用 `tail -n`。
- 不要擅自 kill 归属不明或别人的进程，包括历史会话留下的残留命令——报告给用户。
- 不要修改正在跑的任务的日志/产物目录。
