"""Persist a CAD-bound, planar round cable as a rigid-link/D6 declaration.

This module validates SI inputs and identity. It does not discretize the cable,
author USD, cook meshes, integrate motion, or infer measured material properties.
"""

from copy import deepcopy
from collections.abc import Mapping
import math

from .contract import HIGH_FREQUENCY_SCHEMA_VERSION, RESOLVED_CABLE_SCHEMA_VERSION, AGENTIC_SCHEMA_VERSION, JOINT_SCHEMA_VERSION, SOURCED_SCHEMA_VERSIONS, _closed, _float32, _object, _records, _source
from .deformable import geometry_source_snapshot, validate_target_relations

REPRESENTATION = "rigid_joint_chain"
SCHEMA_VERSION = "1.4"
GROUPS = {
    "geometry": {"centerline": "m", "arc_stations": "m", "free_start": "m", "free_end": "m", "length": "m"},
    "discretization": {"free_segments": "count"},
    "section": {"radius": "m", "endpoint_radius": "m"},
    "mechanics": {"linear_density": "kg/m", "bending_rigidity": "N*m^2", "torsional_rigidity": "N*m^2", "joint_damping": "N*m*s/rad"},
    "limits": {"minimum_bend_radius": "m", "maximum_bend_angle": "deg", "maximum_twist_angle": "deg"},
    "body": {"linear_damping": "1/s", "angular_damping": "1/s", "solver_position_iterations": "count", "solver_velocity_iterations": "count", "enable_speculative_ccd": "boolean", "apply_to_endpoints": "boolean"},
    "collision": {"enabled": "boolean", "contact_offset": "m", "rest_offset": "m", "self_collision": "boolean", "filter_adjacent": "boolean", "filter_endpoint_links": "boolean", "filter_material_neighbors": "boolean"},
    "contact": {"static_friction": "1", "dynamic_friction": "1", "restitution": "1"},
    "scene": {"physics_hz": "count", "gravity_magnitude": "m/s^2"},
}
TOKENS = {
    "geometry": {"coordinate_space": "world", "initial_shape": "planar"},
    "discretization": {"frame_policy": "shortest_arc_x"},
    "section": {"shape": "circle"},
    "mechanics": {"damping_mode": "per_joint", "rest_state": "straight"},
    "scene": {"solver_type": "TGS", "enable_gpu_dynamics": False, "broadphase_type": "MBP"},
}
OPTIONAL_PARAMETERS = {"collision": {"filter_material_neighbors": False}}


def schema_for_chains(records, current=None):
    """New resolution/budgets opt in to1.6; never change an old saved count."""
    if current in SOURCED_SCHEMA_VERSIONS:
        return current
    if current == RESOLVED_CABLE_SCHEMA_VERSION or any(
            isinstance(r, Mapping) and r.get("representation") == REPRESENTATION and
            ("resolution" in r or "resource_budget" in r) for r in records.values()):
        return RESOLVED_CABLE_SCHEMA_VERSION
    if current == HIGH_FREQUENCY_SCHEMA_VERSION:
        return current
    for record in records.values():
        if not isinstance(record, Mapping) or record.get("representation") != REPRESENTATION:
            continue
        scene = record.get("scene", {})
        frequency = scene.get("physics_hz") if isinstance(scene, Mapping) else None
        if isinstance(frequency, Mapping):
            frequency = frequency.get("value")
        if isinstance(frequency, int) and not isinstance(frequency, bool) and frequency > 4096:
            return HIGH_FREQUENCY_SCHEMA_VERSION
    return SCHEMA_VERSION


def _number(value, path):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path}: expected a finite number, not a boolean")
    _float32(value, path)
    return value


def _parameter(raw, unit, path, source, *, resolve, schema_version):
    if resolve:
        from .provenance import parameter
        raw = parameter(raw, unit, path, source)
    obj = _closed(raw, {"value", "unit", "source"}, path, required={"value"} if resolve else True)
    result = {"value": deepcopy(obj["value"]), "unit": obj.get("unit", unit),
              "source": _source(obj.get("source", source), path + ".source")}
    if result["unit"] != unit:
        raise ValueError(f"{path}.unit: expected {unit!r}")
    value = result["value"]
    if path.endswith(".centerline"):
        if not isinstance(value, list) or not 2 <= len(value) <= 100000:
            raise ValueError(f"{path}: require 2..100000 3D points")
        for i, point in enumerate(value):
            if not isinstance(point, list) or len(point) != 3:
                raise ValueError(f"{path}[{i}]: expected a 3D point")
            for coordinate in point:
                _number(coordinate, path)
    elif path.endswith(".arc_stations"):
        if not isinstance(value, list):
            raise ValueError(f"{path}: expected an array")
        for station in value:
            _number(station, path)
    elif unit == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path}: expected a boolean")
    elif unit == "count":
        minimum = 0 if path.endswith(".solver_velocity_iterations") else 1
        unbounded_count = path.endswith(".free_segments") and schema_version in ({RESOLVED_CABLE_SCHEMA_VERSION} | SOURCED_SCHEMA_VERSIONS)
        maximum = 16384 if path.endswith(".physics_hz") and schema_version in ({HIGH_FREQUENCY_SCHEMA_VERSION, RESOLVED_CABLE_SCHEMA_VERSION} | SOURCED_SCHEMA_VERSIONS) else 4096
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum or (not unbounded_count and value > maximum):
            raise ValueError(f"{path}: require an integer >= {minimum}" + (" under an explicit resource budget" if unbounded_count else f" and <= {maximum}"))
    else:
        _number(value, path)
        if value < 0 and not path.endswith(".rest_offset"):
            raise ValueError(f"{path}: must be nonnegative")
    return result


def _planar(points, path):
    origin = points[0]
    vectors = [[p[k] - origin[k] for k in range(3)] for p in points[1:]]
    first = next((v for v in vectors if math.hypot(*v) > 1e-12), None)
    if first is None:
        raise ValueError(f"{path}: centerline has zero length")
    normal = None
    for other in vectors:
        cross = [first[1]*other[2]-first[2]*other[1], first[2]*other[0]-first[0]*other[2], first[0]*other[1]-first[1]*other[0]]
        norm = math.hypot(*cross)
        if norm > 1e-12 * math.hypot(*first) * max(math.hypot(*other), 1e-12):
            normal = [x / norm for x in cross]
            break
    if normal and any(abs(sum(v[k]*normal[k] for k in range(3))) > 1e-8 for v in vectors):
        raise ValueError(f"{path}: non-planar spatial centerlines are not implemented")


def resolve_chain(package, raw, path, *, resolve, schema_version=SCHEMA_VERSION):
    fields = {"representation", "target_node_id", "parent_node_id", "physical_type", "geometry_source", "source", "endpoints"} | set(GROUPS)
    additions = {"resource_budget", "resolution"} if schema_version in ({RESOLVED_CABLE_SCHEMA_VERSION} | SOURCED_SCHEMA_VERSIONS) else set()
    item = _closed(raw, fields | additions, path, required=fields)
    if item["representation"] != REPRESENTATION or item["physical_type"] != REPRESENTATION:
        raise ValueError(f"{path}: representation and physical_type must be {REPRESENTATION}")
    source = _source(item["source"], path + ".source")
    target = item["target_node_id"]
    expected = geometry_source_snapshot(package, target)
    if item["geometry_source"] != expected:
        raise ValueError(f"{path}.geometry_source: stale CAD geometry, unit or occurrence transform")
    nodes = _records(package.occurrence_graph.nodes, "node_id", "occurrence_graph.nodes")
    parent = item["parent_node_id"]
    if parent != nodes[target].get("parent_node_id") or parent not in nodes or nodes[parent]["node_kind"] != "assembly":
        raise ValueError(f"{path}.parent_node_id: expected target's direct assembly occurrence")
    result = {"representation": REPRESENTATION, "target_node_id": target, "parent_node_id": parent,
              "physical_type": REPRESENTATION, "geometry_source": deepcopy(expected), "source": source}
    for group, fields in GROUPS.items():
        constants = TOKENS.get(group, {})
        optional = OPTIONAL_PARAMETERS.get(group, {})
        values = _closed(item[group], set(fields) | set(constants) | ({'source'} if resolve else set()), path + "." + group,
                         required=(set(fields) | set(constants)) - set(optional))
        entry = {}
        for key, token in constants.items():
            if type(values[key]) is not type(token) or values[key] != token:
                raise ValueError(f"{path}.{group}.{key}: only {token!r} is implemented")
            entry[key] = token
        for key, unit in fields.items():
            if key not in values and key in optional:
                if not resolve:
                    # Early candidate 1.4 packages omit this optional switch;
                    # validation must not mutate them. Export treats it as false.
                    continue
                raw = {"value": optional[key], "unit": unit,
                       "source": {"kind": "default", "detail": "Compatibility default: preserve adjacent-only filtering unless material-neighbor filtering is explicitly requested"}}
            else:
                raw = values[key]
            from .provenance import inherited
            entry[key] = _parameter(raw, unit, f"{path}.{group}.{key}", inherited(values, source, path + '.' + group + '.source'), resolve=resolve, schema_version=schema_version)
        result[group] = entry
    def value(group, field):
        return result[group][field]["value"]
    points, stations = value("geometry", "centerline"), value("geometry", "arc_stations")
    length = value("geometry", "length")
    if len(points) != len(stations) or len(stations) < 2 or stations[0] != 0 or length <= 0:
        raise ValueError(f"{path}.geometry: centerline/stations lengths must match, begin at zero, with positive total length")
    if not math.isclose(stations[-1], length, rel_tol=1e-9, abs_tol=1e-10):
        raise ValueError(f"{path}.geometry.length: must equal last arc station")
    for i, (a, b) in enumerate(zip(points, points[1:])):
        ds = stations[i+1] - stations[i]
        chord = math.dist(a, b)
        if ds <= 0 or chord <= 1e-12 or not math.isclose(ds, chord, rel_tol=2e-4, abs_tol=1e-8):
            raise ValueError(f"{path}.geometry.arc_stations: require strictly increasing material arc consistent with each polyline chord")
    _planar(points, path + ".geometry.centerline")
    start, end = value("geometry", "free_start"), value("geometry", "free_end")
    if not 0 <= start < end <= length:
        raise ValueError(f"{path}.geometry: require 0 <= free_start < free_end <= length")
    count = value("discretization", "free_segments")
    if count < 2 or (schema_version not in ({RESOLVED_CABLE_SCHEMA_VERSION} | SOURCED_SCHEMA_VERSIONS) and count > 512):
        raise ValueError(f"{path}.discretization.free_segments: require 2..512")
    if count > 512 and "resource_budget" not in item:
        raise ValueError(f"{path}.resource_budget: counts above the legacy512 guard require an explicit configurable resource budget")
    for group, key in (("section", "radius"), ("section", "endpoint_radius"), ("mechanics", "linear_density"), ("mechanics", "bending_rigidity"), ("mechanics", "torsional_rigidity"), ("limits", "minimum_bend_radius"), ("collision", "contact_offset")):
        if value(group, key) <= 0 or _float32(value(group, key), path) <= 0:
            raise ValueError(f"{path}.{group}.{key}: must be positive")
    for field in ("maximum_bend_angle", "maximum_twist_angle"):
        if not 0 < value("limits", field) < 180:
            raise ValueError(f"{path}.limits.{field}: require 0 < degrees < 180")
    if value("body", "solver_position_iterations") > 255 or value("body", "solver_velocity_iterations") > 255:
        raise ValueError(f"{path}.body: solver iteration counts must be <= 255")
    if _float32(value("collision", "rest_offset"), path) >= _float32(value("collision", "contact_offset"), path):
        raise ValueError(f"{path}.collision.rest_offset: must be less than contact_offset after float32 conversion")
    if value("contact", "restitution") > 1:
        raise ValueError(f"{path}.contact.restitution: require 0..1")
    # Connected capsules overlap at their caps; collisions must be filtered.
    if not value("collision", "filter_adjacent"):
        raise ValueError(f"{path}.collision.filter_adjacent: false is not supported for overlapping capsule links")
    endpoints = _closed(item["endpoints"], {"start", "end"}, path + ".endpoints", required=True)
    result["endpoints"] = {}
    for side, endpoint in endpoints.items():
        endpoint = _object(endpoint, f"{path}.endpoints.{side}")
        mode = endpoint.get("mode")
        if mode not in {"free", "world_fixed", "body_fixed"}:
            raise ValueError(f"{path}.endpoints.{side}.mode: unsupported endpoint mode")
        required = {"mode", "rigid_node_id"} if mode == "body_fixed" else {"mode"}
        endpoint = _closed(endpoint, required, f"{path}.endpoints.{side}", required=True)
        if mode == "body_fixed":
            identity = endpoint["rigid_node_id"]
            if not isinstance(identity, str) or identity == target or identity not in nodes or nodes[identity]["node_kind"] != "part":
                raise ValueError(f"{path}.endpoints.{side}.rigid_node_id: expected another real part occurrence")
        result["endpoints"][side] = deepcopy(dict(endpoint))
    if "resource_budget" in item:
        from .cable_resolution import resource_budget, check_chain_budget
        legacy_budget = schema_version not in SOURCED_SCHEMA_VERSIONS or (not resolve) or ('resolution' in item and all(not isinstance(v, dict) for k, v in item['resource_budget'].items() if k != 'scope'))
        result["resource_budget"] = resource_budget(item["resource_budget"], source=source,
            schema_version='1.6' if legacy_budget else AGENTIC_SCHEMA_VERSION)
        check_chain_budget(result)
    if "resolution" in item:
        if "resource_budget" not in item:
            raise ValueError(f"{path}.resolution: resolved intent requires resource_budget")
        from .cable_resolution import validate_resolution
        result["resolution"] = deepcopy(item["resolution"])
        validate_resolution(result)
    return result


def validate_chain_bindings(package, config):
    records = config.get("cables", {})
    targets = {}
    for identity, record in records.items():
        target = record.get("target_node_id")
        if target is not None:
            if target in targets:
                raise ValueError(f"cables: duplicate target_node_id {target!r}")
            targets[target] = identity
    chains = {r["target_node_id"]: r for r in records.values() if r["representation"] == REPRESENTATION}
    for target, record in chains.items():
        part = config["parts"][target]
        if part.get("physical_type") != REPRESENTATION or "rigid_body" in part:
            raise ValueError(f"parts.{target}: rigid_joint_chain requires matching physical_type and no rigid_body block")
        for endpoint in record["endpoints"].values():
            if endpoint.get("rigid_node_id") in targets:
                raise ValueError("rigid_chain.endpoints: another chain/FEM target cannot be a rigid endpoint")
    for target, part in config["parts"].items():
        if part.get("physical_type") == REPRESENTATION and target not in chains:
            raise ValueError(f"parts.{target}.physical_type: requires exactly one matching rigid_joint_chain declaration")
    validate_target_relations(package, chains)


def upsert_rigid_chain(package, target_node_id, declaration, *, chain_id=None,
                       convert_rigid=False, replace_deformable=False, base_config=None):
    """Return a complete configuration for an explicit CAD occurrence selection.

    Saving is performed by enrich_package and the normal complete-package codec.
    Replacement of an existing FEM/rigid declaration always requires opt-in.
    """
    from .contract import resolve_config, validate_config
    source = geometry_source_snapshot(package, target_node_id)
    embedded = package.root_definition.metadata.get("sca_physics")
    if base_config is not None:
        if embedded is not None:
            raise ValueError("base_config is only accepted for a raw package without sca_physics; existing metadata is preserved")
        embedded = resolve_config(package, base_config)
    if embedded is not None:
        validate_config(package, embedded)
    config = deepcopy(embedded) if embedded is not None else {}
    records = config.setdefault("cables", {})
    matching = [identity for identity, record in records.items() if record.get("target_node_id") == target_node_id]
    if len(matching) > 1:
        raise ValueError("cables: duplicate selected target")
    identity = matching[0] if matching else chain_id or target_node_id
    if matching and chain_id is not None and chain_id != identity:
        raise ValueError("chain_id: cannot rename an existing target")
    if identity in records and not matching:
        raise ValueError("chain_id already belongs to another declaration")
    if matching and records[identity]["representation"] != REPRESENTATION and not replace_deformable:
        raise ValueError("selected target has a FEM declaration; pass replace_deformable=True explicitly")
    record = deepcopy(dict(_object(declaration, "declaration")))
    if 'decision' in record:
        # Task reasoning belongs to the root contract, not a cable record.
        config['decision'] = record.pop('decision')
    for key in ("representation", "physical_type"):
        if key in record and record[key] != REPRESENTATION:
            raise ValueError(f"declaration.{key}: expected {REPRESENTATION}")
    if record.get("target_node_id", target_node_id) != target_node_id:
        raise ValueError("declaration.target_node_id differs from selected occurrence")
    if "geometry_source" in record and record["geometry_source"] != source:
        raise ValueError("declaration.geometry_source: stale CAD binding")
    nodes = _records(package.occurrence_graph.nodes, "node_id", "occurrence_graph.nodes")
    if "parent_node_id" in record and record["parent_node_id"] != nodes[target_node_id].get("parent_node_id"):
        raise ValueError("declaration.parent_node_id: differs from selected occurrence's assembly")
    record.update(representation=REPRESENTATION, physical_type=REPRESENTATION,
                  target_node_id=target_node_id, geometry_source=source,
                  parent_node_id=nodes[target_node_id].get("parent_node_id"))
    records[identity] = record
    part = config.setdefault("parts", {}).setdefault(target_node_id, {})
    if "rigid_body" in part:
        if not convert_rigid:
            raise ValueError("selected target has rigid_body configuration; pass convert_rigid=True explicitly")
        del part["rigid_body"]
    part["physical_type"] = REPRESENTATION
    config["schema_version"] = JOINT_SCHEMA_VERSION if config.get("schema_version") == JOINT_SCHEMA_VERSION else AGENTIC_SCHEMA_VERSION
    return resolve_config(package, config)
