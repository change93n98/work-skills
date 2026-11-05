"""Verify expert GEMM context inside one native trace, without timing changes.

Category decisions precede name aggregation. Conflicting launch links can agree
on an expert scope while the exact launch remains ambiguous.
"""
from collections import defaultdict,Counter
import math
from prof_analyze_perfetto import run_perfetto_query
from device_step_window import DeviceStepIndex


class MoeContextIndex:
    resolution_version = 'moe-source-attribution-v2'

    def __init__(self, tp, classifier, device_index=None, **device_scope):
        self.index = device_index
        self.expert_launches = {}
        self.scope_count = 0
        if not classifier.context_rules:
            return
        names=run_perfetto_query(tp,"SELECT DISTINCT name FROM slice WHERE category='cpu_op'")
        matched={r['name']:classifier.classify_host_operation(r['name']) for r in names}
        matched={n:r for n,r in matched.items() if r is not None}
        if not matched:
            return
        literals=','.join("'"+n.replace("'","''")+"'" for n in matched)
        scopes=run_perfetto_query(tp,f"""SELECT s.id,s.name,s.ts,s.dur,s.track_id,tt.utid AS host_thread
            FROM slice s LEFT JOIN thread_track tt ON tt.id=s.track_id
            WHERE s.category='cpu_op' AND s.name IN ({literals}) ORDER BY s.ts,s.id""")
        if self.index is None:
            self.index=DeviceStepIndex.from_processor(tp,**device_scope)
        self.scope_count=len(scopes)
        for scope in scopes:
            detail=matched[scope['name']]
            for launch in self.index.runtime_ids(scope):
                self.expert_launches[launch]=dict(detail,host_op=scope['name'],
                    host_op_scope_id=scope['id'],host_thread=scope.get('host_thread'))

    def expert_source(self, event):
        link=self.index.links[event['id']]
        candidates=link['candidates']
        if candidates and candidates <= self.expert_launches.keys():
            return self.expert_launches[min(candidates)],link['basis'],None
        if link['basis'] != 'conflicting-flow-correlation' or not link['possible']:
            return None,link['basis'],None
        possible=link['possible']
        if not possible <= self.expert_launches.keys():
            return None,link['basis'],None
        sources=[self.expert_launches[r] for r in sorted(possible)]
        identities={(s['host_op_scope_id'],s['host_thread'],s['category'],s['rule_id']) for s in sources}
        if len(identities)!=1 or sources[0]['host_thread'] is None:
            return None,link['basis'],None
        launches=[self.index.runtimes[r] for r in sorted(possible)]
        if event['dur']<0 or any(r['dur']<0 or r['ts']>event['ts'] for r in launches):
            return None,link['basis'],None
        conflict=dict(event_id=event['id'],duration_ns=event['dur'],correlation=event.get('correlation'),
            device=event.get('device'),stream=event.get('stream'),
            category='group gemm',category_confidence=sources[0]['confidence'],launch_confidence='ambiguous',
            host_op_scope_id=sources[0]['host_op_scope_id'],host_op=sources[0]['host_op'],
            candidate_launches=[dict(r) for r in launches],
            original_association_basis=link['basis'])
        return sources[0],'conflicting-links-same-expert-scope',conflict

    def window(self, raw, classifier, metadata):
        if not self.expert_launches:
            return {}
        start,end=int(metadata['absolute_start_ts_ns']),int(metadata['absolute_end_ts_ns'])
        tracks=set(metadata['track_ids'])
        eligible={r['name']:r for r in raw if classifier.classify_detail(r['name'])['category']=='gemm'}
        stats=defaultdict(lambda:dict(count=0,duration_ns=0,expert_count=0,expert_duration_ns=0,
            ambiguous_count=0,bases=Counter(),rules=[],expert_ids=[],residual_ids=[],conflicts=[]))
        for event in self.index.events:
            if event['name'] not in eligible or event['track_id'] not in tracks or not start<=event['ts']<end:
                continue
            s=stats[event['name']];s['count']+=1;s['duration_ns']+=event['dur']
            link=self.index.links[event['id']];candidates=link['candidates']
            source,basis,conflict=self.expert_source(event)
            if source is not None:
                s['expert_count']+=1;s['expert_duration_ns']+=event['dur'];s['bases'][basis]+=1
                s['rules'].append(source);s['expert_ids'].append(event['id'])
                if conflict:s['conflicts'].append(conflict)
            else:
                s['residual_ids'].append(event['id'])
                if candidates & self.expert_launches.keys() or link['possible'] & self.expert_launches.keys():
                    s['ambiguous_count']+=1
        out={}
        for name,s in stats.items():
            assert s['count']==eligible[name]['record_count'], 'Context event scope differs from original SQL name group'
            assert math.isclose(s['duration_ns']/1000,eligible[name]['total_duration_us'],abs_tol=1e-6)
            if not s['expert_count'] and not s['ambiguous_count']:
                continue
            evidence=dict(version=self.resolution_version,observed_count=s['count'],expert_count=s['expert_count'],expert_duration_us=s['expert_duration_ns']/1000,
                ambiguous_count=s['ambiguous_count'],association_bases=dict(s['bases']),
                residual_count=len(s['residual_ids']),resolved_category_conflict_count=len(s['conflicts']),
                launch_conflicts=s['conflicts'],
                match_basis='same-trace runtime flow/correlation + CPU op descendants/same-native-thread enclosure')
            expert_detail=None
            if s['expert_count']:
                expert_detail=dict(s['rules'][0])
                for key in ('source_categories','host_thread','host_op_scope_id'):
                    expert_detail.pop(key,None)
                host_op=expert_detail.pop('host_op')
                expert_detail.update(category_confidence=expert_detail['confidence'],
                    launch_confidence='ambiguous' if s['conflicts'] else 'confirmed-within-recorded-links')
                expert_detail['evidence']=expert_detail['evidence']+[
                    f"{s['expert_count']} selected invocations have verified expert CPU API category {host_op}."]
                if s['conflicts']:
                    expert_detail['ambiguity_reasons']=expert_detail['ambiguity_reasons']+[
                        f"{len(s['conflicts'])} launch links conflict; all recorded candidates share the same expert CPU scope. Category resolved, exact launch retained as ambiguous."]
            if s['expert_count']==s['count']:
                detail=dict(expert_detail,context_evidence=evidence)
            else:
                detail=classifier.classify_detail(name)
                detail.update(confidence='unknown',category_confidence='unknown',
                    category_candidates=['gemm','group gemm'],context_evidence=evidence)
                detail['ambiguity_reasons']=detail['ambiguity_reasons']+[
                    f"This symbol has {s['expert_count']} confirmed expert invocations out of {s['count']}; measured contributions are separated, residual expert role remains unresolved."]
                if s['expert_count']:
                    residual_detail=classifier.classify_detail(name)
                    residual_detail.update(confidence='unknown',category_confidence='unknown',
                        category_candidates=['gemm','group gemm'],ambiguity_reasons=[
                            'Expert API role is not resolved for these invocations; retain the name-based GEMM bucket.'])
                    detail['allocations']=[
                        dict(record_count=s['expert_count'],duration_ns=s['expert_duration_ns'],
                            event_ids=s['expert_ids'],classification=expert_detail),
                        dict(record_count=len(s['residual_ids']),duration_ns=s['duration_ns']-s['expert_duration_ns'],
                            event_ids=s['residual_ids'],classification=residual_detail)]
                    for part in detail['allocations']:
                        part['window_absolute_pct']=part['duration_ns']/(end-start)*100
            out[name]=detail
        return out
