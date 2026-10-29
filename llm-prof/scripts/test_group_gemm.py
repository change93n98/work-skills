"""Expert grouped products remain distinct from dense GEMM and MoE helpers."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from kernel_categories import CATEGORIES,DENSE_CATEGORIES,DEFAULT_RULES_PATH,KernelClassifier,active_categories
from prof import classify_rows
from prof_analyze import analyze_kernels as analyze_json
from prof_analyze_perfetto import analyze_kernels as analyze_native

TECO_GROUP='void tecolmk_slave_gemm_grouped_batched_v2_weight_half<3, 64>(GemmGroupBatchArgsV2<64>)'

def raw(name,duration):
    return dict(name=name,record_count=1,total_duration_us=duration,avg_duration_us=duration,
                kernel_relative_pct=duration,window_absolute_pct=duration)

class GroupGemmTests(unittest.TestCase):
    def test_confirmed_expert_products_have_group_category(self):
        for platform in ('nv','dcu','teco'):
            for name in ('fused_moe_kernel','fused_moe_kernel_gptq_awq'):
                d=KernelClassifier(platform=platform).classify_detail(name)
                self.assertEqual(d['category'],'group gemm')
                self.assertEqual(d['semantic_type'],'moe_expert_group_gemm')
                self.assertEqual(d['confidence'],'high')
                self.assertTrue(d['evidence'])
        for variant in (TECO_GROUP,TECO_GROUP.replace('<3, 64>','<4, 64>')):
            self.assertEqual(KernelClassifier(platform='teco').classify_detail(variant)['category'],'group gemm')

    def test_dense_and_shared_products_keep_previous_classification(self):
        c=KernelClassifier()
        for name in ('nvjet_sm90_tst_192x8_64x8','ck::DeviceGemm_Xdl_CShuffle<Gelu, Args>',
                     'void tecolmk_slave_ffn_layer_general_fused_for_small<4,32>(FfnLayerGeneralV2Args)',
                     'tecoblas::ual::slave::teco_slave_gemm_NT_Afp16_Bfp16_Cfp16_allReduce(GemmWrapArgs)'):
            self.assertEqual(c.classify_detail(name)['category'],'gemm')

    def test_helpers_and_generic_batched_products_do_not_become_expert_gemm(self):
        c=KernelClassifier()
        for name in ('prepare_for_group_gemm_kernel_impl(Args)','_C_sdaa::moe_routing','local_reduce_fused(Args)',
                     'void vllm::moe::moe_align_block_size_kernel<int>(Args)',
                     'void vllm::moe::count_and_sort_expert_tokens_kernel<int>(Args)',
                     'void vllm::moe::moe_sum_vec_kernel<half,int,8>(Args)',
                     'fused_moe_kernel_prepare','batched_gemm_attention_qk(Args)','weight_permute(Args)'):
            self.assertNotEqual(c.classify_detail(name)['category'],'group gemm',name)

    def test_dense_order_and_moe_denominator(self):
        c=KernelClassifier()
        dense=classify_rows([raw('teco_slave_gemm(Args)',40),raw('WAIT',20)],c)
        self.assertEqual(tuple(s['category'] for s in dense[1]),DENSE_CATEGORIES)
        kernels,summary,excluded,busy=classify_rows([raw('teco_slave_gemm(Args)',40),raw(TECO_GROUP,20),raw('WAIT',20)],c)
        self.assertEqual(tuple(s['category'] for s in summary),CATEGORIES)
        self.assertEqual(busy,60);self.assertEqual(excluded['total_duration_us'],20)
        stats={s['category']:s for s in summary}
        self.assertAlmostEqual(stats['gemm']['kernel_relative_pct'],100*40/60)
        self.assertAlmostEqual(stats['group gemm']['kernel_relative_pct'],100*20/60)
        self.assertEqual(sum(s['record_count'] for s in summary),2)
        self.assertEqual([k['total_duration_us'] for k in kernels],[40,20,20])

    def test_legacy_six_category_artifact_still_controls_its_results(self):
        artifact=json.loads(DEFAULT_RULES_PATH.read_text(encoding='utf-8'))
        artifact['schema_version']=1;artifact['categories']=list(DENSE_CATEGORIES)
        artifact['compatibility_keywords'].pop('group gemm')
        for group,rules in artifact['platforms'].items():artifact['platforms'][group]=[r for r in rules if r['category']!='group gemm']
        artifact['platforms']['common'].append(dict(id='old.explicit_moe',category='gemm',priority=-1,
            patterns=['^fused_moe_kernel$'],reason='legacy fixture',semantic_type='gemm',evidence=['legacy override'],confidence='high'))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'legacy.json';path.write_text(json.dumps(artifact),encoding='utf-8')
            c=KernelClassifier(path)
            self.assertEqual(c.classify_detail('fused_moe_kernel')['category'],'gemm')
            self.assertEqual(tuple(s['category'] for s in classify_rows([raw('fused_moe_kernel',1)],c)[1]),DENSE_CATEGORIES)

    def test_moe_helpers_expose_unresolved_roles_without_guessing_expert_time(self):
        c=KernelClassifier(platform='teco')
        kernels,summary,excluded,busy=classify_rows([raw('teco_slave_gemm(Args)',40),raw('local_reduce_fused(Args)',2)],c)
        self.assertEqual(tuple(s['category'] for s in summary),CATEGORIES)
        self.assertEqual(kernels[0]['category'],'gemm');self.assertEqual(kernels[0]['classification']['confidence'],'unknown')
        self.assertEqual(kernels[0]['classification']['category_candidates'],['gemm','group gemm'])
        self.assertEqual(next(s for s in summary if s['category']=='group gemm')['total_duration_us'],0)
        self.assertEqual(busy,42)

    def test_legacy_analyzers_and_graph_category_path_include_group_gemm(self):
        data=[dict(name='teco_slave_gemm(Args)',dur=40),dict(name=TECO_GROUP,dur=20)]
        for analyzer in (analyze_json,analyze_native):
            stats=analyzer(data)
            self.assertEqual(tuple(stats)[:-1],CATEGORIES)
            self.assertEqual(stats['group gemm']['count'],1)
            self.assertAlmostEqual(stats['group gemm']['percentage'],100/3)
            self.assertEqual(stats['总计']['count'],2)
            self.assertNotIn('group gemm',analyzer([data[0]]))

if __name__=='__main__':unittest.main()
