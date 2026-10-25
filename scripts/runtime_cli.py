"""Guard installed business bytes before dispatching Windows data arguments."""
import base64
import json
import os
from pathlib import Path
import runpy
import sys


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise ValueError("Run this entry with python -I -B")
    if len(sys.argv) != 2 or len(sys.argv[1]) > 6000:
        raise ValueError("expected a base64 JSON argument array, at most 6000 characters")
    args = json.loads(base64.b64decode(sys.argv[1], validate=True).decode("utf-8"))
    if not isinstance(args, list) or not 1 <= len(args) <= 256 or not all(isinstance(x, str) and "\x00" not in x for x in args):
        raise ValueError("expected 1..256 string arguments without NUL")
    scripts = Path(__file__).resolve().parent
    runtime = os.environ.get("SCA_RUNTIME_DIR")
    if not runtime:
        raise ValueError("SCA_RUNTIME_DIR is missing; invoke this installation through its dispatcher")
    runpy.run_path(str(scripts / "install_identity.py"))["guard"](scripts.parent, runtime)
    from sca_physics.cli import main as cli_main
    return cli_main(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, ImportError) as exc:
        print(f"sca-physics: {exc}", file=sys.stderr)
        raise SystemExit(2)
