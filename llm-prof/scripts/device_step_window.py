"""Associate annotation descendants to device events before selecting step anchors.

Correlation IDs are trace-local. Native flow edges can disambiguate reused IDs;
missing edges can be supplemented by unique correlation. No timestamp-nearest
fallback, no name-based exclusion of WAIT/SET, no graph-off trace required when
the graph-on exporter retains links.
"""
from collections import defaultdict
from bisect import bisect_left
from decimal import Decimal
import re

from prof_analyze_perfetto import run_perfetto_query


def _key(value):
    return None if value is None else str(value)


def _argument(name, prefix=''):
    return f"COALESCE(extract_arg({prefix}arg_set_id, 'args.{name}'), extract_arg({prefix}arg_set_id, 'args.{name}_id'))"


def _host_identity(event):
    return ('thread',event['host_thread']) if event.get('host_thread') is not None else ('track',event['track_id'])


def select_step_pair(annotations, stage='decode', step=2, annotation_regex=None,
                     host_track_id=None, annotation_id=None, next_annotation_id=None):
    """One-based phase-local numbering; explicit pairs can span phases."""
    candidates = [a for a in annotations if a['category'] == 'user_annotation']
    if host_track_id is not None:
        candidates = [a for a in candidates if a['track_id'] == host_track_id]
    if annotation_id is not None or next_annotation_id is not None:
        if annotation_id is None or next_annotation_id is None:
            raise ValueError('both --annotation-id and --next-annotation-id are required')
        ids = {a['id']:a for a in candidates}
        if annotation_id not in ids or next_annotation_id not in ids:
            raise ValueError('explicit annotation IDs must identify user_annotation slices on the selected host track')
        pair = [ids[annotation_id], ids[next_annotation_id]]
    else:
        if step < 1:
            raise ValueError('--step is one-based and must be positive')
        pattern = annotation_regex or (r'^execute_context_.*_generation_[1-9]\d*\('
                                      if stage == 'decode' else r'^execute_context_[1-9]\d*\(')
        regex = re.compile(pattern)
        candidates = sorted([a for a in candidates if regex.search(a['name'])],key=lambda a:(a['ts'],a['id']))
        tracks = {_host_identity(a) for a in candidates}
        if len(tracks) > 1:
            raise ValueError('multiple annotation host tracks: specify --host-track-id or explicit annotation IDs')
        if len(candidates) <= step:
            raise ValueError(f'step {step} needs step {step+1}; found {len(candidates)} matching annotations; no CPU/end-of-last-event fallback')
        pair = candidates[step-1:step+1]
    if _host_identity(pair[0]) != _host_identity(pair[1]):
        raise ValueError('step anchors must use annotations on one host track/rank')
    if pair[0]['ts'] >= pair[1]['ts'] or pair[0]['ts']+pair[0]['dur'] > pair[1]['ts']:
        raise ValueError('selected annotations are reversed, overlapping or nested; narrow the regex or specify IDs')
    return tuple(pair)


class DeviceStepIndex:
    def __init__(self, device_events, runtimes, flows, annotations, trace_start_ns,
                 descendants, device_id=None, track_ids=()):
        self.trace_start_ns = int(trace_start_ns)
        self.annotations = annotations
        self.runtimes = {r['id']:r for r in runtimes}
        by_correlation = defaultdict(set)
        for event in runtimes:
            if _key(event.get('correlation')) is not None:
                by_correlation[_key(event['correlation'])].add(event['id'])
        self.events = [e for e in device_events if
                       (device_id is None or _key(e.get('device')) == str(device_id)) and
                       (not track_ids or e['track_id'] in track_ids)]
        self.explicit_device_scope = device_id is not None or bool(track_ids)
        by_flow = defaultdict(set)
        for flow in flows:
            if flow['slice_out'] in self.runtimes:
                by_flow[flow['slice_in']].add(flow['slice_out'])
        self.links = {}
        for event in self.events:
            correlation = by_correlation.get(_key(event.get('correlation')),set())
            flow = by_flow.get(event['id'],set())
            if correlation and flow:
                candidates = correlation & flow
                basis = 'flow+correlation' if candidates else 'conflicting-flow-correlation'
            else:
                candidates = correlation or flow
                basis = 'correlation' if correlation else 'flow' if flow else 'unlinked'
            self.links[event['id']] = dict(candidates=set(candidates), basis=basis,
                possible=set(correlation)|set(flow))
        self.descendants = descendants
        self._scope_cache = {}
        self._enclosed_cache = {}
        self._boundary_cache = {}
        threads = defaultdict(list)
        for r in runtimes:
            if r.get('host_thread') is not None:threads[r['host_thread']].append(r)
        self._runtime_threads = {}
        for tid,rows in threads.items():
            rows.sort(key=lambda r:r['ts'])
            self._runtime_threads[tid]=([r['ts'] for r in rows],rows)

    @classmethod
    def from_processor(cls, tp, categories=('kernel','gpu_memcpy','gpu_memset'), device_id=None, track_ids=()):
        if not categories or any('runtime' in c.lower() or 'driver' in c.lower() or c.lower() in
                ('cpu_op','cpu','user_annotation','python_function') for c in categories):
            raise ValueError('device categories cannot include CPU/runtime/driver events')
        literals = ','.join("'"+c.replace("'","''")+"'" for c in categories)
        device = run_perfetto_query(tp,f'''SELECT id,name,category,ts,dur,track_id,
            {_argument('correlation')} AS correlation,
            {_argument('device')} AS device, {_argument('stream')} AS stream
            FROM slice WHERE category IN ({literals})''')
        runtime = run_perfetto_query(tp,f'''SELECT s.id,s.name,s.category,s.ts,s.dur,s.track_id,
            {_argument('correlation','s.')} AS correlation, tt.utid AS host_thread FROM slice s
            LEFT JOIN thread_track tt ON tt.id=s.track_id
            WHERE lower(s.category) LIKE '%runtime%' OR lower(s.category) LIKE '%driver%' ''')
        annotations = run_perfetto_query(tp,"SELECT s.id,s.name,s.category,s.ts,s.dur,s.track_id,tt.utid AS host_thread FROM slice s LEFT JOIN thread_track tt ON tt.id=s.track_id WHERE s.category='user_annotation'")
        flows = run_perfetto_query(tp,'SELECT slice_out,slice_in FROM flow')
        bounds = run_perfetto_query(tp,'SELECT start_ts FROM trace_bounds')[0]
        return cls(device,runtime,flows,annotations,bounds['start_ts'],
                   lambda sid:{r['id'] for r in run_perfetto_query(tp,f"SELECT id FROM descendant_slice({int(sid)}) WHERE lower(category) LIKE '%runtime%' OR lower(category) LIKE '%driver%'")},
                   device_id,track_ids)

    def runtime_ids(self, annotation):
        sid = annotation['id']
        if sid not in self._scope_cache:
            self._scope_cache[sid] = set(self.descendants(sid)) & self.runtimes.keys()
            enclosed=set()
            tid=annotation.get('host_thread')
            if tid in self._runtime_threads:
                starts,rows=self._runtime_threads[tid]
                for runtime in rows[bisect_left(starts,annotation['ts']):bisect_left(starts,annotation['ts']+annotation['dur'])]:
                    if runtime['ts']+runtime['dur'] <= annotation['ts']+annotation['dur']:
                        enclosed.add(runtime['id'])
            self._enclosed_cache[sid]=enclosed-self._scope_cache[sid]
            self._scope_cache[sid] |= enclosed
        return self._scope_cache[sid]

    def owned_events(self, annotation):
        ids = self.runtime_ids(annotation)
        return [e for e in self.events if self.links[e['id']]['candidates'] and
                self.links[e['id']]['candidates'] <= ids]

    def boundary(self, annotation):
        sid = annotation['id']
        if sid in self._boundary_cache:
            return self._boundary_cache[sid]
        ids = self.runtime_ids(annotation)
        owned = self.owned_events(annotation)
        if not owned:
            raise ValueError(f'annotation {sid}: no unambiguous associated device event; cannot infer a device boundary')
        identities = {_key(e.get('device')) for e in owned}
        if len(identities) > 1:
            raise ValueError(f'annotation {sid}: multiple/unknown device identities {identities}; specify --device-id')
        if identities == {None} and len({e['track_id'] for e in owned}) > 1 and not self.explicit_device_scope:
            raise ValueError('device identity missing on multiple tracks; provide explicit device/track scope')
        first_ts = min(e['ts'] for e in owned)
        tied = sorted([e for e in owned if e['ts'] == first_ts],key=lambda e:e['id'])
        uncertain = [e for e in self.events if self.links[e['id']]['possible'] & ids and
                     (not self.links[e['id']]['candidates'] or not self.links[e['id']]['candidates'] <= ids)]
        if any(e['ts'] <= first_ts for e in uncertain):
            raise ValueError(f'annotation {sid}: an earlier/equal device event has ambiguous ownership or conflicting links')
        for event in tied:
            launch_ids = self.links[event['id']]['candidates']
            if event['dur'] < 0 or any(self.runtimes[r]['ts'] > event['ts'] for r in launch_ids):
                raise ValueError('first device event is unfinished or precedes its launch; inspect clock/correlation evidence')
        nearby_unlinked = [e for e in self.events if annotation['ts'] <= e['ts'] <= first_ts and
                          not self.links[e['id']]['possible']]
        def detail(e):
            link = self.links[e['id']]
            return dict(event_id=e['id'],name=e['name'],category=e['category'],track_id=e['track_id'],
                device=e.get('device'),stream=e.get('stream'),correlation=e.get('correlation'),
                absolute_ts_ns=str(e['ts']),offset_ns=e['ts']-self.trace_start_ns,
                offset_us=str(Decimal(e['ts']-self.trace_start_ns)/1000),duration_ns=e['dur'],
                association_basis=('same-host-thread-enclosure+' if link['candidates'] <= self._enclosed_cache[sid] else 'descendant-runtime+')+link['basis'],
                launches=[dict(self.runtimes[r]) for r in sorted(link['candidates'])])
        value = dict(annotation=dict(annotation),first_event=detail(tied[0]),
            tied_first_events=[detail(e) for e in tied],owned_device_event_count=len(owned),
            later_ambiguous_event_count=len(uncertain),
            boundary_confidence='first-confirmed-link; nearby-unlinked-events' if nearby_unlinked else 'confirmed-within-recorded-links',
            unlinked_near_boundary_count=len(nearby_unlinked),
            unlinked_trace_device_event_count=sum(not self.links[e['id']]['possible'] for e in self.events),
            includes_wait_set=True)
        self._boundary_cache[sid] = value
        return value

    def window(self, current, following):
        if (_host_identity(current) != _host_identity(following) or
                current['ts'] >= following['ts'] or current['ts']+current['dur'] > following['ts']):
            raise ValueError('device step window needs ordered, nonoverlapping annotations on the same native host thread')
        start, end = self.boundary(current),self.boundary(following)
        a,b = int(start['first_event']['absolute_ts_ns']),int(end['first_event']['absolute_ts_ns'])
        if a >= b:
            raise ValueError('associated device boundaries are reversed/equal; no step window can be formed')
        if _key(start['first_event']['device']) != _key(end['first_event']['device']):
            raise ValueError('current and next annotation resolve to different devices')
        in_window = [e for e in self.events if a <= e['ts'] < b]
        owned = self.owned_events(current)
        owned_ids = {e['id'] for e in owned}
        return dict(method='associated-first-device-event',start=start,end=end,
            start_us=str(Decimal(a-self.trace_start_ns)/1000),end_us=str(Decimal(b-self.trace_start_ns)/1000),
            period_us=(b-a)/1000,includes_wait_set=True,statistics_scope='all selected device events starting in [start,end); full dur',
            owned_events_starting_in_window=sum(e['id'] in owned_ids for e in in_window),
            window_events_not_confirmed_owned_by_current=sum(e['id'] not in owned_ids for e in in_window),
            owned_events_crossing_end=sum(e['ts']+e['dur'] > b for e in owned),
            status='device-cycle-window; not a busy-time sum or exclusive invocation attribution')
