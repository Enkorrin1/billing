"""Safe cross-platform entrypoint for the repository's Python test suite."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from _test_isolation import UnsafeTestDatabase, build_isolated_environment


ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Python tests with an isolated temporary database.")
    parser.add_argument("--pattern", default="test*.py", help="unittest discovery filename pattern")
    parser.add_argument("--start-directory", default="tests", help="unittest discovery start directory")
    parser.add_argument(
        "--deny-db",
        action="append",
        default=[],
        metavar="PATH",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    try:
        child_env, temp_holder = build_isolated_environment(denied_paths=args.deny_db)
    except UnsafeTestDatabase as exc:
        print(f"Test run refused: {exc}", file=sys.stderr)
        return 2

    try:
        bootstrap_dir = Path(child_env["BILLING_TEST_ROOT"]) / "python-startup"
        bootstrap_dir.mkdir(parents=True, exist_ok=True)
        (bootstrap_dir / "sitecustomize.py").write_text(
            "from _test_isolation import initialize_test_process\n"
            "initialize_test_process()\n",
            encoding="utf-8",
        )
        python_paths = [str(bootstrap_dir), str(ROOT)]
        python_paths.extend(
            value
            for value in child_env.get("PYTHONPATH", "").split(os.pathsep)
            if value and value not in python_paths
        )
        child_env["PYTHONPATH"] = os.pathsep.join(python_paths)

        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            args.start_directory,
            "-p",
            args.pattern,
            "-v",
        ]
        completed = subprocess.run(command, cwd=ROOT, env=child_env, check=False)
        return completed.returncode
    finally:
        if temp_holder is not None:
            temp_holder.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
