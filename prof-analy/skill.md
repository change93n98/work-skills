# Prof Analy Skill

## 描述
分析模型的profiling trace文件，提取算子信息和性能数据，生成详细的性能分析报告。

## 功能
- 解析PyTorch profiling trace文件（trace.json或trace.json.gz）
- 自动分类算子（gemm、attention、conv_bn、norm、elementwise等）
- 计算性能统计（调用次数、总耗时、平均耗时、占比）
- 生成Excel格式的分析报告
- 提供优化建议

## 使用方法
```
/prof-analy <trace_file_path> [output_path]
```

## 参数
- `trace_file_path`: trace.json或trace.json.gz文件的路径
- `output_path`: 输出Excel文件的路径（可选，默认为trace_analysis.xlsx）

## 示例
```
/prof-analy /path/to/trace.json
/prof-analy /path/to/trace.json.gz /path/to/output.xlsx
```

## 输出
1. **算子详情表（Sheet1）**：每个算子的详细性能数据
2. **分类汇总表（Sheet2）**：按类别统计的性能占比
3. **优化建议**：基于分析结果的优化方向

## 算子分类规则
- **conv_bn**: 卷积和批归一化算子（conv2d、conv3d、batch_norm、nchw2ncxhw等）
- **attention**: 注意力机制相关算子（flash_fwd_kernel、attention等）
- **norm**: 归一化算子（layer_norm、rms_norm、RowwiseMoments、GroupNorm等）
- **gemm**: 矩阵乘法相关算子（Cijk、gemm、matmul等）
- **elementwise**: 逐元素操作算子（add、mul、relu、elementwise等）
- **访存**: 内存访问相关算子（memcpy等）
- **reduction**: 归约操作算子（sum、mean、max等）
- **index**: 索引操作算子（gather、scatter等）
- **shape**: 形状操作算子（reshape、view等）
- **其他**: 其他未分类算子

## 技术特点
- 只分析GPU kernel事件，忽略CPU事件
- 按优先级进行算子分类，避免误分类
- 支持gzip压缩的trace文件
- 生成美观的Excel报告，包含格式化和列宽设置