"""Safety bootstrap shared by the repository's Python test entrypoints."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib.parse import unquote, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parent
PRODUCTION_DB = PROJECT_ROOT / "data" / "app.db"
_TEMP_DIRS: list[tempfile.TemporaryDirectory[str]] = []
_PROTECTED_DB_PATHS: set[Path] = set()
_ORIGINAL_SQLITE_CONNECT = sqlite3.connect


class UnsafeTestDatabase(ValueError):
    """Raised when a test process selects a protected SQLite database."""


def is_test_invocation(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Recognize standard test launchers without matching unrelated Python paths."""
    env = os.environ if environment is None else environment
    if env.get("BILLING_TEST_ISOLATED") == "1":
        return True

    original = list(argv if argv is not None else getattr(sys, "orig_argv", ()))
    if not original:
        original = list(sys.argv)

    if "-m" in original:
        module_index = original.index("-m")
        if module_index + 1 < len(original):
            module = original[module_index + 1].lower()
            if module in {"unittest", "pytest"} or module.startswith("tests.") or module.startswith("test_"):
                return True

    launcher_names = {"pytest", "pytest.exe", "pytest-script.py", "unittest", "unittest.exe"}
    if sys.argv and Path(sys.argv[0]).name.lower() in launcher_names:
        return True

    if "-m" in original:
        return False

    script = original[1] if len(original) > 1 else (sys.argv[0] if sys.argv else "")
    script_path = Path(script)
    script_name = script_path.name.lower()
    is_test_file = script_name.startswith("test_") or script_name.endswith("_test.py")
    if is_test_file and any(part.lower() == "tests" for part in script_path.parts):
        return True
    return False


def _file_uri_path(value: str) -> str:
    if not value.startswith("file:"):
        return value
    parsed = urlsplit(value)
    raw = unquote(parsed.path)
    if parsed.netloc:
        raw = f"//{parsed.netloc}{raw}"
    if os.name == "nt" and len(raw) >= 4 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]
    return raw


def _as_path(value: object, *, base_dir: Path | None = None) -> Path | None:
    if isinstance(value, bytes):
        value = os.fsdecode(value)
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str) or value in ("", ":memory:"):
        return None
    raw = _file_uri_path(value)
    path = Path(raw)
    if not path.is_absolute():
        path = (base_dir or Path.cwd()) / path
    return path.resolve(strict=False)


def _same_path(candidate: Path | None, protected: Path) -> bool:
    if candidate is None:
        return False
    protected = protected.resolve(strict=False)
    if candidate == protected:
        return True
    try:
        return candidate.exists() and protected.exists() and os.path.samefile(candidate, protected)
    except OSError:
        return False


def is_protected_database(value: object, protected_paths: Iterable[Path | str] = ()) -> bool:
    candidate = _as_path(value)
    paths = (PRODUCTION_DB, *protected_paths)
    return any(_same_path(candidate, Path(path)) for path in paths)


def validate_selected_database(
    value: object,
    protected_paths: Iterable[Path | str] = (),
) -> None:
    if is_protected_database(value, protected_paths):
        raise UnsafeTestDatabase(
            "Test isolation refused APP_DB because it targets a protected database. "
            "Choose a temporary database path."
        )


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _environment_protected_paths(env: Mapping[str, str]) -> list[Path]:
    raw = env.get("BILLING_TEST_DENY_DB", "")
    return [Path(value) for value in raw.split(os.pathsep) if value]


def _sanitize_environment(env: dict[str, str], test_root: Path) -> None:
    # Remove credentials and live-service configuration inherited from a shell.
    for name in (
        "ADMIN_EMAIL",
        "ADMIN_NAME",
        "ADMIN_PASSWORD",
        "APP_PUBLIC_URL",
        "APP_SECURE_COOKIE",
        "BOT_CA_BUNDLE",
        "EMAIL_FROM",
        "EMAIL_INBOUND_SECRET",
        "EMAIL_REPLY_TO",
        "IMAP_FOLDER",
        "IMAP_HOST",
        "IMAP_PASSWORD",
        "IMAP_PORT",
        "IMAP_USER",
        "SMTP_HOST",
        "SMTP_PASSWORD",
        "SMTP_PORT",
        "SMTP_SECURITY",
        "SMTP_USER",
        "VAPID_PRIVATE_KEY",
        "VAPID_SUBJECT",
    ):
        env.pop(name, None)

    env.update(
        {
            "APP_DB": str(test_root / "app.db"),
            "BACKGROUND_JOBS": "0",
            "BILLING_TEST_ISOLATED": "1",
            "BILLING_TEST_ROOT": str(test_root),
            "EMAIL_BACKEND": "file",
            "EMAIL_FILE_DIR": str(test_root / "mail"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    if not env.get("PYTHONPATH"):
        env["PYTHONPATH"] = str(PROJECT_ROOT)
    elif str(PROJECT_ROOT) not in env["PYTHONPATH"].split(os.pathsep):
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env["PYTHONPATH"]


def build_isolated_environment(
    source: Mapping[str, str] | None = None,
    *,
    denied_paths: Iterable[Path | str] = (),
) -> tuple[dict[str, str], tempfile.TemporaryDirectory[str] | None]:
    """Return a test-only environment and a holder to keep its temp dir alive."""
    env = dict(os.environ if source is None else source)
    additional = [Path(path) for path in denied_paths]
    inherited_denials = _environment_protected_paths(env)
    protected = [*additional, *inherited_denials]

    # Validate the explicit selection before replacing it with the owned temp DB.
    if "APP_DB" in env:
        validate_selected_database(env["APP_DB"], protected)

    existing_root_value = env.get("BILLING_TEST_ROOT")
    existing_db_value = env.get("APP_DB")
    temp_base = Path(tempfile.gettempdir()).resolve(strict=False)
    if (
        env.get("BILLING_TEST_ISOLATED") == "1"
        and existing_root_value
        and existing_db_value
    ):
        existing_root = Path(existing_root_value).resolve(strict=False)
        existing_db = _as_path(existing_db_value)
        if (
            _inside(existing_root, temp_base)
            and existing_db is not None
            and _inside(existing_db, existing_root)
        ):
            validate_selected_database(existing_db, protected)
            _sanitize_environment(env, existing_root)
            env["BILLING_TEST_DENY_DB"] = os.pathsep.join(
                str(path.resolve(strict=False)) for path in (PRODUCTION_DB, *protected)
            )
            Path(env["EMAIL_FILE_DIR"]).mkdir(parents=True, exist_ok=True)
            return env, None

    holder = tempfile.TemporaryDirectory(prefix="billing-tests-")
    test_root = Path(holder.name).resolve(strict=False)
    _sanitize_environment(env, test_root)
    env["BILLING_TEST_DENY_DB"] = os.pathsep.join(
        str(path.resolve(strict=False)) for path in (PRODUCTION_DB, *protected)
    )
    Path(env["EMAIL_FILE_DIR"]).mkdir(parents=True, exist_ok=True)
    return env, holder


def install_sqlite_write_guard(protected_paths: Iterable[Path | str] = ()) -> None:
    """Block SQLite opens to production and additional protected paths in tests."""
    for value in (PRODUCTION_DB, *protected_paths):
        _PROTECTED_DB_PATHS.add(Path(value).resolve(strict=False))

    if getattr(sqlite3.connect, "_billing_test_guard", False):
        return

    def guarded_connect(database, *args, **kwargs):
        if any(_same_path(_as_path(database), path) for path in _PROTECTED_DB_PATHS):
            raise sqlite3.OperationalError(
                "Test isolation blocked SQLite access to a protected database path."
            )
        return _ORIGINAL_SQLITE_CONNECT(database, *args, **kwargs)

    guarded_connect._billing_test_guard = True
    sqlite3.connect = guarded_connect


def initialize_test_process() -> None:
    """Apply isolation before test modules import the application."""
    try:
        env, holder = build_isolated_environment()
    except UnsafeTestDatabase as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    if holder is not None:
        _TEMP_DIRS.append(holder)
    for name in set(os.environ) - set(env):
        os.environ.pop(name, None)
    os.environ.update(env)
    install_sqlite_write_guard(_environment_protected_paths(env))
