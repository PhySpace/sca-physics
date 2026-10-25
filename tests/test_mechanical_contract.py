"""Optional 1.1 metadata must not change the stable 1.0 snapshot."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from sca_physics.contract import (
    MECHANICAL_FIELDS, resolve_config, template_config, validate_config,
)
from test_contract import package  # Reuse the original occurrence/joint fixture.

PART = "node/assembly/a"


def supplied(group, **fields):
    return {'source': {'kind': 'explicit', 'detail': 'Source-aware software fixture inputs; not a material measurement'}, "parts": {PART: {group: fields}}}


def deferred(unit):
    return {"mode": "engine_default", "unit": unit,
            "source": {"kind": "explicit", "detail": "Use the engine default without authoring a USD opinion"}}


def test_legacy_snapshot_is_exactly_the_frozen_010_result(package):
    # Golden result from original contract SHA 3b175788eb5e65c727553cff9e87bf7ce
    # afa4b13d5976e5bc54bba5dc1fbf1d4, using the original test_contract fixture.
    config = resolve_config(package, {"schema_version":"1.0"})
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == "243fca563d96289ee3637f53c2b45c94ab8a8bba6e29b770bbb7e8bfb8595a02"
    assert config == template_config(package)
    assert config["schema_version"] == "1.0"


@pytest.mark.parametrize("group,field,value", [
    ("rigid_body", "mode", "dynamic"),
    ("rigid_body", "gravity_enabled", False),
    ("rigid_body", "linear_damping", 0),
    ("rigid_body", "angular_damping", .125),
    ("collision", "contact_offset", .002),
    ("collision", "rest_offset", -.001),
    ("contact", "friction_combine_mode", "min"),
    ("contact", "restitution_combine_mode", "multiply"),
])
def test_new_fields_select_17_and_preserve_explicit_zero_false(package, group, field, value):
    inputs = supplied(group, **{field: value})
    original = deepcopy(inputs)
    config = resolve_config(package, inputs)
    assert config["schema_version"] == "1.7"
    wrapper = config["parts"][PART][group][field]
    assert wrapper["value"] == value
    assert type(wrapper["value"]) is type(value)
    assert wrapper["unit"] == MECHANICAL_FIELDS[group][field]
    assert wrapper["source"]["kind"] == "explicit"
    assert inputs == original
    validate_config(package, json.loads(json.dumps(config, allow_nan=False)))
    untouched = config["parts"]["node/assembly/b"]
    assert "rigid_body" not in untouched
    assert set(untouched["collision"]) == {"enabled", "approximation_dynamic", "approximation_static"}
    assert set(untouched["contact"]) == {"static_friction", "dynamic_friction", "restitution"}
    with pytest.raises(ValueError, match="1.0"):
        resolve_config(package, {"schema_version": "1.0", **inputs})
    config["schema_version"] = "1.0"
    with pytest.raises(ValueError, match="1.0"):
        validate_config(package, config)


def test_optional_template_defers_values_without_inventing_body_mode(package):
    config = template_config(package, include_mechanical=True)
    assert config["schema_version"] == "1.1"
    for part in config["parts"].values():
        assert "mode" not in part["rigid_body"]
        for group, fields in MECHANICAL_FIELDS.items():
            for field, unit in fields.items():
                if group == "rigid_body" and field == "mode":
                    continue
                assert part[group][field]["mode"] == "engine_default"
                assert part[group][field]["unit"] == unit
                assert "value" not in part[group][field]
    validate_config(package, config)


@pytest.mark.parametrize("mode", ["static", "dynamic", "kinematic"])
def test_body_modes_and_static_engine_requests_can_be_saved(package, mode):
    config = resolve_config(package, supplied("rigid_body", mode=mode, gravity_enabled=deferred("boolean")))
    assert config["parts"][PART]["rigid_body"]["mode"]["value"] == mode
    validate_config(package, config)


@pytest.mark.parametrize("bad", [None, False, "engine_default", "frozen", {"mode": "engine_default"}])
def test_body_mode_is_explicit_categorical_or_omitted(package, bad):
    with pytest.raises(ValueError):
        resolve_config(package, supplied("rigid_body", mode=bad))


@pytest.mark.parametrize("group,field,bad", [
    ("rigid_body", "gravity_enabled", None),
    ("rigid_body", "gravity_enabled", 0),
    ("rigid_body", "linear_damping", -1),
    ("rigid_body", "linear_damping", True),
    ("rigid_body", "angular_damping", float("nan")),
    ("rigid_body", "angular_damping", float("inf")),
    ("rigid_body", "angular_damping", 1e40),
    ("rigid_body", "angular_damping", 1e-50),
    ("rigid_body", "angular_damping", 10 ** 500),
    ("collision", "contact_offset", 0),
    ("collision", "contact_offset", -.001),
    ("collision", "rest_offset", None),
    ("collision", "rest_offset", False),
    ("contact", "friction_combine_mode", "mean"),
    ("contact", "restitution_combine_mode", "MAX"),
    ("contact", "friction_combine_mode", None),
])
def test_new_value_bounds_types_and_float32_limits(package, group, field, bad):
    with pytest.raises(ValueError):
        resolve_config(package, supplied(group, **{field: bad}))


@pytest.mark.parametrize("bad", [
    {"mode": "auto"},
    {"mode": "engine_default", "value": 0},
    {"mode": "engine_default", "unit": "kg"},
    {"mode": "engine_default", "source": None},
    {"value": 0, "mode": "explicit"},
    {"value": None},
    {"value": 0, "unit": "1"},
    {"value": 0, "source": {"kind": "explicit", "detail": " "}},
])
def test_new_wrappers_are_closed_and_null_is_never_missing(package, bad):
    with pytest.raises(ValueError):
        resolve_config(package, supplied("rigid_body", linear_damping=bad))


def test_engine_default_is_not_allowed_for_legacy_parameters(package):
    with pytest.raises(ValueError):
        resolve_config(package, supplied("contact", static_friction=deferred("1")))


@pytest.mark.parametrize("rest", [-.002, 0])
def test_nonpositive_rest_may_defer_contact_offset(package, rest):
    for contact in ({}, {"contact_offset": deferred("m")}):
        config = resolve_config(package, supplied("collision", rest_offset=rest, **contact))
        assert config["parts"][PART]["collision"]["rest_offset"]["value"] == rest


@pytest.mark.parametrize("fields", [
    {"rest_offset": .001},
    {"rest_offset": .001, "contact_offset": deferred("m")},
    {"rest_offset": .002, "contact_offset": .002},
    {"rest_offset": .003, "contact_offset": .002},
    {"rest_offset": 1., "contact_offset": 1.00000001},  # Rounds equal in USD float32.
])
def test_rest_contact_pair_is_valid_after_float32_conversion(package, fields):
    with pytest.raises(ValueError, match="rest_offset"):
        resolve_config(package, supplied("collision", **fields))


def test_positive_rest_with_larger_explicit_contact_is_valid(package):
    config = resolve_config(package, supplied("collision", rest_offset=.001, contact_offset=.002))
    validate_config(package, config)


def test_persisted_optional_wrappers_are_not_repaired(package):
    config = template_config(package, include_mechanical=True)
    original = deepcopy(config)
    del config["parts"][PART]["rigid_body"]["linear_damping"]["source"]
    with pytest.raises(ValueError, match="source"):
        validate_config(package, config)
    assert config != original
    assert "source" not in config["parts"][PART]["rigid_body"]["linear_damping"]


def test_11_json_schema_and_runtime_agree_on_explicit_and_deferred_forms(package):
    import jsonschema
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas/sca-physics-1.1.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    for config in (template_config(package, include_mechanical=True),
                   resolve_config(package, supplied("rigid_body", mode="dynamic", gravity_enabled=False)),
                   resolve_config(package, supplied("collision", contact_offset=.002, rest_offset=-.001))):
        actual_schema = json.loads((root / f"schemas/sca-physics-{config['schema_version']}.schema.json").read_text(encoding='utf-8'))
        jsonschema.validate(config, actual_schema)
    config = template_config(package, include_mechanical=True)
    config["parts"][PART]["rigid_body"]["linear_damping"]["value"] = 0
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(config, schema)
    with pytest.raises(ValueError):
        validate_config(package, config)


def test_11_schema_requires_explicit_contact_for_positive_rest(package):
    import jsonschema
    schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/sca-physics-1.1.schema.json").read_text(encoding="utf-8"))
    config = template_config(package, include_mechanical=True)
    config["parts"][PART]["collision"]["rest_offset"] = {"value": .001, "unit": "m", "source": {"kind": "explicit", "detail": "Test"}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(config, schema)
    with pytest.raises(ValueError, match="positive rest"):
        validate_config(package, config)
