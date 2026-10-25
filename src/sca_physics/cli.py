"""Inspect, generate reproducible inputs, enrich, and strictly validate packages."""

import argparse
import json
from pathlib import Path
import sys


def _json(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f"JSON non-finite value {value}")
    obj = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique, parse_constant=invalid)
    if not isinstance(obj, dict):
        raise ValueError("configuration must be a JSON object")
    return obj


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sca-physics")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("cable-presets", help="show versioned initial cable categories and their uncalibrated status")
    for name in ("inspect", "validate", "template", "enrich", "update", "set-deformable", "set-rigid-chain", "configure-cable"):
        cmd = sub.add_parser(name)
        cmd.add_argument("package", type=Path)
        if name == "template":
            cmd.add_argument("--output", type=Path, required=True)
            cmd.add_argument("--include-mechanical", action="store_true", help="include optional schema 1.1 engine-default requests; body mode remains native")
        if name in {"enrich", "update", "set-deformable", "set-rigid-chain", "configure-cable"}:
            cmd.add_argument("--config", type=Path)
            cmd.add_argument("--output", type=Path)
            cmd.add_argument("--report", type=Path)
        if name == "set-deformable":
            cmd.add_argument("--target", required=True, help="exact CAD occurrence node_id, shown by inspect")
            cmd.add_argument("--material", type=Path, help="sparse SI material changes; reuses the same target and verified mesh")
            cmd.add_argument("--convert-rigid", action="store_true", help="explicitly remove the selected occurrence's prior rigid_body addon block")
            cmd.add_argument("--cable-id", help="optional first declaration identity; later updates retain this identity")
        if name in {"set-rigid-chain", "configure-cable"}:
            cmd.add_argument("--target", required=True, help="exact existing CAD part occurrence node_id")
            cmd.add_argument("--base-config", type=Path, help="optional initial sparse physics config, only for a raw package without sca_physics")
            cmd.add_argument("--chain-id", help="optional first declaration identity")
            cmd.add_argument("--convert-rigid", action="store_true")
            cmd.add_argument("--replace-deformable", action="store_true", help="explicitly replace this target's FEM declaration")
        if name == "configure-cable":
            cmd.add_argument("--description", help="parsed intent text; may be supplied instead in --config")
            cmd.add_argument("--reconfigure", action="store_true", help="explicitly replace an existing frozen decision; never done during export")
        if name == "validate":
            cmd.add_argument("--expect", type=Path, help="compare embedded resolved metadata to an independent JSON snapshot")
    args = parser.parse_args(argv)
    try:
        from .runtime import check
        facts = check()
        if args.command == "check":
            print(json.dumps(facts, ensure_ascii=False, indent=2))
            return 0
        if args.command == "cable-presets":
            from .cable_presets import PRESETS, PRESET_VERSION, RULE_VERSION, QUALITY, DEFAULT_RESOURCE_BUDGET, LIMITATIONS
            print(json.dumps({"version": PRESET_VERSION, "rule_version": RULE_VERSION, "presets": PRESETS,
                "quality": QUALITY, "default_resource_budget": DEFAULT_RESOURCE_BUDGET,
                "calibrated": False, "limitations": LIMITATIONS}, ensure_ascii=False, indent=2))
            return 0
        from simplecadapi import read_product_package, encode_product_package
        from .contract import inventory, template_config, validate_config
        from .package_io import enrich_package, write_new, write_outputs
        package = read_product_package(data=args.package)
        embedded = package.root_definition.metadata.get("sca_physics")
        if args.command == "inspect":
            result = {"package": str(args.package.resolve()), "root_definition": package.root_id,
                      "metadata_location": package.root_path + "#/metadata/sca_physics",
                      "inventory": inventory(package), "sca_physics": embedded}
        elif args.command == "template":
            result = template_config(package, include_mechanical=args.include_mechanical)
            write_new(args.output, (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        elif args.command == "validate":
            if embedded is None:
                raise ValueError("package has no metadata.sca_physics")
            validate_config(package, embedded)
            if args.expect and embedded != _json(args.expect):
                raise ValueError("embedded physics differs from the expected snapshot")
            result = {"valid": True, "package_hash": package.content_hash, "schema_version": embedded["schema_version"]}
        else:
            output = args.output or args.package.with_name(args.package.stem + ".physics.scadpkg")
            report_path = args.report or output.with_suffix(".physics-report.json")
            for target in (output, report_path):
                if target.exists():
                    raise ValueError(f"output exists: {target}; choose a new path")
            if output.resolve() == report_path.resolve():
                raise ValueError("package output and report must have distinct paths")
            config = _json(args.config) if args.config else None
            if args.command == "set-deformable":
                from .deformable import upsert_deformable_volume
                config = upsert_deformable_volume(package, args.target, config,
                    material=_json(args.material) if args.material else None,
                    convert_rigid=args.convert_rigid, cable_id=args.cable_id)
            if args.command == "set-rigid-chain":
                if config is None:
                    raise ValueError("set-rigid-chain requires --config with an explicit complete declaration")
                from .rigid_chain import upsert_rigid_chain
                config = upsert_rigid_chain(package, args.target, config, chain_id=args.chain_id,
                    convert_rigid=args.convert_rigid, replace_deformable=args.replace_deformable,
                    base_config=_json(args.base_config) if args.base_config else None)
            if args.command == "configure-cable":
                from .cable_inference import configure_cable
                config = config or {}
                if args.description is not None:
                    if "description" in config and config["description"] != args.description:
                        raise ValueError("--description conflicts with the explicit config description")
                    config["description"] = args.description
                config = configure_cable(package, args.target, config, chain_id=args.chain_id,
                    convert_rigid=args.convert_rigid, replace_deformable=args.replace_deformable,
                    base_config=_json(args.base_config) if args.base_config else None, reconfigure=args.reconfigure)
            if args.command == "update":
                if config is None:
                    raise ValueError("update requires --config with a sparse source-aware patch")
                from .update import update_package
                enriched, preserved = update_package(package, config)
            else:
                enriched, preserved = enrich_package(package, config)
            result = {**preserved, "input": str(args.package.resolve()), "output": str(output.resolve()),
                      "metadata_location": enriched.root_path + "#/metadata/sca_physics",
                      "sca_physics": enriched.root_definition.metadata["sca_physics"]}
            write_outputs({output: encode_product_package(enriched),
                           report_path: (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, ImportError, RuntimeError) as exc:
        print(f"sca-physics: {exc}", file=sys.stderr)
        return 2
