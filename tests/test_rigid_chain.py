"""CAD identity, explicit provenance and fail-closed representation boundaries."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_cad_deformable import package, declaration as fem_declaration
from sca_physics.contract import resolve_config, validate_config
from sca_physics.deformable import upsert_deformable_volume
from sca_physics.rigid_chain import upsert_rigid_chain

TARGET = "node/assembly/a"


def declaration():
    return {
        "source": {"kind": "estimated", "detail": "Software acceptance input; not measured cable material"},
        "geometry": {"coordinate_space": "world", "initial_shape": "planar", "centerline": [[0,0,0],[.5,0,0],[1,0,0]], "arc_stations": [0,.5,1], "free_start": 0, "free_end": 1, "length": 1},
        "discretization": {"free_segments": 10, "frame_policy": "shortest_arc_x"},
        "section": {"shape": "circle", "radius": .0025, "endpoint_radius": .00325},
        "mechanics": {"linear_density": .04, "bending_rigidity": .0003, "torsional_rigidity": .00015, "joint_damping": 0, "damping_mode": "per_joint", "rest_state": "straight"},
        "limits": {"minimum_bend_radius": .04, "maximum_bend_angle": 20, "maximum_twist_angle": 90},
        "body": {"linear_damping": 0, "angular_damping": 0, "solver_position_iterations": 64, "solver_velocity_iterations": 0, "enable_speculative_ccd": False, "apply_to_endpoints": False},
        "collision": {"enabled": True, "contact_offset": .00005, "rest_offset": 0, "self_collision": True, "filter_adjacent": True, "filter_endpoint_links": True},
        "contact": {"static_friction": .4, "dynamic_friction": .3, "restitution": .02},
        "scene": {"physics_hz": 480, "gravity_magnitude": 9.81, "solver_type": "TGS", "enable_gpu_dynamics": False, "broadphase_type": "MBP"},
        "endpoints": {"start": {"mode": "body_fixed", "rigid_node_id": "node/assembly/plug_a"}, "end": {"mode": "free"}},
    }


def attached():
    pkg = package()
    config = upsert_rigid_chain(pkg, TARGET, declaration(), chain_id="line")
    config["schema_version"] = "1.4"  # Explicit synthetic legacy snapshot for read-only contract tests.
    validate_config(pkg, config)
    return pkg, config


def test_resolved_identity_zero_false_and_provenance_roundtrip():
    pkg, config = attached()
    assert config["schema_version"] == "1.4"
    line = config["cables"]["line"]
    assert line["representation"] == "rigid_joint_chain"
    assert config["parts"][TARGET]["physical_type"] == "rigid_joint_chain"
    assert line["mechanics"]["joint_damping"]["value"] == 0
    assert line["body"]["enable_speculative_ccd"]["value"] is False
    assert line["body"]["solver_velocity_iterations"]["value"] == 0
    assert line["mechanics"]["bending_rigidity"]["source"] == declaration()["source"]
    validate_config(pkg, json.loads(json.dumps(config)))
    assert "physical_type" not in config["parts"]["node/assembly/b"]


@pytest.mark.parametrize("group,key,value", [
    ("mechanics","rest_state","initial_curve"), ("mechanics","damping_mode","distributed"),
    ("geometry","coordinate_space","local"), ("geometry","initial_shape","spatial"),
    ("section","shape","flat"), ("discretization","frame_policy","arbitrary"),
    ("discretization","free_segments",True), ("discretization","free_segments",3.5),
    ("discretization","free_segments",513), ("section","radius",0),
    ("section","radius",1e-90), ("mechanics","linear_density",-1),
    ("body","enable_speculative_ccd",1), ("body","solver_position_iterations",256),
    ("collision","contact_offset",0), ("collision","rest_offset",.01),
    ("collision","filter_adjacent",False), ("contact","restitution",1.1),
    ("scene","enable_gpu_dynamics",True), ("limits","maximum_bend_angle",180),
])
def test_unsupported_or_invalid_input_fails_closed(group, key, value):
    data = declaration()
    data[group][key] = value
    with pytest.raises(ValueError):
        upsert_rigid_chain(package(), TARGET, data)


def test_unknown_fields_wrong_units_and_missing_persisted_source_are_rejected():
    data = declaration()
    data["mechanics"]["E"] = 2e7
    with pytest.raises(ValueError, match="unknown"):
        upsert_rigid_chain(package(), TARGET, data)
    data = declaration()
    data["mechanics"]["bending_rigidity"] = {"value": .0003, "unit": "Pa"}
    with pytest.raises(ValueError, match="unit"):
        upsert_rigid_chain(package(), TARGET, data)
    pkg, config = attached()
    del config["cables"]["line"]["body"]["linear_damping"]["source"]
    with pytest.raises(ValueError, match="missing"):
        validate_config(pkg, config)


@pytest.mark.parametrize("mode", ["free", "world_fixed", "body_fixed"])
def test_endpoint_modes(mode):
    data = declaration()
    data["endpoints"]["start"] = {"mode": mode}
    if mode == "body_fixed":
        data["endpoints"]["start"]["rigid_node_id"] = "node/assembly/plug_a"
    config = upsert_rigid_chain(package(), TARGET, data)
    assert next(iter(config["cables"].values()))["endpoints"]["start"]["mode"] == mode


def test_spatial_geometry_rejected_independently_of_shape_label():
    data = declaration()
    points = [[0,0,0],[.2,0,0],[.2,.2,0],[.2,.2,.2]]
    data["geometry"].update(centerline=points, arc_stations=[0,.2,.4,.6], length=.6, free_end=.6)
    with pytest.raises(ValueError, match="non-planar"):
        upsert_rigid_chain(package(), TARGET, data)


def test_stations_and_lengths_must_describe_same_material_line():
    data = declaration()
    data["geometry"]["arc_stations"] = [0,.25,1]
    with pytest.raises(ValueError, match="consistent"):
        upsert_rigid_chain(package(), TARGET, data)


def test_stale_brep_and_grounded_target_rejected():
    pkg, config = attached()
    pkg.root_definition.resolved_definitions["shared"].blobs = {"body.brep": b"changed"}
    with pytest.raises(ValueError, match="digest"):
        validate_config(pkg, config)
    pkg = package()
    pkg.occurrence_graph.ground_edges = [{"child_node_id": "node/assembly"}]
    with pytest.raises(ValueError, match="grounded"):
        upsert_rigid_chain(pkg, TARGET, declaration())


def test_rigid_settings_require_explicit_conversion_and_unselected_parts_survive():
    pkg = package()
    pkg.root_definition.metadata = {"sca_physics": resolve_config(pkg, {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {TARGET: {"rigid_body": {"mode": "dynamic"}}, "node/assembly/b": {"rigid_body": {"mode": "kinematic"}}}})}
    with pytest.raises(ValueError, match="convert_rigid"):
        upsert_rigid_chain(pkg, TARGET, declaration())
    config = upsert_rigid_chain(pkg, TARGET, declaration(), convert_rigid=True)
    assert "rigid_body" not in config["parts"][TARGET]
    assert config["parts"]["node/assembly/b"]["rigid_body"]["mode"]["value"] == "kinematic"


def test_fem_replacement_is_explicit_and_old_schema_rejects_chain():
    pkg = package()
    pkg.root_definition.metadata = {"sca_physics": upsert_deformable_volume(pkg, TARGET, fem_declaration(pkg))}
    with pytest.raises(ValueError, match="replace_deformable"):
        upsert_rigid_chain(pkg, TARGET, declaration())
    config = upsert_rigid_chain(pkg, TARGET, declaration(), replace_deformable=True)
    assert len(config["cables"]) == 1
    config["schema_version"] = "1.3"
    with pytest.raises(ValueError, match="requires 1.4"):
        validate_config(pkg, config)


def test_duplicate_targets_and_chain_endpoint_are_rejected():
    pkg, config = attached()
    duplicate = deepcopy(config)
    duplicate["cables"]["other"] = deepcopy(duplicate["cables"]["line"])
    with pytest.raises(ValueError, match="duplicate"):
        validate_config(pkg, duplicate)
    pkg.root_definition.metadata = {"sca_physics": config}
    data = declaration()
    data["endpoints"]["start"]["rigid_node_id"] = TARGET
    with pytest.raises(ValueError, match="chain/FEM"):
        upsert_rigid_chain(pkg, "node/assembly/b", data)


def test_schema_14_accepts_complete_snapshot_and_rejects_unimplemented_policies():
    import jsonschema
    pkg, config = attached()
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/sca-physics-1.4.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(config, schema)
    bad = deepcopy(config)
    bad["cables"]["line"]["mechanics"]["damping_mode"] = "distributed"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def test_base_config_is_single_attach_only_and_preserves_unselected_mode():
    pkg = package()
    base = {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "scene": {"up_axis": "+Y"}, "parts": {
        "node/assembly/plug_a": {"rigid_body": {"mode": "kinematic"}},
    }}
    config = upsert_rigid_chain(pkg, TARGET, declaration(), base_config=base)
    assert config["scene"]["up_axis"]["value"] == "+Y"
    assert config["parts"]["node/assembly/plug_a"]["rigid_body"]["mode"]["value"] == "kinematic"
    assert config["schema_version"] == "1.7"
    assert pkg.root_definition.metadata == {}
    pkg.root_definition.metadata = {"sca_physics": config}
    with pytest.raises(ValueError, match="raw package"):
        upsert_rigid_chain(pkg, TARGET, declaration(), base_config=base)


@pytest.mark.parametrize("identity", ["duplicate", "shared", "node/assembly", "node/missing"])
def test_selection_requires_exact_part_occurrence(identity):
    with pytest.raises(ValueError):
        upsert_rigid_chain(package(), identity, declaration())


@pytest.mark.parametrize("field", ["centerline", "arc_stations", "length"])
def test_mandatory_geometry_does_not_fall_back_to_endpoints(field):
    data = declaration()
    del data["geometry"][field]
    with pytest.raises(ValueError, match="missing"):
        upsert_rigid_chain(package(), TARGET, data)


def test_reference_source_requires_traceable_conditions():
    data = declaration()
    data["source"] = {"kind": "reference", "detail": "Material table"}
    with pytest.raises(ValueError, match="citation"):
        upsert_rigid_chain(package(), TARGET, data)


@pytest.mark.parametrize("value", [float("inf"), float("nan"), True, "0.04"])
def test_mass_input_must_be_positive_finite_numeric(value):
    data = declaration()
    data["mechanics"]["linear_density"] = value
    with pytest.raises(ValueError):
        upsert_rigid_chain(package(), TARGET, data)


def test_independent_read_rejects_unknown_physical_type_on_unselected_part():
    pkg, config = attached()
    config["parts"]["node/assembly/b"]["physical_type"] = "unknown"
    with pytest.raises(ValueError, match="physical_type"):
        validate_config(pkg, config)


def test_optional_material_neighbor_filter_has_explicit_default_and_legacy_reads():
    pkg, config = attached()
    switch = config["cables"]["line"]["collision"]["filter_material_neighbors"]
    assert switch["value"] is False
    assert switch["source"]["kind"] == "default"
    del config["cables"]["line"]["collision"]["filter_material_neighbors"]
    before = deepcopy(config)
    validate_config(pkg, config)
    assert config == before
    data = declaration()
    data["collision"]["filter_material_neighbors"] = True
    config = upsert_rigid_chain(pkg, TARGET, data)
    assert next(iter(config["cables"].values()))["collision"]["filter_material_neighbors"]["value"] is True
    data["collision"]["filter_material_neighbors"] = 1
    with pytest.raises(ValueError, match="boolean"):
        upsert_rigid_chain(pkg, TARGET, data)


@pytest.mark.parametrize("identity", [[], {}, None, 5, "missing", TARGET])
def test_endpoint_identity_errors_are_specific_and_fail_closed(identity):
    data = declaration()
    data["endpoints"]["start"]["rigid_node_id"] = identity
    with pytest.raises(ValueError, match="rigid_node_id"):
        upsert_rigid_chain(package(), TARGET, data)


def test_schema_14_preserves_an_independent_legacy_fem_declaration():
    pkg = package()
    old = upsert_deformable_volume(pkg, TARGET, fem_declaration(pkg), cable_id="fem")
    pkg.root_definition.metadata = {"sca_physics": old}
    result = upsert_rigid_chain(pkg, "node/assembly/b", declaration(), chain_id="chain")
    assert result["schema_version"] == "1.7"
    assert result["cables"]["fem"] == old["cables"]["fem"]
    assert result["parts"][TARGET]["physical_type"] == "deformable_volume"
    assert result["parts"]["node/assembly/b"]["physical_type"] == "rigid_joint_chain"
    import jsonschema
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/sca-physics-1.7.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(result, schema)
    pkg.root_definition.metadata = {"sca_physics": result}
    updated = upsert_deformable_volume(pkg, TARGET, material={"source": {'kind':'explicit','detail':'Synthetic caller fixture values; not a material measurement'}, "density": 1300})
    assert updated["schema_version"] == "1.7"
    assert updated["cables"]["chain"] == result["cables"]["chain"]
    validate_config(pkg, updated)
