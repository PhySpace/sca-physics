"""Code identity rejection tests; fake files are never imported as business modules."""
import json
from pathlib import Path
import runpy
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
H = runpy.run_path(str(ROOT / "scripts/install_identity.py"))


def fixture_install(tmp_path, monkeypatch, *, usd=False):
    payload = tmp_path / ("sca-usd-export" if usd else "sca-physics")
    name = payload.name
    module = name.replace("-", "_")
    package = payload / "src" / module
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("raise RuntimeError('must not import before identity check')\n")
    requirements = 'dependencies = ["sca-physics==0.1.7rc2"]\n' if usd else 'dependencies = []\n'
    (payload / "pyproject.toml").write_text('[project]\nname = "' + name + '"\nversion = "0.1.7rc2"\n' + requirements)
    runtime = tmp_path / "runtime"
    prefix = runtime / ".venv"
    site = prefix / "Lib/site-packages"
    (site / module).mkdir(parents=True)
    (site / module / "__init__.py").write_bytes((package / "__init__.py").read_bytes())
    dist = site / (module + "-0.1.7rc2.dist-info")
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.4\nName: " + name + "\nVersion: 0.1.7rc2\n")
    (prefix / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "base"))
    monkeypatch.setattr(sys.modules["sysconfig"], "get_path", lambda *_: str(site))
    from types import SimpleNamespace
    monkeypatch.setattr(sys.modules["importlib.util"], "find_spec", lambda name: SimpleNamespace(origin=str(site / name / "__init__.py")))
    receipt = {"schema_version": 1, "status": "ready", "payload_root": str(payload.resolve()),
               "package": H["source_identity"](payload), "peer": None}
    if usd:
        peer_root = site / "sca_physics"
        peer_root.mkdir()
        (peer_root / "__init__.py").write_text("PEER = 1\n")
        peer_dist = site / "sca_physics-0.1.7rc2.dist-info"
        peer_dist.mkdir()
        (peer_dist / "METADATA").write_text("Metadata-Version: 2.4\nName: sca-physics\nVersion: 0.1.7rc2\n")
        files = H["file_manifest"](peer_root)
        receipt["peer"] = {"name": "sca-physics", "version": "0.1.7rc2", "module": "sca_physics",
                           "files": files, "code_sha256": H["fingerprint"](files)}
    H["atomic_json"](runtime / H["RECEIPT"], receipt)
    return payload, runtime, site, receipt


def test_matching_bytes_need_no_business_import(tmp_path, monkeypatch):
    payload, runtime, _, _ = fixture_install(tmp_path, monkeypatch)
    result = H["guard"](payload, runtime)
    assert result["package"]["version"] == "0.1.7rc2"


def test_same_version_old_runtime_is_rejected(tmp_path, monkeypatch):
    payload, runtime, site, _ = fixture_install(tmp_path, monkeypatch)
    (site / "sca_physics/__init__.py").write_text("OLD = True\n")
    with pytest.raises(ValueError, match="runtime code differs"):
        H["guard"](payload, runtime)


def test_extra_deleted_module_is_rejected(tmp_path, monkeypatch):
    payload, runtime, site, _ = fixture_install(tmp_path, monkeypatch)
    (site / "sca_physics/stale.py").write_text("OLD = True\n")
    with pytest.raises(ValueError, match="extra="):
        H["guard"](payload, runtime)


def test_payload_update_requires_provision(tmp_path, monkeypatch):
    payload, runtime, _, _ = fixture_install(tmp_path, monkeypatch)
    (payload / "src/sca_physics/__init__.py").write_text("NEW = True\n")
    with pytest.raises(ValueError, match="changed since provision"):
        H["guard"](payload, runtime)


def test_missing_receipt_fails_closed(tmp_path, monkeypatch):
    payload, runtime, _, _ = fixture_install(tmp_path, monkeypatch)
    (runtime / H["RECEIPT"]).unlink()
    with pytest.raises(ValueError, match="receipt is missing"):
        H["guard"](payload, runtime)


def test_cache_is_ignored_but_dependency_change_is_not(tmp_path, monkeypatch):
    payload, runtime, site, _ = fixture_install(tmp_path, monkeypatch)
    cache = site / "sca_physics/__pycache__"
    cache.mkdir()
    (cache / "old.pyc").write_bytes(b"old")
    H["guard"](payload, runtime)
    with (payload / "pyproject.toml").open("a") as f:
        f.write('description = "metadata changed"\n')
    with pytest.raises(ValueError, match="changed since provision"):
        H["guard"](payload, runtime)


def test_wheel_identity_reads_bytes_without_import(tmp_path):
    wheel = tmp_path / "example.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr("sca_physics/__init__.py", "raise RuntimeError('no import')\n")
        z.writestr("sca_physics-0.1.7rc2.dist-info/METADATA", "Name: sca-physics\nVersion: 0.1.7rc2\n")
    actual = H["wheel_identity"](wheel, "sca-physics")
    assert actual["version"] == "0.1.7rc2"
    assert actual["files"]["__init__.py"]
