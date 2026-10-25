"""Boundary tests use graph stubs; package round-trip tests use real SCA."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sca_physics.contract import DEFAULTS, DEMO_PROFILE, inventory, resolve_config, validate_config


@pytest.fixture
def package():
    graph = SimpleNamespace(
        root_definition_id="assembly",
        root_node_id="node/assembly",
        nodes=(
            {"node_id": "node/assembly", "node_kind": "assembly", "definition_id": "assembly"},
            {"node_id": "node/assembly/a", "node_kind": "part", "definition_id": "same-part", "display_name": "duplicate"},
            {"node_id": "node/assembly/b", "node_kind": "part", "definition_id": "same-part", "display_name": "duplicate"},
        ),
        joints=(
            {"joint_id": "joint/assembly/hinge", "joint_type": "revolute"},
            {"joint_id": "joint/assembly/slider", "joint_type": "prismatic"},
            {"joint_id": "joint/assembly/weld", "joint_type": "fixed"},
        ),
    )
    return SimpleNamespace(occurrence_graph=graph)


def part_input(**contact):
    return {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {"node/assembly/a": {"contact": contact}}}


def test_defaults_are_complete_occurrence_bound_snapshot(package):
    config = resolve_config(package)
    validate_config(package, config)
    assert config["default_profile"] == DEMO_PROFILE
    assert len(config["parts"]) == 2  # Shared definition and duplicate names stay distinct.
    a = config["parts"]["node/assembly/a"]
    assert a["definition_id"] == "same-part"
    assert a["contact"]["restitution"]["value"] == 0.1
    assert a["collision"]["approximation_static"]["value"] == "none"
    assert a["collision"]["enabled"]["value"] is True
    assert config["scene"]["up_axis"]["value"] == "+Z"
    assert config["joints"]["joint/assembly/hinge"]["damping"]["unit"] == "N*m*s/rad"
    assert config["joints"]["joint/assembly/slider"]["damping"]["unit"] == "N*s/m"
    assert config["joints"]["joint/assembly/weld"]["damping"]["unit"] == "unsupported"
    assert a["contact"]["static_friction"]["source"]["kind"] == "default"
    assert "demo-v1" in a["contact"]["static_friction"]["source"]["detail"]
    assert "node/assembly" not in inventory(package)["parts"]


def test_zero_false_and_nonzero_si_damping_survive(package):
    supplied = {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'},
        "parts": {"node/assembly/a": {"contact": {"static_friction": 0, "restitution": 0}, "collision": {"enabled": False}}},
        "joints": {
            "joint/assembly/hinge": {"damping": 0.125, "collision_enabled": True},
            "joint/assembly/slider": {"damping": {"value": 0.2, "unit": "N*s/m"}},
        },
        "scene": {"up_axis": "+Y"},
    }
    original = deepcopy(supplied)
    config = resolve_config(package, supplied)
    a = config["parts"]["node/assembly/a"]
    assert a["contact"]["static_friction"]["value"] == 0
    assert a["contact"]["restitution"]["value"] == 0
    assert a["collision"]["enabled"]["value"] is False
    assert a["contact"]["static_friction"]["source"]["kind"] == "explicit"
    assert config["joints"]["joint/assembly/hinge"]["damping"]["value"] == 0.125
    assert config["joints"]["joint/assembly/slider"]["damping"]["value"] == 0.2
    assert supplied == original
    validate_config(package, json.loads(json.dumps(config, allow_nan=False)))


@pytest.mark.parametrize("source", [
    {"kind": "estimated", "detail": "Qualitative demo assumption"},
    {"kind": "reference", "detail": "Dry contact pair", "citation": "https://example.org/table", "conditions": "dry room temperature"},
    {"kind": "explicit", "detail": "User requested 0.75"},
])
def test_sources_are_preserved(package, source):
    config = resolve_config(package, part_input(static_friction={"value": 0.75, "source": source}))
    assert config["parts"]["node/assembly/a"]["contact"]["static_friction"]["source"] == source


def test_resolved_snapshot_does_not_alias_reproducible_input(package):
    source = {"kind": "estimated", "detail": "Demo estimate based on dry contact assumption"}
    supplied = part_input(static_friction={"value": 0.75, "source": source})
    config = resolve_config(package, supplied)
    source["detail"] = "Changed input after resolving"
    adopted = config["parts"]["node/assembly/a"]["contact"]["static_friction"]
    assert adopted["source"]["detail"] == "Demo estimate based on dry contact assumption"
    adopted["source"]["detail"] = "Changed snapshot after resolving"
    assert supplied["parts"]["node/assembly/a"]["contact"]["static_friction"]["source"]["detail"] == "Changed input after resolving"


@pytest.mark.parametrize("bad", [-0.1, float("nan"), float("inf"), -float("inf"), True, "0.2", None, 10 ** 500])
def test_invalid_friction_is_rejected(package, bad):
    with pytest.raises(ValueError):
        resolve_config(package, part_input(static_friction=bad))


@pytest.mark.parametrize("bad", [-0.1, 1.00001, False, None])
def test_restitution_range_and_type(package, bad):
    with pytest.raises(ValueError):
        resolve_config(package, part_input(restitution=bad))


@pytest.mark.parametrize("supplied", [
    {"unexpected": 1},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {"duplicate": {}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {"node/assembly": {}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {"node/assembly/a": {"definition_id": "wrong"}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {"node/assembly/a": {"density": 700}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {"node/assembly/a": {"contact": {"static_friction": {"value": 0.5, "unit": "kg"}}}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {"node/assembly/a": {"collision": {"enabled": 0}}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {"node/assembly/a": {"collision": {"approximation_static": "off"}}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "joints": {"missing": {}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "joints": {"joint/assembly/hinge": {"joint_type": "prismatic"}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "joints": {"joint/assembly/hinge": {"damping": {"value": 1, "unit": "N*m*s/degree"}}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "joints": {"joint/assembly/hinge": {"damping": -1}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "joints": {"joint/assembly/weld": {"damping": 0.1}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "joints": {"joint/assembly/slider": {"collision_enabled": 1}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "scene": {"up_axis": "+X"}},
    {"schema_version": "9.0"},
    {"default_profile": "future-defaults"},
])
def test_invalid_inputs_reject_instead_of_silently_dropping(package, supplied):
    with pytest.raises(ValueError):
        resolve_config(package, supplied)


@pytest.mark.parametrize("supplied", [
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "scene": None},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": None},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {"node/assembly/a": None}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {"node/assembly/a": {"contact": None}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {"node/assembly/a": {"collision": None}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "joints": None},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "joints": {"joint/assembly/hinge": None}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "joints": {"joint/assembly/hinge": {"damping": False}}},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "assembly": None},
    {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "assembly": {"collision_exclusions": None}},
])
def test_explicit_null_containers_are_not_treated_as_missing(package, supplied):
    with pytest.raises(ValueError):
        resolve_config(package, supplied)


@pytest.mark.parametrize("source", [
    {"kind": "guessed", "detail": "no"},
    {"kind": [], "detail": "no"},
    {"kind": "explicit"},
    {"kind": "explicit", "detail": " "},
    {"kind": "reference", "detail": "okay", "citation": ""},
    {"kind": "reference", "detail": "Table value without citation or conditions"},
    {"kind": "reference", "detail": "Table value", "citation": "https://example.org/table"},
    {"kind": "reference", "detail": "Table value", "conditions": "Dry contact"},
    {"kind": "explicit", "detail": "okay", "unknown": "bad"},
])
def test_bad_provenance_is_rejected(package, source):
    with pytest.raises(ValueError):
        resolve_config(package, part_input(static_friction={"value": 0.3, "source": source}))


def test_actual_exclusions_and_explicit_source(package):
    pair = {"a": "node/assembly/a", "b": "node/assembly/b"}
    config = resolve_config(package, {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "assembly": {"collision_exclusions": [pair]}})
    actual = config["assembly"]["collision_exclusions"][0]
    assert actual["a"] == pair["a"]
    assert actual["source"]["kind"] == "explicit"
    validate_config(package, config)


@pytest.mark.parametrize("pairs", [
    [{"a": "node/assembly/a", "b": "missing"}],
    [{"a": "node/assembly/a", "b": "node/assembly"}],
    [{"a": "node/assembly/a", "b": "node/assembly/a"}],
    [{"a": "node/assembly/a"}],
    [{"a": "node/assembly/a", "b": "node/assembly/b"}, {"a": "node/assembly/b", "b": "node/assembly/a"}],
    [{"a": "node/assembly/a", "b": "node/assembly/b", "ignored": 1}],
])
def test_invalid_exclusion_pairs_are_rejected(package, pairs):
    with pytest.raises(ValueError):
        resolve_config(package, {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "assembly": {"collision_exclusions": pairs}})


@pytest.mark.parametrize("path", [
    ("scene",),
    ("parts", "node/assembly/a"),
    ("parts", "node/assembly/a", "contact", "restitution"),
    ("parts", "node/assembly/a", "contact", "restitution", "unit"),
    ("parts", "node/assembly/a", "collision", "enabled", "source"),
    ("joints", "joint/assembly/hinge"),
    ("assembly", "collision_exclusions"),
])
def test_persisted_validation_does_not_repair_missing_fields(package, path):
    config = resolve_config(package)
    target = config
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    with pytest.raises(ValueError):
        validate_config(package, config)


def test_persisted_validation_rejects_unknown_and_bad_values(package):
    config = resolve_config(package)
    config["parts"]["node/assembly/a"]["contact"]["restitution"]["value"] = 2
    with pytest.raises(ValueError, match="restitution"):
        validate_config(package, config)
    config = resolve_config(package)
    config["unexpected"] = 1
    with pytest.raises(ValueError, match="unknown fields"):
        validate_config(package, config)


def test_versioned_default_file_matches_runtime():
    path = Path(__file__).resolve().parents[1] / "defaults" / "demo-v1.json"
    profile = json.loads(path.read_text(encoding="utf-8"))
    assert profile["default_profile"] == DEMO_PROFILE
    assert profile["defaults"] == DEFAULTS


def test_json_schema_accepts_resolved_snapshot_and_rejects_missing_unit(package):
    import jsonschema
    path = Path(__file__).resolve().parents[1] / "schemas" / "sca-physics-1.7.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    config = resolve_config(package)
    jsonschema.validate(config, schema)
    del config["parts"]["node/assembly/a"]["contact"]["restitution"]["unit"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(config, schema)


def test_reference_requirements_agree_between_schema_and_runtime(package):
    import jsonschema
    path = Path(__file__).resolve().parents[1] / "schemas" / "sca-physics-1.7.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    config = resolve_config(package, part_input(static_friction={
        "value": 0.75,
        "source": {"kind": "reference", "detail": "Dry pair test table", "citation": "https://example.org/table", "conditions": "Dry contact, room temperature"},
    }))
    jsonschema.validate(config, schema)
    for required in ("citation", "conditions"):
        broken = deepcopy(config)
        del broken["parts"]["node/assembly/a"]["contact"]["static_friction"]["source"][required]
        with pytest.raises(ValueError, match=required):
            validate_config(package, broken)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(broken, schema)
