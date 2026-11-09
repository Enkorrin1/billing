import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_tests
from _test_isolation import UnsafeTestDatabase, install_sqlite_write_guard, validate_selected_database


class TestRunnerSafety(unittest.TestCase):
    def test_explicit_control_database_is_refused_without_being_modified(self):
        with tempfile.TemporaryDirectory(prefix="billing-guard-control-") as directory:
            control = Path(directory) / "control.db"
            original = b"harmless control file; not a SQLite database"
            control.write_bytes(original)

            with self.assertRaises(UnsafeTestDatabase):
                validate_selected_database(control, [control])

            self.assertEqual(control.read_bytes(), original)

    def test_sqlite_write_guard_blocks_control_file_without_touching_it(self):
        with tempfile.TemporaryDirectory(prefix="billing-guard-control-") as directory:
            control = Path(directory) / "control.db"
            original = b"harmless control file; not a SQLite database"
            control.write_bytes(original)
            install_sqlite_write_guard([control])

            import sqlite3

            with self.assertRaises(sqlite3.OperationalError):
                sqlite3.connect(control)

            self.assertEqual(control.read_bytes(), original)

    def test_runner_refuses_an_explicitly_denied_control_path(self):
        with tempfile.TemporaryDirectory(prefix="billing-guard-control-") as directory:
            control = Path(directory) / "control.db"
            original = b"harmless control file; not a SQLite database"
            control.write_bytes(original)
            with mock.patch.dict(os.environ, {"APP_DB": str(control)}):
                result = run_tests.main(["--deny-db", str(control)])

            self.assertEqual(result, 2)
            self.assertEqual(control.read_bytes(), original)

    def test_direct_python_and_pytest_entrypoints_refuse_before_app_import(self):
        project_root = Path(__file__).resolve().parents[1]
        journey_test = project_root / "tests" / "test_billing_finance_journey.py"
        commands = [
            ("unittest discovery", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", journey_test.name]),
            ("raw test script", [sys.executable, str(journey_test)]),
            ("test module", [sys.executable, "-m", "tests.test_billing_finance_journey"]),
            ("pytest module", [sys.executable, "-m", "pytest", str(journey_test), "-q"]),
        ]
        pytest = shutil.which("pytest")
        if pytest:
            commands.append(("pytest console", [pytest, str(journey_test), "-q"]))

        with tempfile.TemporaryDirectory(prefix="billing-guard-control-") as directory:
            control = Path(directory) / "control.db"
            original = b"harmless control file; not a SQLite database"
            control.write_bytes(original)
            env = os.environ.copy()
            env["APP_DB"] = str(control)
            env["BILLING_TEST_DENY_DB"] = str(control)
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

            for label, command in commands:
                with self.subTest(entrypoint=label):
                    result = subprocess.run(
                        command,
                        cwd=project_root,
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("Test isolation refused", result.stdout)
                    self.assertEqual(control.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
