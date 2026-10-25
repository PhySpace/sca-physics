"""Strict native PhysX volume cable declarations, not rigid joint surrogates.

No material presets are injected. Material values are SI finite-element inputs;
the independent solver owns integration. Geometry is generated downstream from
the declared world-space centreline, not written into native SCA geometry.
"""

from copy import deepcopy
import math

from .contract import _closed, _object, _source, _generated_source, _float32, _records

MATERIAL = {"density": "kg/m^3", "youngs_modulus": "Pa", "poissons_ratio": "1",
            "dynamic_friction": "1", "elasticity_damping": "1/s"}
BODY = {"gravity_enabled": "boolean", "linear_damping": "1/s", "self_collision": "boolean",
        "solver_position_iterations": "count", "enable_speculative_ccd": "boolean",
        "sleep_threshold": "m/s", "settling_threshold": "m/s", "settling_damping": "1/s"}
COLLISION = {"enabled": "boolean", "contact_offset": "m", "rest_offset": "m", "attachment_filtering": "token"}


def _numbers(value, path, *, size=None):
    if not isinstance(value, (list, tuple)) or (size is not None and len(value) != size):
        raise ValueError(f"{path}: expected an array" + (f" of {size} numbers" if size else ""))
    for index, item in enumerate(value):
        _float32(item, f"{path}[{index}]")


def _parameter(raw, unit, path, *, resolve, source=None):
    if resolve:
        from .provenance import parameter
        obj = parameter(raw, unit, path, source)
    else:
        obj = _closed(raw, {"value", "unit", "source"}, path, required=True)
    if obj["unit"] != unit:
        raise ValueError(f"{path}.unit: expected {unit!r}")
    _source(obj["source"], f"{path}.source")
    value = obj["value"]
    if unit == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path}: expected a boolean")
    elif unit == "token":
        if not isinstance(value,str) or value not in {"whole_body","endpoint_elements"}:
            raise ValueError(f"{path}: expected whole_body or endpoint_elements token")
    elif unit == "count":
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{path}: expected a positive integer")
    elif path.endswith("centerline"):
        if not isinstance(value, list) or len(value) < 2:
            raise ValueError(f"{path}: expected at least two 3D world points")
        for index, point in enumerate(value):
            _numbers(point, f"{path}[{index}]", size=3)
        if any(math.dist(a, b) <= 1e-10 for a, b in zip(value, value[1:])):
            raise ValueError(f"{path}: adjacent points must differ")
    elif path.endswith("endpoint_tangents"):
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(f"{path}: expected start/end endpoint unit tangents")
        for index, tangent in enumerate(value):
            _numbers(tangent, f"{path}[{index}]", size=3)
            if not math.isclose(sum(x*x for x in tangent), 1, rel_tol=0, abs_tol=2e-6):
                raise ValueError(f"{path}[{index}]: expected a unit vector")
    elif path.endswith("position"):
        _numbers(value, path, size=3)
    elif path.endswith("quaternion_wxyz"):
        _numbers(value, path, size=4)
        if not math.isclose(sum(x*x for x in value), 1, rel_tol=0, abs_tol=2e-6):
            raise ValueError(f"{path}: expected a unit quaternion in wxyz order")
    else:
        _float32(value, path)
        if path.endswith(("length", "diameter", "density", "youngs_modulus", "contact_offset")):
            if value <= 0:
                raise ValueError(f"{path}: must be positive")
        elif path.endswith("poissons_ratio"):
            if not 0 <= value < .5 or not 0 <= _float32(value,path) < .5:
                raise ValueError(f"{path}: must be at least zero and strictly less than 0.5 for the target native PhysX schema")
        elif not path.endswith("rest_offset") and value < 0:
            raise ValueError(f"{path}: must be nonnegative")
    return deepcopy(dict(obj))


def _group(raw, fields, path, required, *, resolve, source=None):
    from .provenance import inherited
    obj = _closed(raw, set(fields) | ({'source'} if resolve else set()), path, required=set(fields) if required is True else required)
    context = inherited(obj, source, path + '.source')
    return {key: _parameter(value, fields[key], path + "." + key, resolve=resolve, source=context)
            for key, value in obj.items() if key != 'source'}


def cables(package, raw, *, resolve, schema_version="1.4"):
    """Resolve sparse input or strictly validate an independently read snapshot."""
    obj = _object(raw, "cables")
    nodes = _records(package.occurrence_graph.nodes, "node_id", "occurrence_graph.nodes")
    result, bound = {}, set()
    for identity, record in obj.items():
        path = f"cables.{identity}"
        record = _object(record, path)
        if not identity.strip():
            raise ValueError("cables: cable_id must be a nonempty string")
        if record.get("representation") == "rigid_joint_chain":
            from .rigid_chain import resolve_chain
            entry = resolve_chain(package, record, path, resolve=resolve, schema_version=schema_version)
            target = entry["target_node_id"]
            if target in bound:
                raise ValueError(f"{path}.target_node_id: duplicate declaration for {target!r}")
            bound.add(target)
            result[identity] = entry
            continue
        fields = {"parent_node_id", "representation", "geometry", "simulation_mesh", "material", "deformable", "collision", "attachments", "source"}
        required = fields - {"deformable"}
        cad_fields = {"target_node_id", "physical_type", "geometry_source"}
        if "target_node_id" in record:
            fields |= cad_fields
            required |= cad_fields
        item = _closed(record, fields, path, required=required)
        parent = item["parent_node_id"]
        if not isinstance(parent,str) or parent not in nodes or nodes[parent]["node_kind"] != "assembly":
            raise ValueError(f"{path}.parent_node_id: expected a real assembly occurrence node_id")
        if item["representation"] != "physx_deformable_volume":
            raise ValueError(f"{path}.representation: only physx_deformable_volume is implemented")
        entry = {"parent_node_id": parent, "representation": item["representation"],
                 "source": _source(item["source"], path + ".source")}
        is_cad = "target_node_id" in item
        if is_cad:
            from .deformable import geometry_source_snapshot
            target = item["target_node_id"]
            if target in bound:
                raise ValueError(f"{path}.target_node_id: duplicate declaration for {target!r}")
            expected_source = geometry_source_snapshot(package, target)
            if item["geometry_source"] != expected_source:
                raise ValueError(f"{path}.geometry_source: stale CAD geometry, unit or occurrence transform; regenerate the official mesh and dependent attachments/mappings")
            if item["physical_type"] != "deformable_volume":
                raise ValueError(f"{path}.physical_type: expected deformable_volume")
            # A cable belongs to the selected part's direct assembly occurrence.
            if nodes[target].get("parent_node_id") != parent:
                raise ValueError(f"{path}.parent_node_id: must be selected target's direct assembly parent")
            bound.add(target)
            entry.update(target_node_id=target, physical_type="deformable_volume", geometry_source=deepcopy(expected_source))
        geometry_fields = {"length": "m", "diameter": "m", "centerline": "m"}
        if is_cad:
            geometry_fields["endpoint_tangents"] = "1"
        entry["geometry"] = _group(item["geometry"], geometry_fields, path + ".geometry", {"length", "diameter", "centerline"}, resolve=resolve, source=entry['source'])
        geometry = entry["geometry"]
        length = sum(math.dist(a, b) for a, b in zip(geometry["centerline"]["value"], geometry["centerline"]["value"][1:]))
        if not math.isclose(length, geometry["length"]["value"], rel_tol=2e-6, abs_tol=1e-8):
            raise ValueError(f"{path}.geometry.length: must equal declared polyline arc length ({length} m)")
        from .official_mesh import METHOD, validate_generated
        mesh_raw = _object(item["simulation_mesh"], path + ".simulation_mesh")
        method = mesh_raw.get("method")
        if method not in {"swept_tetrahedra", METHOD}:
            raise ValueError(f"{path}.simulation_mesh.method: expected swept_tetrahedra or {METHOD}")
        if is_cad and method != METHOD:
            raise ValueError(f"{path}.simulation_mesh.method: CAD-bound targets require the official persisted volume mesh")
        mesh_fields = {"method", "axial_segments", "radial_segments"}
        if method == METHOD:
            mesh_fields |= {"filter_length", "generated"}
        if is_cad:
            mesh_fields |= {"generation_config", "cache_key"}
        from .provenance import inherited
        mesh = _closed(mesh_raw, mesh_fields | ({'source'} if resolve else set()), path + ".simulation_mesh", required=mesh_fields)
        mesh_source = inherited(mesh, entry['source'], path + '.simulation_mesh.source')
        entry["simulation_mesh"] = {"method": method, **_group({key: mesh[key] for key in ("axial_segments", "radial_segments")}, {"axial_segments": "count", "radial_segments": "count"}, path + ".simulation_mesh", True, resolve=resolve, source=mesh_source)}
        if entry["simulation_mesh"]["axial_segments"]["value"] > 4096 or not 3 <= entry["simulation_mesh"]["radial_segments"]["value"] <= 128:
            raise ValueError(f"{path}.simulation_mesh: require axial_segments <= 4096 and 3 <= radial_segments <= 128")
        if method == METHOD:
            entry["simulation_mesh"]["filter_length"] = _parameter(mesh["filter_length"], "m", path + ".simulation_mesh.filter_length", resolve=resolve, source=mesh_source)
            filter_length = entry["simulation_mesh"]["filter_length"]["value"]
            if not 0 < filter_length < length / 2:
                raise ValueError(f"{path}.simulation_mesh.filter_length: require a positive explicit physical length below half the cable length")
            entry["simulation_mesh"]["generated"] = validate_generated(mesh["generated"], geometry, path + ".simulation_mesh.generated", resolve=resolve,
                                                                      cad_source=expected_source if is_cad else None)
        if is_cad:
            from .deformable import _cache_value, mesh_cache_key
            import json
            generation_config = _object(mesh["generation_config"], path + ".simulation_mesh.generation_config")
            if _cache_value(generation_config.get("reference_geometry")) != _cache_value(geometry):
                raise ValueError(f"{path}.simulation_mesh.generation_config.reference_geometry: must preserve the current canonical measurement and endpoint-normal inputs; regenerate dependent selections/mappings after changes")
            try:
                json.dumps(generation_config, allow_nan=False)
            except (TypeError, ValueError):
                raise ValueError(f"{path}.simulation_mesh.generation_config: expected finite JSON configuration") from None
            entry["simulation_mesh"]["generation_config"] = deepcopy(dict(generation_config))
            entry["simulation_mesh"]["cache_key"] = mesh["cache_key"]
            expected_key = mesh_cache_key(expected_source, entry["simulation_mesh"])
            generated = entry["simulation_mesh"]["generated"]
            if mesh["cache_key"] != expected_key or generated.get("mesh_cache_key") != expected_key:
                raise ValueError(f"{path}.simulation_mesh.cache_key: stale geometry/configuration; regenerate mesh, attachment indices and centerline mapping together")
            for key in ("source_geometry_sha256", "mesh_sha256"):
                value = generated.get(key)
                if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                    raise ValueError(f"{path}.simulation_mesh.generated.{key}: expected a SHA256 digest")
        entry["material"] = _group(item["material"], MATERIAL, path + ".material", {"density", "youngs_modulus", "poissons_ratio"}, resolve=resolve, source=entry['source'])
        if "deformable" in item:
            entry["deformable"] = _group(item["deformable"], BODY, path + ".deformable", False, resolve=resolve, source=entry['source'])
            iterations = entry["deformable"].get("solver_position_iterations", {}).get("value", 1)
            if iterations > 255:
                raise ValueError(f"{path}.deformable.solver_position_iterations: must be <= 255")
        entry["collision"] = _group(item["collision"], COLLISION, path + ".collision", {"enabled", "contact_offset", "rest_offset"}, resolve=resolve, source=entry['source'])
        collision = entry["collision"]
        if collision.get("attachment_filtering",{}).get("value") == "endpoint_elements" and entry["simulation_mesh"]["axial_segments"]["value"] < 3:
            raise ValueError(f"{path}.simulation_mesh.axial_segments: endpoint_elements requires at least 3 segments to leave a colliding middle region")
        if _float32(collision["rest_offset"]["value"], path) >= _float32(collision["contact_offset"]["value"], path):
            raise ValueError(f"{path}.collision.rest_offset: must be less than contact_offset")
        attachments = item["attachments"]
        if not isinstance(attachments, list) or len(attachments) != 2:
            raise ValueError(f"{path}.attachments: expected start and end attachment records")
        entry["attachments"], ends = [], set()
        for index, attachment in enumerate(attachments):
            apath = f"{path}.attachments[{index}]"
            attached = _closed(attachment, {"endpoint", "rigid_node_id", "local_frame", "source"}, apath, required=True)
            endpoint, rigid_id = attached["endpoint"], attached["rigid_node_id"]
            if not isinstance(endpoint,str) or endpoint not in {"start", "end"} or endpoint in ends:
                raise ValueError(f"{apath}.endpoint: require unique start and end")
            ends.add(endpoint)
            if not isinstance(rigid_id,str) or rigid_id not in nodes or nodes[rigid_id]["node_kind"] != "part":
                raise ValueError(f"{apath}.rigid_node_id: expected a real rigid part occurrence node_id")
            frame = _group(attached["local_frame"], {"position": "m", "quaternion_wxyz": "1"}, apath + ".local_frame", True, resolve=resolve, source=attached['source'])
            entry["attachments"].append({"endpoint": endpoint, "rigid_node_id": rigid_id, "local_frame": frame,
                                         "source": _source(attached["source"], apath + ".source")})
        result[identity] = entry
    return result
