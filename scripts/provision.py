"""Provision this payload and commit its independently checked runtime identity."""
import argparse
from pathlib import Path
import runpy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", required=True, type=Path)
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    runpy.run_path(str(scripts / "install_identity.py"))["provision"](scripts.parent, args.runtime_dir)


if __name__ == "__main__":
    main()
