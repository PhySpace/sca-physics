"""Narrow installed-runtime compatibility and occurrence-identity witness.

Use the candidate pair python with -I -B. No sys.path/PYTHONPATH override, mesh
generation, environment mutation or simulation occurs in this verifier.
"""

import argparse
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--legacy-raw", type=Path, required=True)
    parser.add_argument("--legacy-final", type=Path, required=True)
    parser.add_argument("--instances", type=Path, required=True)
    parser.add_argument("--cad-final", type=Path)
    parser.add_argument("--cad-declaration", type=Path, help="official generated declaration for the occurrence witness when the full final is still building")
    parser.add_argument("--reuse-legacy-evidence", type=Path, help="reuse earlier passing legacy roundtrips only if installed module bytes still match")
    parser.add_argument("--reuse-boundary-evidence", type=Path, help="reuse an earlier successful suite command when installed module bytes and CAD final input match")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    import sca_physics
    from sca_physics.contract import resolve_config, validate_config
    from sca_physics.deformable import geometry_source_snapshot, upsert_deformable_volume
    from sca_physics.package_io import enrich_package
    from simplecadapi import read_product_package, encode_product_package
    import sca_physics.deformable
    dump(args.output / "runtime.json", {"executable": sys.executable,
        "versions": {name: importlib.metadata.version(name) for name in ("sca-physics", "sca-usd-export", "simplecadapi")},
        "modules": {module.__name__: {"file": module.__file__, "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
                    for module in (sca_physics, sca_physics.deformable)},
        "argv": sys.argv, "isolated": bool(sys.flags.isolated)})
    if args.reuse_boundary_evidence:
        previous_runtime = json.loads((args.reuse_boundary_evidence.parent / "runtime.json").read_text(encoding="utf-8"))
        current_runtime = json.loads((args.output / "runtime.json").read_text(encoding="utf-8"))
        if previous_runtime["modules"] != current_runtime["modules"] or previous_runtime["versions"] != current_runtime["versions"]:
            raise ValueError("boundary evidence belongs to different installed module bytes or versions")
        previous = json.loads(args.reuse_boundary_evidence.read_text(encoding="utf-8"))
        if previous["returncode"] != 0 or (args.cad_final and str(args.cad_final.resolve()) not in previous["argv"]):
            raise ValueError("boundary evidence failed or did not validate this actual final package")
        dump(args.output / "boundary-reuse.json", {"source": str(args.reuse_boundary_evidence.resolve()), "same_installed_module_bytes": True, "repeated": False})
    else:
        test = Path(__file__).resolve().parents[1] / "tests/test_cad_deformable.py"
        command = [sys.executable, "-I", "-B", str(test), "-v"]
        if args.cad_final:
            command.extend(["--package", str(args.cad_final.resolve())])
        ran = subprocess.run(command, capture_output=True, text=True)
        (args.output / "boundary.stdout.log").write_text(ran.stdout, encoding="utf-8")
        (args.output / "boundary.stderr.log").write_text(ran.stderr, encoding="utf-8")
        dump(args.output / "boundary.command.json", {"argv": command, "returncode": ran.returncode})
        if ran.returncode:
            raise RuntimeError("installed boundary suite failed")
    print("Installed boundary suite passed", flush=True)
    if args.reuse_legacy_evidence:
        previous_runtime = json.loads((args.reuse_legacy_evidence.parent / "runtime.json").read_text(encoding="utf-8"))
        current_runtime = json.loads((args.output / "runtime.json").read_text(encoding="utf-8"))
        if previous_runtime["modules"] != current_runtime["modules"] or previous_runtime["versions"] != current_runtime["versions"]:
            raise ValueError("legacy evidence belongs to different installed module bytes or versions")
        compatibility = json.loads(args.reuse_legacy_evidence.read_text(encoding="utf-8"))
        if {row["schema_version"] for row in compatibility} != {"1.0", "1.1", "1.2"} or not all(row["passed"] for row in compatibility):
            raise ValueError("legacy evidence is incomplete or failed")
        dump(args.output / "legacy-reuse.json", {"source": str(args.reuse_legacy_evidence.resolve()), "same_installed_module_bytes": True, "repeated": False})
    else:
        raw = read_product_package(data=args.legacy_raw)
        compatibility = []
        first = next(iter(resolve_config(raw)["parts"]))
        for version, config in (("1.0", {}), ("1.1", {"parts": {first: {"rigid_body": {"gravity_enabled": True, "linear_damping": .01}}}})):
            start = time.perf_counter()
            resolved = resolve_config(raw, config)
            assert resolved["schema_version"] == version
            enriched, preservation = enrich_package(raw, config)
            reread = read_product_package(data=encode_product_package(enriched))
            validate_config(reread, reread.root_definition.metadata["sca_physics"])
            assert reread.root_definition.metadata["sca_physics"] == resolved
            compatibility.append({"schema_version": version, "passed": True, "elapsed_seconds": time.perf_counter()-start,
                                  "preservation": preservation, "input": str(args.legacy_raw.resolve())})
            print(f"Legacy schema {version}: complete package roundtrip passed", flush=True)
        start = time.perf_counter()
        legacy = read_product_package(data=args.legacy_final)
        legacy_config = deepcopy(legacy.root_definition.metadata["sca_physics"])
        assert legacy_config["schema_version"] == "1.2"
        validate_config(legacy, legacy_config)
        refreshed, preservation = enrich_package(legacy, legacy_config)
        reread = read_product_package(data=encode_product_package(refreshed))
        assert reread.root_definition.metadata["sca_physics"] == legacy_config
        validate_config(reread, legacy_config)
        compatibility.append({"schema_version": "1.2", "passed": True, "elapsed_seconds": time.perf_counter()-start,
                              "preservation": preservation, "input": str(args.legacy_final.resolve()),
                              "legacy_official_generated_mesh_preserved": True})
    dump(args.output / "legacy-compatibility.json", compatibility)
    print("Legacy schema 1.2: complete package roundtrip passed", flush=True)
    instances = read_product_package(data=args.instances)
    candidates = [node for node in instances.occurrence_graph.nodes if node["node_kind"] == "part" and "cable" in node["definition_id"]]
    if len(candidates) != 2:
        raise ValueError("instance witness requires exactly two actual cable occurrences")
    sources = [geometry_source_snapshot(instances, node["node_id"]) for node in candidates]
    assert sources[0]["definition_id"] == sources[1]["definition_id"]
    assert sources[0]["brep_sha256"] == sources[1]["brep_sha256"]
    assert sources[0]["target_node_id"] != sources[1]["target_node_id"]
    witness = {"input": str(args.instances.resolve()), "passed_identity_check": True, "sources": sources,
               "same_definition": True, "same_brep": True, "different_occurrence_ids": True,
               "selected_only_declaration_roundtrip": "not run: final CAD official mesh was not provided",
               "simulation_verified": False}
    if args.cad_final or args.cad_declaration:
        if args.cad_final:
            final = read_product_package(data=args.cad_final)
            selected = [declaration for declaration in final.root_definition.metadata["sca_physics"]["cables"].values() if "target_node_id" in declaration]
            if len(selected) != 1:
                raise ValueError("CAD final witness requires one selected declaration")
            original = selected[0]
        else:
            original = json.loads(args.cad_declaration.read_text(encoding="utf-8-sig"))
        matches = [(node, source) for node, source in zip(candidates, sources)
                   if source["brep_sha256"] == original["geometry_source"]["brep_sha256"]]
        if not matches:
            raise ValueError("cannot reuse actual mesh topology: CAD BREP differs")
        node, source = sorted(matches, key=lambda pair: pair[0]["node_id"])[0]
        declaration = deepcopy(original)
        declaration["parent_node_id"] = node["parent_node_id"]
        declaration.pop("target_node_id")
        declaration.pop("geometry_source")
        from sca_physics.deformable import mesh_cache_key
        spec = declaration["simulation_mesh"]
        generated = spec["generated"]
        import numpy as np
        relative = np.asarray(source["world_transform_m"]) @ np.linalg.inv(np.asarray(original["geometry_source"]["world_transform_m"]))
        if not np.allclose(relative[:3, :3], np.eye(3), rtol=0, atol=1e-12):
            raise ValueError("this witness only supports exact rigid translation, not scaling or rotation")
        shift = relative[:3, 3]
        previous_digest = generated["mesh_sha256"]
        for field in ("points", "reference_points"):
            generated[field] = (np.asarray(generated[field], float) + shift).astype(np.float32).astype(float).tolist()
        declaration["geometry"]["centerline"]["value"] = (np.asarray(declaration["geometry"]["centerline"]["value"], float) + shift).tolist()
        embedding = generated.get("centerline_embedding")
        if embedding:
            indices = np.asarray(embedding["tet_vertex_indices"], int)
            embedding["sample_points_m"] = np.einsum("ni,nij->nj", np.asarray(embedding["weights"]), np.asarray(generated["reference_points"])[indices]).tolist()
            embedding["designed_sample_points_m"] = (np.asarray(embedding["designed_sample_points_m"], float) + shift).tolist()
            embedding["endpoint_float32_snap_m"] = [float(np.linalg.norm(np.asarray(embedding["sample_points_m"])[i]-np.asarray(embedding["designed_sample_points_m"])[i])) for i in (0, -1)]
        spec["generation_config"]["reference_geometry"] = deepcopy(declaration["geometry"])
        from sca_usd_export.deformable_targets import prepare_deformable_surface
        from sca_usd_export.config import ExportConfig
        tessellation = spec["generation_config"]["tessellation"]
        surface = prepare_deformable_surface(args.instances, node["node_id"], config=ExportConfig(**{key: tessellation[key] for key in ("linear_deflection_mm", "angular_deflection_degrees", "relative_deflection")}))
        assert surface["geometry_source"] == source
        generated["source_geometry_sha256"] = surface["source_geometry_sha256"]
        digest = hashlib.sha256()
        for field, dtype in (("points", "<f4"), ("tets", "<i4"), ("surface", "<i4")):
            digest.update(np.asarray(generated[field], dtype=dtype).tobytes())
        generated["mesh_sha256"] = digest.hexdigest()
        generated["provenance"]["occurrence_translation_witness"] = {
            "input_mesh_sha256": previous_digest, "world_translation_m": shift.tolist(),
            "method": "rigid translation of persisted official result for identical BREP; no cooking or mesh generation invoked",
            "topology_unchanged": True, "cache_invalidated_and_rekeyed": True,
            "reference_points_and_material_point_mapping_updated": True}
        key = mesh_cache_key(source, spec)
        spec["cache_key"] = key
        spec["generated"]["mesh_cache_key"] = key
        # This fixture has a mounting plate instead of the full plug assembly.
        # Associate both end sections to its correct local reference positions,
        # and explicitly select a kinematic plate for a legal native endpoint.
        # This is a declaration/persistence witness, not a material comparison.
        other = next(item for item in candidates if item["node_id"] != node["node_id"])
        plate = next(item for item in instances.occurrence_graph.nodes if item["node_kind"] == "part" and item["node_id"].endswith("/plate"))
        plate_inverse = np.linalg.inv(np.asarray(geometry_source_snapshot(instances, plate["node_id"])["world_transform_m"]))
        centerline = declaration["geometry"]["centerline"]["value"]
        for attachment in declaration["attachments"]:
            attachment["rigid_node_id"] = plate["node_id"]
            point = centerline[0 if attachment["endpoint"] == "start" else -1]
            local = (plate_inverse @ np.r_[point, 1])[:3].tolist()
            if isinstance(attachment["local_frame"]["position"], dict):
                attachment["local_frame"]["position"]["value"] = local
            else:
                attachment["local_frame"]["position"] = local
        config = upsert_deformable_volume(instances, node["node_id"], declaration, cable_id="selected_instance")
        config["parts"][plate["node_id"]]["rigid_body"] = {"mode": "kinematic"}
        changed, preservation = enrich_package(instances, config)
        reread = read_product_package(data=encode_product_package(changed))
        snapshot = reread.root_definition.metadata["sca_physics"]
        assert snapshot["parts"][node["node_id"]]["physical_type"] == "deformable_volume"
        assert "physical_type" not in snapshot["parts"][other["node_id"]]
        assert len(snapshot["cables"]) == 1
        assert snapshot["cables"]["selected_instance"]["target_node_id"] == node["node_id"]
        adopted_mesh = snapshot["cables"]["selected_instance"]["simulation_mesh"]["generated"]
        assert adopted_mesh["points"] == generated["points"]
        assert adopted_mesh["reference_points"] == generated["reference_points"]
        assert adopted_mesh["tets"] == original["simulation_mesh"]["generated"]["tets"]
        assert adopted_mesh["surface"] == original["simulation_mesh"]["generated"]["surface"]
        from sca_physics.package_io import write_new
        saved = write_new(args.output / "two-occurrence-selected.scadpkg", encode_product_package(reread))
        witness.update(selected_only_declaration_roundtrip=True, selected_node_id=node["node_id"],
                       untouched_node_id=other["node_id"], preservation=preservation,
                       saved_package=str(saved), endpoint_fixture=plate["node_id"],
                       actual_surface_sha256=surface["source_geometry_sha256"],
                       rigid_translation_m=shift.tolist(),
                       original_cache_key=original["simulation_mesh"]["cache_key"], new_cache_key=key,
                       scope="Real shared-BREP declaration/persistence isolation; plate endpoint fixture is not the full cable material comparison and has not been simulated")
    dump(args.output / "two-occurrence-witness.json", witness)
    dump(args.output / "result.json", {"passed": True, "installed_boundary_passed": True,
         "legacy_versions": [row["schema_version"] for row in compatibility],
         "two_occurrence_identity_passed": True,
         "two_occurrence_declaration_passed": witness["selected_only_declaration_roundtrip"] is True,
         "actual_cad_material_update_roundtrip_run": bool(args.cad_final), "simulation_run": False})
    print("Physics verification complete: " + str(args.output), flush=True)


if __name__ == "__main__":
    main()
