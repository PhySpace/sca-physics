"""Public source-aware partial updates of already enriched product packages."""

from collections.abc import Mapping
from copy import deepcopy


def _wrapper(value):
    return isinstance(value, Mapping) and ("value" in value or value.get("mode") == "engine_default")


def _merge(previous, patch, context=None, path="patch"):
    # Parameter wrappers are atomic. A new value never inherits old provenance,
    # units, or an engine-default mode. Group-level new sources still resolve.
    if isinstance(patch, Mapping) and "source" in patch:
        from .provenance import source
        context = source(patch["source"], path + ".source")
    if _wrapper(previous) or _wrapper(patch):
        # A declaration's persisted group source is old provenance too. Bind
        # replacements to a field/group source present in this patch before
        # merging, rather than allowing resolve to reuse the saved group source.
        if isinstance(patch, Mapping):
            replacement = deepcopy(dict(patch))
        else:
            replacement = {"value": deepcopy(patch)}
        if "source" not in replacement:
            if context is None:
                raise ValueError(path + ".source: a changed parameter requires a new field/group source in this patch")
            replacement["source"] = deepcopy(context)
        return replacement
    if not isinstance(previous, Mapping) or not isinstance(patch, Mapping):
        return deepcopy(patch)
    result = deepcopy(dict(previous))
    for key, value in patch.items():
        result[key] = deepcopy(value) if key == "source" else _merge(result.get(key), value, context, path + "." + key)
    return result


def _bind_added_sources(previous, current, patch, context=None, path="patch"):
    """New optional fields also inherit only this patch's source context.

    A legacy cable declaration may retain a group-level source. Resolving a
    newly introduced scalar against that declaration must not reuse its source.
    Scalar structural IDs remain scalars; the resolved contract identifies the
    actual parameters without guessing from field names.
    """
    if isinstance(patch, Mapping) and "source" in patch:
        from .provenance import source
        context = source(patch["source"], path + ".source")
    if _wrapper(current) and not _wrapper(previous):
        if context is None:
            raise ValueError(path + ".source: a new parameter requires a field/group source in this patch")
        current["source"] = deepcopy(context)
    elif isinstance(current, Mapping) and isinstance(patch, Mapping):
        for key in patch.keys() & current.keys():
            old = previous.get(key) if isinstance(previous, Mapping) else None
            _bind_added_sources(old, current[key], patch[key], context, path + "." + key)


def update_config(package, patch):
    """Return a complete validated config with only the supplied fields replaced.

    Requires an existing valid physics snapshot. Lists replace atomically; no
    null/deletion syntax is supported. Optional joint/articulation fields opt in
    to schema 1.8 unless the caller explicitly requested a different schema.
    Existing explicit parameters require a new explicit source when changed.
    This function does not mutate the package or the patch.
    """
    from .contract import _object, resolve_config, validate_config
    from .joint_physics import SCHEMA_VERSION, has_new_fields
    patch = _object(patch, "patch")
    metadata = getattr(getattr(package, "root_definition", None), "metadata", {})
    previous = metadata.get("sca_physics")
    if previous is None:
        raise ValueError("update requires an existing sca_physics snapshot; use enrich for a raw package")
    validate_config(package, previous)
    merged = _merge(previous, patch)
    if "schema_version" not in patch and has_new_fields(merged):
        merged["schema_version"] = SCHEMA_VERSION
    resolved = resolve_config(package, merged)
    # Legacy chains may intentionally omit an optional compatibility switch.
    # Re-resolving an unrelated joint must not materialize that switch, change
    # a frozen segmentation decision or replace historical numeric budgets.
    for identity, record in previous.get("cables", {}).items():
        changed = patch.get("cables", {})
        if isinstance(changed, Mapping) and identity not in changed:
            resolved["cables"][identity] = deepcopy(record)
    _bind_added_sources(previous, resolved, patch)
    validate_config(package, resolved)
    return resolved


def update_package(package, patch):
    """Apply a partial update through the ordinary official package rebuild."""
    from .package_io import _rebuild_package
    previous_version = package.root_definition.metadata.get("sca_physics", {}).get("schema_version")
    result, report = _rebuild_package(package, update_config(package, patch))
    report["physics_update"] = {"mode": "partial", "previous_schema_version": previous_version,
        "schema_version": result.root_definition.metadata["sca_physics"]["schema_version"],
        "schema_upgrade_automatic": "schema_version" not in patch and previous_version != result.root_definition.metadata["sca_physics"]["schema_version"],
        "parameter_wrappers": "atomic replacement; new values never inherit old provenance"}
    return result, report
