"""Regression against compact metadata extracted from real SDAA probe traces."""
import json
import unittest
from pathlib import Path
from kernel_categories import KernelClassifier


class IsolatedT100EvidenceTests(unittest.TestCase):
    def test_captured_matrix_symbols_stay_gemm_without_collective(self):
        fixture=json.loads((Path(__file__).resolve().parent.parent/'evals/t100-isolated-gemm-evidence.json').read_text(encoding='utf8'))
        self.assertEqual(fixture['visible_device_count'],1)
        self.assertFalse(fixture['distributed_initialized'])
        self.assertFalse(fixture['graph_enabled'])
        self.assertEqual(len(fixture['cases']),8)
        classifier=KernelClassifier(platform='teco')
        for case in fixture['cases']:
            self.assertTrue(case['correctness']['passed'])
            self.assertEqual(len(case['kernel_names']),1)
            for name in case['kernel_names']:
                detail=classifier.classify_detail(name)
                self.assertEqual(detail['category'],'gemm')
                self.assertEqual(detail['semantic_type'],'gemm_small_mn_local_reduce')
                self.assertEqual(detail['confidence'],'high')
        self.assertFalse(fixture['true_collective_control']['gemm_allReduce_present'])


if __name__=='__main__':
    unittest.main()
