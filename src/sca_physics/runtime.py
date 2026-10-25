"""Fast descriptor probe; importing the CAD kernel is reserved for operations."""

import importlib.metadata
import importlib.util
import os
from pathlib import Path
import platform
import sys


def check() -> dict:
    prefix = Path(sys.prefix).resolve()
    if sys.prefix == sys.base_prefix or sys.version_info[:2] != (3, 12):
        raise ValueError("sca-physics requires its own CPython 3.12 virtual environment")
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise ValueError("this build was verified on windows-x86_64")
    expected = os.environ.get("SCA_RUNTIME_DIR")
    if expected and prefix != (Path(expected) / ".venv").resolve():
        raise ValueError("interpreter does not belong to SCA_RUNTIME_DIR/.venv")
    if "include-system-site-packages = false" not in (prefix / "pyvenv.cfg").read_text().lower():
        raise ValueError("system site packages must not be inherited")
    versions = {name: importlib.metadata.version(name) for name in ("simplecadapi", "sca-physics")}
    if versions["simplecadapi"] != "2.2.5":
        raise ValueError("only SCA 2.2.5 has been validated")
    origins = {}
    for module in ("simplecadapi", "sca_physics"):
        spec = importlib.util.find_spec(module)
        if not spec or not spec.origin or not Path(spec.origin).resolve().is_relative_to(prefix):
            raise ValueError(f"{module} must be installed inside the addon environment")
        origins[module] = spec.origin
    return {"ok": True, "executable": sys.executable, "prefix": str(prefix),
            "versions": versions, "origins": origins, "system_site_packages": False}
