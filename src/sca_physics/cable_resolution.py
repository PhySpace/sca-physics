"""Validate frozen resolution snapshots and configurable scene safeguards.

Reading a saved package never consults current presets or chooses segments again.
"""
from copy import deepcopy
import hashlib
import json
import math
from .contract import _closed
from .cable_presets import DEFAULT_RESOURCE_BUDGET


def _value(record, group, key):
    value = record[group][key]
    return value["value"] if isinstance(value, dict) else value


def resource_budget(raw, *, partial=False, source=None, schema_version='1.7'):
    from .provenance import inherited, parameter
    obj = _closed(raw, set(DEFAULT_RESOURCE_BUDGET) | {"scope", 'source'}, "resource_budget", required=set() if partial else set(DEFAULT_RESOURCE_BUDGET))
    if obj.get("scope", "scene") != "scene":
        raise ValueError("resource_budget.scope: only scene is supported")
    context = inherited(obj, source, 'resource_budget.source')
    result = {'scope': 'scene'} if 'scope' in obj else {}
    for key in DEFAULT_RESOURCE_BUDGET:
        if key not in obj and not partial:
            continue
        if schema_version in {'1.7', '1.8'}:
            if key in obj:
                result[key] = parameter(obj[key], 'count', 'resource_budget.' + key, context)
            else:
                result[key] = {'value': DEFAULT_RESOURCE_BUDGET[key], 'unit': 'count', 'source': {
                    'kind': 'default', 'detail': 'Versioned scene resource safeguard; not a physics accuracy limit'}}
        else:
            result[key] = deepcopy(obj.get(key, DEFAULT_RESOURCE_BUDGET[key]))
    budget_values(result)
    return result


def budget_values(raw):
    """Read legacy integer or1.7 wrapped budgets without modifying the snapshot."""
    obj = _closed(raw, set(DEFAULT_RESOURCE_BUDGET) | {'scope'}, 'resource_budget', required=set(DEFAULT_RESOURCE_BUDGET))
    result = {}
    for key in DEFAULT_RESOURCE_BUDGET:
        item = obj[key]
        if isinstance(item, dict):
            from .provenance import parameter
            item = parameter(item, 'count', 'resource_budget.' + key)['value']
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise ValueError('resource_budget.' + key + ': require a positive integer')
        result[key] = item
    if 'scope' in obj:
        if obj['scope'] != 'scene':
            raise ValueError('resource_budget.scope: only scene is supported')
        result['scope'] = 'scene'
    return result


def check_chain_budget(record, *, other_parts=0):
    """Scalar guards precede allocating link/filter arrays. CAD part estimate is conservative."""
    budget = budget_values(record["resource_budget"])
    n = _value(record, "discretization", "free_segments")
    if isinstance(n, bool) or not isinstance(n, int) or n < 2:
        raise ValueError("discretization.free_segments: require an integer >=2")
    start, end, length = (_value(record, "geometry", k) for k in ("free_start", "free_end", "length"))
    extra = int(start > 0) + int(end < length)
    links = n + extra
    endpoint_joints = sum(e["mode"] != "free" for e in record["endpoints"].values())
    work = links * _value(record, "scene", "physics_hz") * (
        _value(record, "body", "solver_position_iterations") + _value(record, "body", "solver_velocity_iterations"))
    counts = {"bodies": links + other_parts, "joints": links - 1 + endpoint_joints,
              "colliders": links + other_parts, "solver_work_per_second": work}
    for key, amount in counts.items():
        if amount > budget["max_" + key]:
            raise ValueError(f"resource_budget.max_{key}: estimated {amount} exceeds {budget['max_' + key]}; no truncation. Explicitly raise the budget, reduce scene load or request a lower quality.")
    # Allocate only after the scalar body/work guards. No all-pair list is built.
    if not _value(record, "collision", "self_collision"):
        filtered = links * (links - 1) // 2
    else:
        filtered = links - 1
        switch = record["collision"].get("filter_material_neighbors", False)
        switch = switch.get("value") if isinstance(switch, dict) else switch
        if switch:
            ds = (end - start) / n
            intervals = []
            if start > 0:
                intervals.append((0., start, _value(record, "section", "endpoint_radius")))
            intervals.extend((start + i*ds, start + (i+1)*ds, _value(record, "section", "radius")) for i in range(n))
            if end < length:
                intervals.append((end, length, _value(record, "section", "endpoint_radius")))
            for i, (_, a_end, ra) in enumerate(intervals):
                # Normally finite material neighbors; guard during counting even for huge caps.
                for j in range(i + 2, links):
                    b_start, _, rb = intervals[j]
                    if b_start - a_end <= ra + rb + 1e-12:
                        filtered += 1
                        if filtered > budget["max_filtered_pairs"]:
                            raise ValueError("resource_budget.max_filtered_pairs: material-neighbor filtering exceeds budget")
                    elif j < links - 1:
                        # Interior radii are constant. The last endpoint can be larger.
                        if end < length and j < links - 1 and intervals[-1][0] - a_end <= ra + intervals[-1][2] + 1e-12:
                            filtered += 1
                        break
    endpoint_filters = sum(e["mode"] == "body_fixed" for e in record["endpoints"].values()) if _value(record, "collision", "filter_endpoint_links") else 0
    filtered += endpoint_filters
    counts["filtered_pairs"] = filtered
    counts["contact_pairs"] = max(0, counts["colliders"] * (counts["colliders"] - 1) // 2 - filtered)
    for key in ("filtered_pairs", "contact_pairs"):
        if counts[key] > budget["max_" + key]:
            raise ValueError(f"resource_budget.max_{key}: estimated {counts[key]} exceeds {budget['max_' + key]}; no truncation")
    return {"scope": "chain plus conservative CAD-part count; exporter checks actual entire-scene grouping", "counts": counts,
            "budget": budget, "passed": True, "native_performance_or_accuracy_proven": False}


def _canonical(value):
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def resolved_fingerprint(record):
    materialized = {k: v for k, v in record.items() if k != "resolution"}
    return "sha256:" + hashlib.sha256(json.dumps(_canonical(materialized), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def decision_fingerprint(snapshot):
    materialized = {k: v for k, v in snapshot.items() if k != "decision_fingerprint"}
    return "sha256:" + hashlib.sha256(json.dumps(_canonical(materialized), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def validate_resolution(record):
    """Check the saved decision against saved effective values, not live defaults."""
    fields = {"format_version", "description", "category", "preset", "request", "geometry", "parameter_sources",
              "selection", "solver", "resource_check", "validation", "limitations", "resolved_fingerprint", "decision_fingerprint"}
    snapshot = _closed(record["resolution"], fields, "resolution", required=True)
    if snapshot["format_version"] != "cable-resolution-1":
        raise ValueError("resolution.format_version: unsupported version")
    for field in ("description", "category", "resolved_fingerprint"):
        if not isinstance(snapshot[field], str) or not snapshot[field]:
            raise ValueError(f"resolution.{field}: require nonempty text")
    preset = _closed(snapshot["preset"], {"id", "version", "reference_url", "assumption"}, "resolution.preset", required=True)
    if not all(isinstance(value, str) and value for value in preset.values()):
        raise ValueError("resolution.preset: require nonempty versioned provenance")
    selected = _closed(snapshot["selection"], {"mode", "rule_version", "quality", "criteria", "requested_segment_length_m",
        "candidate_segment_length_m", "free_segments", "actual_material_segment_length_m", "free_length_m",
        "material_interval_count", "minimum_initial_curve_radius_m"}, "resolution.selection", required=True)
    if selected["mode"] not in {"auto", "explicit", "target_length"}:
        raise ValueError("resolution.selection.mode: unsupported mode")
    if selected["free_segments"] != _value(record, "discretization", "free_segments"):
        raise ValueError("resolution.selection.free_segments differs from saved effective count")
    free_length = _value(record, "geometry", "free_end") - _value(record, "geometry", "free_start")
    for key, actual in (("free_length_m", free_length), ("actual_material_segment_length_m", free_length/selected["free_segments"])):
        if isinstance(selected[key], bool) or not isinstance(selected[key], (int, float)) or not math.isclose(selected[key], actual, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(f"resolution.selection.{key}: inconsistent saved resolution")
    if snapshot["resolved_fingerprint"] != resolved_fingerprint(record):
        raise ValueError("resolution.resolved_fingerprint: saved effective declaration changed; explicitly reconfigure rather than silently infer")
    if snapshot["decision_fingerprint"] != decision_fingerprint(snapshot):
        raise ValueError("resolution.decision_fingerprint: saved intent/provenance/decision changed")
    for name in ("request", "geometry", "parameter_sources", "solver", "resource_check", "validation"):
        if not isinstance(snapshot[name], dict):
            raise ValueError(f"resolution.{name}: expected an object")
    if not isinstance(snapshot["limitations"], list) or not all(isinstance(x, str) for x in snapshot["limitations"]):
        raise ValueError("resolution.limitations: expected text list")
    if snapshot["validation"] != {"configuration": "validated", "native_runtime": "not_asserted_by_planner", "physical_accuracy": "not_established"}:
        raise ValueError("resolution.validation: planner cannot assert native or physical accuracy")
    return deepcopy(dict(snapshot))
