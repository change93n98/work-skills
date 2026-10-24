import unittest
from device_step_window import DeviceStepIndex,select_step_pair

BASE=1792745261566929000
def annotation(i,ts=0,track=2,name=None):
    return dict(id=i,name=name or 'execute_context_0(0)_generation_1(2)',category='user_annotation',
                ts=BASE+ts,dur=10,track_id=track)
def runtime(i,correlation,ts=11):
    return dict(id=i,name='sdaaGraphLaunch',category='privateuse1_runtime',ts=BASE+ts,
                dur=3,track_id=2,correlation=correlation)
def event(i,ts,correlation=11,name='kernel',device=0,track=3,dur=1,category='kernel'):
    return dict(id=i,ts=BASE+ts,dur=dur,name=name,category=category,correlation=correlation,
                device=device,stream=171,track_id=track)
def index(events,runtimes=None,flows=(),**kwargs):
    return DeviceStepIndex(events,runtimes or [runtime(11,11),runtime(22,22,60)],flows,
        [annotation(1,10),annotation(2,60)],BASE,lambda sid:{11} if sid==1 else {22},**kwargs)


class DeviceStepWindowTests(unittest.TestCase):
    def test_wait_set_zero_duration_are_first_device_candidates(self):
        idx=index([event(1,20,name='SET',dur=0,category='gpu_memset'),event(2,21,name='WAIT',category='gpu_memset'),
                   event(3,25),event(4,80,22)])
        proof=idx.window(annotation(1,10),annotation(2,60))
        self.assertEqual(proof['start']['first_event']['name'],'SET')
        self.assertEqual(proof['start']['owned_device_event_count'],3)
        self.assertEqual(proof['period_us'],.06)
        self.assertTrue(proof['includes_wait_set'])

    def test_graph_launch_fanout_and_missing_flow_supplement(self):
        idx=index([event(1,20),event(2,30),event(3,80,22)],flows=[dict(slice_out=11,slice_in=1)])
        self.assertEqual(len(idx.owned_events(annotation(1,10))),2)
        self.assertEqual(idx.boundary(annotation(1,10))['first_event']['association_basis'],'descendant-runtime+flow+correlation')
        self.assertEqual(idx.links[2]['basis'],'correlation')

    def test_reused_correlation_is_resolved_by_direct_flow(self):
        launches=[runtime(11,11),runtime(91,11)]
        idx=index([event(1,20)],launches,[dict(slice_out=11,slice_in=1)])
        self.assertEqual(idx.boundary(annotation(1,10))['first_event']['launches'][0]['id'],11)

    def test_ambiguous_earlier_event_and_conflicting_evidence_fail(self):
        for flows in ([],[dict(slice_out=91,slice_in=1)]):
            launches=[runtime(11,11),runtime(91,11 if not flows else 91)]
            idx=index([event(1,20),event(2,30,22)],launches+[runtime(22,22)],flows)
            idx.descendants=lambda sid:{11,22}
            with self.subTest(flows=flows),self.assertRaises(ValueError):idx.boundary(annotation(1,10))

    def test_flow_only_exporter_and_no_link_failure(self):
        idx=index([event(1,20,None)],flows=[dict(slice_out=11,slice_in=1)])
        self.assertEqual(idx.boundary(annotation(1,10))['first_event']['association_basis'],'descendant-runtime+flow')
        with self.assertRaises(ValueError):index([event(1,20,999)]).boundary(annotation(1,10))

    def test_device_scope_must_be_explicit_for_mixed_devices(self):
        events=[event(1,20,device=1),event(2,30,device=0)]
        with self.assertRaises(ValueError):index(events).boundary(annotation(1,10))
        self.assertEqual(index(events,device_id=0).boundary(annotation(1,10))['first_event']['event_id'],2)

    def test_nearby_unlinked_event_is_audited_not_silently_assigned(self):
        idx=index([event(1,20,None),event(2,25)])
        proof=idx.boundary(annotation(1,10))
        self.assertEqual(proof['unlinked_near_boundary_count'],1)
        self.assertIn('nearby-unlinked',proof['boundary_confidence'])
        self.assertEqual(proof['first_event']['event_id'],2)

    def test_equal_timestamp_ties_are_preserved(self):
        proof=index([event(2,20),event(1,20,name='WAIT')]).boundary(annotation(1,10))
        self.assertEqual([e['event_id'] for e in proof['tied_first_events']],[1,2])

    def test_clock_contradiction_and_reversed_device_order_fail(self):
        with self.assertRaises(ValueError):index([event(1,9)]).boundary(annotation(1,10))
        idx=index([event(1,90),event(2,80,22)])
        with self.assertRaises(ValueError):idx.window(annotation(1,10),annotation(2,60))

    def test_window_ownership_and_overlap_are_reported(self):
        idx=index([event(1,20,dur=70),event(2,30,999),event(3,80,22)])
        proof=idx.window(annotation(1,10),annotation(2,60))
        self.assertEqual(proof['owned_events_crossing_end'],1)
        self.assertEqual(proof['window_events_not_confirmed_owned_by_current'],1)

    def test_arbitrary_one_based_steps_and_last_step_error(self):
        scopes=[annotation(i,i*20) for i in range(1,5)]
        for n in (1,2,3):
            self.assertEqual([a['id'] for a in select_step_pair(scopes,step=n)],[n,n+1])
        for n in (0,-1,4):
            with self.subTest(n=n),self.assertRaises(ValueError):select_step_pair(scopes,step=n)

    def test_custom_sequence_explicit_pair_and_host_track_ambiguity(self):
        scopes=[annotation(1,10,name='forward-1'),annotation(2,40,name='forward-2')]
        self.assertEqual(select_step_pair(scopes,step=1,annotation_regex=r'^forward')[0]['id'],1)
        self.assertEqual(select_step_pair(scopes,annotation_id=1,next_annotation_id=2)[1]['id'],2)
        with self.assertRaises(ValueError):select_step_pair(scopes,annotation_id=1)
        scopes=[annotation(1,10),annotation(2,40,track=4)]
        with self.assertRaises(ValueError):select_step_pair(scopes,step=1)
        with self.assertRaises(ValueError):select_step_pair(scopes,annotation_id=1,next_annotation_id=2)

    def test_nested_annotations_cannot_be_counted_as_adjacent_steps(self):
        scopes=[dict(annotation(1,10),dur=100),annotation(2,20)]
        with self.assertRaises(ValueError):select_step_pair(scopes,step=1)

    def test_overlapping_display_tracks_use_same_underlying_thread(self):
        launches=[dict(runtime(11,11),host_thread=5,track_id=10)]
        idx=index([event(1,20)],launches)
        idx.descendants=lambda sid:set()
        scope=dict(annotation(1,10,track=11),host_thread=5)
        proof=idx.boundary(scope)
        self.assertIn('same-host-thread-enclosure',proof['first_event']['association_basis'])
        idx=index([event(1,20)],launches);idx.descendants=lambda sid:set()
        with self.assertRaises(ValueError):idx.boundary(dict(scope,host_thread=6))
        pair=[scope,dict(annotation(2,40,track=12),host_thread=5)]
        self.assertEqual(select_step_pair(pair,step=1)[1]['id'],2)


if __name__=='__main__':unittest.main()
