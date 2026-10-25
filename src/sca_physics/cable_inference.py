"""Resolve parsed user intent into a frozen, CAD-bound whole-cable declaration.

No online service, language model or random sampling is used. The Agent supplies
the applicable category and sourced decisions; unknown descriptions never select a preset.
"""
from copy import deepcopy
import math

from .cable_geometry import resolve_geometry, initial_curvature_radius, _positive
from .cable_presets import PRESETS, PRESET_VERSION, RULE_VERSION, SOLVER_POLICY_VERSION, QUALITY, LIMITATIONS
from .cable_resolution import resource_budget, budget_values, check_chain_budget, resolved_fingerprint, decision_fingerprint
from .contract import _closed, _source, inventory, validate_config
from .provenance import parameter, inherited, derived

PROPERTIES = {
    "linear_density": ("mechanics", "kg/m"), "equivalent_density": (None, "kg/m^3"),
    "bending_rigidity": ("mechanics", "N*m^2"), "torsional_rigidity": ("mechanics", "N*m^2"),
    "joint_damping": ("mechanics", "N*m*s/rad"), "linear_damping": ("body", "1/s"),
    "angular_damping": ("body", "1/s"), "static_friction": ("contact", "1"),
    "dynamic_friction": ("contact", "1"), "restitution": ("contact", "1"),
    "minimum_bend_radius": ("limits", "m"), "maximum_bend_angle": ("limits", "deg"),
    "maximum_twist_angle": ("limits", "deg"), "gravity_magnitude": ("scene", "m/s^2"),
    "enabled": ("collision", "boolean"), "self_collision": ("collision", "boolean"),
    "enable_speculative_ccd": ("body", "boolean"), "apply_to_endpoints": ("body", "boolean"),
    "contact_offset": ("collision", "m"), "rest_offset": ("collision", "m"),
}
CLASS_KIND = {"user": "explicit", "reference": "reference", "calibrated": "reference",
              "preset": "default", "engineering_estimate": "estimated", 'derived': 'derived'}


def _continued_request(package, target, request, reconfigure):
    embedded = package.root_definition.metadata.get("sca_physics")
    if embedded is None:
        return dict(request)
    validate_config(package, embedded)
    matches = [c for c in embedded.get("cables", {}).values() if c.get("target_node_id") == target]
    if not matches:
        return dict(request)
    previous = matches[0]
    if previous.get("representation") != "rigid_joint_chain":
        # Representation conversion is guarded by upsert's explicit flag, not
        # interpreted as a continuation of an unrelated volume declaration.
        return dict(request)
    if not reconfigure:
        raise ValueError("target already has a saved cable decision; export it unchanged or explicitly pass --reconfigure to make a new decision")
    resolution = previous.get("resolution")
    old = resolution["request"] if resolution else {}
    old = deepcopy(old)
    # Old raw requests can contain unlabelled values or ignored alternatives.
    # Continue from actual saved wrappers, never relabel or resurrect those inputs.
    if resolution:
        retained = {}
        for name, (group, _) in PROPERTIES.items():
            if group and name in previous[group]:
                retained[name] = deepcopy(previous[group][name])
        old['properties'] = retained
        old.pop('evidence', None)
        old['discretization'] = {'mode': 'explicit', 'free_segments': deepcopy(previous['discretization']['free_segments'])}
        old['solver'] = {key: deepcopy(previous[group][key]) for key, group in (
            ('physics_hz', 'scene'), ('solver_position_iterations', 'body'), ('solver_velocity_iterations', 'body'))}
        if 'resource_budget' in previous:
            old['resource_budget'] = deepcopy(previous['resource_budget'])
        # Saved geometry is already fully identified and sourced.
        if 'geometry' in old:
            old['geometry'] = {key: deepcopy(resolution['geometry'].get('parameters', {}).get(key, {
                'value': resolution['geometry'][key], 'unit': 'm', 'source': previous['geometry']['centerline' if key == 'centerline_m' else 'length']['source']}))
                for key in ('centerline_m', 'diameter_m')}
    merged = deepcopy(old)
    merged.update(deepcopy(dict(request)))
    for group in ("properties", "evidence", "resource_budget", "solver"):
        if group in request:
            updates = _closed(request[group], set(PROPERTIES) if group in {"properties", "evidence"} else
                {"physics_hz", "solver_position_iterations", "solver_velocity_iterations"} if group == "solver" else
                {"max_bodies", "max_joints", "max_colliders", "max_filtered_pairs", "max_contact_pairs", "max_solver_work_per_second", "scope"}, "request." + group)
            merged[group] = {**deepcopy(old.get(group, {})), **deepcopy(dict(updates))}
            if group in {"properties", "evidence"}:
                for present, alternate in (("linear_density", "equivalent_density"), ("equivalent_density", "linear_density")):
                    if present in updates and alternate not in updates:
                        merged[group].pop(alternate, None)
    if resolution:
        merged.setdefault("category", resolution["category"])
        if "feel" not in request:
            merged["feel"] = old.get("feel", "normal")
    else:
        # A mere qualitative edit must not discard an old explicit count or
        # higher-priority numeric provenance. Changing mode is an explicit input.
        merged.setdefault("discretization", {"mode": "explicit", "free_segments": deepcopy(previous["discretization"]["free_segments"])})
        merged.setdefault("endpoints", deepcopy(previous["endpoints"]))
        retained = {}
        for name, (group, _) in PROPERTIES.items():
            if group and name in previous[group]:
                item = previous[group][name]
                retained[name] = deepcopy(item)
        merged["properties"] = {**retained, **merged.get("properties", {})}
        retained_solver = {}
        for key, group in (("physics_hz", "scene"), ("solver_position_iterations", "body"),
                           ("solver_velocity_iterations", "body")):
            item = previous[group][key]
            retained_solver[key] = deepcopy(item)
        merged["solver"] = {**retained_solver, **merged.get("solver", {})}
    return merged


def _candidate(raw, name, *, evidence=False, source=None):
    if isinstance(raw, dict):
        raw = _closed(raw, {"value", "unit", "source", "classification"}, "request.properties." + name, required={"value"})
        unit = raw.get("unit", PROPERTIES[name][1])
        source = _source(raw.get("source", source), "request.properties." + name + ".source")
        default_class = {"explicit": "user", "reference": "reference", "estimated": "engineering_estimate", "default": "preset", 'derived': 'derived'}[source["kind"]]
        classification = raw.get("classification", default_class)
        if classification not in CLASS_KIND or CLASS_KIND[classification] != source["kind"]:
            raise ValueError(f"request.properties.{name}: classification and source.kind disagree")
        value = raw["value"]
    else:
        value, unit = raw, PROPERTIES[name][1]
        source = _source(source, 'request.properties.' + name + '.source')
        classification = {"explicit": "user", "reference": "reference", "estimated": "engineering_estimate", "default": "preset", 'derived': 'derived'}[source['kind']]
    if unit != PROPERTIES[name][1]:
        raise ValueError(f"request.properties.{name}.unit: expected {PROPERTIES[name][1]}")
    if evidence and classification not in {"reference", "calibrated"}:
        raise ValueError("request.evidence: values require reference/calibrated classification and a corresponding source")
    result = parameter({'value': value, 'unit': unit, 'source': source}, unit, 'request.properties.' + name)
    if unit == 'boolean':
        if not isinstance(value, bool):
            raise ValueError('request.properties.' + name + ': expected a boolean')
    else:
        from .contract import _float32
        _float32(value, 'request.properties.' + name)
        if name not in {'rest_offset'} and value < 0:
            raise ValueError('request.properties.' + name + ': require nonnegative value')
        if name in {'linear_density','equivalent_density','bending_rigidity','torsional_rigidity','contact_offset','minimum_bend_radius'} and value <= 0:
            raise ValueError('request.properties.' + name + ': require positive value')
        if name == 'restitution' and value > 1:
            raise ValueError('request.properties.restitution: require0..1')
    return {**result, "classification": classification}


def _seed(value, name, classification, detail):
    return {"value": value, "unit": PROPERTIES[name][1], "source": {"kind": "default", "detail": detail},
            "classification": "preset"}


def _solver_parameter(raw, key):
    path = "request.solver." + key
    source = None
    if isinstance(raw, dict):
        raw = _closed(raw, {"value", "unit", "source"}, path, required={"value"})
        if raw.get("unit", "count") != "count":
            raise ValueError(path + ".unit: expected count")
        return {"value": deepcopy(raw["value"]), "unit": "count",
                "source": _source(raw.get("source", source), path + ".source")}
    return {"value": deepcopy(raw), "unit": "count", "source": source}


def _guard_legacy_structure(package, target, declaration, reconfigure):
    """Do not silently convert legacy structure outside the intent interface."""
    if not reconfigure:
        return
    previous = next((item for item in package.root_definition.metadata.get("sca_physics", {}).get("cables", {}).values()
                     if item.get("target_node_id") == target), None)
    if not previous or previous.get("representation") != "rigid_joint_chain" or "resolution" in previous:
        return

    def same(a, b):
        a = a["value"] if isinstance(a, dict) else a
        b = b["value"] if isinstance(b, dict) else b
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
        if isinstance(a, bool) or isinstance(b, bool):
            return type(a) is type(b) and a == b
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
        return a == b

    fields = {"geometry": ("coordinate_space", "initial_shape", "centerline", "arc_stations", "free_start", "free_end", "length"),
              "section": ("shape", "radius", "endpoint_radius"),
              "collision": ("filter_adjacent", "filter_endpoint_links", "filter_material_neighbors"),
              "scene": ("solver_type", "enable_gpu_dynamics", "broadphase_type")}
    for group, names in fields.items():
        for name in names:
            # Early1.4 snapshots may omit the optional material-neighbour switch.
            old = previous[group].get(name, False)
            if not same(old, declaration[group][name]):
                raise ValueError(f"legacy reconfigure would change {group}.{name}; this automatic interface cannot preserve that legacy structure. Keep the saved package or continue editing with set-rigid-chain.")
            if name in previous[group]:
                declaration[group][name] = deepcopy(previous[group][name])


def select_segments(geometry, preset, quality, mechanics, supplied, *, budget=None, gravity=9.81):
    supplied = _closed(supplied or {}, {"mode", "free_segments", "target_segment_length_m"}, "request.discretization")
    mode = supplied.get("mode", "auto")
    fields = {"auto": {"mode"}, "explicit": {"mode", "free_segments"}, "target_length": {"mode", "target_segment_length_m"}}
    if mode not in fields or set(supplied) - fields[mode] or (fields[mode] - {"mode"}) - set(supplied):
        raise ValueError("request.discretization: choose exactly auto, explicit+free_segments, or target_length+target_segment_length_m; conflicting inputs are rejected")
    q = QUALITY[quality]
    length, diameter = geometry["free_length_m"], geometry["diameter_m"]
    radius = initial_curvature_radius(geometry["centerline_m"])
    # Gravity length is a resolution feature, not a prescribed sag/bend outcome.
    gravity_length = (mechanics["bending_rigidity"]["value"] / (mechanics["linear_density"]["value"] * gravity)) ** (1/3) if gravity > 0 else None
    criteria = {
        "diameter_feature_m": preset["diameters_per_segment"] * diameter * q["length_factor"],
        "quality_length_feature_m": length / q["minimum_segments"],
    }
    if gravity_length is not None:
        criteria['elastogravity_feature_m'] = preset['gravity_length_fraction'] * gravity_length * q['length_factor']
    if radius is not None:
        criteria["initial_turn_feature_m"] = 2 * radius * math.sin(math.radians(q["turn_degrees"]) / 2)
        tolerance = min(radius, q["sagitta_diameters"] * diameter)
        criteria["initial_sagitta_feature_m"] = 2 * math.sqrt(max(0., 2*radius*tolerance-tolerance*tolerance))
    requested = None
    if mode == "auto":
        candidate = min(criteria.values())
        n = max(2, math.ceil(length / candidate))
    elif mode == "target_length":
        requested_raw = supplied['target_segment_length_m']
        requested = _positive(requested_raw['value'] if isinstance(requested_raw, dict) else requested_raw, "request.discretization.target_segment_length_m")
        candidate = requested
        n = max(2, math.ceil(length / candidate))
    else:
        n = supplied["free_segments"]
        n = n['value'] if isinstance(n, dict) else n
        if isinstance(n, bool) or not isinstance(n, int) or n < 2:
            raise ValueError("request.discretization.free_segments: require an integer >=2")
        candidate = None
    if budget is not None:
        extras = int(geometry["free_start_m"] > 0) + int(geometry["free_end_m"] < geometry["length_m"])
        if n + extras > budget_values(budget)["max_bodies"]:
            raise ValueError("resource_budget.max_bodies: selected count exceeds budget; no truncation or hidden coarsening")
    try:
        actual_length = length / n
    except (OverflowError, ZeroDivisionError):
        raise ValueError("request.discretization: count cannot produce a representable material segment length") from None
    _positive(actual_length, "request.discretization.actual_material_segment_length_m")
    if candidate is None:
        candidate = actual_length
    return {"mode": mode, "rule_version": RULE_VERSION, "quality": quality, "criteria": criteria,
            "requested_segment_length_m": requested, "candidate_segment_length_m": candidate,
            "free_segments": n, "actual_material_segment_length_m": actual_length, "free_length_m": length,
            "material_interval_count": n + int(geometry["free_start_m"] > 0) + int(geometry["free_end_m"] < geometry["length_m"]),
            "minimum_initial_curve_radius_m": radius}


def configure_cable(package, target_node_id, request, *, chain_id=None, convert_rigid=False,
                    replace_deformable=False, base_config=None, reconfigure=False):
    from .rigid_chain import upsert_rigid_chain
    request = _closed(request, {"description", "category", "preset_version", "feel", "quality", "geometry", "endpoints",
                               "properties", "evidence", "discretization", "resource_budget", "solver", 'source', 'decision'}, "request", required={"description"})
    description = request["description"]
    if not isinstance(description, str) or not description.strip() or len(description) > 10000:
        raise ValueError("request.description: require 1..10000 characters")
    request = deepcopy(dict(request))
    context = inherited(request, path='request.source')
    for group in ('properties', 'evidence', 'solver', 'resource_budget'):
        if group not in request:
            continue
        allowed = set(PROPERTIES) if group in {'properties', 'evidence'} else {'physics_hz', 'solver_position_iterations', 'solver_velocity_iterations'} if group == 'solver' else {'max_bodies', 'max_joints', 'max_colliders', 'max_filtered_pairs', 'max_contact_pairs', 'max_solver_work_per_second', 'scope'}
        values = _closed(request[group], allowed | {'source'}, 'request.' + group)
        group_source = inherited(values, context, 'request.' + group + '.source')
        request[group] = {key: _candidate(value, key, evidence=group == 'evidence', source=group_source) if group in {'properties', 'evidence'} else parameter(value, 'count', 'request.' + group + '.' + key, group_source)
            if key != 'scope' else value for key, value in values.items() if key != 'source'}
    if 'discretization' in request:
        values = _closed(request['discretization'], {'mode', 'free_segments', 'target_segment_length_m', 'source'}, 'request.discretization')
        disc_source = inherited(values, context, 'request.discretization.source')
        request['discretization'] = {key: parameter(value, 'count' if key == 'free_segments' else 'm', 'request.discretization.' + key, disc_source)
            if key != 'mode' else value for key, value in values.items() if key != 'source'}
    request = _continued_request(package, target_node_id, request, reconfigure)
    category = request.get('category')
    if category not in PRESETS:
        raise ValueError(f"request.category: supported initial categories are {sorted(PRESETS)}")
    if request.get("preset_version", PRESET_VERSION) != PRESET_VERSION:
        raise ValueError("request.preset_version: unsupported preset version for a new decision; existing saved packages do not re-resolve")
    feel = request.get("feel", "normal")
    quality = request.get("quality", "balanced")
    if feel not in {"normal", "stiffer", "softer"} or quality not in QUALITY:
        raise ValueError("request: unsupported feel or quality")
    preset = PRESETS[category]
    geometry = resolve_geometry(package, target_node_id, request.get("geometry"), context)
    diameter = geometry["diameter_m"]
    ratio = diameter / preset["reference_diameter_m"]
    factor = {"normal": 1., "stiffer": 2., "softer": .5}[feel]
    estimate = f"Engineering starting estimate for whole {category}, preset{PRESET_VERSION}; not measured/calibrated. EI/GJ scale as diameter^4 within the assumed similar construction; feel{feel} factor{factor} applies only to preset stiffness."
    preset_basis = f"Category preset{category}@{PRESET_VERSION}: {preset['reference_detail']} Reference:{preset['reference_url']}"
    seeds = {
        "linear_density": _seed(preset["reference_linear_density_kg_m"] * ratio**2, "linear_density", "preset", preset_basis),
        "bending_rigidity": _seed(preset["bending_rigidity_Nm2"] * ratio**4 * factor, "bending_rigidity", "engineering_estimate", estimate),
        "torsional_rigidity": _seed(preset["torsional_rigidity_Nm2"] * ratio**4 * factor, "torsional_rigidity", "engineering_estimate", estimate),
        "joint_damping": _seed(preset["joint_damping_Nms_rad"], "joint_damping", "engineering_estimate", "Phenomenological per-joint starting damping; not measured, not rescaled with N or fitted to numerical error"),
    }
    for key, base_value, power, feel_factor in (
        ('linear_density',preset['reference_linear_density_kg_m'],2,1.),
        ('bending_rigidity',preset['bending_rigidity_Nm2'],4,factor),
        ('torsional_rigidity',preset['torsional_rigidity_Nm2'],4,factor)):
        if ratio != 1 or feel_factor != 1:
            basis = _seed(base_value,key,'preset' if key == 'linear_density' else 'engineering_estimate',preset_basis if key == 'linear_density' else estimate)
            calculated=derived('diameter-power-scale-v1',{
                'base': {k:v for k,v in basis.items() if k != 'classification'},
                'diameter': geometry['parameters']['diameter_m'],
                'reference_diameter':{'value':preset['reference_diameter_m'],'unit':'m','source':{'kind':'default','detail':preset_basis}},
                'power':{'value':power,'unit':'count','source':{'kind':'default','detail':'Similar circular construction engineering scaling exponent'}},
                'factor':{'value':feel_factor,'unit':'1','source':{'kind':'default','detail':'Uncalibrated preset feel multiplier'}}},preset_basis if key == 'linear_density' else estimate)
            seeds[key]={**calculated,'classification':'derived'}
    defaults = {"linear_damping": .05, "angular_damping": .05, "static_friction": preset["static_friction"],
                "dynamic_friction": preset["dynamic_friction"], "restitution": .02,
                "minimum_bend_radius": preset["minimum_bend_radius_diameters"]*diameter,
                "maximum_bend_angle": 60., "maximum_twist_angle": 120., "gravity_magnitude": 9.81,
                "enabled": True, "self_collision": True, "contact_offset": diameter*.05, "rest_offset": 0.}
    defaults.update(enable_speculative_ccd=True, apply_to_endpoints=True)
    for key, value in defaults.items():
        seeds[key] = _seed(value, key, "engineering_estimate", "Explicit initial contact/constraint/drag estimate; no measured-object or general accuracy claim")
    supplied = _closed(request.get("properties", {}), set(PROPERTIES), "request.properties")
    evidence = _closed(request.get("evidence", {}), set(PROPERTIES), "request.evidence")
    chosen = {}
    for key in set(PROPERTIES) - {"equivalent_density"}:
        chosen[key] = _candidate(supplied[key], key) if key in supplied else _candidate(evidence[key], key, evidence=True) if key in evidence else seeds[key]
    for values in (supplied, evidence):
        if 'linear_density' in values and 'equivalent_density' in values:
            raise ValueError('request: linear_density and equivalent_density are mutually exclusive within the same submitted layer')
    density_layer = supplied if {'linear_density', 'equivalent_density'} & supplied.keys() else evidence
    if 'equivalent_density' in density_layer:
        density = _candidate(density_layer['equivalent_density'], 'equivalent_density', evidence=density_layer is evidence)
        item = derived('circle-rod-lambda-v1', {'density': {k:v for k,v in density.items() if k != 'classification'},
            'diameter': geometry['parameters']['diameter_m']}, 'Whole-line equivalent density converted using actual circular outer area; not a homogeneous-material claim')
        chosen['linear_density'] = {**item, 'classification': 'derived'}
    mechanics = {key: {k: deepcopy(v) for k, v in item.items() if k != "classification"}
                 for key, item in chosen.items() if PROPERTIES[key][0] == "mechanics"}
    for key in ("linear_density", "bending_rigidity", "torsional_rigidity"):
        _positive(mechanics[key]["value"], "request.properties." + key)
    budget_input = request.get('resource_budget', {})
    # Unlabelled integers can reach this branch only from a validated saved
    # legacy decision, after new submitted fields were strictly normalized.
    retained_legacy_budget = any(not isinstance(v, dict) for k,v in budget_input.items() if k != 'scope')
    budget = resource_budget(budget_input, partial=True, source=context, schema_version='1.6' if retained_legacy_budget else '1.7')
    selection = select_segments(geometry, preset, quality, mechanics, request.get("discretization"), budget=budget, gravity=chosen['gravity_magnitude']['value'])
    q = QUALITY[quality]
    solver_input = _closed(request.get("solver", {}), {"physics_hz", "solver_position_iterations", "solver_velocity_iterations"}, "request.solver")
    solver = {"physics_hz": round(preset["physics_hz"] * q["frequency_factor"]),
              "solver_position_iterations": q["position_iterations"], "solver_velocity_iterations": q["velocity_iterations"]}
    solver.update({key: _solver_parameter(value, key) for key, value in solver_input.items()})
    solver_settings = {key: value["value"] if isinstance(value, dict) else value for key, value in solver.items()}
    source = {"kind": "default", "detail": f"Program-filled initial configuration for intent:{description}; category{category}@{PRESET_VERSION}; submitted sourced values override these fillers; no online model or object calibration"}
    if selection['mode'] == 'explicit':
        count_parameter = deepcopy(request['discretization']['free_segments'])
    else:
        target = request['discretization']['target_segment_length_m'] if selection['mode'] == 'target_length' else {
            'value': selection['candidate_segment_length_m'], 'unit': 'm', 'source': {'kind': 'default', 'detail': 'Versioned program resolution feature minimum; not an error-adaptive or calibrated length'}}
        count_parameter = derived('segment-count-v1', {'length': geometry['parameters']['free_length_m'], 'target_length': target}, 'Deterministic max(2,ceil(free length/target length)); no truncation')
    declaration = {
        "source": source,
        "geometry": {"coordinate_space": "world", "initial_shape": "planar", "centerline": geometry["centerline_m"],
                     "arc_stations": geometry["arc_stations_m"], "free_start": geometry["free_start_m"],
                     "free_end": geometry["free_end_m"], "length": geometry["length_m"]},
        "discretization": {"free_segments": count_parameter, "frame_policy": "shortest_arc_x"},
        "section": {"shape": "circle", "radius": diameter/2, "endpoint_radius": diameter/2},
        "mechanics": {**mechanics, "damping_mode": "per_joint", "rest_state": "straight"},
        "body": {"solver_position_iterations": solver["solver_position_iterations"], "solver_velocity_iterations": solver["solver_velocity_iterations"],
                 "enable_speculative_ccd": True, "apply_to_endpoints": True},
        "collision": {"filter_adjacent": True, "filter_endpoint_links": True, "filter_material_neighbors": True},
        "contact": {}, "limits": {},
        "scene": {"physics_hz": solver["physics_hz"], "solver_type": "TGS", "enable_gpu_dynamics": False, "broadphase_type": "MBP"},
        "endpoints": deepcopy(request.get("endpoints", {"start": {"mode": "free"}, "end": {"mode": "free"}})),
        "resource_budget": budget,
    }
    radius_parameter=derived('scale-v1',{'base':geometry['parameters']['diameter_m'],
        'factor':{'value':.5,'unit':'1','source':{'kind':'default','detail':'Circle radius equals diameter/2'}}},'Circular radius from actual diameter')
    declaration['section']['radius']=radius_parameter
    declaration['section']['endpoint_radius']=deepcopy(radius_parameter)
    for field, key in (('centerline', 'centerline_m'), ('arc_stations', 'arc_stations_m'), ('free_start', 'free_start_m'), ('free_end', 'free_end_m'), ('length', 'length_m')):
        declaration['geometry'][field] = deepcopy(geometry['parameters'][key])
    for key, item in chosen.items():
        if PROPERTIES[key][0] == "mechanics":
            continue
        declaration[PROPERTIES[key][0]][key] = {k: deepcopy(v) for k, v in item.items() if k != "classification"}
    _guard_legacy_structure(package, target_node_id, declaration, reconfigure)
    config = upsert_rigid_chain(package, target_node_id, declaration, chain_id=chain_id,
        convert_rigid=convert_rigid, replace_deformable=replace_deformable, base_config=base_config)
    record = next(c for c in config["cables"].values() if c["target_node_id"] == target_node_id)
    if 'decision' in request:
        from .contract import _decision
        config['decision'] = _decision(request['decision'])
    limitations = list(LIMITATIONS)
    if not preset["diameter_range_m"][0] <= diameter <= preset["diameter_range_m"][1]:
        limitations.append("Geometry diameter is outside this category preset's initial applicability interval; extrapolation is not calibrated.")
    record["resolution"] = {
        "format_version": "cable-resolution-1", "description": description, "category": category,
        "preset": {"id": category, "version": PRESET_VERSION, "reference_url": preset["reference_url"], "assumption": preset["label"] + "; engineering equivalent stiffness, not the supplier's measured EI/GJ"},
        "request": deepcopy(dict(request)), "geometry": deepcopy(geometry),
        "parameter_sources": {key: {"classification": item["classification"], "source": deepcopy(item["source"])} for key, item in chosen.items()},
        "selection": selection,
        "solver": {"policy_version": SOLVER_POLICY_VERSION, "settings": solver_settings, "quality": quality,
                   "export_geometry_absolute_tolerance_m": max(1e-8, 2. ** (math.floor(math.log2(max(abs(x) for p in geometry["centerline_m"] for x in p) + diameter)) - 23)),
                   "export_tolerance_purpose": "One float32 ULP at the saved world-coordinate scale; geometry serialization rounding guard only, not a relaxed physical accuracy gate; explicit exporter config takes precedence.",
                   "status": "engineering_initial_not_accuracy_guarantee", "finite_trial_budget": {"maximum_trials": 2, "maximum_simulated_seconds_per_trial": .5},
                   "automatic_unbounded_refinement": False},
        "resource_check": check_chain_budget(record, other_parts=len(inventory(package)["parts"]) - 1),
        "validation": {"configuration": "validated", "native_runtime": "not_asserted_by_planner", "physical_accuracy": "not_established"},
        "limitations": limitations,
        "resolved_fingerprint": resolved_fingerprint(record),
    }
    record["resolution"]["decision_fingerprint"] = decision_fingerprint(record["resolution"])
    validate_config(package, config)
    return config
