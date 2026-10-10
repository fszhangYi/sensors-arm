"""Path helpers for sensors-arm (mirrors sensors-dcs layout)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ID = "sensors-arm"
APP_TITLE = "sensors-arm"

_LAUNCH_CWD: Path | None = None


def capture_launch_cwd(cwd: str | Path | None = None) -> Path:
    global _LAUNCH_CWD
    if _LAUNCH_CWD is None:
        _LAUNCH_CWD = Path(cwd if cwd is not None else Path.cwd()).expanduser().resolve()
    return _LAUNCH_CWD


def launch_cwd() -> Path:
    return capture_launch_cwd()


def resolve_config_path(path: str | Path) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = launch_cwd() / p
    return p.resolve()


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def package_root() -> Path:
    return Path(__file__).resolve().parent


def static_dir() -> Path:
    return package_root() / "static"


def sensors_src_dir() -> Path:
    root = project_root()
    for candidate in (
        root / "sensors" / "src",
        root.parent / "sensors" / "src",
    ):
        if (candidate / "sensors").is_dir():
            return candidate
    return root / "sensors" / "src"


def ensure_sensors_import() -> Path:
    """Prefer local ./sensors symlink on sys.path."""
    src = sensors_src_dir()
    if src.is_dir():
        s = str(src)
        if s in sys.path:
            sys.path.remove(s)
        sys.path.insert(0, s)
    return src


def user_data_dir() -> Path:
    override = os.environ.get("SENSORS_ARM_USER_DATA")
    if override:
        p = Path(override).expanduser().resolve()
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        p = base / APP_ID
    else:
        p = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / APP_ID
    p.mkdir(parents=True, exist_ok=True)
    return p
