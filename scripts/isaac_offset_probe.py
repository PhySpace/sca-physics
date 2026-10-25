"""Probe Isaac 5's actual rigid-collider offset domain with tiny in-memory cubes.

This diagnoses the local Omni PhysX parser and backend; it does not change any
SCA package, exported asset, installation or persistent simulation setting.
Run with the selected Isaac installation's python.bat -B SCRIPT --report NEW.json.
Use --isaac-root INSTALL_DIR if VERSION is not above the active interpreter.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback


def plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    try:
        return [plain(v) for v in value]
    except TypeError:
        return str(value)


def probe(name, contact, rest, expected):
    import numpy as np
    from pxr import Gf, PhysicsSchemaTools, PhysxSchema, Usd, UsdGeom, UsdPhysics, UsdUtils
    from carb.eventdispatcher import get_eventdispatcher
    import omni.kit.app
    import omni.physx
    import omni.physics.tensors
    from omni.physx.bindings._physx import PhysicsSceneStats

    result = {"name": name, "requested_contact_offset_m": contact,
              "requested_rest_offset_m": rest, "expected_accepted": expected,
              "executed": False, "accepted": False, "parser_errors": [], "runtime_warnings": []}
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, "Z")
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdPhysics.SetStageKilogramsPerUnit(stage, 1.0)
    scene = UsdPhysics.Scene.Define(stage, "/World/Scene")
    scene.CreateGravityDirectionAttr(Gf.Vec3f(0, 0, -1))
    scene.CreateGravityMagnitudeAttr(0.0)
    px_scene = PhysxSchema.PhysxSceneAPI.Apply(scene.GetPrim())
    px_scene.CreateEnableGPUDynamicsAttr(False)
    px_scene.CreateBroadphaseTypeAttr("MBP")
    px_scene.CreateSolverTypeAttr("TGS")
    cube = UsdGeom.Cube.Define(stage, "/World/Cube")
    cube.CreateSizeAttr(0.1)
    cube.AddTranslateOp().Set(Gf.Vec3d(0, 0, 1))
    body = cube.GetPrim()
    UsdPhysics.RigidBodyAPI.Apply(body)
    UsdPhysics.MassAPI.Apply(body).CreateMassAttr(1.0)
    UsdPhysics.CollisionAPI.Apply(body)
    collision = PhysxSchema.PhysxCollisionAPI.Apply(body)
    if contact is not None:
        collision.CreateContactOffsetAttr(contact)
    if rest is not None:
        collision.CreateRestOffsetAttr(rest)
    result["usd_authored"] = {"contact": collision.GetContactOffsetAttr().HasAuthoredValueOpinion(),
                              "rest": collision.GetRestOffsetAttr().HasAuthoredValueOpinion()}
    result["usd_readback"] = {"contact": str(collision.GetContactOffsetAttr().Get()),
                             "rest": str(collision.GetRestOffsetAttr().Get())}
    simulation = omni.physx.get_physx_simulation_interface()
    cache = UsdUtils.StageCache.Get()
    attached, view = False, None

    def on_error(event):
        payload = plain(dict(event.payload))
        if payload.get("source") == "usdrt.population.plugin" and payload.get("message") == "Last global time was not created. Did you call setEnableUsdNoticeHandling?":
            result["runtime_warnings"].append(payload)
        else:
            result["parser_errors"].append(payload)

    observer = get_eventdispatcher().observe_event(
        event_name=omni.kit.app.GLOBAL_EVENT_ERROR_LOG_IMMEDIATE,
        on_event=on_error, observer_name="Stable 0.1.1 collider-offset domain probe")
    try:
        stage_id = cache.Insert(stage).ToLongInt()
        simulation.attach_stage(stage_id)
        attached = True
        simulation.simulate(1/240, 0.0)
        simulation.fetch_results()
        view = omni.physics.tensors.create_simulation_view("warp", stage_id)
        rigid = view.create_rigid_body_view("/World/Cube")
        if rigid.count != 1:
            raise AssertionError(f"Expected one real PhysX rigid, got {rigid.count}")
        actual_contact = float(rigid.get_contact_offsets().numpy().reshape(-1)[0])
        actual_rest = float(rigid.get_rest_offsets().numpy().reshape(-1)[0])
        stats = PhysicsSceneStats()
        got_stats = omni.physx.get_physx_statistics_interface().get_physx_scene_statistics(
            stage_id, PhysicsSchemaTools.sdfPathToInt(scene.GetPath()), stats)
        result["backend"] = {"contact_offset_m": actual_contact, "rest_offset_m": actual_rest,
                             "body_paths": list(rigid.prim_paths), "device": str(view.device),
                             "actual_dynamic_count": int(stats.nb_dynamic_rigids) if got_stats else None,
                             "statistics_available": bool(got_stats)}
        result["requested_values_match_backend"] = bool((contact is None or np.isclose(actual_contact, contact, atol=1e-9, rtol=1e-6))
                                                       and (rest is None or np.isclose(actual_rest, rest, atol=1e-9, rtol=1e-6)))
        result["accepted"] = bool(result["requested_values_match_backend"] and not result["parser_errors"])
        result["executed"] = True
    except Exception:
        result["traceback"] = traceback.format_exc()
    finally:
        observer = None
        if view is not None:
            view.invalidate()
        if attached:
            simulation.detach_stage()
        cache.Erase(stage)
    result["ok"] = result["executed"] and (expected is None or result["accepted"] == expected)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
    from isaacsim import SimulationApp
    app = SimulationApp({"headless": True, "disable_viewport_updates": True})
    result = {"ok": False, "scope": "Isaac 5 / Omni PhysX 107.3.18 parser plus real backend offset readback",
              "asset_files_modified": [], "simulation_settings_modified": [], "probes": []}
    try:
        import omni.physx
        from pxr import Usd
        result["versions"] = {"python": sys.version, "openusd": list(Usd.GetVersion()),
                              "physx_module": str(omni.physx.__file__),
                              "isaac_install_version": isaac_version}
        for case in (
            ("positive_contact_zero_rest", .005, 0.0, True),
            ("positive_contact_negative_rest", .005, -.001, True),
            ("zero_contact_negative_rest", 0.0, -.001, False),
            ("zero_contact_zero_rest", 0.0, 0.0, False),
            ("equal_positive_offsets", .001, .001, False),
            ("rest_exceeds_contact", .001, .002, False),
            ("negative_contact", -.001, -.002, False),
            ("engine_default_no_authored_offsets", None, None, True),
        ):
            item = probe(*case)
            result["probes"].append(item)
            print(json.dumps({k: item[k] for k in ("name", "executed", "accepted", "ok")}), flush=True)
        result["ok"] = all(p["ok"] for p in result["probes"])
    except Exception:
        result["traceback"] = traceback.format_exc()
    finally:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"ok": result["ok"], "report": str(args.report)}), flush=True)
        finally:
            app.close()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
