"""Reproduce the cache-key failure using SCA's real canonical JSON encoder."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


def previous_value(value):
    if isinstance(value, dict):
        if set(value) <= {"value", "unit", "source"} and "value" in value:
            return previous_value(value["value"])
        return {key: previous_value(item) for key, item in value.items() if key != "source"}
    if isinstance(value, (list, tuple)):
        return [previous_value(item) for item in value]
    return value


def previous_key(source, mesh):
    spec = {key: value for key, value in mesh.items() if key not in {"generated", "cache_key"}}
    data = {"contract": "cad-volume-mesh-1", "geometry_source": source, "simulation_mesh": previous_value(spec)}
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--declaration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from simplecadapi.artifacts.canonical import canonical_bytes
    from sca_physics.deformable import mesh_cache_key
    import sca_physics.deformable
    raw = json.loads(args.declaration.read_text(encoding="utf-8-sig"))
    canonical = json.loads(canonical_bytes(raw))
    prior = [previous_key(item["geometry_source"], item["simulation_mesh"]) for item in (raw, canonical)]
    current = [mesh_cache_key(item["geometry_source"], item["simulation_mesh"]) for item in (raw, canonical)]
    output = {"executable": sys.executable, "installed_module": sca_physics.deformable.__file__,
        "installed_module_sha256": hashlib.sha256(Path(sca_physics.deformable.__file__).read_bytes()).hexdigest(),
        "argv": sys.argv, "input": str(args.declaration.resolve()),
        "official_canonical_encoder": "simplecadapi.artifacts.canonical.canonical_bytes",
        "previous_raw_key": prior[0], "previous_after_official_canonical_json_key": prior[1],
        "previous_failure_reproduced": prior[0] != prior[1],
        "current_raw_key": current[0], "current_after_official_canonical_json_key": current[1],
        "current_roundtrip_invariant": current[0] == current[1],
        "geometry_unchanged": raw["geometry"] == canonical["geometry"],
        "mesh_points_unchanged": raw["simulation_mesh"]["generated"]["points"] == canonical["simulation_mesh"]["generated"]["points"],
        "tets_unchanged": raw["simulation_mesh"]["generated"]["tets"] == canonical["simulation_mesh"]["generated"]["tets"],
        "example_types": {"raw_cooking_scale": type(raw["simulation_mesh"]["generation_config"]["cooking_scale"]).__name__,
                          "canonical_cooking_scale": type(canonical["simulation_mesh"]["generation_config"]["cooking_scale"]).__name__}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
