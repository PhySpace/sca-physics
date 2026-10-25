"""Isaac 5 acceptance of the stable 0.1.1 eight-instance rigid-body fixture.

Inputs: --usd ASSET --expect JSON --report NEW_JSON. Expectation JSON contains
scene_path and objects:{role:{body_path,shape_paths,mode,gravity_enabled,
linear_damping,angular_damping,contact_offset,rest_offset,
friction_combine_mode,restitution_combine_mode}}. Scalar values or package
parameter wrappers are accepted; engine_default requires no USD value opinion.

The only stimulus is a one-time backend velocity seed. No tested physics
attribute, pose, solver setting, geometry or material is replaced by this tool.
Use --isaac-root INSTALL_DIR if VERSION is not above the active interpreter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import traceback


DT = 1 / 240
STEPS = 48


def plain(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if hasattr(value, "tolist"):
        return plain(value.tolist())
    try:
        return [plain(v) for v in value]
    except TypeError:
        return str(value)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def layer_hashes(stage):
    return {str(Path(layer.realPath).resolve()): sha256(layer.realPath)
            for layer in stage.GetUsedLayers() if not layer.anonymous and layer.realPath}


def expected_value(value):
    if isinstance(value, dict):
        return None if value.get("mode") == "engine_default" else value.get("value")
    return None if value == "engine_default" else value


def array(value):
    import numpy as np
    return np.asarray(value.numpy() if hasattr(value, "numpy") else value).copy()


def configuration(stage):
    result = {}
    for prim in stage.Traverse():
        attrs = {}
        for attribute in prim.GetAuthoredAttributes():
            name = attribute.GetName()
            if name in ("physics:velocity", "physics:angularVelocity"):
                continue
            if name.startswith(("physics:", "physxRigidBody:", "physxCollision:", "physxMaterial:", "physxScene:")):
                attrs[name] = plain(attribute.Get())
        if attrs:
            result[str(prim.GetPath())] = attrs
    return result


def run(source, expectation):
    import numpy as np
    from pxr import PhysicsSchemaTools, PhysxSchema, Usd, UsdGeom, UsdPhysics, UsdShade, UsdUtils
    from carb.eventdispatcher import get_eventdispatcher
    import omni.kit.app
    import omni.physx
    import omni.physics.tensors
    from omni.physx.bindings._physx import PhysicsSceneStats

    result = {"ok": False, "scope": "Eight-field stable 0.1.1 fixture: USD opinions, actual PhysX readback and limited free rigid dynamics",
              "dt_s": DT, "steps": STEPS, "stimuli": [], "forbidden_asset_parameter_overrides": [],
              "checks": [], "objects": {}, "parser_errors": [], "runtime_warnings": [],
              "limitations": ["Combine tokens are USD readback plus backend material registration evidence; no exposed C++ combine getter or contact-combination behavior test",
                              "Kinematic gravity and damping are readback only; no dynamic-integration claim for these fields",
                              "No contact, impact, robot, articulation or generic schema coverage test"]}

    def check(name, condition, actual, expected):
        result["checks"].append({"name": name, "ok": bool(condition), "actual": plain(actual), "expected": plain(expected)})

    def equal(name, actual, expected, tolerance=1e-6):
        if isinstance(expected, (bool, str)) or (isinstance(expected, list) and all(isinstance(v, str) for v in expected)):
            condition = actual == expected
        else:
            condition = actual is not None and np.allclose(actual, expected, rtol=1e-5, atol=tolerance)
        check(name, condition, actual, expected)

    def read_field(label, attribute, expected):
        value = expected_value(expected)
        actual = attribute.Get() if attribute else None
        authored = bool(attribute and attribute.HasAuthoredValueOpinion())
        if value is None:
            check(label + ": engine_default has no USD value opinion", not authored, authored, False)
        else:
            check(label + ": explicit USD opinion", authored, authored, True)
            equal(label + ": USD value", actual, value)
        return {"value": plain(actual), "has_authored_value": authored, "expected": plain(expected)}

    stage, view, attached, observer = None, None, False, None
    cache = UsdUtils.StageCache.Get()
    simulation = omni.physx.get_physx_simulation_interface()
    try:
        stage = Usd.Stage.Open(str(source))
        if not stage:
            raise ValueError("USD did not open")
        result["dependency_sha256_before"] = layer_hashes(stage)
        config_before = configuration(stage)
        stage.SetEditTarget(stage.GetSessionLayer())
        check("SI / Z stage convention", UsdGeom.GetStageMetersPerUnit(stage) == 1 and UsdPhysics.GetStageKilogramsPerUnit(stage) == 1
              and str(UsdGeom.GetStageUpAxis(stage)) == "Z", {"metres": UsdGeom.GetStageMetersPerUnit(stage),
              "kilograms": UsdPhysics.GetStageKilogramsPerUnit(stage), "up_axis": str(UsdGeom.GetStageUpAxis(stage))}, "m/kg/Z")
        scene_path = expectation["scene_path"]
        scene = UsdPhysics.Scene(stage.GetPrimAtPath(scene_path))
        if not scene:
            raise ValueError("Expected packaged PhysicsScene: " + scene_path)
        scene_px = PhysxSchema.PhysxSceneAPI(scene.GetPrim())
        # The legacy exporter need not author a PhysxSceneAPI. Verify actual CPU
        # below; absence of this optional scene field is not an asset failure.
        check("fixture does not explicitly request GPU dynamics", scene_px.GetEnableGPUDynamicsAttr().Get() is not True,
              scene_px.GetEnableGPUDynamicsAttr().Get(), "false or unauthored; actual CPU device checked after attach")
        check("exact eight expected roles", set(expectation["objects"]) == {
            "anchor", "static", "dynamic", "kinematic", "gravity_off", "linear_damped", "angular_damped", "control"},
            sorted(expectation["objects"]), "eight named fixture roles")
        xform_cache = UsdGeom.XformCache()
        modes, material_paths = {}, {}
        for role, expected in expectation["objects"].items():
            body = stage.GetPrimAtPath(expected["body_path"])
            if not body:
                raise ValueError(f"Missing {role} body prim: {expected['body_path']}")
            rigid = UsdPhysics.RigidBodyAPI(body)
            enabled = bool(body.HasAPI(UsdPhysics.RigidBodyAPI) and rigid.GetRigidBodyEnabledAttr().Get())
            mode = "static" if not enabled else ("kinematic" if rigid.GetKinematicEnabledAttr().Get() else "dynamic")
            modes[role] = mode
            wanted_mode = expected_value(expected.get("mode"))
            if wanted_mode is not None:
                equal(role + ": USD body mode", mode, wanted_mode)
            body_px = PhysxSchema.PhysxRigidBodyAPI(body)
            audit = {"body_path": str(body.GetPath()), "resolved_mode": mode,
                     "initial_world_origin_m": plain(xform_cache.GetLocalToWorldTransform(body).ExtractTranslation()),
                     "fields": {}, "shapes": [], "samples": []}
            result["objects"][role] = audit
            if "mass_kg" in expected:
                equal(role + ": preserved authored native mass", UsdPhysics.MassAPI(body).GetMassAttr().Get(), expected["mass_kg"], 1e-9)
            for field, attribute_name in (("linear_damping", "physxRigidBody:linearDamping"),
                                           ("angular_damping", "physxRigidBody:angularDamping")):
                audit["fields"][field] = read_field(f"{role}.{field}", body.GetAttribute(attribute_name), expected.get(field, "engine_default"))
            gravity_expected = expected.get("gravity_enabled", "engine_default")
            target_value = expected_value(gravity_expected)
            disable_expected = "engine_default" if target_value is None else not target_value
            audit["fields"]["disable_gravity"] = read_field(role + ".disable_gravity",
                body.GetAttribute("physxRigidBody:disableGravity"), disable_expected)
            for shape_path in expected["shape_paths"]:
                shape = stage.GetPrimAtPath(shape_path)
                if not shape:
                    raise ValueError("Missing collider " + shape_path)
                check(role + ": actual enabled collider " + shape_path,
                      shape.HasAPI(UsdPhysics.CollisionAPI) and UsdPhysics.CollisionAPI(shape).GetCollisionEnabledAttr().Get() is True,
                      shape.GetAppliedSchemas(), "enabled CollisionAPI")
                shape_record = {"path": shape_path, "fields": {}}
                audit["shapes"].append(shape_record)
                for field, usd_name in (("contact_offset", "physxCollision:contactOffset"), ("rest_offset", "physxCollision:restOffset")):
                    shape_record["fields"][field] = read_field(f"{role}.{field}", shape.GetAttribute(usd_name), expected.get(field, "engine_default"))
                material, binding = UsdShade.MaterialBindingAPI(shape).ComputeBoundMaterial(materialPurpose="physics")
                if not material or not binding:
                    raise ValueError("Missing bound physical material for " + shape_path)
                material_paths[shape_path] = str(material.GetPath())
                shape_record["physics_material_path"] = str(material.GetPath())
                if "contact_material_path" in expected:
                    equal(role + ": bound contact material path", str(material.GetPath()), expected["contact_material_path"])
                material_api = UsdPhysics.MaterialAPI(material.GetPrim())
                for field, getter in (("static_friction", material_api.GetStaticFrictionAttr),
                                      ("dynamic_friction", material_api.GetDynamicFrictionAttr),
                                      ("restitution", material_api.GetRestitutionAttr)):
                    if field in expected:
                        equal(f"{role}: preserved authored {field}", getter().Get(), expected[field])
                for field, usd_name in (("friction_combine_mode", "physxMaterial:frictionCombineMode"),
                                         ("restitution_combine_mode", "physxMaterial:restitutionCombineMode")):
                    shape_record["fields"][field] = read_field(f"{role}.{field}", material.GetPrim().GetAttribute(usd_name), expected.get(field, "engine_default"))

        def on_error(event):
            payload = plain(dict(event.payload))
            if payload.get("source") == "usdrt.population.plugin" and payload.get("message") == "Last global time was not created. Did you call setEnableUsdNoticeHandling?":
                result["runtime_warnings"].append(payload)
            else:
                result["parser_errors"].append(payload)

        observer = get_eventdispatcher().observe_event(event_name=omni.kit.app.GLOBAL_EVENT_ERROR_LOG_IMMEDIATE,
            on_event=on_error, observer_name="Stable 0.1.1 exported eight-field fixture")
        stage_id = cache.Insert(stage).ToLongInt()
        simulation.attach_stage(stage_id)
        attached = True
        simulation.simulate(DT, 0.0)
        simulation.fetch_results()
        view = omni.physics.tensors.create_simulation_view("numpy", stage_id)
        view.set_subspace_roots("/")
        equal("actual tensor device", str(view.device), "cpu")
        body_views = {}
        for role, expected in expectation["objects"].items():
            if modes[role] == "static":
                continue
            rigid_view = view.create_rigid_body_view([expected["body_path"]])
            equal(role + ": backend body count", int(rigid_view.count), 1)
            equal(role + ": backend exact body path", list(rigid_view.prim_paths), [expected["body_path"]])
            body_views[role] = rigid_view
            audit = result["objects"][role]
            backend = {"body_paths": list(rigid_view.prim_paths), "mass_kg": plain(array(rigid_view.get_masses())),
                       "disable_gravity": plain(array(rigid_view.get_disable_gravities())),
                       "contact_offsets_m": plain(array(rigid_view.get_contact_offsets())),
                       "rest_offsets_m": plain(array(rigid_view.get_rest_offsets())),
                       "material_static_dynamic_restitution": plain(array(rigid_view.get_material_properties()))}
            audit["backend"] = backend
            if "mass_kg" in expected:
                check(role + ": preserved native mass in actual backend", np.allclose(array(rigid_view.get_masses()), expected["mass_kg"], atol=1e-9, rtol=1e-5), backend["mass_kg"], expected["mass_kg"])
            if all(field in expected for field in ("static_friction", "dynamic_friction", "restitution")):
                wanted_material = [expected[field] for field in ("static_friction", "dynamic_friction", "restitution")]
                check(role + ": actual backend material three coefficients", np.allclose(array(rigid_view.get_material_properties()), wanted_material, atol=1e-6, rtol=1e-5), backend["material_static_dynamic_restitution"], wanted_material)
            for field, actual in (("contact_offset", array(rigid_view.get_contact_offsets())), ("rest_offset", array(rigid_view.get_rest_offsets()))):
                wanted = expected_value(expected.get(field))
                if wanted is not None:
                    check(f"{role}.{field}: actual backend getter", np.allclose(actual, wanted, atol=1e-9, rtol=1e-5), actual, wanted)
            wanted_gravity = expected_value(expected.get("gravity_enabled"))
            if wanted_gravity is not None:
                check(role + ": actual backend gravity flag", np.all(array(rigid_view.get_disable_gravities()) == int(not wanted_gravity)),
                      backend["disable_gravity"], int(not wanted_gravity))
            seed = np.zeros((1, 6), dtype=np.float32)
            if role in ("linear_damped", "control"):
                seed[0, 0] = .2
            if role in ("angular_damped", "control"):
                seed[0, 5] = 2.0
            if np.any(seed):
                rigid_view.set_velocities(seed, np.array([0], dtype=np.uint32))
                result["stimuli"].append({"role": role, "type": "one-time backend initial velocity",
                    "linear_m_s": seed[0, :3].tolist(), "angular_rad_s": seed[0, 3:].tolist(),
                    "scope": "external test stimulus; no asset coefficient or pose edit"})

        registration = omni.physx.get_physxunittests_interface()
        for shape_path, wanted in material_paths.items():
            actual = [str(p) for p in registration.get_materials_paths(shape_path)]
            check("backend registered physical material: " + shape_path, wanted in actual, actual, wanted)
        actual_stats = registration.get_physics_stats()
        result["actual_physx_statistics"] = plain(actual_stats)
        for mode, key in (("dynamic", "numDynamicRigids"), ("kinematic", "numKinematicBodies"), ("static", "numStaticRigids")):
            equal("backend mode count " + mode, actual_stats[key], sum(m == mode for m in modes.values()))
        equal("backend articulation count", actual_stats["numArticulations"], 0)

        def sample(time):
            for role, rigid_view in body_views.items():
                result["objects"][role]["samples"].append({"time_after_stimulus_s": time,
                    "pose_xyz_xyzw": array(rigid_view.get_transforms())[0].tolist(),
                    "velocity_xyz_m_s_omega_xyz_rad_s": array(rigid_view.get_velocities())[0].tolist()})

        sample(0.0)
        for step in range(1, STEPS+1):
            simulation.simulate(DT, step*DT)
            simulation.fetch_results()
            sample(step*DT)
        for role, audit in result["objects"].items():
            if modes[role] == "static":
                final = UsdGeom.XformCache().GetLocalToWorldTransform(stage.GetPrimAtPath(audit["body_path"])).ExtractTranslation()
                equal(role + ": static authored frame preserved", list(final), audit["initial_world_origin_m"], 1e-9)
                audit["behavior_evidence"] = "actual static-actor counts and registered collider; unchanged authored static frame"
                continue
            first, last = audit["samples"][0], audit["samples"][-1]
            p0, p1 = np.array(first["pose_xyz_xyzw"]), np.array(last["pose_xyz_xyzw"])
            v0, v1 = np.array(first["velocity_xyz_m_s_omega_xyz_rad_s"]), np.array(last["velocity_xyz_m_s_omega_xyz_rad_s"])
            check(role + ": finite backend state", np.isfinite(p1).all() and np.isfinite(v1).all(), last, "finite")
            if role in ("kinematic", "gravity_off"):
                check(role + ": no uncommanded translation", np.linalg.norm(p1[:3]-p0[:3]) < 1e-6, p1[:3]-p0[:3], "less than 1 micrometre")
            if role == "dynamic":
                gravity = np.asarray(scene.GetGravityDirectionAttr().Get()) * scene.GetGravityMagnitudeAttr().Get()
                predicted = p0[:3] + v0[:3]*(DT*STEPS) + gravity * DT**2 * STEPS*(STEPS+1)/2
                check("dynamic: actual free gravity integration", np.allclose(p1[:3], predicted, atol=2e-5, rtol=0), p1[:3], predicted)
                check("dynamic: visible gravity displacement", p0[2]-p1[2] > .15, p0[2]-p1[2], "greater than .15m")
            for field, component in (("linear_damping", 0), ("angular_damping", 5)):
                if (field == "linear_damping" and role in ("linear_damped", "control")) or (field == "angular_damping" and role in ("angular_damped", "control")):
                    damping = expected_value(expectation["objects"][role][field])
                    predicted = v0[component] * max(0, 1-float(damping)*DT)**STEPS
                    check(f"{role}: actual {field} decay versus c*dt update", np.isclose(v1[component], predicted, atol=1e-4, rtol=3e-4),
                          v1[component], predicted)
                    audit.setdefault("damping_behavior", {})[field] = {"initial": v0[component], "final": v1[component],
                        "predicted": predicted, "coefficient_1_s": damping, "duration_s": DT*STEPS}
        result["configuration_unchanged_in_stage"] = config_before == configuration(stage)
        check("all tested asset parameters unchanged", result["configuration_unchanged_in_stage"], configuration(stage), config_before)
        check("no PhysX parser/runtime errors", not result["parser_errors"], result["parser_errors"], [])
        result["ok"] = all(c["ok"] for c in result["checks"])
    except Exception:
        result["traceback"] = traceback.format_exc()
    finally:
        observer = None
        if view is not None:
            view.invalidate()
        if attached:
            simulation.detach_stage()
        if stage is not None:
            result["dependency_sha256_after"] = layer_hashes(stage)
            result["source_files_unchanged"] = result["dependency_sha256_after"] == result.get("dependency_sha256_before")
            result["ok"] = result["ok"] and result["source_files_unchanged"]
            cache.Erase(stage)
    return plain(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usd", type=Path, required=True)
    parser.add_argument("--expect", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--isaac-root", type=Path)
    args, _ = parser.parse_known_args()
    if args.report.exists():
        parser.error("Use a new report path")
    roots = [args.isaac_root] if args.isaac_root else Path(sys.executable).resolve().parents
    version_file = next((root / "VERSION" for root in roots if (root / "VERSION").is_file()), None)
    if version_file is None:
        parser.error("Cannot locate Isaac VERSION; pass --isaac-root INSTALL_DIR")
    isaac_version = version_file.read_text(encoding="utf-8").strip()
    source = args.usd.resolve()
    expectation = json.loads(args.expect.read_text(encoding="utf-8-sig"))
    from isaacsim import SimulationApp
    # Avoid Kit's immediate process exit at shutdown so a failed report can
    # propagate its nonzero Python exit status to the process recorder.
    app = SimulationApp({"headless": True, "disable_viewport_updates": True, "fast_shutdown": False})
    result = {"ok": False}
    try:
        result = run(source, expectation)
        from pxr import Usd
        import omni.physx
        result.update(usd=str(source), expectation=str(args.expect.resolve()), expectation_sha256=sha256(args.expect),
                      checker_sha256=sha256(__file__), python=sys.version, openusd=list(Usd.GetVersion()),
                      physx_module=str(omni.physx.__file__), isaac_version=isaac_version)
    except Exception:
        result["traceback"] = traceback.format_exc()
    finally:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(plain(result), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            print(json.dumps({"ok": result["ok"], "report": str(args.report),
                              "checks": len(result.get("checks", [])), "failed": [c["name"] for c in result.get("checks", []) if not c["ok"]]}), flush=True)
        finally:
            app.close()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
