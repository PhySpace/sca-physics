"""Whole-cable decisions use real CAD and survive complete-package saving.

These are software/contract checks, not native stability or material calibration.
All output is owned by pytest's externally configured temporary directory.
"""
from copy import deepcopy
import json
import math
from pathlib import Path

import jsonschema
import pytest
import simplecadapi as scad

from sca_physics.cable_geometry import initial_curvature_radius
from sca_physics.cable_inference import configure_cable, select_segments
from sca_physics.cable_presets import DEFAULT_RESOURCE_BUDGET, PRESETS
from sca_physics.contract import inventory, validate_config
from sca_physics.package_io import enrich_package
from sca_physics.rigid_chain import upsert_rigid_chain


def cylinder(length_m=.3, diameter_m=.0026):
    """Build supported evaluated CAD, rather than inventing a package mock."""
    suffix = f"{round(length_m*1e6)}-{round(diameter_m*1e6)}"

    @scad.part(id="inference-cylinder-" + suffix)
    def wire():
        solid = scad.make_cylinder_rsolid(radius=diameter_m*500, height=length_m*1000,
                                         bottom_face_center=(0, 0, 800), axis=(1, 0, 0))
        part = scad.make_part_rpart("inference-cylinder-" + suffix, solid)
        return scad.assign_material_rpart(part, scad.make_material_rmaterial(
            "inference-cad-material", density=1200, density_unit="kg/m^3"))
    definition = wire()

    @scad.assemble(id="inference-assembly-" + suffix, definitions=(definition,))
    def assembly():
        return scad.add_component_rassembly(scad.make_assembly_rassembly("inference-assembly-" + suffix),
            definition.value, "wire", scad.identity_placement_rplacement())
    package = scad.build_product_package(assembly())
    return package, next(iter(inventory(package)["parts"]))


@pytest.fixture(scope="module")
def cad():
    return cylinder()


def decide(cad, **request):
    package, target = cad
    return configure_cable(package, target, {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, 'category': 'stranded_wire', "description": "ordinary flexible wire", **request})


def chain(config):
    return next(iter(config["cables"].values()))


def schema(version="1.7"):
    return json.loads((Path(__file__).resolve().parents[1] / "schemas" /
                       f"sca-physics-{version}.schema.json").read_text(encoding="utf-8"))


def large_budget():
    return {key: 10**12 for key in DEFAULT_RESOURCE_BUDGET}


def reference(value, *, classification="reference"):
    return {"value": value, "classification": classification,
            "source": {"kind": "reference", "detail": "Synthetic software acceptance evidence, not an actual material test",
                       "citation": "urn:sca:software-test:evidence", "conditions": "Synthetic test only"}}


def test_real_cad_dimension_reading_and_changed_geometry_changes_resolution(cad):
    short = chain(decide(cad))
    longer = chain(decide(cylinder(1.2, .0026)))
    thicker = chain(decide(cylinder(1.2, .0052)))
    geometry = short["resolution"]["geometry"]
    assert geometry["method"] == "evaluated_brep_solid_cylinder"
    assert geometry["length_m"] == pytest.approx(.3)
    assert geometry["diameter_m"] == pytest.approx(.0026)
    for actual, expected in zip(geometry["centerline_m"], [[0, 0, .8], [.3, 0, .8]]):
        assert actual == pytest.approx(expected)
    ns, nl, nt = (record["discretization"]["free_segments"]["value"] for record in (short, longer, thicker))
    assert nl > ns >= 20
    assert nt < nl
    assert thicker["mechanics"]["linear_density"]["value"] == pytest.approx(
        longer["mechanics"]["linear_density"]["value"]*4)
    assert thicker["mechanics"]["bending_rigidity"]["value"] == pytest.approx(
        longer["mechanics"]["bending_rigidity"]["value"]*16)


def test_user_zero_false_and_evidence_priority_are_preserved(cad):
    config = decide(cad, properties={"joint_damping": 0, "linear_damping": 0,
        "angular_damping": 0, "gravity_magnitude": 0, "enabled": False,
        "bending_rigidity": 7e-4, "linear_density": {"value": .08,
            "source": {"kind": "estimated", "detail": "Lower-priority synthetic estimate"}}},
        evidence={"bending_rigidity": reference(9e-4), "linear_density": reference(.03)},
        solver={"solver_velocity_iterations": 0})
    record = chain(config)
    for group, key in (("mechanics", "joint_damping"), ("body", "linear_damping"),
                       ("body", "angular_damping"), ("scene", "gravity_magnitude"),
                       ("body", "solver_velocity_iterations")):
        assert record[group][key]["value"] == 0
    assert record["collision"]["enabled"]["value"] is False
    assert record["mechanics"]["bending_rigidity"]["value"] == 7e-4
    assert record["mechanics"]["linear_density"]["value"] == .08
    sources = record["resolution"]["parameter_sources"]
    assert sources["bending_rigidity"]["classification"] == "user"
    assert sources["linear_density"]["classification"] == "engineering_estimate"
    validate_config(cad[0], config)


def test_whole_line_equivalent_density_conversion_and_ambiguity(cad):
    record = chain(decide(cad, properties={"equivalent_density": 2000}))
    assert record["mechanics"]["linear_density"]["value"] == pytest.approx(2000*math.pi*.0026**2/4)
    with pytest.raises(ValueError, match="mutually exclusive"):
        decide(cad, properties={"equivalent_density": 2000, "linear_density": .02})


def test_category_and_feel_are_versioned_and_do_not_change_mass_or_loss(cad):
    normal = chain(decide(cad))
    stiffer = chain(decide(cad, feel="stiffer"))
    rope = chain(decide(cad, description="ordinary jump rope", category="pvc_jump_rope"))
    assert rope["resolution"]["category"] == "pvc_jump_rope"
    assert normal["resolution"]["category"] == "stranded_wire"
    assert normal["resolution"]["preset"]["version"]
    assert normal["resolution"]["validation"]["physical_accuracy"] == "not_established"
    for key in ("bending_rigidity", "torsional_rigidity"):
        assert stiffer["mechanics"][key]["value"] == pytest.approx(normal["mechanics"][key]["value"]*2)
    for key in ("linear_density", "joint_damping"):
        assert stiffer["mechanics"][key] == normal["mechanics"][key]
    for key in ("linear_damping", "angular_damping"):
        assert stiffer["body"][key] == normal["body"][key]
    assert normal["resolution"]["parameter_sources"]["bending_rigidity"]["classification"] in {"preset", "derived"}


def test_curvature_rules_refine_the_known_planar_polyline_without_native():
    radius = .02
    angles = [i*math.pi/10 for i in range(11)]
    # A tangent straight lead makes the global curvature constraint active;
    # a short isolated arc would already be finer under the minimum20 rule.
    points = [[radius, -.2, 0]] + [[radius*math.cos(a), radius*math.sin(a), 0] for a in angles]
    length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    geometry = {"centerline_m": points, "diameter_m": .0026, "length_m": length,
                "free_length_m": length, "free_start_m": 0., "free_end_m": length}
    mechanics = {"linear_density": {"value": .015}, "bending_rigidity": {"value": .0005}}
    straight = {**geometry, "centerline_m": [[0, 0, 0], [length, 0, 0]]}
    assert initial_curvature_radius(points) == pytest.approx(radius)
    curved = select_segments(geometry, PRESETS["stranded_wire"], "balanced", mechanics, {})
    flat = select_segments(straight, PRESETS["stranded_wire"], "balanced", mechanics, {})
    assert curved["free_segments"] > flat["free_segments"]
    assert curved["actual_material_segment_length_m"] <= curved["criteria"]["initial_turn_feature_m"]
    assert curved["actual_material_segment_length_m"] <= curved["criteria"]["initial_sagitta_feature_m"]
    with pytest.raises(ValueError, match="cusp"):
        initial_curvature_radius([[0, 0, 0], [1, 0, 0], [0, 0, 0]])


@pytest.mark.parametrize("discretization", [
    {"mode": "auto", "free_segments": 20},
    {"mode": "explicit", "free_segments": 20, "target_segment_length_m": .01},
    {"mode": "target_length", "target_segment_length_m": .01, "free_segments": 20},
    {"free_segments": 20}, {"mode": "explicit"}, {"mode": "target_length"},
    {"mode": "explicit", "free_segments": True},
])
def test_discretization_conflicts_fail_instead_of_silently_selecting_a_mode(cad, discretization):
    with pytest.raises(ValueError, match="discretization"):
        decide(cad, discretization=discretization)


def test_explicit_and_target_length_modes_save_the_requested_count(cad):
    explicit = chain(decide(cad, discretization={"mode": "explicit", "free_segments": 37}))
    target = chain(decide(cad, discretization={"mode": "target_length", "target_segment_length_m": .011}))
    assert explicit["discretization"]["free_segments"]["value"] == 37
    assert target["discretization"]["free_segments"]["value"] == math.ceil(.3/.011)
    assert target["resolution"]["selection"]["requested_segment_length_m"] == .011


@pytest.mark.parametrize("n", [512, 513])
def test_larger_explicit_count_requires_and_obeys_a_budget_without_truncation(cad, n):
    config = decide(cad, discretization={"mode": "explicit", "free_segments": n}, resource_budget=large_budget())
    assert config["schema_version"] == "1.7"
    assert chain(config)["discretization"]["free_segments"]["value"] == n
    jsonschema.validate(config, schema())
    if n > 512:
        record = deepcopy(chain(config))
        del record["resolution"]
        del record["resource_budget"]
        with pytest.raises(ValueError, match="budget|512"):
            upsert_rigid_chain(cad[0], cad[1], record)
    with pytest.raises(ValueError, match="resource_budget"):
        decide(cad, discretization={"mode": "explicit", "free_segments": n})


def test_extreme_count_is_rejected_by_scalar_budget_before_interval_arrays(cad, monkeypatch):
    import sca_physics.cable_resolution as resolution
    def forbidden(*args, **kwargs):
        raise AssertionError("An interval loop was entered before rejecting the scalar body budget")
    monkeypatch.setattr(resolution, "range", forbidden, raising=False)
    with pytest.raises(ValueError, match="max_bodies"):
        decide(cad, discretization={"mode": "explicit", "free_segments": 100_000_000})


@pytest.mark.parametrize("case_request", [
    {"properties": {"bending_rigidity": 5e-324, "linear_density": 1e308}},
    {"discretization": {"mode": "explicit", "free_segments": 10**1000}},
    {"discretization": {"mode": "target_length", "target_segment_length_m": 1e-320}},
], ids=["mechanical-float-underflow", "huge-integer-count", "tiny-target-length"])
def test_extreme_numeric_requests_fail_with_a_configuration_error(cad, case_request):
    with pytest.raises(ValueError):
        decide(cad, **case_request)


def test_complete_package_roundtrip_is_frozen_after_live_preset_changes(cad, tmp_path, monkeypatch):
    config = decide(cad)
    final, _ = enrich_package(cad[0], config)
    path = tmp_path / "frozen-cable.scadpkg"
    path.write_bytes(scad.encode_product_package(final))
    monkeypatch.setitem(PRESETS["stranded_wire"], "bending_rigidity_Nm2", 123.)
    monkeypatch.setitem(PRESETS["stranded_wire"], "diameters_per_segment", .001)
    reopened = scad.read_product_package(path)
    saved = reopened.root_definition.metadata["sca_physics"]
    assert saved == config
    validate_config(reopened, saved)
    with pytest.raises(ValueError, match="already has a saved cable decision"):
        configure_cable(reopened, cad[1], {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, 'category': 'stranded_wire', "description": "ordinary wire"})


@pytest.mark.parametrize("field", ["solver", "parameter_sources", "request", "geometry", "selection", "limitations"])
def test_saved_decision_evidence_tampering_is_rejected(cad, field):
    config = decide(cad)
    decision = chain(config)["resolution"]
    if field == "solver":
        decision[field]["settings"]["physics_hz"] += 1
    elif field == "parameter_sources":
        decision[field]["bending_rigidity"]["source"]["detail"] = "Changed evidence after saving"
    elif field == "request":
        decision[field]["description"] = "A different original user request"
    elif field == "geometry":
        decision[field]["diameter_m"] *= 2
    elif field == "selection":
        decision[field]["rule_version"] = "different-rule"
    else:
        decision[field].append("Unregistered later claim")
    with pytest.raises(ValueError, match="fingerprint|resolution"):
        validate_config(cad[0], config)


def test_schema16_and_legacy_contract_boundaries(cad):
    config = decide(cad)
    jsonschema.Draft202012Validator.check_schema(schema())
    jsonschema.validate(config, schema())
    for version in ("1.4", "1.5"):
        previous = deepcopy(config)
        previous["schema_version"] = version
        with pytest.raises(ValueError, match="1.7|resolution|resource_budget"):
            validate_config(cad[0], previous)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(previous, schema(version))
    # A legacy declaration in a1.6 package remains legal without inference fields.
    legacy = deepcopy(config)
    for field in ("resolution", "resource_budget"):
        del chain(legacy)[field]
    validate_config(cad[0], legacy)
    jsonschema.validate(legacy, schema())


def test_schema16_budget_conditions_cover_decisions_and_large_legacy_counts(cad):
    config = decide(cad)
    without_budget = deepcopy(config)
    del chain(without_budget)["resource_budget"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(without_budget, schema())
    large = deepcopy(config)
    del chain(large)["resolution"]
    del chain(large)["resource_budget"]
    chain(large)["discretization"]["free_segments"] = {"value":513,"unit":"count","source":{'kind':'explicit','detail':'Synthetic caller fixture values; not a material measurement'}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(large, schema())
    with pytest.raises(ValueError, match="budget|512"):
        validate_config(cad[0], large)


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_nonpositive_or_noninteger_resource_limits_are_rejected(cad, value):
    with pytest.raises(ValueError, match="resource_budget"):
        decide(cad, resource_budget={"max_bodies": value})


def test_persisted_effective_material_tampering_does_not_trigger_new_inference(cad):
    config = decide(cad)
    chain(config)["mechanics"]["bending_rigidity"]["value"] *= 2
    with pytest.raises(ValueError, match="fingerprint|derived"):
        validate_config(cad[0], config)


@pytest.mark.parametrize("properties", [{"EA": 1000}, {"young_modulus": 1e9}, {"linear_density": True}])
def test_unimplemented_or_wrong_typed_material_properties_fail_closed(cad, properties):
    with pytest.raises(ValueError):
        decide(cad, properties=properties)


def test_explicit_geometry_must_agree_with_actual_supported_cylinder(cad):
    source = {"kind": "explicit", "detail": "Synthetic caller CAD polyline"}
    for geometry in ({"centerline_m": [[0, 0, .8], [.4, 0, .8]], "diameter_m": .0026, "source": source},
                     {"centerline_m": [[0, 0, .8], [.3, 0, .8]], "diameter_m": .0052, "source": source}):
        with pytest.raises(ValueError, match="conflicts"):
            decide(cad, geometry=geometry)
