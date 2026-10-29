"""Verify expert GEMM context inside one native trace, without timing changes.

Only a uniform name-group can be promoted. Mixed or partially linked symbols
remain explicit ambiguities; aggregated XLSX cannot reconstruct this evidence.
"""
from collections import defaultdict,Counter
from prof_analyze_perfetto import run_perfetto_query
from device_step_window import DeviceStepIndex


class MoeContextIndex:
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
                self.expert_launches[launch]=dict(detail,host_op=scope['name'])

    def window(self, raw, classifier, metadata):
        if not self.expert_launches:
            return {}
        start,end=int(metadata['absolute_start_ts_ns']),int(metadata['absolute_end_ts_ns'])
        tracks=set(metadata['track_ids'])
        eligible={r['name']:r for r in raw if classifier.classify_detail(r['name'])['category']=='gemm'}
        stats=defaultdict(lambda:dict(count=0,expert_count=0,expert_duration_ns=0,ambiguous_count=0,bases=Counter(),rules=[]))
        for event in self.index.events:
            if event['name'] not in eligible or event['track_id'] not in tracks or not start<=event['ts']<end:
                continue
            s=stats[event['name']];s['count']+=1
            link=self.index.links[event['id']];candidates=link['candidates']
            expert=candidates & self.expert_launches.keys()
            if candidates and expert==candidates:
                s['expert_count']+=1;s['expert_duration_ns']+=event['dur'];s['bases'][link['basis']]+=1
                s['rules'].append(self.expert_launches[min(expert)])
            elif expert or link['possible'] & self.expert_launches.keys():s['ambiguous_count']+=1
        out={}
        for name,s in stats.items():
            assert s['count']==eligible[name]['record_count'], 'Context event scope differs from original SQL name group'
            if not s['expert_count'] and not s['ambiguous_count']:
                continue
            evidence=dict(observed_count=s['count'],expert_count=s['expert_count'],expert_duration_us=s['expert_duration_ns']/1000,
                ambiguous_count=s['ambiguous_count'],association_bases=dict(s['bases']),
                match_basis='same-trace runtime flow/correlation + CPU op descendants/same-native-thread enclosure')
            if s['expert_count']==s['count'] and not s['ambiguous_count']:
                detail=dict(s['rules'][0]);detail.pop('source_categories',None)
                detail['context_evidence']=evidence
                detail['evidence']=detail['evidence']+[f"All {s['count']} selected invocations are linked to expert CPU API {detail.pop('host_op')}."]
                out[name]=detail
            else:
                detail=classifier.classify_detail(name)
                detail.update(confidence='unknown',category_candidates=['gemm','group gemm'],context_evidence=evidence)
                detail['ambiguity_reasons']=detail['ambiguity_reasons']+[
                    f"This aggregated symbol has {s['expert_count']} confirmed expert invocations out of {s['count']}; do not move the entire row or guess a duration split."]
                out[name]=detail
        return out
