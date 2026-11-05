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

    def test_mixed_symbol_splits_measured_calls_and_keeps_raw_sql(self):
        raw,c,e=self.evidence(scope_end=50)
        d=e['teco_slave_gemm(Args)'];self.assertEqual(d['category'],'gemm');self.assertEqual(d['confidence'],'unknown')
        self.assertEqual(d['context_evidence']['expert_count'],1);self.assertEqual(d['category_candidates'],['gemm','group gemm'])
        rows,summary,excluded,busy=classify_rows(raw,c,e)
        self.assertEqual(next(s for s in summary if s['category']=='gemm')['total_duration_us'],.005)
        self.assertEqual(next(s for s in summary if s['category']=='group gemm')['total_duration_us'],.005)
        self.assertEqual(rows[0]['record_count'],2)
        self.assertEqual(rows[0]['total_duration_us'],.01)
        self.assertEqual([p['event_ids'] for p in rows[0]['category_parts']],[[101],[102]])
        self.assertEqual(sum(p['record_count'] for p in rows[0]['category_parts']),2)
        self.assertEqual(busy,.01)

    def conflict_evidence(self, scopes, confidence=None):
        runtimes=[dict(id=i,name='sdaaLaunchKernel',category='privateuse1_runtime',ts=t,dur=1,
            track_id=i,host_thread=1,correlation=i) for i,t in [(1,10),(2,20)]]
        event=dict(id=101,name='teco_slave_gemm(Args)',category='kernel',ts=30,dur=5,
            track_id=10,device=0,stream=7,correlation=2)
        index=DeviceStepIndex([event],runtimes,[dict(slice_out=1,slice_in=101)],[],0,lambda sid:set())
        classifier=KernelClassifier(platform='teco')
        if confidence is not None:
            original=classifier.classify_host_operation
            classifier.classify_host_operation=lambda name:dict(original(name),confidence=confidence)
        def query(tp,sql):
            return [dict(name='_C_sdaa::group_gemm_v2')] if 'DISTINCT name' in sql else scopes
        raw=[dict(name=event['name'],record_count=1,total_duration_us=.005,avg_duration_us=.005,
            kernel_relative_pct=100,window_absolute_pct=5)]
        with patch('moe_context.run_perfetto_query',side_effect=query):
            context=MoeContextIndex(None,classifier,index)
            detail=context.window(raw,classifier,dict(absolute_start_ts_ns='0',absolute_end_ts_ns='100',track_ids=[10]))
        self.assertEqual(index.links[101]['candidates'],set())
        self.assertEqual(index.links[101]['basis'],'conflicting-flow-correlation')
        return raw,classifier,detail[event['name']]

    def scope(self,sid,start,duration):
        return dict(id=sid,name='_C_sdaa::group_gemm_v2',ts=start,dur=duration,track_id=1,host_thread=1)

    def test_conflicting_links_share_expert_scope_resolve_category_only(self):
        raw,classifier,detail=self.conflict_evidence([self.scope(10,0,100)])
        self.assertEqual(detail['category'],'group gemm')
        self.assertEqual(detail['category_confidence'],'high')
        self.assertEqual(detail['launch_confidence'],'ambiguous')
        evidence=detail['context_evidence']
        self.assertEqual(evidence['resolved_category_conflict_count'],1)
        self.assertEqual(evidence['expert_duration_us'],.005)
        self.assertEqual(evidence['launch_conflicts'][0]['host_op_scope_id'],10)
        self.assertEqual([r['id'] for r in evidence['launch_conflicts'][0]['candidate_launches']],[1,2])
        rows,summary,excluded,busy=classify_rows(raw,classifier,{raw[0]['name']:detail})
        self.assertEqual(next(s for s in summary if s['category']=='group gemm')['record_count'],1)
        self.assertEqual(rows[0]['total_duration_us'],.005)

    def test_conflict_with_unverified_candidate_keeps_role_unresolved(self):
        raw,classifier,detail=self.conflict_evidence([self.scope(10,0,15)])
        self.assertEqual(detail['category'],'gemm')
        self.assertEqual(detail['confidence'],'unknown')
        self.assertEqual(detail['context_evidence']['expert_count'],0)
        self.assertFalse(detail.get('allocations'))

    def test_custom_source_confidence_is_preserved(self):
        raw,classifier,detail=self.conflict_evidence([self.scope(10,0,100)],confidence='medium')
        self.assertEqual(detail['confidence'],'medium')
        self.assertEqual(detail['category_confidence'],'medium')
        self.assertEqual(detail['context_evidence']['launch_conflicts'][0]['category_confidence'],'medium')

    def test_conflicting_links_to_distinct_expert_invocations_remain_unresolved(self):
        raw,classifier,detail=self.conflict_evidence([self.scope(10,0,15),self.scope(11,15,85)])
        self.assertEqual(detail['category'],'gemm')
        self.assertEqual(detail['context_evidence']['resolved_category_conflict_count'],0)

    def test_allocations_cannot_reuse_an_event(self):
        raw,classifier,evidence=self.evidence(scope_end=50)
        evidence[raw[0]['name']]['allocations'][1]['event_ids']=[101]
        with self.assertRaisesRegex(ValueError,'Invalid per-invocation allocations'):
            classify_rows(raw,classifier,evidence)

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
