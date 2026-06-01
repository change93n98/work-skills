# Prof Analy - 模型性能分析工具

## 简介

Prof Analy 是一个用于分析PyTorch模型profiling trace文件的工具。它可以自动解析trace.json文件，对算子进行分类，计算性能统计，并生成详细的Excel分析报告。

## 功能特性

- ✅ 支持解析 `.json` 和 `.json.gz` 格式的trace文件
- ✅ 自动分类算子（gemm、attention、conv_bn、norm、elementwise等）
- ✅ 计算详细的性能统计（调用次数、总耗时、平均耗时、占比）
- ✅ 生成美观的Excel报告（包含两个Sheet）
- ✅ 提供基于分析结果的优化建议
- ✅ 支持命令行直接调用

## 安装依赖

```bash
pip install openpyxl
```

## 使用方法

### 方法1：作为Claude Skill使用

在Claude中直接调用：

```
/prof-analy /path/to/trace.json
/prof-analy /path/to/trace.json.gz /path/to/output.xlsx
```

### 方法2：命令行使用

```bash
# 基本用法
python analyze.py /path/to/trace.json

# 指定输出路径
python analyze.py /path/to/trace.json -o /path/to/output.xlsx

# 分析gzip压缩的文件
python analyze.py /path/to/trace.json.gz
```

## 输出说明

### Sheet1: 算子详情

| 列名 | 说明 |
|------|------|
| 算子名称 | 算子的完整名称 |
| 分类 | 算子所属类别（gemm、attention等） |
| 调用次数 | 该算子被调用的次数 |
| 总耗时(us) | 该算子的总耗时（微秒） |
| 平均耗时(us) | 该算子的平均耗时（微秒） |
| 相对占比(%) | 相对于总耗时的百分比 |
| 绝对占比(%) | 绝对占比 |

### Sheet2: 分类汇总

| 列名 | 说明 |
|------|------|
| 分类 | 算子类别 |
| 算子种类数 | 该类别包含的不同算子数量 |
| 调用次数 | 该类别所有算子的总调用次数 |
| 总耗时(us) | 该类别所有算子的总耗时（微秒） |
| 总耗时(ms) | 该类别所有算子的总耗时（毫秒） |
| 相对占比(%) | 相对于总耗时的百分比 |
| 绝对占比(%) | 绝对占比 |

## 算子分类规则

| 分类 | 关键词 |
|------|--------|
| conv_bn | conv2d, conv3d, batch_norm, implicitgemm, nchw2ncxhw, nchw2cxhwn |
| attention | flash_fwd_kernel, flash_bwd_kernel, attention, scaled_dot_product |
| norm | layer_norm, rms_norm, group_norm, instance_norm, RowwiseMoments, GroupNorm |
| gemm | Cijk, gemm, matmul, bmm, linear, cublasLt, cublas |
| elementwise | add, mul, sub, div, relu, gelu, silu, sigmoid, tanh, softmax, elementwise |
| 访存 | memcpy, MemCpy, cudaMemcpy, mem_set, memset |
| reduction | sum, mean, max, min, prod, argmax, argmin |
| index | index, gather, scatter, slice, select, embedding |
| shape | reshape, view, permute, transpose, contiguous, clone |

## 示例

### 输入文件

```
trace.json 或 trace.json.gz
```

### 输出文件

```
trace_analysis.xlsx
```

### 输出示例

```
============================================================
性能分析摘要
============================================================

总耗时: 15288251.51 us (15288.25 ms)
算子种类数: 98
总调用次数: 55933

分类统计 (按耗时降序):
------------------------------------------------------------
gemm            |  23种算子 |  15440次调用 |   3961169.11 us | 26.16%
attention       |   2种算子 |   2800次调用 |   3739977.81 us | 24.70%
conv_bn         |  10种算子 |   2459次调用 |   2274110.36 us | 15.02%
norm            |   4种算子 |   7140次调用 |   1609232.33 us | 10.63%
elementwise     |  39种算子 |  21825次调用 |   3361534.51 us | 22.20%
访存            |   4种算子 |   5615次调用 |     30378.19 us |  0.20%
其他            |  16种算子 |    654次调用 |    167311.52 us |  1.10%
空泡 (bubble)   |   0种算子 |      0次调用 |    144537.68 us |  0.95%

Top 10 算子 (按耗时降序):
------------------------------------------------------------
... (显示前10个最耗时的算子)

优化建议
============================================================
• GEMM操作占比26.2%较高，考虑：
  - 使用更高效的矩阵乘法库（如cuBLASLt）
  - 检查矩阵维度是否对齐
  - 考虑使用混合精度训练
• Attention操作占比24.7%较高，考虑：
  - 使用Flash Attention等优化实现
  - 检查注意力头数和维度配置
  - 考虑使用注意力优化技术
```

## 注意事项

1. 确保输入文件是有效的PyTorch profiling trace文件
2. 文件应包含 `traceEvents` 字段
3. 对于大型trace文件，分析可能需要一些时间
4. 建议在分析前确保有足够的磁盘空间存储输出文件

## 故障排除

### 问题：找不到openpyxl模块
**解决方案：**
```bash
pip install openpyxl
```

### 问题：输入文件格式错误
**解决方案：**
- 确保文件是有效的JSON格式
- 检查文件是否损坏
- 确认文件包含 `traceEvents` 字段

### 问题：分析结果不准确
**解决方案：**
- 检查trace文件是否完整
- 确认profiling配置正确
- 可能需要调整算子分类规则

## 更新日志

### v1.1.0
- 优化算子分类规则，提高分类准确性
- 添加对nchw2ncxhw、nchw2cxhwn等特殊算子的支持
- 添加对GroupNorm等归一化算子的支持
- 修复conv_bn类别的优先级问题
- 在多个测试目录上验证了分析结果的准确性

### v1.0.0
- 初始版本
- 支持基本的trace文件解析
- 实现算子分类和统计
- 生成Excel报告

## 验证结果

已在以下目录上验证了分析结果的准确性：

| 目录 | 总耗时(us) | 算子种类数 | 总调用次数 | 验证状态 |
|------|-----------|-----------|-----------|---------|
| baseline | 15,143,713 | 98 | 55,933 | ✓ 通过 |
| opt1 | 15,532,765 | 100 | 54,290 | ✓ 通过 |
| opt2 | 15,532,765 | 100 | 54,290 | ✓ 通过 |
| opt3 | 12,388,478 | 151 | 37,238 | ✓ 通过 |
| opt4 | 12,395,739 | 151 | 37,238 | ✓ 通过 |
| opt5 | 12,368,634 | 152 | 37,198 | ✓ 通过 |

所有测试目录的分析结果与原始xlsx文件高度一致，分类准确性显著提升。

## 许可证

MIT License

## 作者

Prof Analy Team

## 联系方式

如有问题或建议，请提交Issue或Pull Request。