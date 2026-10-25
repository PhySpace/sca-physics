"""Occurrence selection and repeatable post-model volume-deformable updates.

This module changes only addon metadata. It never edits CAD, cooks a mesh, or
integrates motion. The companion exporter verifies the actual CAD surface.
"""

from copy import deepcopy
import hashlib
import json
import math

from .contract import _closed, _object, _records

CAD_SCHEMA_VERSION = "1.3"


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _definitions(root):
    found = {root.definition_id: root}
    for child in getattr(root, "resolved_definitions", {}).values():
        for key, value in _definitions(child).items():
            if key in found and found[key].content_hash != value.content_hash:
                raise ValueError(f"ambiguous CAD definition_id {key!r}")
            found[key] = value
    return found


def geometry_source_snapshot(package, target_node_id):
    """Freeze BREP identity and the selected occurrence's actual SI transform.

    The official SCA placement decoder handles its canonical integer encoding.
    Shared definitions stay shared: the identity here is always an occurrence.
    """
    nodes = _records(package.occurrence_graph.nodes, "node_id", "occurrence_graph.nodes")
    if not isinstance(target_node_id, str) or target_node_id not in nodes:
        raise ValueError(f"target_node_id: unknown CAD occurrence {target_node_id!r}; select an exact node_id, not a name or definition_id")
    node = nodes[target_node_id]
    if node.get("node_kind") != "part":
        raise ValueError("target_node_id: expected an existing CAD part occurrence")
    definition = _definitions(package.root_definition).get(node["definition_id"])
    if definition is None:
        raise ValueError("geometry_source: target definition is not in the package closure")
    ref = getattr(definition, "solid_cache_ref", None)
    if ref is None or ref.path not in definition.blobs:
        raise ValueError("geometry_source: target has no evaluated BREP; capture the model first")
    native_unit = getattr(definition, "units", None)
    if native_unit != "mm":
        raise ValueError(f"geometry_source: unsupported native length unit {native_unit!r}; current SCA export contract requires mm")
    brep = hashlib.sha256(bytes(definition.blobs[ref.path])).hexdigest()
    if str(ref.sha256).removeprefix("sha256:") != brep:
        raise ValueError("geometry_source: evaluated BREP digest mismatch")
    chain, seen = [], set()
    current = target_node_id
    while current is not None:
        if current in seen or current not in nodes:
            raise ValueError("geometry_source: cyclic or incomplete occurrence parent chain")
        seen.add(current)
        record = nodes[current]
        chain.append(record)
        current = record.get("parent_node_id")
    from simplecadapi.product.placement import placement_from_canonical
    world = [[1., 0., 0., 0.], [0., 1., 0., 0.], [0., 0., 1., 0.], [0., 0., 0., 1.]]
    for record in reversed(chain):
        canonical = record.get("transform")
        if canonical is None:
            raise ValueError(f"geometry_source: missing transform on {record['node_id']}")
        placement = placement_from_canonical(canonical)
        axes = [placement.x_axis, placement.y_axis, placement.z_axis]
        local = [[float(axes[j][i]) for j in range(3)] + [float(placement.origin[i]) * .001] for i in range(3)]
        local.append([0., 0., 0., 1.])
        world = [[sum(world[i][k] * local[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
    if not all(math.isfinite(x) for row in world for x in row):
        raise ValueError("geometry_source: non-finite world transform")
    semantic_definition = deepcopy(definition.to_dict())
    semantic_definition.pop("content_hash", None)
    semantic_definition.get("metadata", {}).pop("sca_physics", None)
    return {"kind": "cad_occurrence", "target_node_id": target_node_id,
            "definition_id": definition.definition_id, "definition_content_hash": "sha256:" + _sha(semantic_definition),
            "brep_sha256": brep, "native_length_unit": native_unit, "mesh_length_unit": "m",
            "world_transform_m": world, "world_transform_sha256": _sha(world)}


def _cache_value(value):
    if isinstance(value, dict):
        if set(value) <= {"value", "unit", "source"} and "value" in value:
            # Units of the contract's wrapped fields are fixed and validated.
            # Sparse input and its resolved snapshot must have the same key.
            return _cache_value(value["value"])
        return {key: _cache_value(item) for key, item in value.items() if key != "source"}
    if isinstance(value, (tuple, list)):
        return [_cache_value(item) for item in value]
    # The official SCA canonical JSON archive writes integral floats as ints.
    # These have identical units/physical values and must not invalidate a mesh
    # merely because the complete product package was saved and reopened.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def mesh_cache_key(geometry_source, simulation_mesh):
    """Material-independent key; every geometric/configuration input matters.

    Generated topology and its dependent node selections/embeddings are one
    payload. A key mismatch rejects all of it rather than reusing old indices.
    """
    spec = {key: value for key, value in simulation_mesh.items() if key not in {"generated", "cache_key"}}
    return _sha(_cache_value({"contract": "cad-volume-mesh-1", "geometry_source": geometry_source,
                             "simulation_mesh": spec}))


def validate_target_relations(package, targets):
    """Reject native fixed/ground/joint semantics we cannot preserve as FEM.

    End-region attachment declarations are the supported explicit connection
    mechanism. Nothing is silently dropped or converted into a rigid weld.
    """
    if not targets:
        return
    nodes = _records(package.occurrence_graph.nodes, "node_id", "occurrence_graph.nodes")
    def touches(candidate, target):
        return candidate == target or (isinstance(candidate, str) and target.startswith(candidate + "/"))
    for edge in getattr(package.occurrence_graph, "ground_edges", ()):
        child = edge.get("child_node_id")
        if any(touches(child, target) for target in targets):
            raise ValueError(f"deformable target is grounded (including a grounded ancestor): {child}; remove native grounding or use an explicit supported deformable attachment")
    connectors = {record.get("connector_snapshot_id"): record for record in getattr(package.occurrence_graph, "connectors", ())}
    for joint in getattr(package.occurrence_graph, "joints", ()):
        for side in ("connector_a", "connector_b"):
            endpoint = joint.get(side, {})
            candidates = [endpoint.get("node_id")] if isinstance(endpoint, dict) else []
            reference = endpoint.get("connector_snapshot_id") if isinstance(endpoint, dict) else endpoint
            if reference in connectors:
                candidates.append(connectors[reference].get("node_id"))
            if any(touches(candidate, target) for candidate in candidates for target in targets):
                raise ValueError(f"deformable target participates in native joint {joint.get('joint_id')!r}; declare supported deformable attachments explicitly instead")


def validate_cad_bindings(package, config):
    targets = {}
    for identity, declaration in config.get("cables", {}).items():
        if declaration.get("representation") == "rigid_joint_chain":
            continue
        target = declaration.get("target_node_id")
        if target is None:
            continue
        if target in targets:
            raise ValueError(f"cables: duplicate deformable declarations for target_node_id {target!r}: {targets[target]!r}, {identity!r}")
        targets[target] = identity
        part = config["parts"][target]
        if part.get("physical_type") != "deformable_volume":
            raise ValueError(f"parts.{target}.physical_type: CAD deformable target requires deformable_volume")
        if "rigid_body" in part:
            raise ValueError(f"parts.{target}: rigid_body conflicts with deformable_volume; use convert_rigid=True explicitly")
    for target, part in config["parts"].items():
        if part.get("physical_type") == "rigid_joint_chain":
            continue  # Validated independently by the versioned chain validator.
        if "physical_type" in part and (part["physical_type"] != "deformable_volume" or target not in targets):
            raise ValueError(f"parts.{target}.physical_type: requires exactly one matching CAD deformable declaration")
    for declaration in config.get("cables", {}).values():
        if declaration.get("representation") == "rigid_joint_chain":
            continue
        all_targets = {record.get("target_node_id") for record in config.get("cables", {}).values()}
        if any(attachment["rigid_node_id"] in all_targets for attachment in declaration["attachments"]):
            raise ValueError("cables.attachments.rigid_node_id: a deformable target cannot be used as a rigid endpoint")
    validate_target_relations(package, targets)


def upsert_deformable_volume(package, target_node_id, declaration=None, *, material=None,
                             convert_rigid=False, cable_id=None):
    """Return a full enrich_package config for one CAD occurrence.

    First call supplies a declaration with frozen official mesh and attachments.
    Later material-only calls preserve the same declaration and mesh byte values.
    Pass the returned config to enrich_package, then save the complete package.
    """
    from .contract import resolve_config, validate_config
    source = geometry_source_snapshot(package, target_node_id)
    embedded = package.root_definition.metadata.get("sca_physics")
    if embedded is not None and declaration is None:
        validate_config(package, embedded)
    config = deepcopy(embedded) if embedded is not None else {}
    config['schema_version'] = '1.8' if config.get('schema_version') == '1.8' else '1.7'
    records = config.setdefault("cables", {})
    matching = [identity for identity, record in records.items() if record.get("target_node_id") == target_node_id]
    if len(matching) > 1:
        raise ValueError("cables: ambiguous duplicate target declarations")
    if matching and records[matching[0]].get("representation") == "rigid_joint_chain":
        raise ValueError("selected target is a rigid_joint_chain; an implicit FEM replacement is not supported")
    identity = matching[0] if matching else cable_id or target_node_id
    if cable_id is not None and matching and cable_id != identity:
        raise ValueError("cable_id: cannot rename an existing target during a material update")
    if identity in records and not matching:
        raise ValueError(f"cable_id {identity!r} already belongs to a different declaration")
    if declaration is None and not matching:
        raise ValueError("first CAD deformable declaration requires geometry, official mesh and attachment configuration")
    record = deepcopy(declaration) if declaration is not None else deepcopy(records[identity])
    if record.get("target_node_id", target_node_id) != target_node_id:
        raise ValueError("declaration.target_node_id: does not match selected occurrence")
    if "geometry_source" in record and record["geometry_source"] != source:
        raise ValueError("geometry_source: CAD geometry/units/transform changed; regenerate the official mesh and dependent selections")
    record.update(target_node_id=target_node_id, physical_type="deformable_volume", geometry_source=source)
    if material is not None:
        from .cable_contract import _group, MATERIAL
        material = _group(material, MATERIAL, 'material', False, resolve=True)
        record.setdefault("material", {}).update(material)
    mesh = record.get("simulation_mesh", {})
    expected = mesh_cache_key(source, mesh)
    # A missing key may be supplied once while attaching an externally generated
    # mesh, but its generated provenance key is mandatory and never inferred.
    if "cache_key" not in mesh:
        mesh["cache_key"] = expected
    records[identity] = record
    part = config.setdefault("parts", {}).setdefault(target_node_id, {})
    if "rigid_body" in part:
        if not convert_rigid:
            raise ValueError("selected occurrence has rigid_body configuration; pass convert_rigid=True to explicitly remove its rigid settings")
        del part["rigid_body"]
    part["physical_type"] = "deformable_volume"
    return resolve_config(package, config)
