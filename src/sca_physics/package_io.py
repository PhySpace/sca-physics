"""Rebuild through official SCA objects, preserving all non-physics semantics."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from .contract import resolve_config, validate_config


def _definitions(root: Any) -> dict[str, Any]:
    result = {root.definition_id: root}
    for child in getattr(root, "resolved_definitions", {}).values():
        result.update(_definitions(child))
    return result


def _without_root_identity(value: Any, root_id: str) -> Any:
    """Scene/occurrence identities change with root metadata, never geometry."""
    if isinstance(value, list):
        return [_without_root_identity(item, root_id) for item in value]
    if not isinstance(value, dict):
        return value
    result = {k: _without_root_identity(v, root_id) for k, v in value.items()}
    if value.get("definition_id") == root_id:
        for key in ("content_hash", "revision", "product_asset_id"):
            result.pop(key, None)
    if value.get("node_id") == "node/" + root_id:
        properties = result.get("properties", {})
        properties.pop("content_hash", None)
        properties.pop("revision", None)
    return result


def preservation_report(before: Any, after: Any) -> dict[str, Any]:
    """Fail closed if an official rebuild changes existing asset semantics."""
    old, new = _definitions(before.root_definition), _definitions(after.root_definition)
    if old.keys() != new.keys():
        raise ValueError("definition closure changed during physics enrichment")
    root_id = before.root_id
    for identity in old:
        a, b = old[identity].to_dict(), new[identity].to_dict()
        if identity == root_id:
            for obj in (a, b):
                obj.pop("content_hash", None)
                obj["metadata"].pop("sca_physics", None)
        if a != b or dict(old[identity].blobs) != dict(new[identity].blobs):
            raise ValueError(f"native definition/geometry/material/history changed: {identity}")
    a = _without_root_identity(deepcopy(dict(before.occurrence_graph.manifest)), root_id)
    b = _without_root_identity(deepcopy(dict(after.occurrence_graph.manifest)), root_id)
    a.pop("content_hash", None)
    b.pop("content_hash", None)
    if a != b:
        raise ValueError("occurrence transforms, connectors, joints or grounding changed")
    if bool(before.scene_path) != bool(after.scene_path):
        raise ValueError("existing scene projection was lost or unexpectedly added")
    if before.scene_path:
        # ProductPackage.scene decodes and validates on access. Reuse the same
        # checked views for all comparisons; large scene archives otherwise
        # get reopened once per preserved geometry/source/history blob.
        before_scene, after_scene = before.scene, after.scene
        a = deepcopy(dict(before_scene.manifest))
        b = deepcopy(dict(after_scene.manifest))
        # Only the root product asset and references to its digest may change.
        for obj in (a, b):
            obj.pop("revision", None)
            obj["product_assets"] = [x for x in obj["product_assets"] if x["definition_id"] != root_id]
        a = _without_root_identity(a, root_id)
        b = _without_root_identity(b, root_id)
        if a != b:
            raise ValueError("existing scene cannot be preserved by the official rebuild; no output written")
        # Scene geometry, entities, source snapshots and feature assets stay byte identical.
        for key in ("geometry_assets", "entity_assets", "source_assets", "feature_graph_assets"):
            for record in before_scene.manifest[key]:
                uri = record["uri"]
                if before_scene.blobs[uri] != after_scene.blobs.get(uri):
                    raise ValueError(f"scene asset changed: {uri}")
    return {
        "native_definitions_preserved": True, "geometry_material_history_blobs_preserved": True,
        "occurrences_connectors_joints_grounding_preserved": True,
        "scene_projection_preserved": bool(before.scene_path),
        "input_package_hash": before.content_hash, "output_package_hash": after.content_hash,
        "input_root_hash": before.root_definition.content_hash,
        "output_root_hash": after.root_definition.content_hash,
    }


def enrich_package(package: Any, config: dict | None = None) -> tuple[Any, dict]:
    if "sca_physics" in package.root_definition.metadata:
        if config is None:
            raise ValueError("package already contains sca_physics; supply an explicit replacement config or use upsert_deformable_volume for a material update")
        # A complete explicit replacement is independently validated below.
        # This also allows refreshing a stale cache after a deliberate CAD edit;
        # validating the old geometry binding first would make repair impossible.
    resolved = resolve_config(package, config)
    return _rebuild_package(package, resolved)


def _rebuild_package(package: Any, resolved: dict) -> tuple[Any, dict]:
    """Shared strict official rebuild for enrichment and partial updates."""
    from simplecadapi import build_product_package, encode_product_package, read_product_package
    validate_config(package, resolved)
    root = replace(package.root_definition,
                   metadata={**package.root_definition.metadata, "sca_physics": resolved}, content_hash="")
    from .scene_preservation import attach_preserved_scene
    built = attach_preserved_scene(package, build_product_package(root, include_scene=False))
    # This is also a complete archive/schema/digest roundtrip before any output.
    loaded = read_product_package(data=encode_product_package(built))
    validate_config(loaded, loaded.root_definition.metadata["sca_physics"])
    if loaded.root_definition.metadata["sca_physics"] != resolved:
        raise ValueError("metadata changed after official package roundtrip")
    return loaded, preservation_report(package, loaded)


def write_new(path: str | Path, data: bytes) -> Path:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(data)
    return destination


def write_outputs(outputs: dict[Path, bytes]) -> None:
    """Reserve both outputs exclusively and clean up our files on write failure."""
    handles = []
    try:
        for path in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            handles.append((path, path.open("xb")))
        for path, handle in handles:
            handle.write(outputs[path])
        for _, handle in handles:
            handle.close()
    except BaseException:
        for path, handle in handles:
            handle.close()
            path.unlink(missing_ok=True)
        raise
