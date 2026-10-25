"""Occurrence/cache boundaries using standard unittest and official placements."""

from collections import Counter
from copy import deepcopy
import hashlib
import struct
from types import SimpleNamespace
import unittest

REAL_PACKAGE = None
REAL_TARGET = None

from sca_physics.contract import resolve_config, validate_config
from sca_physics.deformable import geometry_source_snapshot, mesh_cache_key, upsert_deformable_volume


IDENTITY = {"origin": [0, 0, 0], "x_axis": [1000000000, 0, 0],
            "y_axis": [0, 1000000000, 0], "z_axis": [0, 0, 1000000000]}


class Definition:
    definition_id = "shared"
    content_hash = "sha256:source-definition"
    units = "mm"
    resolved_definitions = {}
    metadata = {}
    blobs = {"body.brep": b"fixture evaluated geometry"}
    solid_cache_ref = SimpleNamespace(path="body.brep", sha256="sha256:" + hashlib.sha256(blobs["body.brep"]).hexdigest())

    def to_dict(self):
        return {"definition_id": self.definition_id, "units": self.units,
                "content_hash": self.content_hash, "metadata": deepcopy(self.metadata)}


def package():
    definition = Definition()
    root = SimpleNamespace(definition_id="assembly", content_hash="sha256:root", metadata={},
                           resolved_definitions={"shared": definition})
    nodes = [{"node_id": "node/assembly", "node_kind": "assembly", "definition_id": "assembly", "parent_node_id": None, "transform": deepcopy(IDENTITY)}]
    for identity in ("a", "b", "plug_a", "plug_b"):
        nodes.append({"node_id": "node/assembly/" + identity, "node_kind": "part", "definition_id": "shared",
                      "display_name": "duplicate", "parent_node_id": "node/assembly", "transform": deepcopy(IDENTITY)})
    graph = SimpleNamespace(root_definition_id="assembly", root_node_id="node/assembly",
                            nodes=nodes, joints=[], connectors=[], ground_edges=[])
    return SimpleNamespace(root_definition=root, occurrence_graph=graph)


def mesh_digest(generated):
    digest = hashlib.sha256()
    for field, code in (("points", "f"), ("tets", "i"), ("surface", "i")):
        for row in generated[field]:
            digest.update(struct.pack("<" + code * len(row), *row))
    return digest.hexdigest()


def declaration(pkg, target="node/assembly/a"):
    points = [[0, .01, 0], [-.008, -.005, 0], [.008, -.005, 0],
              [0, .01, 1], [-.008, -.005, 1], [.008, -.005, 1]]
    tets = [[0, 1, 2, 3], [1, 2, 3, 4], [2, 3, 4, 5]]
    from sca_physics.official_mesh import _det, _sub, METHOD, OFFICIAL_API
    for tet in tets:
        a, b, c, d = [points[i] for i in tet]
        if _det(_sub(b, a), _sub(c, a), _sub(d, a)) < 0:
            tet[1], tet[2] = tet[2], tet[1]
    faces = Counter()
    for a, b, c, d in tets:
        for face in ((a, b, c), (a, b, d), (a, c, d), (b, c, d)):
            faces[tuple(sorted(face))] += 1
    generated = {"points": points, "reference_points": deepcopy(points), "tets": tets,
                 "surface": [list(face) for face, count in faces.items() if count == 1],
                 "ends": {"start": [0, 1, 2], "end": [3, 4, 5]},
                 "provenance": {"method": METHOD, "api": OFFICIAL_API},
                 "source_geometry_sha256": "0" * 64}
    result = {"parent_node_id": "node/assembly", "representation": "physx_deformable_volume",
              "geometry": {"length": 1., "diameter": .03, "centerline": [[0, 0, 0], [0, 0, 1]]},
              "simulation_mesh": {"method": METHOD, "axial_segments": 3, "radial_segments": 3,
                                  "filter_length": .02, "generation_config": {"tessellation": {"linear_deflection_mm": .1}}},
              "material": {"density": 1200., "youngs_modulus": 1e7, "poissons_ratio": .35, "elasticity_damping": .01},
              "deformable": {"gravity_enabled": True, "linear_damping": .01},
              "collision": {"enabled": True, "contact_offset": .001, "rest_offset": 0},
              "attachments": [], "source": {"kind": "explicit", "detail": "Software contract fixture; not physical validation"}}
    for endpoint, z in (("start", 0), ("end", 1)):
        result["attachments"].append({"endpoint": endpoint, "rigid_node_id": "node/assembly/plug_" + ("a" if endpoint == "start" else "b"),
            "local_frame": {"position": [0, 0, z], "quaternion_wxyz": [1, 0, 0, 0]},
            "source": {"kind": "explicit", "detail": "Full actual end section"}})
    result["simulation_mesh"]["generation_config"]["reference_geometry"] = deepcopy(result["geometry"])
    source = geometry_source_snapshot(pkg, target)
    key = mesh_cache_key(source, result["simulation_mesh"])
    generated.update(mesh_cache_key=key, mesh_sha256=mesh_digest(generated))
    result["simulation_mesh"].update(cache_key=key, generated=generated)
    return result


class CADDeformableTests(unittest.TestCase):
    def setUp(self):
        self.pkg = package()

    def attached(self):
        config = upsert_deformable_volume(self.pkg, "node/assembly/a", declaration(self.pkg), cable_id="selected")
        self.pkg.root_definition.metadata = {"sca_physics": config}
        return config

    def test_material_update_retains_occurrence_declaration_and_entire_mesh(self):
        old = self.attached()
        updated = upsert_deformable_volume(self.pkg, "node/assembly/a", material={"source": {'kind':'explicit','detail':'Synthetic caller fixture values; not a material measurement'}, "youngs_modulus": 2e7, "poissons_ratio": .4, "density": 1500.})
        self.assertEqual(set(updated["cables"]), {"selected"})
        self.assertEqual(updated["cables"]["selected"]["simulation_mesh"], old["cables"]["selected"]["simulation_mesh"])
        self.assertEqual(updated["cables"]["selected"]["material"]["density"]["value"], 1500.)
        self.assertEqual(updated["parts"]["node/assembly/a"]["physical_type"], "deformable_volume")
        self.assertNotIn("physical_type", updated["parts"]["node/assembly/b"])
        self.assertNotIn("rigid_body", updated["parts"]["node/assembly/a"])
        self.assertEqual(old["cables"]["selected"]["material"]["density"]["value"], 1200.)

    def test_exact_target_ids_reject_names_definitions_and_assemblies(self):
        for target in ("duplicate", "shared", "node/missing", "node/assembly"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                geometry_source_snapshot(self.pkg, target)

    def test_duplicates_and_rigid_conflicts_reject(self):
        config = self.attached()
        bad = deepcopy(config)
        bad["cables"]["duplicate"] = deepcopy(bad["cables"]["selected"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_config(self.pkg, bad)
        bad = deepcopy(config)
        bad["parts"]["node/assembly/a"]["rigid_body"] = {}
        with self.assertRaisesRegex(ValueError, "rigid_body"):
            resolve_config(self.pkg, bad)

    def test_explicit_rigid_conversion_changes_only_selected_occurrence(self):
        base = resolve_config(self.pkg, {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {"node/assembly/a": {"rigid_body": {"mode": "dynamic"}},
                                                  "node/assembly/b": {"rigid_body": {"mode": "dynamic"}}}})
        self.pkg.root_definition.metadata = {"sca_physics": base}
        with self.assertRaisesRegex(ValueError, "convert_rigid"):
            upsert_deformable_volume(self.pkg, "node/assembly/a", declaration(self.pkg))
        result = upsert_deformable_volume(self.pkg, "node/assembly/a", declaration(self.pkg), convert_rigid=True)
        self.assertNotIn("rigid_body", result["parts"]["node/assembly/a"])
        self.assertEqual(result["parts"]["node/assembly/b"], base["parts"]["node/assembly/b"])

    def test_mesh_config_or_occurrence_transform_invalidates_cache(self):
        config = self.attached()
        bad = deepcopy(config)
        bad["cables"]["selected"]["simulation_mesh"]["generation_config"]["tessellation"]["linear_deflection_mm"] = .2
        with self.assertRaisesRegex(ValueError, "cache_key"):
            validate_config(self.pkg, bad)
        self.pkg.occurrence_graph.nodes[1]["transform"]["origin"][0] = 1000000000
        with self.assertRaisesRegex(ValueError, "geometry_source"):
            validate_config(self.pkg, config)

    def test_cache_survives_native_integer_float_json_canonicalization(self):
        item = declaration(self.pkg)
        source = geometry_source_snapshot(self.pkg, "node/assembly/a")
        spec = item["simulation_mesh"]
        spec["generation_config"]["cooking_scale"] = 1000.0
        spec["generation_config"]["tessellation"]["angular_deflection_degrees"] = 20.0
        def canonical(value):
            if isinstance(value, dict):
                return {key: canonical(item) for key, item in value.items()}
            if isinstance(value, list):
                return [canonical(item) for item in value]
            return int(value) if isinstance(value, float) and value.is_integer() else value
        self.assertEqual(mesh_cache_key(source, spec), mesh_cache_key(canonical(source), canonical(spec)))

    def test_payload_tamper_and_wrong_units_reject(self):
        config = self.attached()
        bad = deepcopy(config)
        bad["cables"]["selected"]["simulation_mesh"]["generated"]["mesh_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "digest"):
            validate_config(self.pkg, bad)
        bad = deepcopy(config)
        bad["cables"]["selected"]["material"]["density"]["unit"] = "kg/mm^3"
        with self.assertRaisesRegex(ValueError, "unit"):
            validate_config(self.pkg, bad)
        self.pkg.root_definition.resolved_definitions["shared"].units = "m"
        with self.assertRaisesRegex(ValueError, "unit"):
            validate_config(self.pkg, config)


    def test_grounded_or_joint_targets_are_not_silently_dropped(self):
        config = self.attached()
        self.pkg.occurrence_graph.ground_edges.append({"child_node_id": "node/assembly/a", "parent_node_id": "node/assembly"})
        with self.assertRaisesRegex(ValueError, "grounded"):
            validate_config(self.pkg, config)
        self.pkg.occurrence_graph.ground_edges.clear()
        self.pkg.occurrence_graph.connectors.append({"connector_snapshot_id": "port/a", "node_id": "node/assembly/a"})
        self.pkg.occurrence_graph.joints.append({"joint_id": "joint/fixed", "joint_type": "fixed", "connector_a": {"connector_snapshot_id": "port/a"}})
        # The contract checks relation safety before asking an exporter to drop it.
        from sca_physics.deformable import validate_target_relations
        with self.assertRaisesRegex(ValueError, "native joint"):
            validate_target_relations(self.pkg, {"node/assembly/a"})

    def test_legacy_schema_still_resolves(self):
        self.assertEqual(resolve_config(self.pkg, {"schema_version":"1.0"})["schema_version"], "1.0")
        self.assertEqual(resolve_config(self.pkg, {'schema_version':'1.1', 'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {"node/assembly/a": {"rigid_body": {"mode": "dynamic"}}}})["schema_version"], "1.1")
        legacy = declaration(self.pkg)
        for key in ("generation_config", "cache_key"):
            legacy["simulation_mesh"].pop(key)
        for key in ("source_geometry_sha256", "mesh_cache_key", "mesh_sha256"):
            legacy["simulation_mesh"]["generated"].pop(key)
        self.assertEqual(resolve_config(self.pkg, {'schema_version':'1.2', "cables": {"legacy": legacy}})["schema_version"], "1.2")

    def test_optional_sleep_settling_are_explicit_si_parameters(self):
        item = declaration(self.pkg)
        item["deformable"].update(sleep_threshold=0., settling_threshold=0., settling_damping=.01)
        config = upsert_deformable_volume(self.pkg, "node/assembly/a", item)
        body = config["cables"]["node/assembly/a"]["deformable"]
        self.assertEqual(body["sleep_threshold"]["unit"], "m/s")
        self.assertEqual(body["settling_threshold"]["value"], 0.)
        self.assertEqual(body["settling_damping"]["unit"], "1/s")
        body["sleep_threshold"]["unit"] = "cm/s"
        with self.assertRaisesRegex(ValueError, "unit"):
            validate_config(self.pkg, config)

    def test_real_endpoint_normals_override_measurement_chord(self):
        import math
        item = declaration(self.pkg)
        line = [[0, 0, 0], [.001, 0, .5], [0, 0, 1]]
        item["geometry"]["centerline"] = line
        item["geometry"]["length"] = sum(math.dist(a, b) for a, b in zip(line, line[1:]))
        spec = item["simulation_mesh"]
        def rekey():
            spec["generation_config"]["reference_geometry"] = deepcopy(item["geometry"])
            key = mesh_cache_key(geometry_source_snapshot(self.pkg, "node/assembly/a"), spec)
            spec["cache_key"] = key
            spec["generated"]["mesh_cache_key"] = key
        rekey()
        with self.assertRaisesRegex(ValueError, "endpoint cross-section"):
            upsert_deformable_volume(self.pkg, "node/assembly/a", item)
        item["geometry"]["endpoint_tangents"] = {"value": [[0, 0, 1], [0, 0, -1]], "unit": "1"}
        rekey()
        config = upsert_deformable_volume(self.pkg, "node/assembly/a", item)
        self.assertEqual(config["cables"]["node/assembly/a"]["geometry"]["endpoint_tangents"]["value"], [[0, 0, 1], [0, 0, -1]])


class RealCADPackageTests(unittest.TestCase):
    def setUp(self):
        if REAL_PACKAGE is None:
            self.skipTest("pass --package to inspect the real CAD fixture")
        from simplecadapi import read_product_package
        self.pkg = read_product_package(data=REAL_PACKAGE)
        embedded = self.pkg.root_definition.metadata.get("sca_physics", {})
        targets = [record["target_node_id"] for record in embedded.get("cables", {}).values()
                   if record.get("representation") == "physx_deformable_volume" and "target_node_id" in record]
        if REAL_TARGET is not None:
            self.target = REAL_TARGET
        elif len(targets) == 1:
            self.target = targets[0]
        else:
            raise ValueError("real CAD fixture requires --target unless it contains exactly one CAD-bound FEM declaration")

    def test_actual_brep_source_survives_complete_official_package_roundtrip(self):
        from simplecadapi import encode_product_package, read_product_package
        from sca_physics.package_io import enrich_package
        before = geometry_source_snapshot(self.pkg, self.target)
        embedded = self.pkg.root_definition.metadata.get("sca_physics")
        config = deepcopy(embedded) if embedded is not None else {"schema_version": "1.3", "cables": {}}
        enriched, preservation = enrich_package(self.pkg, config)
        reread = read_product_package(data=encode_product_package(enriched))
        self.assertEqual(geometry_source_snapshot(reread, self.target), before)
        self.assertEqual(before["native_length_unit"], "mm")
        self.assertEqual(before["mesh_length_unit"], "m")
        self.assertTrue(preservation["geometry_material_history_blobs_preserved"])

    def test_actual_selected_material_update_reuses_same_mesh_and_identity(self):
        from simplecadapi import encode_product_package, read_product_package
        from sca_physics.package_io import enrich_package
        embedded = self.pkg.root_definition.metadata.get("sca_physics", {})
        selected = [(key, record) for key, record in embedded.get("cables", {}).items() if record.get("target_node_id") == self.target]
        if len(selected) != 1:
            self.skipTest("raw CAD fixture has no attached official mesh yet; rerun on final package")
        identity, old = selected[0]
        updated = upsert_deformable_volume(self.pkg, self.target, material={"source": {'kind':'explicit','detail':'Synthetic caller fixture values; not a material measurement'}, "youngs_modulus": 234567890., "poissons_ratio": .31, "density": 1234.})
        enriched, preservation = enrich_package(self.pkg, updated)
        reread = read_product_package(data=encode_product_package(enriched))
        adopted = reread.root_definition.metadata["sca_physics"]
        self.assertEqual(adopted["cables"][identity]["target_node_id"], self.target)
        self.assertEqual(adopted["cables"][identity]["simulation_mesh"], old["simulation_mesh"])
        self.assertEqual(adopted["cables"][identity]["material"]["youngs_modulus"]["value"], 234567890.)
        self.assertEqual(adopted["cables"][identity]["material"]["poissons_ratio"]["value"], .31)
        self.assertEqual(adopted["cables"][identity]["material"]["density"]["value"], 1234.)
        self.assertEqual(len(adopted["cables"]), len(embedded["cables"]))
        self.assertTrue(preservation["geometry_material_history_blobs_preserved"])



if __name__ == "__main__":
    import argparse
    import sys
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--package")
    parser.add_argument("--target", help="exact CAD part occurrence; inferred only from a unique CAD-bound FEM declaration")
    parsed, remaining = parser.parse_known_args()
    REAL_PACKAGE = parsed.package
    REAL_TARGET = parsed.target
    unittest.main(argv=[sys.argv[0], *remaining])
