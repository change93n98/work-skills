#!/usr/bin/env python3
"""
Prof Analy 测试脚本
测试prof-analy skill的各项功能
"""

import sys
import os
import tempfile
import json
import gzip

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analyze import ProfAnalyzer


def create_test_trace():
    """创建测试用的trace文件"""
    # 创建一个简单的trace数据
    trace_data = {
        "schemaVersion": 1,
        "deviceProperties": [
            {
                "id": 0,
                "name": "TestGPU",
                "totalGlobalMem": 8589934592,
                "computeMajor": 8,
                "computeMinor": 0
            }
        ],
        "traceEvents": [
            # GPU kernel事件
            {
                "ph": "X",
                "cat": "kernel",
                "name": "flash_fwd_kernel_16x64_prefetch",
                "pid": 12345,
                "tid": 12345,
                "ts": 1000000,
                "dur": 100000
            },
            {
                "ph": "X",
                "cat": "kernel",
                "name": "Cijk_Alik_Bljk_BBH_MT256x256x16",
                "pid": 12345,
                "tid": 12345,
                "ts": 1100000,
                "dur": 200000
            },
            {
                "ph": "X",
                "cat": "kernel",
                "name": "conv2d_ncxdhw16_bf16_fwd_implicitgemm",
                "pid": 12345,
                "tid": 12345,
                "ts": 1300000,
                "dur": 150000
            },
            {
                "ph": "X",
                "cat": "kernel",
                "name": "void at::native::vectorized_elementwise_kernel",
                "pid": 12345,
                "tid": 12345,
                "ts": 1450000,
                "dur": 50000
            },
            {
                "ph": "X",
                "cat": "kernel",
                "name": "void at::native::vectorized_layer_norm_kernel",
                "pid": 12345,
                "tid": 12345,
                "ts": 1500000,
                "dur": 80000
            },
            # 内存操作事件
            {
                "ph": "X",
                "cat": "gpu_memcpy",
                "name": "hipMemcpyAsync",
                "pid": 12345,
                "tid": 12345,
                "ts": 1580000,
                "dur": 10000
            },
            # CPU事件（应该被忽略）
            {
                "ph": "X",
                "cat": "cpu_op",
                "name": "torch::autograd::VariableType::add",
                "pid": 12345,
                "tid": 12345,
                "ts": 1590000,
                "dur": 5000
            },
            # 用户标注事件（应该被忽略）
            {
                "ph": "X",
                "cat": "user_annotation",
                "name": "ProfilerStep#0",
                "pid": 12345,
                "tid": 12345,
                "ts": 1595000,
                "dur": 1000000
            }
        ]
    }

    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(trace_data, f)
        temp_file = f.name

    return temp_file


def test_basic_analysis():
    """测试基本分析功能"""
    print("=== 测试基本分析功能 ===")

    # 创建测试trace文件
    temp_file = create_test_trace()
    print(f"创建测试trace文件: {temp_file}")

    try:
        # 创建分析器
        analyzer = ProfAnalyzer()

        # 执行分析
        output_file = temp_file.replace('.json', '_analysis.xlsx')
        analyzer.analyze(temp_file, output_file)

        # 验证输出文件
        if os.path.exists(output_file):
            print(f"✓ 成功生成分析报告: {output_file}")
            # 清理输出文件
            os.unlink(output_file)
        else:
            print("✗ 未能生成分析报告")

    except Exception as e:
        print(f"✗ 分析失败: {e}")

    finally:
        # 清理临时文件
        os.unlink(temp_file)


def test_classification():
    """测试分类功能"""
    print("\n=== 测试分类功能 ===")

    analyzer = ProfAnalyzer()

    # 测试用例
    test_cases = [
        ("flash_fwd_kernel_16x64_prefetch", "attention"),
        ("Cijk_Alik_Bljk_BBH_MT256x256x16", "gemm"),
        ("conv2d_ncxdhw16_bf16_fwd_implicitgemm", "conv_bn"),
        ("void at::native::vectorized_elementwise_kernel", "elementwise"),
        ("void at::native::vectorized_layer_norm_kernel", "norm"),
        ("hipMemcpyAsync", "访存"),
        ("void at::native::vectorized_gather_kernel", "index"),
        ("unknown_kernel", "其他"),
    ]

    print("测试算子分类:")
    for name, expected_category in test_cases:
        actual_category = analyzer.classify_operator(name)
        status = "✓" if actual_category == expected_category else "✗"
        print(f"  {status} {name[:50]:50} -> {actual_category:15} (期望: {expected_category})")


def test_gzip_support():
    """测试gzip压缩文件支持"""
    print("\n=== 测试gzip压缩文件支持 ===")

    # 创建测试trace文件
    temp_json = create_test_trace()

    try:
        # 创建gzip压缩文件
        temp_gz = temp_json + '.gz'
        with open(temp_json, 'rb') as f_in:
            with gzip.open(temp_gz, 'wb') as f_out:
                f_out.write(f_in.read())

        print(f"创建gzip压缩文件: {temp_gz}")

        # 测试分析gzip文件
        analyzer = ProfAnalyzer()
        output_file = temp_gz.replace('.json.gz', '_analysis.xlsx')
        analyzer.analyze(temp_gz, output_file)

        if os.path.exists(output_file):
            print(f"✓ 成功分析gzip压缩文件")
            os.unlink(output_file)
        else:
            print("✗ 未能分析gzip压缩文件")

    except Exception as e:
        print(f"✗ gzip测试失败: {e}")

    finally:
        # 清理临时文件
        if os.path.exists(temp_json):
            os.unlink(temp_json)
        if os.path.exists(temp_gz):
            os.unlink(temp_gz)


def test_custom_rules():
    """测试自定义分类规则"""
    print("\n=== 测试自定义分类规则 ===")

    analyzer = ProfAnalyzer()

    # 自定义规则
    custom_rules = {
        'matrix_ops': ['Cijk', 'gemm', 'matmul'],
        'attention_ops': ['flash_fwd_kernel', 'attention'],
        'other': []
    }

    # 保存原始规则
    original_rules = analyzer.category_rules.copy()

    try:
        # 应用自定义规则
        analyzer.category_rules = custom_rules

        # 测试分类
        test_cases = [
            ("Cijk_Alik_Bljk_BBH_MT256x256x16", "matrix_ops"),
            ("flash_fwd_kernel_16x64_prefetch", "attention_ops"),
            ("unknown_kernel", "other"),
        ]

        print("使用自定义规则测试分类:")
        for name, expected_category in test_cases:
            actual_category = analyzer.classify_operator(name)
            status = "✓" if actual_category == expected_category else "✗"
            print(f"  {status} {name[:50]:50} -> {actual_category:15} (期望: {expected_category})")

    finally:
        # 恢复原始规则
        analyzer.category_rules = original_rules


def main():
    """主测试函数"""
    print("Prof Analy 测试套件")
    print("=" * 50)

    # 运行所有测试
    test_basic_analysis()
    test_classification()
    test_gzip_support()
    test_custom_rules()

    print("\n" + "=" * 50)
    print("测试完成！")


if __name__ == '__main__':
    main()