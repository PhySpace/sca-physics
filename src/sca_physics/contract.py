"""Versioned, occurrence-bound physics metadata independent of SCA internals.

Only ``resolve_config`` supplies defaults. ``validate_config`` checks the complete
persisted snapshot, so damaged or incomplete metadata cannot silently be repaired
by an exporter. Values use SI units; geometry retains the native SCA coordinates.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import math
import struct
from typing import Any

SCHEMA_VERSION = "1.0"
MECHANICAL_SCHEMA_VERSION = "1.1"
CABLE_SCHEMA_VERSION = "1.2"
CAD_SCHEMA_VERSION = "1.3"
RIGID_CHAIN_SCHEMA_VERSION = "1.4"
HIGH_FREQUENCY_SCHEMA_VERSION = "1.5"
RESOLVED_CABLE_SCHEMA_VERSION = "1.6"
AGENTIC_SCHEMA_VERSION = "1.7"
JOINT_SCHEMA_VERSION = "1.8"
SOURCED_SCHEMA_VERSIONS = frozenset({AGENTIC_SCHEMA_VERSION, JOINT_SCHEMA_VERSION})
RIGID_CHAIN_SCHEMA_VERSIONS = frozenset({RIGID_CHAIN_SCHEMA_VERSION, HIGH_FREQUENCY_SCHEMA_VERSION, RESOLVED_CABLE_SCHEMA_VERSION}) | SOURCED_SCHEMA_VERSIONS
CAD_BOUND_SCHEMA_VERSIONS = frozenset({CAD_SCHEMA_VERSION}) | RIGID_CHAIN_SCHEMA_VERSIONS
CABLE_SCHEMA_VERSIONS = frozenset({CABLE_SCHEMA_VERSION}) | CAD_BOUND_SCHEMA_VERSIONS
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION, MECHANICAL_SCHEMA_VERSION}) | CABLE_SCHEMA_VERSIONS
DEMO_PROFILE = "demo-v1"
SOURCE_KINDS = frozenset({"explicit", "reference", "estimated", "default"})
# These are OpenUSD mesh collision tokens supported by the companion exporter.
COLLISION_APPROXIMATIONS = frozenset(
    {"none", "convexHull", "convexDecomposition", "boundingCube", "boundingSphere"}
)
BODY_MODES = frozenset({"static", "dynamic", "kinematic"})
COMBINE_MODES = frozenset({"average", "min", "multiply", "max"})
MECHANICAL_FIELDS = {
    "rigid_body": {"mode": "token", "gravity_enabled": "boolean", "linear_damping": "1/s", "angular_damping": "1/s"},
    "collision": {"contact_offset": "m", "rest_offset": "m"},
    "contact": {"friction_combine_mode": "token", "restitution_combine_mode": "token"},
}
DEFAULTS = {
    "scene": {"up_axis": "+Z"},
    "contact": {"static_friction": 0.5, "dynamic_friction": 0.4, "restitution": 0.1},
    "collision": {
        "enabled": True,
        "approximation_dynamic": "convexHull",
        "approximation_static": "none",
    },
    "joint": {"damping": 0.0, "collision_enabled": False},
    "collision_exclusions": [],
}
_MISSING = object()


def _decision(raw):
    obj = _closed(raw, {'purpose', 'representation', 'rationale', 'assumptions', 'limitations', 'bindings'}, 'decision',
                  required={'purpose', 'representation', 'rationale'})
    for key in ('purpose', 'representation', 'rationale'):
        if not isinstance(obj[key], str) or not obj[key].strip():
            raise ValueError('decision.' + key + ': require nonempty text')
    for key in ('assumptions', 'limitations'):
        if key in obj and (not isinstance(obj[key], list) or not all(isinstance(x, str) and x.strip() for x in obj[key])):
            raise ValueError('decision.' + key + ': require a text list')
    if 'bindings' in obj:
        if not isinstance(obj['bindings'], list):
            raise ValueError('decision.bindings: require an array')
        for index, binding in enumerate(obj['bindings']):
            binding = _closed(binding, {'field','material_id','basis'}, f'decision.bindings[{index}]', required=True)
            if any(not isinstance(value,str) or not value.strip() for value in binding.values()):
                raise ValueError('decision.bindings: require nonempty field/material_id/basis')
    return deepcopy(dict(obj))


def _validate_decision_bindings(config):
    for index, binding in enumerate(config.get('decision',{}).get('bindings',[])):
        field=binding['field']
        keys=[key.replace('~1','/').replace('~0','~') for key in field[1:].split('/')] if field.startswith('/') else field.split('.')
        value=config
        try:
            for key in keys:
                value=value[key]
        except (KeyError,TypeError):
            raise ValueError(f'decision.bindings[{index}].field: no saved parameter at {field!r}') from None
        if not isinstance(value,Mapping) or not {'value','unit','source'} <= value.keys():
            raise ValueError(f'decision.bindings[{index}].field: require an actual parameter wrapper')


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise ValueError(f"{path}: expected an object with string keys")
    return value


def _closed(value: Any, allowed: set[str], path: str, *, required: bool | set[str] = False) -> Mapping[str, Any]:
    obj = _object(value, path)
    extra = set(obj) - allowed
    required_fields = allowed if required is True else required if isinstance(required, set) else set()
    missing = required_fields - set(obj)
    if extra:
        raise ValueError(f"{path}: unknown fields {sorted(extra)}")
    if missing:
        raise ValueError(f"{path}: missing fields {sorted(missing)}")
    return obj


def _records(raw: Any, key: str, path: str) -> dict[str, Mapping[str, Any]]:
    records = raw.values() if isinstance(raw, Mapping) else raw
    result = {}
    for record in records:
        obj = _object(record, path)
        identity = obj.get(key)
        if not isinstance(identity, str) or not identity:
            raise ValueError(f"{path}: missing {key}")
        if identity in result:
            raise ValueError(f"{path}: duplicate {key} {identity!r}")
        result[identity] = obj
    return result


def inventory(package: Any) -> dict[str, Any]:
    """Return package IDs suitable for config generation; never bind by names."""
    graph = package.occurrence_graph
    nodes = _records(graph.nodes, "node_id", "occurrence_graph.nodes")
    joints = _records(graph.joints, "joint_id", "occurrence_graph.joints")
    parts = {
        identity: {
            "definition_id": node["definition_id"],
            "display_name": node.get("display_name"),
            "node_kind": "part",
        }
        for identity, node in sorted(nodes.items())
        if node["node_kind"] == "part"
    }
    return {
        "root_definition_id": getattr(graph, "root_definition_id", None),
        "root_node_id": getattr(graph, "root_node_id", None),
        "parts": parts,
        "joints": {
            identity: {
                "joint_type": joint["joint_type"],
                "connector_a": deepcopy(dict(joint.get("connector_a", {}))),
                "connector_b": deepcopy(dict(joint.get("connector_b", {}))),
            }
            for identity, joint in sorted(joints.items())
        },
    }


def _source(value: Any, path: str) -> dict[str, Any]:
    from .provenance import source
    return source(dict(_object(value, path)), path)


def _generated_source(kind: str, path: str) -> dict[str, str]:
    if kind == "default":
        return {
            "kind": "default",
            "detail": f"{DEMO_PROFILE}: demonstration default for {path}; not a measurement",
        }
    return {"kind": "explicit", "detail": f"Explicit configuration input for {path}"}


def _check_value(value: Any, unit: str, path: str) -> None:
    if unit == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path}: expected a boolean")
    elif unit == "axis":
        if value not in ("+Y", "+Z"):
            raise ValueError(f"{path}: only +Y and +Z are supported by the USD exporter")
    elif unit == "token":
        if not isinstance(value, str) or value not in COLLISION_APPROXIMATIONS:
            raise ValueError(f"{path}: unsupported collision approximation {value!r}")
    else:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path}: expected a finite number, not a boolean")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError(f"{path}: expected a finite number")
        if value < 0:
            raise ValueError(f"{path}: must be nonnegative")
        if path.endswith("restitution") and value > 1:
            raise ValueError(f"{path}: restitution must be in [0, 1]")
        if unit == "unsupported" and value != 0:
            raise ValueError(f"{path}: nonzero damping is unsupported for this joint type")


def _parameter(raw: Any, default: Any, unit: str, path: str, source=None) -> dict[str, Any]:
    if raw is _MISSING:
        obj = {"value": deepcopy(default), "unit": unit, "source": _generated_source("default", path)}
    else:
        from .provenance import parameter
        obj = parameter(raw, unit, path, source)
    _validate_parameter(obj, unit, path)
    return obj


def _validate_parameter(raw: Any, unit: str, path: str) -> None:
    obj = _closed(raw, {"value", "unit", "source"}, path, required=True)
    if obj["unit"] != unit:
        raise ValueError(f"{path}.unit: expected {unit!r}, got {obj['unit']!r}")
    _check_value(obj["value"], unit, path)
    _source(obj["source"], f"{path}.source")


def _float32(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path}: expected a finite number, not a boolean")
    try:
        encoded = struct.unpack("f", struct.pack("f", value))[0]
    except (OverflowError, struct.error):
        raise ValueError(f"{path}: must fit a finite USD float32") from None
    if not math.isfinite(encoded) or (value != 0 and encoded == 0):
        raise ValueError(f"{path}: must fit a finite USD float32 without underflow to zero")
    return encoded


def _validate_mechanical_parameter(raw: Any, group: str, field: str, path: str) -> None:
    unit = MECHANICAL_FIELDS[group][field]
    obj = _object(raw, path)
    if "mode" in obj:
        obj = _closed(obj, {"mode", "unit", "source"}, path, required=True)
        if group == "rigid_body" and field == "mode":
            raise ValueError(f"{path}: body mode does not support engine_default; omit it for native inference")
        if obj["mode"] != "engine_default":
            raise ValueError(f"{path}.mode: expected 'engine_default'")
    else:
        obj = _closed(obj, {"value", "unit", "source"}, path, required=True)
        value = obj["value"]
        if field == "mode":
            if not isinstance(value, str) or value not in BODY_MODES:
                raise ValueError(f"{path}: expected static, dynamic or kinematic")
        elif field == "gravity_enabled":
            if not isinstance(value, bool):
                raise ValueError(f"{path}: expected a boolean")
        elif field.endswith("combine_mode"):
            if not isinstance(value, str) or value not in COMBINE_MODES:
                raise ValueError(f"{path}: expected one of {sorted(COMBINE_MODES)}")
        else:
            _float32(value, path)
            if field == "contact_offset" and value <= 0:
                raise ValueError(f"{path}: must be positive")
            if field.endswith("damping") and value < 0:
                raise ValueError(f"{path}: must be nonnegative")
    if obj["unit"] != unit:
        raise ValueError(f"{path}.unit: expected {unit!r}, got {obj['unit']!r}")
    _source(obj["source"], f"{path}.source")


def _mechanical_parameter(raw: Any, group: str, field: str, path: str, source=None) -> dict[str, Any]:
    unit = MECHANICAL_FIELDS[group][field]
    if isinstance(raw, Mapping):
        if "mode" in raw:
            wrapped = _closed(raw, {"mode", "unit", "source"}, path)
            obj = {"mode": wrapped["mode"], "unit": wrapped.get("unit", unit),
                   "source": _source(wrapped.get("source", source), path + '.source')}
        else:
            wrapped = _closed(raw, {"value", "unit", "source"}, path)
            if "value" not in wrapped:
                raise ValueError(f"{path}: parameter wrapper requires value")
            obj = {"value": deepcopy(wrapped["value"]), "unit": wrapped.get("unit", unit),
                   "source": _source(wrapped.get("source", source), path + '.source')}
    else:
        obj = {"value": deepcopy(raw), "unit": unit, "source": _source(source, path + '.source')}
    _validate_mechanical_parameter(obj, group, field, path)
    return obj


def _mechanical_paths(obj: Mapping[str, Any]) -> list[str]:
    parts = obj.get("parts", {})
    if not isinstance(parts, Mapping):
        return []
    paths = []
    for identity, part in parts.items():
        if not isinstance(part, Mapping):
            continue
        if "rigid_body" in part:
            paths.append(f"parts.{identity}.rigid_body")
        for group in ("contact", "collision"):
            values = part.get(group, {})
            if isinstance(values, Mapping):
                paths.extend(f"parts.{identity}.{group}.{field}" for field in MECHANICAL_FIELDS[group] if field in values)
    return paths


def _schema_version(obj: Mapping[str, Any], *, resolve: bool) -> str:
    from .joint_physics import has_new_fields
    joint_physics = has_new_fields(obj)
    paths = _mechanical_paths(obj)
    cad = any(isinstance(c, Mapping) and "target_node_id" in c for c in obj.get("cables", {}).values()) if isinstance(obj.get("cables", {}), Mapping) else False
    chains = any(isinstance(c, Mapping) and c.get("representation") == "rigid_joint_chain" for c in obj.get("cables", {}).values()) if isinstance(obj.get("cables", {}), Mapping) else False
    if chains:
        from .rigid_chain import schema_for_chains
        inferred = schema_for_chains(obj["cables"])
    else:
        inferred = CAD_SCHEMA_VERSION if cad else CABLE_SCHEMA_VERSION if "cables" in obj else MECHANICAL_SCHEMA_VERSION if paths else SCHEMA_VERSION
    version = obj.get("schema_version", JOINT_SCHEMA_VERSION if joint_physics else AGENTIC_SCHEMA_VERSION) if resolve else obj["schema_version"]
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError("sca_physics.schema_version: unsupported version")
    if joint_physics and version != JOINT_SCHEMA_VERSION:
        raise ValueError("sca_physics.schema_version: joint physics, articulation and coupling fields require schema 1.8")
    if version == SCHEMA_VERSION and paths:
        raise ValueError(f"sca_physics.schema_version: 1.0 does not allow mechanical fields {paths}")
    if version not in CABLE_SCHEMA_VERSIONS and "cables" in obj:
        raise ValueError(f"sca_physics.schema_version: {version} does not allow cables")
    if cad and version not in CAD_BOUND_SCHEMA_VERSIONS:
        raise ValueError("sca_physics.schema_version: CAD occurrence deformables require 1.3")
    if chains and version not in RIGID_CHAIN_SCHEMA_VERSIONS:
        raise ValueError("sca_physics.schema_version: rigid_joint_chain requires 1.4, 1.5, 1.6, 1.7 or 1.8")
    return version


def _validate_offsets(part: Mapping[str, Any], path: str) -> None:
    collision = part["collision"]
    rest = collision.get("rest_offset")
    contact = collision.get("contact_offset")
    rest_value = rest["value"] if rest is not None and "value" in rest else None
    contact_value = contact["value"] if contact is not None and "value" in contact else None
    if rest_value is not None and rest_value > 0 and contact_value is None:
        raise ValueError(f"{path}.collision.rest_offset: positive rest offset requires explicit positive contact_offset")
    if rest_value is not None and contact_value is not None:
        if rest_value >= contact_value or _float32(rest_value, path) >= _float32(contact_value, path):
            raise ValueError(f"{path}.collision.rest_offset: must be less than contact_offset after USD float32 conversion")


def _damping_unit(joint_type: str) -> str:
    return {"revolute": "N*m*s/rad", "prismatic": "N*s/m"}.get(joint_type, "unsupported")


def _input_references(raw: Any, actual: Mapping[str, Any], path: str, *, complete: bool = False) -> Mapping[str, Any]:
    obj = _object(raw, path)
    extra = set(obj) - set(actual)
    missing = set(actual) - set(obj) if complete else set()
    if extra:
        raise ValueError(f"{path}: unknown package references {sorted(extra)}")
    if missing:
        raise ValueError(f"{path}: missing package references {sorted(missing)}")
    return obj


def _exclusions(raw: Any, parts: Mapping[str, Any], *, resolve: bool, source=None) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("assembly.collision_exclusions: expected an array")
    result = []
    seen = set()
    for index, record in enumerate(raw):
        path = f"assembly.collision_exclusions[{index}]"
        obj = _closed(record, {"a", "b", "source"}, path, required=not resolve)
        for side in ("a", "b"):
            if not isinstance(obj.get(side), str) or obj[side] not in parts:
                raise ValueError(f"{path}.{side}: expected an existing part occurrence node_id")
        if obj["a"] == obj["b"]:
            raise ValueError(f"{path}: a collision exclusion cannot reference itself")
        pair = tuple(sorted((obj["a"], obj["b"])))
        if pair in seen:
            raise ValueError(f"{path}: duplicate collision exclusion pair")
        seen.add(pair)
        adopted = obj.get("source", source)
        result.append({"a": obj["a"], "b": obj["b"], "source": _source(adopted, f"{path}.source")})
    return result


def resolve_config(package: Any, input_dict: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate user inputs and freeze all adopted values, units and provenance."""
    supplied = {} if input_dict is None else input_dict
    obj = _closed(supplied, {"schema_version", "default_profile", "scene", "parts", "joints", "assembly", "cables", "couplings", "source", "decision"}, "sca_physics")
    from .provenance import inherited
    root_source = inherited(obj, path='sca_physics.source')
    version = _schema_version(obj, resolve=True)
    if obj.get("default_profile", DEMO_PROFILE) != DEMO_PROFILE:
        raise ValueError("sca_physics.default_profile: unsupported default profile")
    actual = inventory(package)
    scene = _closed(obj.get("scene", {}), {"up_axis", "source"}, "scene")
    result = {
        "schema_version": version,
        "default_profile": DEMO_PROFILE,
        "scene": {"up_axis": _parameter(scene.get("up_axis", _MISSING), DEFAULTS["scene"]["up_axis"], "axis", "scene.up_axis", inherited(scene, root_source, 'scene.source'))},
        "parts": {},
        "joints": {},
        "assembly": {},
    }
    supplied_parts = _input_references(obj.get("parts", {}), actual["parts"], "parts")
    for identity, native in actual["parts"].items():
        path = f"parts.{identity}"
        allowed = {"definition_id", "contact", "collision", "source"} | ({"rigid_body"} if version != SCHEMA_VERSION else set()) | ({"physical_type"} if version in CAD_BOUND_SCHEMA_VERSIONS else set())
        part = _closed(supplied_parts.get(identity, {}), allowed, path)
        part_source = inherited(part, root_source, path + '.source')
        if part.get("definition_id", native["definition_id"]) != native["definition_id"]:
            raise ValueError(f"{path}.definition_id: does not match package occurrence")
        resolved = {"definition_id": native["definition_id"], "contact": {}, "collision": {}}
        if "physical_type" in part:
            choices = {"deformable_volume", "rigid_joint_chain"} if version in RIGID_CHAIN_SCHEMA_VERSIONS else {"deformable_volume"}
            if part["physical_type"] not in choices:
                raise ValueError(f"{path}.physical_type: unsupported physical representation")
            resolved["physical_type"] = part["physical_type"]
        for group in ("contact", "collision"):
            optional = set(MECHANICAL_FIELDS[group]) if version != SCHEMA_VERSION else set()
            values = _closed(part.get(group, {}), set(DEFAULTS[group]) | optional | {'source'}, f"{path}.{group}")
            group_source = inherited(values, part_source, path + '.' + group + '.source')
            for field, default in DEFAULTS[group].items():
                unit = "1" if group == "contact" else "boolean" if field == "enabled" else "token"
                resolved[group][field] = _parameter(values.get(field, _MISSING), default, unit, f"{path}.{group}.{field}", group_source)
            for field in MECHANICAL_FIELDS[group]:
                if field in values:
                    resolved[group][field] = _mechanical_parameter(values[field], group, field, f"{path}.{group}.{field}", group_source)
        if "rigid_body" in part:
            values = _closed(part["rigid_body"], set(MECHANICAL_FIELDS["rigid_body"]) | {'source'}, f"{path}.rigid_body")
            group_source = inherited(values, part_source, path + '.rigid_body.source')
            resolved["rigid_body"] = {field: _mechanical_parameter(value, "rigid_body", field, f"{path}.rigid_body.{field}", group_source)
                                      for field, value in values.items() if field != 'source'}
        _validate_offsets(resolved, path)
        result["parts"][identity] = resolved
    supplied_joints = _input_references(obj.get("joints", {}), actual["joints"], "joints")
    from .joint_physics import FIELDS as JOINT_FIELDS, joint_fields, articulation
    for identity, native in actual["joints"].items():
        path = f"joints.{identity}"
        joint = _closed(supplied_joints.get(identity, {}), {"joint_type", "damping", "collision_enabled", "source"} | (set(JOINT_FIELDS) if version == JOINT_SCHEMA_VERSION else set()), path)
        joint_source = inherited(joint, root_source, path + '.source')
        kind = native["joint_type"]
        if joint.get("joint_type", kind) != kind:
            raise ValueError(f"{path}.joint_type: does not match package joint")
        result["joints"][identity] = {
            "joint_type": kind,
            "damping": _parameter(joint.get("damping", _MISSING), DEFAULTS["joint"]["damping"], _damping_unit(kind), f"{path}.damping", joint_source),
            "collision_enabled": _parameter(joint.get("collision_enabled", _MISSING), DEFAULTS["joint"]["collision_enabled"], "boolean", f"{path}.collision_enabled", joint_source),
        }
        result["joints"][identity].update(joint_fields(joint, kind, path, resolve=True, source=joint_source))
    assembly = _closed(obj.get("assembly", {}), {"collision_exclusions", "source"} | ({"articulation"} if version == JOINT_SCHEMA_VERSION else set()), "assembly")
    result["assembly"]["collision_exclusions"] = _exclusions(assembly.get("collision_exclusions", []), actual["parts"], resolve=True, source=inherited(assembly, root_source, 'assembly.source'))
    if "articulation" in assembly:
        result["assembly"]["articulation"] = articulation(package, assembly["articulation"], resolve=True, source=inherited(assembly, root_source, 'assembly.source'))
    if "couplings" in obj:
        from .couplings import couplings
        result["couplings"] = couplings(obj["couplings"], result, resolve=True, source=root_source)
    if 'decision' in obj:
        result['decision'] = _decision(obj['decision'])
    if version in CABLE_SCHEMA_VERSIONS:
        from .cable_contract import cables
        cable_inputs = deepcopy(obj.get('cables', {}))
        for record in cable_inputs.values():
            if 'source' not in record and root_source is not None:
                record['source'] = deepcopy(root_source)
        result["cables"] = cables(package, cable_inputs, resolve=True, schema_version=version)
    validate_config(package, result)
    from .provenance import protect_explicit
    root = getattr(package, 'root_definition', None)
    protect_explicit(getattr(root, 'metadata', {}).get('sca_physics'), result)
    return result


def template_config(package: Any, *, include_mechanical: bool = False) -> dict[str, Any]:
    """Keep the legacy template by default; opt in to explicit engine deferral."""
    if not include_mechanical:
        return resolve_config(package, {'schema_version': SCHEMA_VERSION})
    supplied = {"schema_version": MECHANICAL_SCHEMA_VERSION, "parts": {}}
    for identity in inventory(package)["parts"]:
        part = {}
        for group, fields in MECHANICAL_FIELDS.items():
            part[group] = {field: {"mode": "engine_default", "unit": unit,
                                  "source": {"kind": "default", "detail": f"Mechanical template defers {identity}.{group}.{field} to the engine; no numeric value or USD opinion is supplied"}}
                           for field, unit in fields.items() if not (group == "rigid_body" and field == "mode")}
        supplied["parts"][identity] = part
    return resolve_config(package, supplied)


def validate_config(package: Any, config: Any) -> None:
    """Check persisted metadata strictly, including IDs and completeness.

    This function never fills missing fields or changes the caller's object.
    Unsupported nonzero damping is rejected rather than silently ignored.
    """
    required_top = {"schema_version", "default_profile", "scene", "parts", "joints", "assembly"}
    obj = _closed(config, required_top | {"cables", "couplings", "decision"}, "sca_physics", required=required_top)
    version = _schema_version(obj, resolve=False)
    from .provenance import validate_tree
    validate_tree(obj, legacy=version not in SOURCED_SCHEMA_VERSIONS)
    if 'decision' in obj:
        if version not in SOURCED_SCHEMA_VERSIONS:
            raise ValueError('decision requires schema 1.7 or 1.8')
        _decision(obj['decision'])
        _validate_decision_bindings(obj)
    if obj["default_profile"] != DEMO_PROFILE:
        raise ValueError("sca_physics.default_profile: unsupported default profile")
    actual = inventory(package)
    scene = _closed(obj["scene"], {"up_axis"}, "scene", required=True)
    _validate_parameter(scene["up_axis"], "axis", "scene.up_axis")
    parts = _input_references(obj["parts"], actual["parts"], "parts", complete=True)
    for identity, native in actual["parts"].items():
        path = f"parts.{identity}"
        required = {"definition_id", "contact", "collision"}
        part = _closed(parts[identity], required | ({"rigid_body"} if version != SCHEMA_VERSION else set()) | ({"physical_type"} if version in CAD_BOUND_SCHEMA_VERSIONS else set()), path, required=required)
        if part["definition_id"] != native["definition_id"]:
            raise ValueError(f"{path}.definition_id: does not match package occurrence")
        if "physical_type" in part:
            choices = {"deformable_volume", "rigid_joint_chain"} if version in RIGID_CHAIN_SCHEMA_VERSIONS else {"deformable_volume"}
            if part["physical_type"] not in choices:
                raise ValueError(f"{path}.physical_type: unsupported physical representation")
        for group in ("contact", "collision"):
            optional = set(MECHANICAL_FIELDS[group]) if version != SCHEMA_VERSION else set()
            values = _closed(part[group], set(DEFAULTS[group]) | optional, f"{path}.{group}", required=set(DEFAULTS[group]))
            for field in DEFAULTS[group]:
                unit = "1" if group == "contact" else "boolean" if field == "enabled" else "token"
                _validate_parameter(values[field], unit, f"{path}.{group}.{field}")
            for field in MECHANICAL_FIELDS[group]:
                if field in values:
                    _validate_mechanical_parameter(values[field], group, field, f"{path}.{group}.{field}")
        if "rigid_body" in part:
            values = _closed(part["rigid_body"], set(MECHANICAL_FIELDS["rigid_body"]), f"{path}.rigid_body")
            for field, value in values.items():
                _validate_mechanical_parameter(value, "rigid_body", field, f"{path}.rigid_body.{field}")
        _validate_offsets(part, path)
    joints = _input_references(obj["joints"], actual["joints"], "joints", complete=True)
    from .joint_physics import FIELDS as JOINT_FIELDS, joint_fields, articulation
    for identity, native in actual["joints"].items():
        path = f"joints.{identity}"
        required = {"joint_type", "damping", "collision_enabled"}
        joint = _closed(joints[identity], required | (set(JOINT_FIELDS) if version == JOINT_SCHEMA_VERSION else set()), path, required=required)
        if joint["joint_type"] != native["joint_type"]:
            raise ValueError(f"{path}.joint_type: does not match package joint")
        _validate_parameter(joint["damping"], _damping_unit(native["joint_type"]), f"{path}.damping")
        _validate_parameter(joint["collision_enabled"], "boolean", f"{path}.collision_enabled")
        joint_fields(joint, native["joint_type"], path, resolve=False)
    assembly = _closed(obj["assembly"], {"collision_exclusions"} | ({"articulation"} if version == JOINT_SCHEMA_VERSION else set()), "assembly", required={"collision_exclusions"})
    _exclusions(assembly["collision_exclusions"], actual["parts"], resolve=False)
    if "articulation" in assembly:
        articulation(package, assembly["articulation"], resolve=False)
    if "couplings" in obj:
        from .couplings import couplings
        couplings(obj["couplings"], obj, resolve=False)
    if version in CABLE_SCHEMA_VERSIONS:
        from .cable_contract import cables
        if "cables" not in obj:
            raise ValueError("sca_physics.cables: missing required volume declaration field")
        cables(package, obj["cables"], resolve=False, schema_version=version)
    if version in CAD_BOUND_SCHEMA_VERSIONS:
        from .deformable import validate_cad_bindings
        validate_cad_bindings(package, obj)
    if version in RIGID_CHAIN_SCHEMA_VERSIONS:
        from .rigid_chain import validate_chain_bindings
        validate_chain_bindings(package, obj)
