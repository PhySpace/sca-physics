"""Actual SCA package invariants, rather than only a serialized metadata test."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest
import simplecadapi as scad
from simplecadapi.artifacts.assembly_io import materialize_definition

from sca_physics.contract import resolve_config, validate_config
from sca_physics.package_io import enrich_package, preservation_report

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def raw():
    return scad.read_product_package(data=ROOT / "verification/raw.scadpkg")


def test_real_assembly_roundtrip_and_native_restore(raw):
    inputs = json.loads((ROOT / "examples/pendulum/physics-input.json").read_text())
    final, report = enrich_package(raw, inputs)
    reread = scad.read_product_package(data=scad.encode_product_package(final))
    physics = reread.root_definition.metadata["sca_physics"]
    validate_config(reread, physics)
    assert physics["parts"]["node/passive_pendulum/base"]["contact"]["restitution"]["value"] == 0.2
    assert physics["parts"]["node/passive_pendulum/arm"]["contact"]["restitution"]["value"] == 0.35
    assert physics["joints"]["joint/passive_pendulum/hinge"]["damping"]["value"] == 0.0008
    assembly = materialize_definition(reread.root_definition)
    assert assembly.get_component("base").item.material.density == 7.85e-6
    assert assembly.get_component("arm").item.material.density == 2.7e-6
    assert len(assembly.constraints) == 1
    assert report["geometry_material_history_blobs_preserved"]
    assert report["scene_projection_preserved"]
    assert scad.load_product_package(data=scad.encode_product_package(final)).content_hash == final.root_definition.content_hash
    with pytest.raises(ValueError, match="already contains"):
        enrich_package(final)


def test_official_hashes_and_physics_expectation_detect_mutation(raw):
    final, _ = enrich_package(raw)
    physics = deepcopy(final.root_definition.metadata["sca_physics"])
    physics["parts"]["node/passive_pendulum/base"]["contact"]["restitution"]["value"] = 2.0
    with pytest.raises(ValueError, match="restitution"):
        validate_config(final, physics)
    # Legal alternative values are structurally valid; an independent expected
    # snapshot, not just a schema check, is necessary to detect semantic drift.
    physics = deepcopy(final.root_definition.metadata["sca_physics"])
    physics["scene"]["up_axis"]["value"] = "+Y"
    validate_config(final, physics)
    assert physics != final.root_definition.metadata["sca_physics"]
    encoded = bytearray(scad.encode_product_package(final))
    encoded[len(encoded) // 2] ^= 1
    with pytest.raises(Exception):
        scad.read_product_package(data=bytes(encoded))


def test_single_part_without_scene_supported(raw):
    part = raw.root_definition.resolved_definitions["pendulum_arm"]
    package = scad.build_product_package(part, include_scene=False)
    final, report = enrich_package(package)
    assert final.root_kind == "single_solid"
    assert final.scene_path is None
    assert len(final.root_definition.metadata["sca_physics"]["parts"]) == 1
    assert final.root_definition.solid_cache_ref == part.solid_cache_ref
    assert not report["scene_projection_preserved"]


def test_geometry_mutation_is_not_accepted_as_metadata_edit(raw):
    other = replace(raw.root_definition, metadata={**raw.root_definition.metadata, "name": "Changed title"}, content_hash="")
    rebuilt = scad.build_product_package(other)
    with pytest.raises(ValueError, match="native definition"):
        preservation_report(raw, rebuilt)


def test_root_scene_custom_properties_are_not_ignored():
    from sca_physics.package_io import _without_root_identity
    a = {"node_id": "node/root", "properties": {"content_hash": "a", "user_note": "keep"}}
    b = {"node_id": "node/root", "properties": {"content_hash": "b"}}
    assert _without_root_identity(a, "root") != _without_root_identity(b, "root")


def test_failed_report_write_does_not_leave_package(tmp_path):
    from sca_physics.package_io import write_outputs
    blocked = tmp_path / "blocked"
    blocked.write_text("file, not a directory")
    package = tmp_path / "final.scadpkg"
    with pytest.raises(OSError):
        write_outputs({package: b"package", blocked / "report.json": b"report"})
    assert not package.exists()


def test_optional_mechanical_metadata_roundtrips_without_native_changes(raw):
    before = scad.encode_product_package(raw)
    identity = "node/passive_pendulum/arm"
    inputs = {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {identity: {
        "rigid_body": {"mode": "dynamic", "gravity_enabled": False, "linear_damping": 0, "angular_damping": .125},
        "collision": {"contact_offset": .002, "rest_offset": -.001},
        "contact": {"friction_combine_mode": "max", "restitution_combine_mode": "average"},
    }}}
    inputs.setdefault("source", {'kind':'explicit','detail':'Synthetic caller fixture values; not a material measurement'})
    final, report = enrich_package(raw, inputs)
    reread = scad.read_product_package(data=scad.encode_product_package(final))
    snapshot = reread.root_definition.metadata["sca_physics"]
    assert snapshot["schema_version"] == "1.7"
    assert snapshot == resolve_config(raw, inputs)
    assert snapshot["parts"][identity]["rigid_body"]["gravity_enabled"]["value"] is False
    assert snapshot["parts"][identity]["rigid_body"]["linear_damping"]["value"] == 0
    assert report["geometry_material_history_blobs_preserved"]
    assert report["occurrences_connectors_joints_grounding_preserved"]
    assert report["scene_projection_preserved"]
    assert scad.encode_product_package(raw) == before


def test_engine_default_intents_roundtrip_without_synthesized_values(raw):
    from sca_physics.contract import MECHANICAL_FIELDS, template_config
    expected = template_config(raw, include_mechanical=True)
    final, report = enrich_package(raw, expected)
    reread = scad.read_product_package(data=scad.encode_product_package(final))
    adopted = reread.root_definition.metadata["sca_physics"]
    assert adopted == expected
    for part in adopted["parts"].values():
        assert "mode" not in part["rigid_body"]
        for group, fields in MECHANICAL_FIELDS.items():
            for field in fields:
                if group == "rigid_body" and field == "mode":
                    continue
                assert part[group][field]["mode"] == "engine_default"
                assert "value" not in part[group][field]
    assert report["geometry_material_history_blobs_preserved"]
    assert report["scene_projection_preserved"]


@pytest.mark.parametrize("mechanical", [False, True])
def test_template_cli_keeps_legacy_default_and_has_explicit_opt_in(raw, tmp_path, monkeypatch, mechanical):
    from sca_physics.cli import main
    from sca_physics.contract import template_config
    # Runtime isolation is checked separately by addon check; this test exercises
    # CLI selection, official package reading, and the generated output bytes.
    monkeypatch.setattr("sca_physics.runtime.check", lambda: {"ok": True})
    output = tmp_path / "template.json"
    argv = ["template", str(ROOT / "verification/raw.scadpkg"), "--output", str(output)]
    if mechanical:
        argv.append("--include-mechanical")
    assert main(argv) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result == template_config(raw, include_mechanical=mechanical)
    assert result["schema_version"] == ("1.1" if mechanical else "1.0")


def test_rigid_chain_cli_saves_complete_bound_package_without_external_path_dependency(tmp_path, monkeypatch):
    from sca_physics.cli import main
    from sca_physics.deformable import geometry_source_snapshot
    monkeypatch.setattr("sca_physics.runtime.check", lambda: {"ok": True})
    raw_path = ROOT / "verification/rigid-chain-raw.scadpkg"
    initial = scad.read_product_package(data=raw_path)
    source = geometry_source_snapshot(initial, "node/round_cable_demo/wire")
    output = tmp_path / "chain.scadpkg"
    base = tmp_path / "base.json"
    base.write_text(json.dumps({'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "scene": {"up_axis": "+Y"}}), encoding="utf-8")
    assert main(["set-rigid-chain", str(raw_path), "--target", "node/round_cable_demo/wire",
                 "--chain-id", "wire", "--config", str(ROOT / "examples/rigid_chain/chain.json"),
                 "--base-config", str(base), "--output", str(output)]) == 0
    # Re-read only the saved bytes: no declaration object or input file is used.
    reread = scad.read_product_package(data=output)
    config = reread.root_definition.metadata["sca_physics"]
    validate_config(reread, config)
    assert config["schema_version"] == "1.7"
    assert config["scene"]["up_axis"]["value"] == "+Y"
    assert geometry_source_snapshot(reread, "node/round_cable_demo/wire") == source
    line = config["cables"]["wire"]
    assert line["geometry"]["centerline"]["value"] == [[0, 0, .1], [.25, 0, .1]]
    assert line["collision"]["filter_material_neighbors"]["value"] is True
    assert line["endpoints"] == {"start": {"mode": "world_fixed"}, "end": {"mode": "free"}}
    assert preservation_report(initial, reread)["geometry_material_history_blobs_preserved"]
    assert "sca_physics" not in initial.root_definition.metadata
