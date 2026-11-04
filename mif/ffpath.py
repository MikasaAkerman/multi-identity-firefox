"""Locating the Firefox executable on each platform."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from .config import MifError

MACOS_CANDIDATES = (
    Path("/Applications/Firefox.app/Contents/MacOS/firefox"),
    Path.home() / "Applications/Firefox.app/Contents/MacOS/firefox",
)

WINDOWS_CANDIDATES = (
    Path(r"C:\Program Files\Mozilla Firefox\firefox.exe"),
    Path(r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"),
)

_REGISTRY_KEY = r"SOFTWARE\Mozilla\Mozilla Firefox"


def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


def _from_env() -> Path | None:
    for var in ("MIF_FIREFOX_BIN", "FIREFOX_BIN"):
        value = os.environ.get(var)
        if value:
            path = Path(value)
            if not path.is_file():
                raise MifError(f"{var} points at a missing file: {path}")
            return path
    return None


def _from_windows_registry() -> Path | None:
    import winreg

    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    hives = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
    for hive in hives:
        for view in views:
            access = winreg.KEY_READ | view
            try:
                with winreg.OpenKey(hive, _REGISTRY_KEY, 0, access) as key:
                    version, _ = winreg.QueryValueEx(key, "CurrentVersion")
                main = rf"{_REGISTRY_KEY}\{version}\Main"
                with winreg.OpenKey(hive, main, 0, access) as key:
                    exe, _ = winreg.QueryValueEx(key, "PathToExe")
            except OSError:
                continue
            path = Path(exe)
            if path.is_file():
                return path
    return None


def firefox_binary() -> Path:
    """Return the Firefox executable, or raise with an actionable message."""
    found = _from_env()
    if found:
        return found

    if is_macos():
        for candidate in MACOS_CANDIDATES:
            if candidate.is_file():
                return candidate
        raise MifError(
            "Firefox not found in /Applications or ~/Applications.\n"
            "Install Firefox, or set FIREFOX_BIN to its executable."
        )

    if is_windows():
        found = _from_windows_registry()
        if found:
            return found
        for candidate in WINDOWS_CANDIDATES:
            if candidate.is_file():
                return candidate
        raise MifError(
            "Firefox not found in the registry or under Program Files.\n"
            r"Install Firefox, or set FIREFOX_BIN to ...\firefox.exe."
        )

    which = shutil.which("firefox")
    if which:
        return Path(which)
    raise MifError("firefox not found on PATH. Set FIREFOX_BIN to its executable.")


def wants_arm64_launch(binary: Path) -> bool:
    """True when the binary should be forced onto its arm64 slice.

    Launching a universal binary from a script otherwise lands on the x86_64
    slice and runs the whole browser under Rosetta.
    """
    if not is_macos() or platform.machine() != "arm64":
        return False
    try:
        slices = subprocess.run(
            ["/usr/bin/lipo", "-archs", str(binary)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        return False
    return "arm64" in slices
