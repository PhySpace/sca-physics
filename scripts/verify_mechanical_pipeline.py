"""Installed-runtime acceptance of the legacy enrich pipeline; writes fresh results.

Pass a captured examples/mechanical_v1_1 package and the isolated candidate profile.
All CLI steps run in independent processes, without source-path injection.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="reuse completed command logs in this same isolated run")
    args = parser.parse_args()
    root, run = args.root.resolve(), args.run.resolve()
    profile = json.loads((run / "candidate-profile.json").read_text())
    out = run / "pipeline"
    out.mkdir(exist_ok=args.resume)
    commands = json.loads((out / "commands.json").read_text()) if args.resume and (out / "commands.json").exists() else []

    def invoke(name, plugin, *arguments):
        module = "sca_physics" if plugin == "physics" else "sca_usd_export"
        cmd = [profile["pythons"][plugin], "-I", "-B", "-m", module, *map(str, arguments)]
        if any(item["name"] == name and item["argv"] == cmd and item["returncode"] == 0 for item in commands):
            return json.loads((out / (name + ".log")).read_text())
        result = subprocess.run(cmd, capture_output=True, env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"))
        (out / (name + ".log")).write_bytes(result.stdout + result.stderr)
        commands.append({"name": name, "argv": cmd, "returncode": result.returncode})
        (out / "commands.json").write_text(json.dumps(commands, indent=2))
        result.check_returncode()
        return json.loads(result.stdout)

    for plugin in ("physics", "usd"):
        facts = invoke("check-" + plugin, plugin, "check")
        assert facts["ok"]
        (out / (plugin + "-runtime.json")).write_text(json.dumps(facts, indent=2))
    raw = run / "fixture_raw.scadpkg"
    info = invoke("inspect-raw", "physics", "inspect", raw)
    parts = info["inventory"]["parts"]
    roles = ("anchor", "static", "dynamic", "kinematic", "gravity_off", "linear_damped", "angular_damped", "control")
    identities = {}
    for role in roles:
        matching = [node for node in parts if node == "node/mechanical_acceptance/" + role]
        assert len(matching) == 1, (role, matching)
        identities[role] = matching[0]
    assert len(parts) == 8 and len({part["definition_id"] for part in parts.values()}) == 1
    (out / "identities.json").write_text(json.dumps({role: {"node_id": node, **parts[node]} for role, node in identities.items()}, indent=2))

    def explicit(value, unit):
        return {"value": value, "unit": unit, "source": {"kind": "explicit", "detail": "Artificial acceptance value, not measured material data"}}

    def engine(unit):
        return {"mode": "engine_default", "unit": unit, "source": {"kind": "default", "detail": "Explicitly retain PhysX 107.3.18 engine default; no authored value"}}

    modes = {role: "dynamic" for role in roles}
    modes.update(anchor="static", static="static", kinematic="kinematic")
    config = {"schema_version": "1.1", "parts": {}}
    for index, role in enumerate(roles):
        node = identities[role]
        body = {"mode": explicit(modes[role], "token")}
        if modes[role] != "static":
            body["gravity_enabled"] = explicit(role in {"dynamic", "kinematic"}, "boolean")
        if role == "linear_damped":
            body["linear_damping"] = explicit(2.4, "1/s")
        if role == "angular_damped":
            body["angular_damping"] = explicit(1.8, "1/s")
        if role == "control":
            body.update(linear_damping=explicit(0, "1/s"), angular_damping=explicit(0, "1/s"))
        if role == "kinematic":
            body["angular_damping"] = engine("1/s")
        contact = {"static_friction": explicit(0.23 + index * 0.07, "1"),
                   "dynamic_friction": explicit(0.17 + index * 0.05, "1"),
                   "restitution": explicit(0.04 + index * 0.02, "1"),
                   "friction_combine_mode": explicit("multiply" if index % 2 else "min", "token"),
                   "restitution_combine_mode": explicit("max" if index % 2 else "multiply", "token")}
        collision = {"contact_offset": explicit(0.0008 + index * 0.00001, "m"),
                     "rest_offset": explicit(-0.0001, "m")}
        if role == "anchor":
            contact.update(friction_combine_mode=engine("token"), restitution_combine_mode=engine("token"))
            collision = {"contact_offset": engine("m"), "rest_offset": engine("m")}
        config["parts"][node] = {"definition_id": parts[node]["definition_id"], "rigid_body": body, "contact": contact, "collision": collision}
    cfg = out / "mechanical-input.json"
    cfg.write_text(json.dumps(config, indent=2) + "\n")
    invoke("template-legacy", "physics", "template", raw, "--output", out / "template-legacy.json")
    invoke("template-mechanical", "physics", "template", raw, "--output", out / "template-mechanical.json", "--include-mechanical")
    final = out / "mechanical.scadpkg"
    invoke("enrich", "physics", "enrich", raw, "--config", cfg, "--output", final)
    invoke("validate-package", "physics", "validate", final)
    after = invoke("inspect-final", "physics", "inspect", final)
    embedded = after["sca_physics"]
    assert embedded["schema_version"] == "1.1"
    for node, requested in config["parts"].items():
        for section in ("rigid_body", "contact", "collision"):
            for field, value in requested[section].items():
                assert embedded["parts"][node][section][field] == value, (node, field)
    usd = out / "mechanical.usda"
    invoke("export", "usd", "export", final, usd)
    invoke("validate-usd", "usd", "validate", usd)
    report = json.loads(usd.with_suffix(".report.json").read_text())
    physics = report["physics"]
    assert physics["dynamic_body_count"] == 5 and physics["kinematic_body_count"] == 1 and physics["static_group_count"] == 2
    objects = {}
    materials = set()
    for role, node in identities.items():
        groups = [g for g in physics["groups"] if any(p["node_id"] == node for p in g["parts"])]
        assert len(groups) == 1, (role, groups)
        group = groups[0]
        part = next(p for p in group["parts"] if p["node_id"] == node)
        materials.add(part["contact_material_path"])
        record = {"node_id": node, "body_path": group["body_path"], "shape_paths": [part["shape_path"]],
                  "contact_material_path": part["contact_material_path"], "mode": modes[role],
                  "static_friction": part["contact"]["static_friction"]["value"],
                  "dynamic_friction": part["contact"]["dynamic_friction"]["value"],
                  "restitution": part["contact"]["restitution"]["value"], "mass_kg": group["mass_kg"]}
        for section in ("rigid_body", "contact", "collision"):
            for field, value in config["parts"][node][section].items():
                if field != "mode" and "value" in value:
                    record[field] = value["value"]
        objects[role] = record
    assert len(materials) == 8, "Shared geometry must not share occurrence contact material"
    expected = {"objects": objects, "scene_path": physics["scene"]["prim_path"]}
    (out / "expect.json").write_text(json.dumps(expected, indent=2))

    legacy = root / "personal-workspace/results/sca-physics/20261019_stable_coexistence_184500/validation"
    legacy_config = root / "personal-workspace/archive/plugin-baselines/20261019_pre_authoring/sca-physics/examples/pendulum/physics-input.json"
    legacy_final = out / "legacy.scadpkg"
    invoke("legacy-inspect", "physics", "inspect", legacy / "final.scadpkg")
    invoke("legacy-enrich", "physics", "enrich", legacy / "raw.scadpkg", "--config", legacy_config, "--output", legacy_final)
    invoke("legacy-validate", "physics", "validate", legacy_final)
    old_info = json.loads((out / "legacy-inspect.log").read_text())
    new_info = invoke("legacy-inspect-new", "physics", "inspect", legacy_final)
    assert old_info["sca_physics"] == new_info["sca_physics"], "Legacy resolved snapshot changed"
    invoke("legacy-export", "usd", "export", legacy_final, out / "legacy.usda")
    invoke("legacy-validate-usd", "usd", "validate", out / "legacy.usda")
    summary = {"ok": True, "legacy_snapshot_unchanged": True, "shared_definition": True,
               "independent_material_count": len(materials), "package_roundtrip": True,
               "export_reopen": True, "schema_version": "1.1", "backend_test_pending": True}
    (out / "pipeline-result.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
