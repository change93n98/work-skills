"""Summarize comparable GDN stages without splitting fused kernel durations."""

from collections import defaultdict
import re


def summarize_gdn(kernels, metadata, groups):
    parts = [part for row in kernels for part in row.get('category_parts', [row])
             if part['category'] == 'GDN']
    if not parts:
        return None

    subtypes = {part['classification']['semantic_type'] for part in parts}
    has_prefill = bool(subtypes & {'gdn_conv', 'gdn_gating_qk_fused', *groups['Chunk 主计算']})
    has_decode = bool(subtypes & {'gdn_conv_update', *groups['递推主计算']})
    stage = metadata.get('stage')
    scope = stage if stage in ('prefill', 'decode') else 'unknown'
    anchor = metadata.get('device_step', {}).get('start', {}).get('annotation', {}).get('name', '')
    mixed_anchor = re.match(r'^execute_context_[1-9]\d*\(\d+\)_generation_[1-9]\d*\(', anchor)
    if mixed_anchor or (has_prefill and has_decode) or (stage == 'prefill' and has_decode) or (stage == 'decode' and has_prefill):
        scope = 'mixed-or-stage-mismatch'

    groups = dict(groups)
    if scope == 'decode':
        groups['卷积后准备与递推'] = groups.pop('卷积后准备') + groups.pop('递推主计算')
    by_subtype = {subtype: group for group, types in groups.items() for subtype in types}
    allocations = defaultdict(list)
    for part in parts:
        subtype = part['classification']['semantic_type']
        allocations[by_subtype.get(subtype, '未对齐 GDN 子项')].append(part)

    rows = []
    for group in (*groups, '未对齐 GDN 子项'):
        if group not in allocations:
            continue
        items = allocations[group]
        rows.append(dict(group=group, record_count=sum(item['record_count'] for item in items),
                         total_duration_us=sum(item['total_duration_us'] for item in items),
                         kernel_kinds=len({item['name'] for item in items}),
                         semantic_types=sorted({item['classification']['semantic_type'] for item in items})))
    candidates = [dict(name=row['name'], **row['classification']['gdn_graph_candidate'])
                  for row in kernels if 'gdn_graph_candidate' in row['classification']]
    return dict(scope=scope, rows=rows, graph_candidates=candidates)
