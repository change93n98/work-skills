#!/usr/bin/env python3
"""Conservative cross-trace attribution; mapping durations never enter reports.

Chrome/Kineto trace format, including CUDA, HIP and PrivateUse1/SDAA.
IDs are used only within the mapping trace. Cross-trace matching uses symbols.
"""

import math
import re
from bisect import bisect_left, bisect_right
from collections import defaultdict

from kernel_categories import should_exclude_kernel

DEVICE_CATEGORIES = {
    "kernel", "gpu_kernel", "cuda_kernel", "hip_kernel", "sdaa_kernel",
    "device_kernel", "gpu_memcpy", "gpu_memset",
}


def arg(event, *names):
    """Accept common exporter spellings without inventing vendor-specific IDs."""
    values = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v
              for k, v in (event.get("args") or {}).items()}
    for name in names:
        value = values.get(re.sub(r"[^a-z0-9]", "", name.lower()))
        if value is not None:
            return str(value)
    return None


def external_id(event):
    return arg(event, "External id", "external_id")


def correlation(event):
    return arg(event, "correlation", "correlation_id")


def complete(event):
    return (isinstance(event, dict) and event.get("ph", "X") == "X"
            and isinstance(event.get("ts"), (int, float))
            and isinstance(event.get("dur"), (int, float))
            and math.isfinite(event["ts"]) and math.isfinite(event["dur"])
            and event["dur"] > 0)


def device_events(events, extra_categories=(), pid=None, device=None, window=None):
    """Never infer device duration from cpu_op names or stream arguments."""
    categories = DEVICE_CATEGORIES | {c.strip().lower() for c in extra_categories}
    if categories & {"cpu_op", "python_function", "user_annotation"} or any(
            "runtime" in c or "driver" in c for c in categories):
        raise ValueError("Device categories cannot include host/runtime events")
    selected = []
    for event in events:
        if not complete(event) or str(event.get("cat", "")).lower() not in categories:
            continue
        if should_exclude_kernel(str(event.get("name", ""))):
            continue
        if pid is not None and str(event.get("pid")) != str(pid):
            continue
        if device is not None and arg(event, "device", "device_id") != str(device):
            continue
        if window and not (window[0] <= event["ts"]
                           and event["ts"] + event["dur"] <= window[1]):
            continue
        selected.append(event)
    identities = {(str(e.get("pid")), arg(e, "device", "device_id")) for e in selected}
    if len(identities) > 1:
        raise ValueError("Multiple device tracks selected; specify pid/device per trace: "
                         + repr(sorted(identities, key=str)))
    return selected


def normalized_name(name):
    """Only strip addresses, whitespace and trailing argument signatures.

    Template parameters, numerical suffixes and case remain significant.
    """
    text = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", str(name)).strip()
    if text.startswith("void "):
        text = text[5:]
    if text.endswith(")"):
        depth = 0
        for index in range(len(text) - 1, -1, -1):
            if text[index] == ")":
                depth += 1
            elif text[index] == "(":
                depth -= 1
                if depth == 0:
                    text = text[:index]
                    break
    return re.sub(r"\s+", "", text)


class IntervalIndex:
    """Find enclosing host frames without scanning an entire thread per kernel."""
    def __init__(self, events):
        self.events = sorted(events, key=lambda e: e["ts"])
        self.starts = [e["ts"] for e in self.events]
        self.size = 1 << (max(1, len(self.events)) - 1).bit_length()
        self.ends = [float("-inf")] * (2 * self.size)
        for index, event in enumerate(self.events):
            self.ends[self.size + index] = event["ts"] + event["dur"]
        for index in range(self.size - 1, 0, -1):
            self.ends[index] = max(self.ends[2 * index], self.ends[2 * index + 1])

    def at(self, timestamp):
        limit = bisect_right(self.starts, timestamp)
        output = []
        pending = [(1, 0, self.size)]
        while pending:
            node, start, end = pending.pop()
            if start >= limit or self.ends[node] <= timestamp:
                continue
            if end - start == 1:
                output.append(self.events[start])
            else:
                middle = (start + end) // 2
                pending.extend(((node * 2, start, middle), (node * 2 + 1, middle, end)))
        return output


def is_graph_launch(event):
    name = str(event.get("name", "")).lower()
    return "graph" in name and any(s in name for s in ("launch", "replay"))


def is_runtime(event):
    cat = str(event.get("cat", "")).lower()
    return "runtime" in cat or "driver" in cat


class SourceIndex:
    def __init__(self, events, kernels):
        self.cpu_by_id = defaultdict(list)
        self.launches = defaultdict(list)
        frames = defaultdict(list)
        cpu_threads = defaultdict(list)
        wanted_correlations = {correlation(k) for k in kernels} - {None}
        wanted_ids = {external_id(k) for k in kernels} - {None}
        launch_threads = set()
        # Index only links needed by selected device events, including exporter
        # PrivateUse1 runtimes. Do not retain millions of unrelated Python frames.
        for event in events:
            if not complete(event):
                continue
            if is_runtime(event) and correlation(event) in wanted_correlations:
                self.launches[correlation(event)].append(event)
                launch_threads.add((str(event.get("pid")), str(event.get("tid"))))
                if external_id(event) is not None:
                    wanted_ids.add(external_id(event))
        for event in events:
            if not complete(event) or event.get("cat") != "cpu_op":
                continue
            thread = (str(event.get("pid")), str(event.get("tid")))
            if external_id(event) in wanted_ids:
                self.cpu_by_id[external_id(event)].append(event)
            if thread in launch_threads:
                cpu_threads[thread].append(event)
        query_times = defaultdict(set)
        for groups in (self.cpu_by_id.values(), self.launches.values()):
            for hosts in groups:
                for host in hosts:
                    thread = (str(host.get("pid")), str(host.get("tid")))
                    query_times[thread].add(host["ts"] + min(host["dur"] / 2, 0.5))
        query_times = {key: sorted(value) for key, value in query_times.items()}
        for event in events:
            if not complete(event) or event.get("cat") != "python_function":
                continue
            thread = (str(event.get("pid")), str(event.get("tid")))
            times = query_times.get(thread, [])
            index = bisect_left(times, event["ts"])
            if index < len(times) and times[index] < event["ts"] + event["dur"]:
                frames[thread].append(event)
        self.frames = {key: IntervalIndex(value) for key, value in frames.items()}
        self.cpu_threads = {key: IntervalIndex(value) for key, value in cpu_threads.items()}

    def site(self, host, cpu, basis):
        thread = (str(host.get("pid")), str(host.get("tid")))
        frames = self.frames.get(thread)
        timestamp = host["ts"] + min(host["dur"] / 2, 0.5)
        active = frames.at(timestamp) if frames else []
        # Keep the innermost informative Python scope, plus a short stack for audit.
        active.sort(key=lambda e: e["dur"])
        informative = [e for e in active if not any(token in str(e.get("name", ""))
                       for token in ("<built-in", "torch/_ops.py", "torch/nn/modules/module.py",
                                     "triton/runtime/", "triton/backends/", "threading.py", "_bootstrap"))]
        chosen = (informative or active)
        location = str(chosen[0]["name"]) if chosen else None
        if location is None and cpu:
            location = arg(cpu, "Call stack", "Python stack", "stack")
        return {
            "cpu_op": str(cpu["name"]) if cpu else None,
            "python_location": location,
            "python_stack": [str(e["name"]) for e in active[:8]],
            "host_pid": str(host.get("pid")), "host_tid": str(host.get("tid")),
            "attribution_basis": basis,
        }

    def sources(self, kernel):
        launches = self.launches.get(correlation(kernel), [])
        launches = [e for e in launches if e["ts"] <= kernel["ts"]]
        # Reused correlations: use the most recent event per host thread, while
        # retaining different threads as distinct, potentially ambiguous links.
        latest = {}
        for launch in launches:
            thread = (str(launch.get("pid")), str(launch.get("tid")))
            if thread not in latest or launch["ts"] > latest[thread]["ts"]:
                latest[thread] = launch
        launches = list(latest.values())
        # A graph replay scope is not evidence for the original per-kernel operator.
        if launches and all(is_graph_launch(e) for e in launches):
            return [], "graph-launch-only"
        ambiguous_launch = any(is_graph_launch(e) for e in launches)
        launches = [e for e in launches if not is_graph_launch(e)]
        hosts = []
        ext = external_id(kernel)
        if ext is not None:
            cpu_ops = self.cpu_by_id.get(ext, [])
            cpu_ops = [e for e in cpu_ops if e["ts"] <= kernel["ts"]]
            # Disambiguate reused IDs by the linked host launch when available.
            if launches:
                cpu_ops = [e for e in cpu_ops if any(
                    str(e.get("pid")) == str(l.get("pid"))
                    and str(e.get("tid")) == str(l.get("tid"))
                    and e["ts"] <= l["ts"] < e["ts"] + e["dur"] for l in launches)]
            hosts.extend((cpu, cpu, "external-id") for cpu in cpu_ops)
        if not hosts:
            for launch in launches:
                linked = self.cpu_by_id.get(external_id(launch), [])
                cpu_ops = [e for e in linked if str(e.get("pid")) == str(launch.get("pid"))
                           and str(e.get("tid")) == str(launch.get("tid"))
                           and e["ts"] <= launch["ts"] < e["ts"] + e["dur"]]
                basis = "correlation+launch-external-id"
                if not cpu_ops:
                    thread = (str(launch.get("pid")), str(launch.get("tid")))
                    index = self.cpu_threads.get(thread)
                    enclosing = index.at(launch["ts"]) if index else []
                    if enclosing:
                        minimum = min(e["dur"] for e in enclosing)
                        cpu_ops = [e for e in enclosing if e["dur"] == minimum]
                    basis = "correlation+host-thread-enclosure"
                hosts.extend((launch, cpu, basis) for cpu in cpu_ops)
                if not cpu_ops:
                    hosts.append((launch, None, "correlation+python-frame"))
        sites = [self.site(host, cpu, basis) for host, cpu, basis in hosts
                 if not is_graph_launch(cpu or host)]
        sites = [site for site in sites if site["cpu_op"] or site["python_location"]]
        return sites, ("mixed-graph-and-kernel-launch-links" if sites and ambiguous_launch
                       else "missing-host-link" if not sites else None)


def build_mapping(events, kernels):
    index = SourceIndex(events, kernels)
    mapping = {}
    for kernel in kernels:
        name = str(kernel["name"])
        entry = mapping.setdefault(name, {"sites": {}, "unresolved_count": 0,
                                         "unresolved_reasons": set(), "link_ambiguities": set()})
        sites, reason = index.sources(kernel)
        if not sites:
            entry["unresolved_count"] += 1
            entry["unresolved_reasons"].add(reason)
        elif reason:
            entry["link_ambiguities"].add(reason)
        seen = set()
        for site in sites:
            key = (site["cpu_op"], site["python_location"], site["host_pid"], site["host_tid"])
            if key not in entry["sites"]:
                entry["sites"][key] = dict(site, observation_count=0, attribution_basis=[])
            candidate = entry["sites"][key]
            if site["attribution_basis"] not in candidate["attribution_basis"]:
                candidate["attribution_basis"].append(site["attribution_basis"])
            if key not in seen:
                candidate["observation_count"] += 1
                seen.add(key)
    return mapping


def attach_sources(rows, mapping, pair_differences=()):
    normalized = defaultdict(list)
    for name in mapping:
        normalized[normalized_name(name)].append(name)
    for row in rows:
        name = row["kernel_name"]
        names = [name] if name in mapping else normalized.get(normalized_name(name), [])
        basis = "name:exact" if name in mapping else "name:normalized" if names else "none"
        sources = [dict(site, mapping_kernel=key) for key in names
                   for site in mapping[key]["sites"].values()]
        unresolved = sum(mapping[key]["unresolved_count"] for key in names)
        reasons = []
        reasons.extend(sorted({r for key in names for r in mapping[key]["link_ambiguities"]}))
        if len(names) > 1:
            reasons.append("multiple-mapping-symbols")
        if len(sources) > 1:
            reasons.append("multiple-source-sites")
        if unresolved and sources:
            reasons.append("mapping-occurrences-without-source")
        if pair_differences:
            reasons.append("pair-config-differences")
        if not names:
            status = "unresolved"
            reasons.append("no-symbol-match")
        elif not sources:
            status = "unresolved"
            reasons.extend(sorted({r for key in names for r in mapping[key]["unresolved_reasons"]}))
        elif reasons:
            status = "ambiguous"
        elif not sources[0]["cpu_op"] or not sources[0]["python_location"]:
            status = "partial"
            reasons.append("incomplete-host-source")
        else:
            status = "mapped"
        row.update({"source_status": status, "match_basis": basis,
                    "source_candidates": sources, "ambiguity_reasons": reasons,
                    "mapping_unresolved_count": unresolved,
                    "source_scope": "cross-trace-symbol; not per-replay-instance"})
    return rows
