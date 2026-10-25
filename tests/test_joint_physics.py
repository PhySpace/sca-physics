"""Joint metadata, atomic source-aware updates, and complete package evidence."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import jsonschema

from test_contract import package
from sca_physics.contract import resolve_config, validate_config
from sca_physics import update_config, update_package

SOURCE = {"kind": "estimated", "detail": "Conservative software actuator test configuration; not hardware specifications"}
EXPLICIT = {"kind": "explicit", "detail": "Caller explicitly sets this synthetic test parameter"}
HINGE = "joint/assembly/hinge"
SLIDER = "joint/assembly/slider"
ROOT = Path(__file__).resolve().parents[1]


def drive(mode="position"):
    return {"mode": mode, "type": "force", "target_position": .2, "target_velocity": -.03,
        "stiffness": 2 if mode == "position" else 0, "damping": .4, "max_force": 3}


def joint(mode="position"):
    return {"motion": "limited", "lower_limit": -.5, "upper_limit": .5, "max_velocity": .7,
        "friction": 0, "damping": .02, "drive": drive(mode)}


def inputs():
    return {"source": SOURCE, "joints": {HINGE: joint(), SLIDER: joint("velocity")},
        "assembly": {"articulation": {"enabled": True, "root_node_id": "node/assembly", "fixed_base": True}}}


def attached(package, config):
    package.root_definition = SimpleNamespace(metadata={"sca_physics": config})
    return package


def test_sourced_angular_linear_snapshot_and_schema(package):
    config = resolve_config(package, inputs())
    assert config["schema_version"] == "1.8"
    assert config["joints"][HINGE]["drive"]["stiffness"]["unit"] == "N*m/rad"
    assert config["joints"][SLIDER]["drive"]["max_force"]["unit"] == "N"
    assert config["joints"][SLIDER]["drive"]["target_velocity"]["value"] == -.03
    assert config["joints"][HINGE]["friction"]["value"] == 0
    assert config["joints"][HINGE]["drive"]["damping"]["source"] == SOURCE
    validate_config(package, json.loads(json.dumps(config)))
    schema = json.loads((ROOT / "schemas/sca-physics-1.8.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(config, schema)
    damaged = deepcopy(config)
    del damaged["joints"][SLIDER]["drive"]["damping"]
    with pytest.raises(ValueError, match="missing"):
        validate_config(package, damaged)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(damaged, schema)


@pytest.mark.parametrize("field,value", [
    ("motion", "locked"), ("lower_limit", float("nan")), ("upper_limit", -.6),
    ("max_velocity", -1), ("friction", -1), ("friction", True),
    ("lower_limit", {"value": -.3, "unit": "deg"}),
    ("max_velocity", 1e60), ("max_velocity", 1e-90),
])
def test_invalid_joint_fields_rejected(package, field, value):
    data = inputs()
    data["joints"][HINGE][field] = value
    with pytest.raises(ValueError):
        resolve_config(package, data)


@pytest.mark.parametrize("field,value", [("type", "acceleration"), ("mode", "torque"),
    ("stiffness", 0), ("damping", -1), ("max_force", 0), ("target_position", .6),
    ("target_position", {"value": .2, "unit": "degree"})])
def test_invalid_drive_fields_rejected(package, field, value):
    data = inputs()
    data["joints"][HINGE]["drive"][field] = value
    with pytest.raises(ValueError):
        resolve_config(package, data)


def test_velocity_off_free_and_native_joint_boundaries(package):
    data = inputs()
    data["joints"][SLIDER]["drive"]["stiffness"] = 1
    with pytest.raises(ValueError, match="zero stiffness"):
        resolve_config(package, data)
    data["joints"][SLIDER]["drive"].update(stiffness=0, damping=0)
    with pytest.raises(ValueError, match="positive damping"):
        resolve_config(package, data)
    data["joints"][SLIDER] = {"motion": "free", "drive": drive("off")}
    config = resolve_config(package, data)
    assert config["joints"][SLIDER]["drive"]["mode"]["value"] == "off"
    data["joints"][SLIDER]["lower_limit"] = 0
    with pytest.raises(ValueError, match="limited motion"):
        resolve_config(package, data)
    with pytest.raises(ValueError, match="native revolute or prismatic"):
        resolve_config(package, {"source": SOURCE, "joints": {"joint/assembly/weld": {"friction": 0}}})


def test_new_fields_reject_old_schema_but_old_defaults_stay(package):
    assert resolve_config(package)["schema_version"] == "1.7"
    for version in ["1.0", "1.1", "1.4", "1.6", "1.7"]:
        with pytest.raises(ValueError, match="require schema 1.8"):
            resolve_config(package, {**inputs(), "schema_version": version})
    for root in ["missing", "same-part", "duplicate", None, []]:
        data = inputs()
        data["assembly"]["articulation"]["root_node_id"] = root
        with pytest.raises(ValueError, match="root_node_id"):
            resolve_config(package, data)


def test_articulation_optional_self_collisions_preserves_false_and_source(package):
    data = inputs()
    original = resolve_config(package, data)
    assert "self_collisions" not in original["assembly"]["articulation"]
    data["assembly"]["articulation"]["self_collisions"] = False
    config = resolve_config(package, data)
    assert config["assembly"]["articulation"]["self_collisions"] == {"value": False, "unit": "boolean", "source": SOURCE}
    validate_config(package, config)


def test_atomic_update_preserves_other_values_and_sources(package):
    before = resolve_config(package, inputs())
    attached(package, before)
    patch = {"joints": {HINGE: {"drive": {"target_position": {"value": -.1, "unit": "rad", "source": EXPLICIT}}}}}
    after = update_config(package, patch)
    expected = deepcopy(before)
    expected["joints"][HINGE]["drive"]["target_position"] = patch["joints"][HINGE]["drive"]["target_position"]
    assert after == expected
    assert package.root_definition.metadata["sca_physics"] == before
    assert patch["joints"][HINGE]["drive"]["target_position"]["source"] == EXPLICIT
    for replacement in [0, {"value": .1}, {"value": .1, "unit": "rad"}]:
        with pytest.raises(ValueError, match="source"):
            update_config(package, {"joints": {HINGE: {"drive": {"target_position": replacement}}}})
    assert update_config(package, {}) == before


def test_update_auto_schema_upgrade_and_explicit_authority(package):
    before = resolve_config(package, {"schema_version": "1.0"})
    attached(package, before)
    after = update_config(package, {"source": SOURCE, "joints": {HINGE: joint()}})
    assert after["schema_version"] == "1.8"
    assert after["parts"] == before["parts"]
    assert after["joints"][SLIDER] == before["joints"][SLIDER]
    with pytest.raises(ValueError, match="require schema 1.8"):
        update_config(package, {"schema_version": "1.7", "source": SOURCE, "joints": {HINGE: joint()}})
    attached(package, resolve_config(package, {"source": EXPLICIT, "joints": {HINGE: joint()}}))
    with pytest.raises(ValueError, match="explicit user"):
        update_config(package, {"source": SOURCE, "joints": {HINGE: {"drive": {"target_position": .1}}}})


def test_real_package_update_preserves_native_and_independent_read(tmp_path):
    import subprocess
    import sys
    import simplecadapi as scad
    from sca_physics.package_io import enrich_package
    raw = scad.read_product_package(data=ROOT / "verification/raw.scadpkg")
    enriched, _ = enrich_package(raw, {"schema_version": "1.0"})
    actual_id = next(iter(enriched.root_definition.metadata["sca_physics"]["joints"]))
    updated, report = update_package(enriched, {"source": SOURCE, "joints": {actual_id: joint()}})
    assert report["physics_update"]["schema_upgrade_automatic"] is True
    assert report["occurrences_connectors_joints_grounding_preserved"]
    output = tmp_path / "joint.scadpkg"
    expected = tmp_path / "expected.json"
    output.write_bytes(scad.encode_product_package(updated))
    expected.write_text(json.dumps(updated.root_definition.metadata["sca_physics"]), encoding="utf-8")
    checked = subprocess.run([sys.executable, "-I", "-B", "-m", "sca_physics", "validate", str(output), "--expect", str(expected)],
        capture_output=True, text=True, encoding="utf-8", check=False)
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["schema_version"] == "1.8"


def test_update_keeps_existing_cable_snapshot_and_native_semantics():
    from test_rigid_chain import attached as chain_attached
    pkg, before = chain_attached()
    del before["cables"]["line"]["collision"]["filter_material_neighbors"]
    pkg.root_definition.metadata = {"sca_physics": before}
    after = update_config(pkg, {"source": SOURCE, "assembly": {"articulation": {
        "enabled": False, "root_node_id": "node/assembly", "fixed_base": False}}})
    assert after["cables"] == before["cables"]
    assert after["parts"] == before["parts"]
    assert after["schema_version"] == "1.8"
    validate_config(pkg, after)
    with pytest.raises(ValueError, match="source"):
        update_config(pkg, {"cables": {"line": {"collision": {"filter_material_neighbors": True}}}})
    explicit = update_config(pkg, {"source": EXPLICIT, "cables": {"line": {"collision": {"filter_material_neighbors": True}}}})
    assert explicit["cables"]["line"]["collision"]["filter_material_neighbors"]["source"] == EXPLICIT


def test_scene_preservation_decodes_each_scene_once_and_still_checks_blobs():
    import simplecadapi as scad
    from sca_physics.package_io import preservation_report
    pkg = scad.read_product_package(data=ROOT / "verification/raw.scadpkg")
    assert pkg.scene_path

    class Counted:
        def __init__(self, package, scene=None):
            self.package, self.supplied_scene, self.reads = package, scene, 0

        def __getattr__(self, name):
            return getattr(self.package, name)

        @property
        def scene(self):
            self.reads += 1
            return self.supplied_scene if self.supplied_scene is not None else self.package.scene

    before, after = Counted(pkg), Counted(pkg)
    assert preservation_report(before, after)["scene_projection_preserved"]
    assert (before.reads, after.reads) == (1, 1)
    scene = pkg.scene
    corrupted = SimpleNamespace(manifest=deepcopy(dict(scene.manifest)), blobs=dict(scene.blobs))
    uri = next(record["uri"] for key in ("geometry_assets", "entity_assets", "source_assets", "feature_graph_assets") for record in scene.manifest[key])
    corrupted.blobs[uri] += b"altered"
    with pytest.raises(ValueError, match="scene asset changed"):
        preservation_report(Counted(pkg), Counted(pkg, corrupted))


def mimic_inputs():
    data = inputs()
    data["joints"][SLIDER] = {"motion": "limited", "lower_limit": -.004, "upper_limit": .004, "damping": 0}
    data["couplings"] = {"rack": {"representation": "mimic", "reference_joint_id": HINGE,
        "follower_joint_id": SLIDER, "gearing": .006, "offset": .001}}
    return data


def test_mimic_metadata_sources_units_schema_and_partial_update(package):
    before = resolve_config(package, mimic_inputs())
    coupling = before["couplings"]["rack"]
    assert coupling["gearing"] == {"value": .006, "unit": "m/rad", "source": SOURCE}
    assert coupling["offset"]["value"] == .001
    assert coupling["source"] == SOURCE
    schema = json.loads((ROOT / "schemas/sca-physics-1.8.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(before, schema)
    attached(package, before)
    patch = {"source": EXPLICIT, "couplings": {"rack": {"offset": -.001}}}
    after = update_config(package, patch)
    assert after["couplings"]["rack"]["offset"] == {"value": -.001, "unit": "m", "source": EXPLICIT}
    expected = deepcopy(before)
    expected["couplings"]["rack"]["offset"] = after["couplings"]["rack"]["offset"]
    assert after == expected
    with pytest.raises(ValueError, match="source"):
        update_config(package, {"couplings": {"rack": {"gearing": .007}}})


@pytest.mark.parametrize("field,value", [("representation", "gear"), ("reference_joint_id", SLIDER),
    ("follower_joint_id", HINGE), ("follower_joint_id", "missing"), ("gearing", 0),
    ("gearing", float("inf")), ("gearing", True), ("offset", float("nan")),
    ("gearing", {"value": .006, "unit": "m/deg"}), ("unknown", 0)])
def test_invalid_mimic_declarations_reject(package, field, value):
    data = mimic_inputs()
    data["couplings"]["rack"][field] = value
    with pytest.raises(ValueError):
        resolve_config(package, data)


def test_mimic_requires_articulation_limited_range_no_follower_drive(package):
    data = mimic_inputs()
    data["assembly"]["articulation"]["enabled"] = False
    with pytest.raises(ValueError, match="enabled articulation"):
        resolve_config(package, data)
    data = mimic_inputs()
    data["joints"][SLIDER] = {"motion": "free"}
    with pytest.raises(ValueError, match="limited motion"):
        resolve_config(package, data)
    data = mimic_inputs()
    data["joints"][SLIDER]["drive"] = drive()
    data["joints"][SLIDER]["drive"]["target_position"] = 0
    with pytest.raises(ValueError, match="independent active drive"):
        resolve_config(package, data)
    data["joints"][SLIDER]["drive"]["mode"] = "off"
    data["joints"][SLIDER]["damping"] = .1
    with pytest.raises(ValueError, match="passive damping must be zero"):
        resolve_config(package, data)
    data = mimic_inputs()
    data["couplings"]["other"] = deepcopy(data["couplings"]["rack"])
    with pytest.raises(ValueError, match="only one coupling owner"):
        resolve_config(package, data)
    data = mimic_inputs()
    data["couplings"]["rack"]["offset"] = 5
    with pytest.raises(ValueError, match="no feasible mimic"):
        resolve_config(package, data)
    data = mimic_inputs()
    data["schema_version"] = "1.7"
    with pytest.raises(ValueError, match="require schema 1.8"):
        resolve_config(package, data)


def test_resolved_17_cable_upgrades_without_changing_saved_resolution(tmp_path):
    import simplecadapi as scad
    from test_cable_inference import cylinder, decide
    from sca_physics.package_io import enrich_package
    raw, target = cylinder()
    before = decide((raw, target))
    package, _ = enrich_package(raw, before)
    root_id = package.occurrence_graph.root_node_id
    updated, _ = update_package(package, {"source": SOURCE, "assembly": {"articulation": {
        "enabled": False, "root_node_id": root_id, "fixed_base": False}}})
    reread = scad.read_product_package(data=scad.encode_product_package(updated))
    after = reread.root_definition.metadata["sca_physics"]
    assert after["schema_version"] == "1.8"
    assert after["cables"] == before["cables"]
    assert after["parts"] == before["parts"]
    validate_config(reread, after)
