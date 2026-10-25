"""Frequency compatibility, unchanged limits and complete-package persistence."""

from copy import deepcopy
import json
from pathlib import Path

import jsonschema
import pytest

from sca_physics.contract import resolve_config, validate_config
from sca_physics.deformable import upsert_deformable_volume
from sca_physics.rigid_chain import upsert_rigid_chain
from test_cad_deformable import package, declaration as fem_declaration
from test_rigid_chain import TARGET, attached, declaration

ROOT = Path(__file__).resolve().parents[1]


def schema(version):
    return json.loads((ROOT / f"schemas/sca-physics-{version}.schema.json").read_text(encoding="utf-8"))


def test_schema_15_changes_only_identity_and_rigid_chain_frequency():
    old, new = schema("1.4"), schema("1.5")
    jsonschema.Draft202012Validator.check_schema(new)
    new["$id"] = old["$id"]
    new["title"] = old["title"]
    new["properties"]["schema_version"]["const"] = "1.4"
    new["$defs"]["rigidJointChain"]["properties"]["scene"]["properties"]["physics_hz"]["properties"]["value"]["maximum"] = 4096
    assert new == old


@pytest.mark.parametrize("frequency,version", [(1, "1.4"), (4096, "1.4"),
                                               (4097, "1.5"), (7680, "1.5"),
                                               (8192, "1.5"), (16384, "1.5")])
@pytest.mark.parametrize("wrapped", [False, True])
def test_new_chain_uses_minimum_schema_for_requested_frequency(frequency, version, wrapped):
    data = declaration()
    data["scene"]["physics_hz"] = {"value": frequency, "unit": "count"} if wrapped else frequency
    pkg = package()
    config = upsert_rigid_chain(pkg, TARGET, data, chain_id="line")
    assert config["schema_version"] == "1.7"
    validate_config(pkg, config)
    jsonschema.validate(config, schema("1.7"))
    inferred = deepcopy(config)
    del inferred["schema_version"]
    assert resolve_config(pkg, inferred)["schema_version"] == "1.7"


@pytest.mark.parametrize("version,frequency,valid", [
    ("1.4", 4096, True), ("1.4", 4097, False), ("1.4", 16384, False),
    ("1.5", 1, True), ("1.5", 16384, True), ("1.5", 16385, False),
    ("1.5", True, False), ("1.5", 480.5, False), ("1.5", 0, False),
    ("1.5", -1, False),
])
def test_persisted_schema_range_is_enforced_without_mutation(version, frequency, valid):
    pkg, config = attached()
    config["schema_version"] = version
    config["cables"]["line"]["scene"]["physics_hz"]["value"] = frequency
    before = deepcopy(config)
    if valid:
        validate_config(pkg, config)
        jsonschema.validate(config, schema(version))
    else:
        with pytest.raises(ValueError, match="physics_hz"):
            validate_config(pkg, config)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(config, schema(version))
    assert config == before


@pytest.mark.parametrize("frequency", [True, 16384.0, 16385, 0, -1])
def test_bad_new_frequency_is_not_clipped_or_coerced(frequency):
    data = declaration()
    data["scene"]["physics_hz"] = frequency
    with pytest.raises(ValueError, match="physics_hz"):
        upsert_rigid_chain(package(), TARGET, data)


def test_existing_14_stays_14_until_high_frequency_and_15_never_downgrades():
    pkg, old = attached()
    pkg.root_definition.metadata = {"sca_physics": old}
    before = deepcopy(old)
    data = declaration()
    data["scene"]["physics_hz"] = 4096
    updated = upsert_rigid_chain(pkg, TARGET, data)
    assert updated["schema_version"] == "1.7"
    assert pkg.root_definition.metadata["sca_physics"] == before
    data["scene"]["physics_hz"] = 16384
    updated = upsert_rigid_chain(pkg, TARGET, data)
    assert updated["schema_version"] == "1.7"
    pkg.root_definition.metadata = {"sca_physics": updated}
    data["scene"]["physics_hz"] = 480
    assert upsert_rigid_chain(pkg, TARGET, data)["schema_version"] == "1.7"


@pytest.mark.parametrize("group,key,value,valid", [
    ("discretization", "free_segments", 2, True),
    ("discretization", "free_segments", 512, True),
    ("discretization", "free_segments", 1, False),
    ("discretization", "free_segments", 513, False),
    ("body", "solver_position_iterations", 255, True),
    ("body", "solver_position_iterations", 256, False),
    ("body", "solver_velocity_iterations", 0, True),
    ("body", "solver_velocity_iterations", 255, True),
    ("body", "solver_velocity_iterations", 256, False),
])
def test_high_frequency_does_not_expand_other_count_limits(group, key, value, valid):
    pkg, config = attached()
    config["schema_version"] = "1.5"
    config["cables"]["line"]["scene"]["physics_hz"]["value"] = 16384
    config["cables"]["line"][group][key]["value"] = value
    if valid:
        validate_config(pkg, config)
        jsonschema.validate(config, schema("1.5"))
    else:
        with pytest.raises(ValueError):
            validate_config(pkg, config)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(config, schema("1.5"))


def test_mixed_package_fem_update_preserves_high_frequency_schema_and_chain():
    pkg = package()
    old = upsert_deformable_volume(pkg, TARGET, fem_declaration(pkg), cable_id="fem")
    pkg.root_definition.metadata = {"sca_physics": old}
    data = declaration()
    data["scene"]["physics_hz"] = 16384
    config = upsert_rigid_chain(pkg, "node/assembly/b", data, chain_id="chain")
    pkg.root_definition.metadata = {"sca_physics": config}
    updated = upsert_deformable_volume(pkg, TARGET, material={"source": {'kind':'explicit','detail':'Synthetic caller fixture values; not a material measurement'}, "density": 1300})
    assert updated["schema_version"] == "1.7"
    assert updated["cables"]["chain"] == config["cables"]["chain"]
    validate_config(pkg, updated)
    jsonschema.validate(updated, schema("1.7"))


@pytest.mark.parametrize("frequency,version", [(4096, "1.4"), (16384, "1.5")])
def test_cli_complete_package_save_and_read_uses_only_persisted_frequency(tmp_path, monkeypatch, frequency, version):
    import simplecadapi as scad
    from sca_physics.cli import main
    from sca_physics.package_io import preservation_report

    # Test command selection, official codec and files; installed runtime probes
    # and independent exporter processes are verified separately in integration.
    monkeypatch.setattr("sca_physics.runtime.check", lambda: {"ok": True})
    raw = ROOT / "verification/rigid-chain-raw.scadpkg"
    data = json.loads((ROOT / "examples/rigid_chain/chain.json").read_text(encoding="utf-8"))
    data["scene"]["physics_hz"] = frequency
    source = tmp_path / "declaration.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "chain.scadpkg"
    assert main(["set-rigid-chain", str(raw), "--target", "node/round_cable_demo/wire",
                 "--chain-id", "wire", "--config", str(source), "--output", str(output)]) == 0
    source.unlink()
    reread = scad.read_product_package(data=output)
    persisted = reread.root_definition.metadata["sca_physics"]
    before = deepcopy(persisted)
    assert persisted["schema_version"] == "1.7"
    assert persisted["cables"]["wire"]["scene"]["physics_hz"]["value"] == frequency
    validate_config(reread, persisted)
    jsonschema.validate(persisted, schema("1.7"))
    assert persisted == before
    assert preservation_report(scad.read_product_package(data=raw), reread)["geometry_material_history_blobs_preserved"]
