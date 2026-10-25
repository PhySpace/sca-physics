"""Sourced optional joint/actuator metadata; native CAD frames remain authoritative.

This module declares SI parameters, not a controller or a motor specification.
The companion exporter checks backend articulation topology and maps the one
available force drive channel, including passive and active damping.
"""

from copy import deepcopy
from .contract import _closed, _float32, _source

SCHEMA_VERSION = "1.8"
FIELDS = frozenset({"motion", "lower_limit", "upper_limit", "max_velocity", "friction", "drive"})
DRIVE_FIELDS = frozenset({"mode", "type", "target_position", "target_velocity", "stiffness", "damping", "max_force"})
TOKENS = {"motion": {"free", "limited"}, "mode": {"off", "position", "velocity"}, "type": {"force"}}


def units(kind):
    if kind not in {"revolute", "prismatic"}:
        raise ValueError("joint physics parameters require a native revolute or prismatic joint")
    angular = kind == "revolute"
    return {"motion": "token", "lower_limit": "rad" if angular else "m",
            "upper_limit": "rad" if angular else "m", "friction": "1",
            "max_velocity": "rad/s" if angular else "m/s", "mode": "token", "type": "token",
            "target_position": "rad" if angular else "m", "target_velocity": "rad/s" if angular else "m/s",
            "stiffness": "N*m/rad" if angular else "N/m", "damping": "N*m*s/rad" if angular else "N*s/m",
            "max_force": "N*m" if angular else "N"}


def parameter(raw, unit, field, path, *, resolve, source=None):
    if resolve:
        from .provenance import parameter as sourced_parameter
        raw = sourced_parameter(raw, unit, path, source)
    obj = _closed(raw, {"value", "unit", "source"}, path, required=True)
    if obj["unit"] != unit:
        raise ValueError(f"{path}.unit: expected {unit!r}")
    _source(obj["source"], path + ".source")
    value = obj["value"]
    if field in TOKENS:
        if not isinstance(value, str) or value not in TOKENS[field]:
            raise ValueError(f"{path}: expected one of {sorted(TOKENS[field])}")
    elif unit == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path}: expected a boolean")
    else:
        _float32(value, path)
        if field in {"stiffness", "damping", "max_velocity", "friction"} and value < 0:
            raise ValueError(f"{path}: must be nonnegative")
        if field == "max_force" and value <= 0:
            raise ValueError(f"{path}: must be positive")
    return deepcopy(dict(obj))


def joint_fields(raw, kind, path, *, resolve, source=None):
    """Resolve only explicitly supplied fields; never add optional defaults."""
    supplied = {key: value for key, value in raw.items() if key in FIELDS}
    if not supplied:
        return {}
    field_units = units(kind)
    result = {}
    for field, value in supplied.items():
        if field != "drive":
            result[field] = parameter(value, field_units[field], field, path + "." + field,
                                      resolve=resolve, source=source)
            continue
        from .provenance import inherited
        dpath = path + ".drive"
        drive = _closed(value, set(DRIVE_FIELDS) | ({"source"} if resolve else set()), dpath,
                        required=set(DRIVE_FIELDS))
        context = inherited(drive, source, dpath + ".source")
        result["drive"] = {key: parameter(drive[key], field_units[key], key, dpath + "." + key,
                                          resolve=resolve, source=context) for key in sorted(DRIVE_FIELDS)}
        values = {key: wrapper["value"] for key, wrapper in result["drive"].items()}
        if values["mode"] == "position" and values["stiffness"] <= 0:
            raise ValueError(dpath + ".stiffness: position mode requires positive stiffness")
        if values["mode"] == "velocity":
            if values["stiffness"] != 0:
                raise ValueError(dpath + ".stiffness: velocity mode requires zero stiffness")
            if values["damping"] <= 0:
                raise ValueError(dpath + ".damping: velocity mode requires positive damping")
    motion = result.get("motion", {}).get("value")
    limits = {key for key in ("lower_limit", "upper_limit") if key in result}
    if motion == "limited":
        if len(limits) != 2:
            raise ValueError(path + ": limited motion requires lower_limit and upper_limit")
        lower, upper = (result[key]["value"] for key in ("lower_limit", "upper_limit"))
        if lower >= upper or _float32(lower, path) >= _float32(upper, path):
            raise ValueError(path + ": lower_limit must be less than upper_limit after USD float32 conversion")
        drive = result.get("drive", {})
        if drive.get("mode", {}).get("value") == "position" and not lower <= drive["target_position"]["value"] <= upper:
            raise ValueError(path + ".drive.target_position: outside declared joint limits")
    elif limits:
        raise ValueError(path + ": lower_limit/upper_limit require explicit limited motion")
    return result


def articulation(package, raw, *, resolve, source=None):
    """Bind a requested articulation root to a stable package occurrence ID.

    This is identity validation only. Fixed-group reduction, connectivity, tree
    ownership and backend DOF support are checked by the companion exporter.
    """
    path = "assembly.articulation"
    fields = {"enabled", "root_node_id", "fixed_base"}
    obj = _closed(raw, fields | {"self_collisions"} | ({"source"} if resolve else set()), path, required=fields)
    from .provenance import inherited
    context = inherited(obj, source, path + ".source")
    root = obj["root_node_id"]
    from .contract import inventory
    actual = inventory(package)
    if not isinstance(root, str) or root not in {actual["root_node_id"], *actual["parts"]}:
        raise ValueError(path + ".root_node_id: expected the package root or an existing part occurrence node_id")
    return {"root_node_id": root, **{key: parameter(obj[key], "boolean", key, path + "." + key,
            resolve=resolve, source=context) for key in ("enabled", "fixed_base", "self_collisions") if key in obj}}


def has_new_fields(config):
    joints = config.get("joints", {})
    assembly = config.get("assembly", {})
    return ("couplings" in config or isinstance(joints, dict) and any(isinstance(j, dict) and FIELDS & j.keys() for j in joints.values())
            or isinstance(assembly, dict) and "articulation" in assembly)
