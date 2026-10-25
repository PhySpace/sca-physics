"""Qualitative edits retain explicit values, endpoint bindings and manual counts."""
from copy import deepcopy
import pytest
import simplecadapi as scad
from test_cable_inference import cylinder, chain
from sca_physics.cable_inference import configure_cable
from sca_physics.package_io import enrich_package
from sca_physics.rigid_chain import upsert_rigid_chain


def synthetic_legacy(record):
    record = deepcopy(record)
    def walk(value):
        if isinstance(value, dict):
            if 'value' in value and 'source' in value and value['source'].get('kind') == 'derived':
                value['source'] = {'kind':'explicit','detail':'Synthetic caller fixture values; not a material measurement'}
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
    walk(record)
    return record


def test_qualitative_edit_retains_explicit_values_count_solver_and_endpoints():
    package, target = cylinder()
    request = {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, 'category': 'stranded_wire', "description": "普通软电线", "properties": {"linear_density": .02, "bending_rigidity": .0008, "joint_damping": 0},
        "discretization": {"mode": "explicit", "free_segments": 7}, "solver": {"physics_hz": 900},
        "endpoints": {"start": {"mode": "world_fixed"}, "end": {"mode": "free"}}}
    old = configure_cable(package, target, request)
    saved, _ = enrich_package(package, old)
    new = chain(configure_cable(saved, target, {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "description": "这根线比较硬一些"}, reconfigure=True))
    assert new["discretization"]["free_segments"]["value"] == 7
    assert new["mechanics"]["linear_density"]["value"] == .02
    assert new["mechanics"]["bending_rigidity"]["value"] == .0008
    assert new["mechanics"]["joint_damping"]["value"] == 0
    assert new["mechanics"]["torsional_rigidity"] == chain(old)["mechanics"]["torsional_rigidity"]
    assert new["scene"]["physics_hz"]["value"] == 900
    assert new["endpoints"] == request["endpoints"]


def test_rope_category_inferred_in_old_description_survives_stiffer_edit():
    package, target = cylinder(.3, .005)
    old = configure_cable(package, target, {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, 'category': 'pvc_jump_rope', "description": "普通跳绳"})
    saved, _ = enrich_package(package, old)
    new = chain(configure_cable(saved, target, {'source': {'kind':'explicit','detail':'Synthetic caller fixture values; not a material measurement'}, "description": "比较硬一些"}, reconfigure=True))
    assert new["resolution"]["category"] == "pvc_jump_rope"
    assert new["mechanics"]["linear_density"] == chain(old)["mechanics"]["linear_density"]
    assert new["mechanics"]["bending_rigidity"] == chain(old)["mechanics"]["bending_rigidity"]
    assert new["mechanics"]["joint_damping"] == chain(old)["mechanics"]["joint_damping"]


def test_legacy_explicit_count_survives_explicit_reconfiguration():
    package, target = cylinder()
    declaration = synthetic_legacy(chain(configure_cable(package, target, {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, 'category': 'stranded_wire', "description": "普通软电线"})))
    declaration.pop("resolution")
    declaration.pop("resource_budget")
    declaration["discretization"]["free_segments"]["value"] = 7
    declaration["mechanics"]["linear_density"] = {"value": .025, "unit": "kg/m", "source": {"kind": "explicit", "detail": "User line mass"}}
    explicit_solver = {"kind": "explicit", "detail": "User solver input"}
    reference_solver = {"kind": "reference", "detail": "Synthetic reference setting", "citation": "urn:test:solver",
                        "conditions": "Software regression input only"}
    preserved = (("scene", "physics_hz", 900, explicit_solver),
                 ("body", "solver_position_iterations", 32, reference_solver),
                 ("body", "solver_velocity_iterations", 0, explicit_solver),
                 ("body", "enable_speculative_ccd", False, explicit_solver),
                 ("body", "apply_to_endpoints", False, explicit_solver))
    for group, key, value, source in preserved:
        declaration[group][key] = {"value": value, "unit": "boolean" if isinstance(value, bool) else "count", "source": source}
    old = upsert_rigid_chain(package, target, declaration)
    assert old["schema_version"] == "1.7"
    saved, _ = enrich_package(package, old)
    new = chain(configure_cable(saved, target, {'source': {'kind':'explicit','detail':'Synthetic caller fixture values; not a material measurement'}, "category":"stranded_wire", "description": "比较硬一些"}, reconfigure=True))
    assert new["discretization"]["free_segments"]["value"] == 7
    assert new["mechanics"]["linear_density"]["value"] == .025
    for group, key, _, _ in preserved:
        assert new[group][key] == declaration[group][key]
    assert new["resolution"]["solver"]["settings"] == {
        "physics_hz": 900, "solver_position_iterations": 32, "solver_velocity_iterations": 0}


def test_reconfigure_explicit_new_solver_and_body_switches_override_prior_choices():
    package, target = cylinder()
    request = {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, 'category': 'stranded_wire', "description": "ordinary flexible wire", "solver": {"physics_hz": 900, "solver_velocity_iterations": 0},
               "properties": {"enable_speculative_ccd": False, "apply_to_endpoints": False}}
    old = configure_cable(package, target, request)
    saved, _ = enrich_package(package, old)
    new = chain(configure_cable(saved, target, {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "description": "stiffer", "solver": {"physics_hz": 1200},
        "properties": {"enable_speculative_ccd": True}}, reconfigure=True))
    assert new["scene"]["physics_hz"]["value"] == 1200
    assert new["scene"]["physics_hz"]["source"]["kind"] == "explicit"
    assert new["body"]["solver_velocity_iterations"]["value"] == 0
    assert new["body"]["enable_speculative_ccd"]["value"] is True
    assert new["body"]["apply_to_endpoints"]["value"] is False
    assert new["resolution"]["parameter_sources"]["apply_to_endpoints"]["classification"] == "user"


@pytest.mark.parametrize("legacy_choice", ["free_interval", "endpoint_radius", "endpoint_filter", "material_filter", "centerline_samples"])
def test_unsupported_legacy_structure_is_rejected_without_changing_saved_input(legacy_choice):
    package, target = cylinder()
    declaration = synthetic_legacy(chain(configure_cable(package, target, {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, 'category': 'stranded_wire', "description": "ordinary flexible wire"})))
    for name in ("resolution", "resource_budget"):
        declaration.pop(name)
    if legacy_choice == "free_interval":
        declaration["geometry"]["free_start"]["value"] = .005
        declaration["geometry"]["free_end"]["value"] = .295
    elif legacy_choice == "endpoint_radius":
        declaration["section"]["endpoint_radius"]["value"] *= 2
    elif legacy_choice == "endpoint_filter":
        declaration["collision"]["filter_endpoint_links"]["value"] = False
    elif legacy_choice == "material_filter":
        declaration["collision"]["filter_material_neighbors"]["value"] = False
    else:
        a, b = declaration["geometry"]["centerline"]["value"]
        declaration["geometry"]["centerline"]["value"] = [a, [(x+y)/2 for x, y in zip(a, b)], b]
        declaration["geometry"]["arc_stations"]["value"] = [0., .15, .3]
    legacy = upsert_rigid_chain(package, target, declaration)
    saved, _ = enrich_package(package, legacy)
    encoded = scad.encode_product_package(saved)
    with pytest.raises(ValueError, match="legacy reconfigure.*set-rigid-chain"):
        configure_cable(saved, target, {'source': {'kind':'explicit','detail':'Synthetic caller fixture values; not a material measurement'}, "category":"stranded_wire", "description": "stiffer"}, reconfigure=True)
    assert scad.encode_product_package(saved) == encoded
