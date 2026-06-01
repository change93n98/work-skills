# Prof Analy - 快速开始指南

## 🎯 功能简介

Prof Analy 是一个用于分析PyTorch模型profiling trace文件的工具，可以：
- 自动解析trace.json文件
- 智能分类GPU算子
- 生成详细的性能分析报告
- 提供优化建议

## 📦 安装

### 1. 安装依赖
```bash
pip install openpyxl
```

### 2. 验证安装
```bash
cd ~/.claude/skills/prof-analy
python3 test_prof_analy.py
```

## 🚀 使用方法

### 方法1：作为Claude Skill使用（推荐）

在Claude对话中直接调用：
```
/prof-analy /path/to/trace.json
```

或者指定输出路径：
```
/prof-analy /path/to/trace.json.gz /path/to/output.xlsx
```

### 方法2：命令行使用

```bash
# 基本用法
python3 ~/.claude/skills/prof-analy/analyze.py /path/to/trace.json

# 分析gzip压缩文件
python3 ~/.claude/skills/prof-analy/analyze.py /path/to/trace.json.gz

# 指定输出路径
python3 ~/.claude/skills/prof-analy/analyze.py /path/to/trace.json -o output.xlsx
```

### 方法3：Python脚本调用

```python
import sys
sys.path.insert(0, '/path/to/prof-analy')

from analyze import ProfAnalyzer

# 创建分析器
analyzer = ProfAnalyzer()

# 执行分析
analyzer.analyze('/path/to/trace.json', 'output.xlsx')
```

## 📊 输出说明

### Excel报告包含两个Sheet：

#### Sheet1: 算子详情
| 列名 | 说明 |
|------|------|
| 算子名称 | GPU kernel的完整名称 |
| 分类 | 算子所属类别 |
| 调用次数 | 该算子被调用的次数 |
| 总耗时(us) | 该算子的总耗时（微秒） |
| 平均耗时(us) | 该算子的平均耗时（微秒） |
| 相对占比(%) | 相对于总耗时的百分比 |
| 绝对占比(%) | 绝对占比 |

#### Sheet2: 分类汇总
| 列名 | 说明 |
|------|------|
| 分类 | 算子类别 |
| 算子种类数 | 该类别包含的不同算子数量 |
| 调用次数 | 该类别所有算子的总调用次数 |
| 总耗时(us) | 该类别所有算子的总耗时（微秒） |
| 总耗时(ms) | 该类别所有算子的总耗时（毫秒） |
| 相对占比(%) | 相对于总耗时的百分比 |
| 绝对占比(%) | 绝对占比 |

## 🏷️ 算子分类规则

| 分类 | 关键词 | 说明 |
|------|--------|------|
| conv_bn | conv2d, conv3d, batch_norm, implicitgemm, nchw2ncxhw, nchw2cxhwn | 卷积和批归一化 |
| attention | flash_fwd_kernel, attention, scaled_dot_product | 注意力机制 |
| norm | layer_norm, rms_norm, RowwiseMoments, GroupNorm | 归一化操作 |
| gemm | Cijk, gemm, matmul, bmm, cublasLt | 矩阵乘法 |
| elementwise | add, mul, relu, gelu, elementwise | 逐元素操作 |
| 访存 | memcpy, MemCpy, cudaMemcpy | 内存访问 |
| reduction | sum, mean, max, min | 归约操作 |
| index | gather, scatter, index | 索引操作 |
| shape | reshape, view, transpose | 形状操作 |
| 其他 | - | 未分类的算子 |

## 🔧 自定义分类规则

你可以自定义分类规则：

```python
from analyze import ProfAnalyzer

analyzer = ProfAnalyzer()

# 自定义规则
custom_rules = {
    'matrix_ops': ['Cijk', 'gemm', 'matmul'],
    'attention_ops': ['flash_fwd_kernel', 'attention'],
    'activation_ops': ['relu', 'gelu', 'silu'],
    'other': []
}

analyzer.category_rules = custom_rules
```

## 📁 文件结构

```
~/.claude/skills/prof-analy/
├── skill.md              # Skill定义文件
├── analyze.py            # 核心分析脚本
├── README.md             # 详细说明文档
├── QUICKSTART.md         # 快速开始指南（本文件）
├── example.py            # 使用示例
└── test_prof_analy.py    # 测试脚本
```

## 🧪 测试

运行测试脚本验证功能：
```bash
cd ~/.claude/skills/prof-analy
python3 test_prof_analy.py
```

## 📝 使用示例

### 示例1：分析SDXL模型trace
```bash
python3 ~/.claude/skills/prof-analy/analyze.py \
    /public/home/changhl/client/aliyun/public/sdxl/trace.json.gz \
    -o sdxl_analysis.xlsx
```

### 示例2：批量分析多个trace文件
```python
from analyze import ProfAnalyzer

analyzer = ProfAnalyzer()

trace_files = [
    'model1_trace.json.gz',
    'model2_trace.json.gz',
    'model3_trace.json.gz',
]

for trace_file in trace_files:
    output_file = trace_file.replace('.json.gz', '_analysis.xlsx')
    analyzer.analyze(trace_file, output_file)
```

## ⚠️ 注意事项

1. **文件格式**：支持.json和.json.gz格式
2. **事件类型**：只分析GPU kernel事件，忽略CPU事件
3. **内存使用**：大型trace文件可能需要较多内存
4. **依赖库**：需要安装openpyxl库

## 🐛 故障排除

### 问题：找不到openpyxl模块
```bash
pip install openpyxl
# 或者
pip3 install --user openpyxl
```

### 问题：分析结果不准确
- 检查trace文件是否完整
- 确认profiling配置正确
- 可能需要调整分类规则

### 问题：内存不足
- 尝试分析较小的trace文件
- 增加系统内存
- 使用更高效的JSON解析器

## 📞 获取帮助

查看详细文档：
```bash
cat ~/.claude/skills/prof-analy/README.md
```

查看使用示例：
```bash
python3 ~/.claude/skills/prof-analy/example.py
```

## 🎉 开始使用

现在你可以开始使用Prof Analy了！

```bash
# 分析你的第一个trace文件
/prof-analy /path/to/your/trace.json.gz
```

祝你分析愉快！🚀