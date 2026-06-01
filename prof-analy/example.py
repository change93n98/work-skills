#!/usr/bin/env python3
"""
Prof Analy 使用示例
演示如何使用prof-analy skill分析trace文件
"""

import sys
import os

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analyze import ProfAnalyzer


def example_basic_usage():
    """基本使用示例"""
    print("=== 基本使用示例 ===")

    # 创建分析器
    analyzer = ProfAnalyzer()

    # 分析trace文件
    # 注意：请将路径替换为实际的trace文件路径
    trace_file = "/path/to/your/trace.json.gz"
    output_file = "example_output.xlsx"

    print(f"分析文件: {trace_file}")
    print(f"输出文件: {output_file}")

    # 检查文件是否存在
    if not os.path.exists(trace_file):
        print(f"错误：找不到文件 {trace_file}")
        print("请修改trace_file变量为实际的trace文件路径")
        return

    # 执行分析
    analyzer.analyze(trace_file, output_file)


def example_custom_classification():
    """自定义分类规则示例"""
    print("\n=== 自定义分类规则示例 ===")

    # 创建分析器
    analyzer = ProfAnalyzer()

    # 自定义分类规则
    custom_rules = {
        'matrix_ops': ['Cijk', 'gemm', 'matmul', 'bmm', 'linear'],
        'attention_ops': ['flash_fwd_kernel', 'flash_bwd_kernel', 'attention'],
        'conv_ops': ['convolution', 'conv2d', 'conv3d', 'cudnn'],
        'activation_ops': ['relu', 'gelu', 'silu', 'sigmoid', 'tanh', 'softmax'],
        'memory_ops': ['memcpy', 'MemCpy', 'cudaMemcpy', 'memset'],
        'other': []  # 其他所有算子
    }

    # 更新分类规则
    analyzer.category_rules = custom_rules

    print("已更新分类规则为自定义版本")
    print("新的分类规则:")
    for category, keywords in custom_rules.items():
        print(f"  {category}: {keywords[:5]}...")  # 只显示前5个关键词


def example_analysis_workflow():
    """完整分析工作流示例"""
    print("\n=== 完整分析工作流示例 ===")

    # 步骤1：创建分析器
    analyzer = ProfAnalyzer()

    # 步骤2：加载trace文件
    trace_file = "/path/to/trace.json.gz"
    print(f"步骤1: 加载trace文件 {trace_file}")

    if not os.path.exists(trace_file):
        print(f"错误：找不到文件 {trace_file}")
        return

    data = analyzer.load_trace(trace_file)
    events = data.get('traceEvents', [])

    # 步骤3：分析事件
    print(f"步骤2: 分析 {len(events)} 个事件")
    operator_stats, category_stats, total_dur = analyzer.analyze_events(events)

    # 步骤4：计算百分比
    print("步骤3: 计算百分比")
    analyzer.calculate_percentages(operator_stats, category_stats, total_dur)

    # 步骤5：打印摘要
    print("步骤4: 打印分析摘要")
    analyzer.print_summary(operator_stats, category_stats, total_dur)

    # 步骤6：生成优化建议
    print("步骤5: 生成优化建议")
    analyzer.generate_optimization_suggestions(category_stats, total_dur)

    # 步骤7：创建Excel报告
    output_file = "workflow_output.xlsx"
    print(f"步骤6: 创建Excel报告 {output_file}")
    analyzer.create_excel_report(operator_stats, category_stats, total_dur, output_file)

    print("\n分析工作流完成！")


def example_batch_processing():
    """批量处理示例"""
    print("\n=== 批量处理示例 ===")

    # 创建分析器
    analyzer = ProfAnalyzer()

    # 示例：批量处理多个trace文件
    trace_files = [
        "/path/to/trace1.json.gz",
        "/path/to/trace2.json.gz",
        "/path/to/trace3.json.gz",
    ]

    for i, trace_file in enumerate(trace_files, 1):
        print(f"\n处理文件 {i}/{len(trace_files)}: {trace_file}")

        if not os.path.exists(trace_file):
            print(f"跳过：文件不存在")
            continue

        # 生成输出文件名
        base_name = os.path.splitext(os.path.basename(trace_file))[0]
        if base_name.endswith('.json'):
            base_name = base_name[:-5]  # 移除.json后缀
        output_file = f"analysis_{base_name}.xlsx"

        # 执行分析
        try:
            analyzer.analyze(trace_file, output_file)
            print(f"成功：报告已保存到 {output_file}")
        except Exception as e:
            print(f"错误：分析失败 - {e}")


def main():
    """主函数"""
    print("Prof Analy 使用示例")
    print("=" * 50)

    # 运行示例
    example_basic_usage()
    example_custom_classification()
    example_analysis_workflow()
    example_batch_processing()

    print("\n" + "=" * 50)
    print("示例运行完成！")
    print("\n提示：")
    print("1. 请将示例中的路径替换为实际的trace文件路径")
    print("2. 可以根据需要自定义分类规则")
    print("3. 批量处理可以提高工作效率")


if __name__ == '__main__':
    main()