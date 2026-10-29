"""Expert role needs native launch links, not broad GEMM-name reassignment."""
from unittest.mock import patch
import unittest
from kernel_categories import KernelClassifier
from device_step_window import DeviceStepIndex
from moe_context import MoeContextIndex
from prof import classify_rows

class MoeContextTests(unittest.TestCase):
    def index(self,scope_end=100,wrong_thread=False,unlinked=False):
        runtimes=[dict(id=i,name='sdaaLaunchKernel',category='privateuse1_runtime',ts=t,dur=1,
                       track_id=1,host_thread=2 if wrong_thread else 1,correlation=i) for i,t in [(1,10),(2,60)]]
        events=[dict(id=100+i,name='teco_slave_gemm(Args)',category='kernel',ts=t+2,dur=5,
                     track_id=10,device=0,stream=7,correlation=999 if unlinked else i) for i,t in [(1,10),(2,60)]]
        desc=set() if wrong_thread else {r['id'] for r in runtimes if r['ts']+r['dur']<=scope_end}
        index=DeviceStepIndex(events,runtimes,[] if unlinked else [dict(slice_out=i,slice_in=100+i) for i in (1,2)],[],0,lambda sid:desc)
        scope=dict(id=10,name='_C_sdaa::group_gemm_v2',ts=0,dur=scope_end,track_id=1,host_thread=1)
        return index,scope

    def evidence(self,**kwargs):
        index,scope=self.index(**kwargs);classifier=KernelClassifier(platform='teco')
        def query(tp,sql):return [dict(name=scope['name'])] if 'DISTINCT name' in sql else [scope]
        raw=[dict(name='teco_slave_gemm(Args)',record_count=2,total_duration_us=.01,avg_duration_us=.005,kernel_relative_pct=100,window_absolute_pct=10)]
        with patch('moe_context.run_perfetto_query',side_effect=query):
            context=MoeContextIndex(None,classifier,index)
            evidence=context.window(raw,classifier,dict(absolute_start_ts_ns='0',absolute_end_ts_ns='100',track_ids=[10]))
        return raw,classifier,evidence

    def test_uniform_expert_launches_promote_generic_symbol_without_timing_change(self):
        raw,classifier,evidence=self.evidence()
        detail=evidence['teco_slave_gemm(Args)']
        self.assertEqual(detail['category'],'group gemm')
        self.assertEqual(detail['context_evidence']['expert_count'],2)
        self.assertEqual(detail['context_evidence']['association_bases'],{'flow+correlation':2})
        rows,summary,excluded,busy=classify_rows(raw,classifier,evidence)
        self.assertEqual(rows[0]['total_duration_us'],.01);self.assertEqual(busy,.01)
        self.assertEqual(next(s for s in summary if s['category']=='group gemm')['record_count'],2)

    def test_mixed_symbol_is_not_wholesale_promoted_or_split_by_guess(self):
        raw,c,e=self.evidence(scope_end=50)
        d=e['teco_slave_gemm(Args)'];self.assertEqual(d['category'],'gemm');self.assertEqual(d['confidence'],'unknown')
        self.assertEqual(d['context_evidence']['expert_count'],1);self.assertEqual(d['category_candidates'],['gemm','group gemm'])
        rows,summary,excluded,busy=classify_rows(raw,c,e)
        self.assertEqual(next(s for s in summary if s['category']=='gemm')['total_duration_us'],.01)
        self.assertEqual(next(s for s in summary if s['category']=='group gemm')['total_duration_us'],0)

    def test_temporal_overlap_on_another_native_thread_is_not_source_evidence(self):
        raw,c,e=self.evidence(wrong_thread=True)
        self.assertFalse(e);self.assertEqual(c.classify_detail(raw[0]['name'])['category'],'gemm')

    def test_unlinked_devices_do_not_inherit_nearby_expert_role(self):
        raw,c,e=self.evidence(unlinked=True)
        self.assertFalse(e)

    def test_host_rule_is_separate_from_kernel_name_rules(self):
        c=KernelClassifier(platform='teco')
        self.assertEqual(c.classify_host_operation('_C_sdaa::group_gemm_v2')['category'],'group gemm')
        self.assertNotEqual(c.classify_detail('_C_sdaa::group_gemm_v2')['category'],'group gemm')

if __name__=='__main__':unittest.main()
