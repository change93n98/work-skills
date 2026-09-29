# Kernel 分类规则与平台适配

`prof_analyze.py` 与 `prof_analyze_perfetto.py` 共用 `scripts/kernel_categories.py`，避免两种解析路径的分类结果不一致。输出继续保持六个稳定类别：

- `gemm`
- `通信 (comm)`
- `FlashAttention (fa)`
- `Triton`
- `其他elementwise`
- `memcpy/memset`

未知但有效的计算 kernel 仍归入 `其他elementwise`，以兼容已有 Excel/JSON 消费方，但会标记 `fallback:unknown`，必须通过 audit 报告复核。运行时等待标记不计为计算 kernel。

## 平台命名覆盖

### ROCm / DCU

识别 rocBLAS、hipBLASLt、CK GEMM/FMHA、RCCL、HIP memcpy/memset 等命名。

### NVIDIA

识别 cuBLAS/cuBLASLt、NVJet、CUTLASS、FlashAttention、NCCL、Triton 和 CUDA memcpy/memset。CUTLASS FlashAttention 会先按 attention 识别，其余 CUTLASS kernel 按 GEMM 处理。

### 太初 T100

当前规则基于真实 T100 trace 覆盖以下常见前缀和模式：

| 类别 | 典型模式 |
|---|---|
| GEMM | `tecoblas::*teco_slave_gemm*`、`slave_gemm_*`、`slave_mm_*`、`GemmWrapArgs` |
| 通信 | `tccl_*`、`allReduce`、`all_gather`、`reduce_scatter` |
| Attention | `teco_slave_flash_attention*`、`fused_block_attention*`、`block_attention*` |
| Elementwise/融合算子 | `tecolmk_slave_fused_norm*`、`ffn_layer_general*`、`causal_conv1d*`、DeltaRule、`fused_qk_gemma_norm_mrope`、sampling、rope、softmax |
| 内存操作 | `sdaart::sdaaMemcpy*`、`copy_stride_dma*`、`set_tensor` |
| 非计算标记 | 精确 `WAIT` 和明确 profiler marker 会排除，由 phase window 与 kernel busy time 的差值体现在 bubble 中 |

若新增 T100 kernel 大量落入 `其他elementwise`，先按总耗时排序检查名称，再只添加稳定的库/算子模式；不要按一次运行中的完整模板实例名逐条硬编码。

## 分类优先级

1. profiler/WAIT 等排除项；
2. 通信融合 kernel（例如 GEMM+all-reduce）；
3. FlashAttention/分页 attention；
4. NVIDIA CUTLASS 非 attention kernel；
5. 六类模式表；
6. 未知有效 kernel 回退到 `其他elementwise`。

修改规则后至少执行：

```bash
python scripts/test_kernel_categories.py
python scripts/prof_analyze.py --trace-file <t100-trace.json.gz> --output-dir <output-dir> --verbose
```

同时使用一个已有 NVIDIA 或 DCU trace 做回归，确认原分类未被 T100 规则抢占。

## 已发现并防止的误判

- `gemma` 不是 `gemm`：`fused_qk_gemma_norm_mrope` 由本地 tecovllm 代码证明是 norm/rope 融合。
- T100 `tecodnn::*broadcast_add`、`no_broadcast_*`、`masked_fill_*` 是单卡逐元素 kernel，不是通信；通信必须有 TCCL/NCCL/RCCL 或明确 collective 名。
- `prefill_cache`、`reshape_and_cache_flash`、`block_kv_gather` 是 KV cache/layout，不是 FlashAttention。
- CUTLASS 需要先判断 `FlashAttn` 和 `DeltaRule`，剩余明确矩阵乘路径才按 GEMM 兜底。
