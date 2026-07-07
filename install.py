#!/usr/bin/env python3
"""Install cq into the current Python environment (no new venv created).

Usage:
    python install.py              # install with runtime dependencies
    python install.py --dev        # also install pytest / dev dependencies

This installs the package in editable mode using the interpreter that runs
this script, so you can run it from inside an existing conda env, venv, or
system Python without creating a new virtual environment.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Install cq into the current Python environment.")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Also install development dependencies (pytest, pytest-asyncio).",
    )
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(project_root, ".[dev]") if args.dev else project_root

    cmd = [sys.executable, "-m", "pip", "install", "-e", target]

    print(f"Installing cq using: {' '.join(cmd)}")
    print(f"Interpreter: {sys.executable}")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as exc:
        print(f"Installation failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode

    print("\nInstallation complete. You can now run:")
    print("  cq init")
    print("  cq tui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
