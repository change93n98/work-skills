# 在实际 runner 中添加标注

以下是 vLLM V1/SDAA 同类 runner 的模板，不是可跨版本盲打的补丁。先确认变量和 CPU 字段的语义；字段不存在时使用该版本的对应状态，不能以 token 数猜测阶段。

## 1. 保存本轮阶段

放在真实、非空请求路径，输入准备已完成且状态有效之后、graph 分发之前。不要放进 dummy/capture 共用的静态判断函数，也不要增加设备同步或修改请求状态。

```python
self._phase_trace_step = getattr(self, "_phase_trace_step", 0) + 1
phase_step = self._phase_trace_step
computed = self.input_batch.num_computed_tokens_cpu[:num_reqs].tolist()
prompt = self.input_batch.num_prompt_tokens[:num_reqs].tolist()
pending_prompt = [c < p for c, p in zip(computed, prompt)]
phase = (
    "prefill"
    if all(pending_prompt)
    else "mixed"
    if any(pending_prompt)
    else "decode"
)
```

这两个字段在所验证的 V1 实现中是已有 CPU 数据；别把同名设备 Tensor `.cpu().tolist()` 加进热路径。空 batch 提前返回或单独标记 idle，避免空列表的 `all()` 被误解为 prefill。

`mixed` 表示 batch 中同时包含 prefill 和 decode。若实际模型已有权威阶段字段，优先使用它，并核对缓存命中、chunked prefill 等语义。

## 2. 标注最终选图结果

等 graph 模式和 padding 最终确定后构造名称。变量名按当前 runner 调整，保留原有执行/上下文顺序。

```python
phase_label = (
    f"PHASE_GRAPH step={phase_step} phase={phase} "
    f"tokens={num_tokens_unpadded} padded={num_tokens_padded} "
    f"mode={cudagraph_mode.name} "
    f"computed={computed} prompt={prompt}"
)
```

在原有包围 `_model_forward(...)` 的 `with (...)` 中增加一项：

```python
torch.profiler.record_function(phase_label),
```

保留 `set_forward_context(...)`、connector 等原有上下文和完整 forward 参数。scope 要持续到真正 forward/replay 返回，不能只包 `_determine_batch_execution_and_padding()`，否则 scope 内没有模型的 graph replay。

这只是诊断标注，不能修改 `force_uniform_decode`、`cudagraph_mode`、metadata 或 graph 缓冲区。需要检查 MTP 草稿时，在其真实 forward 外单独加 `DRAFT_GRAPH` 前缀的 scope，不扩大主模型标注范围冒充同一阶段。

## 3. 加载与验证

复制完整 Python 包到 `RUN_DIR/python/`。服务进程中设置：

```bash
export PYTHONPATH="$RUN_DIR/python${PYTHONPATH:+:$PYTHONPATH}"
```

用同一解释器和环境确认 `inspect.getsourcefile()` 指向副本，父类的选图实现仍来自预期安装。父进程和 worker 都要继承此环境；仅在不参与进程启动的终端里 export 不会影响服务。不要覆盖其他必要的 `PYTHONPATH`。

若已有 diff，只有版本、上下文都匹配时才在副本上应用；先 `patch --dry-run TARGET DIFF`。不要把旧版本的行号、绝对路径或原已加标注的副本重复套用到其他模型。

## 4. 搜索与判断

```text
phase=prefill tokens=2
mode=PIECEWISE
phase=decode
```

step 编号可能包含预热，因此优先按 phase/tokens/mode 搜索。字段 `computed` 是本轮开始前已计算数量，`prompt` 是 prompt 总长度；`tokens` 为本轮调度数量，`padded` 为执行补齐后的数量。

只在标签、源码实际读取位置、加载路径及调用范围都已核验后，把 mode 当作直接证据。scope 内的 CPU GraphLaunch 计数可以佐证 replay 范围，但不是设备耗时；异步设备 kernel 的持续时间需结合 correlation/flow 分析，不能直接按 CPU scope 时间截断当成总 GPU 时间。
