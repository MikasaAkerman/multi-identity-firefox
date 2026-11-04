"""Locating browser executables on each platform."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import MifError


def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


@dataclass(frozen=True)
class BinarySpec:
    """Where one browser's executable lives, per platform.

    ``macos_bundles`` entries are ``(app bundle name, executable inside
    Contents/MacOS)``. ``windows_subpaths`` are relative to Program Files and
    ``%LOCALAPPDATA%``. ``windows_app_paths`` are looked up under the
    per-user and per-machine ``App Paths`` registry keys; leave it empty when
    the exe name is shared with another browser (Chromium's ``chrome.exe``
    would otherwise resolve to Google Chrome).
    """

    key: str
    display_name: str
    env_vars: tuple[str, ...]
    macos_bundles: tuple[tuple[str, str], ...]
    windows_app_paths: tuple[str, ...]
    windows_subpaths: tuple[str, ...]
    path_names: tuple[str, ...]
    use_firefox_registry: bool = False


def _env_hint(spec: BinarySpec) -> str:
    return " or ".join(spec.env_vars)


def _from_env(spec: BinarySpec) -> Path | None:
    for var in spec.env_vars:
        value = os.environ.get(var)
        if not value:
            continue
        path = Path(value)
        if not path.is_file():
            raise MifError(f"{var} points at a missing file: {path}")
        return path
    return None


def _missing(spec: BinarySpec) -> MifError:
    hint = _env_hint(spec)
    if is_macos():
        return MifError(
            f"{spec.display_name} not found in /Applications or ~/Applications.\n"
            f"Install {spec.display_name}, or set {hint} to its executable."
        )
    if is_windows():
        return MifError(
            f"{spec.display_name} not found in the registry or under Program Files.\n"
            f"Install {spec.display_name}, or set {hint} to its executable."
        )
    return MifError(
        f"{spec.display_name} not found on PATH. Set {hint} to its executable."
    )


def _macos_candidates(spec: BinarySpec) -> list[Path]:
    roots = (Path("/Applications"), Path.home() / "Applications")
    found: list[Path] = []
    for bundle, executable in spec.macos_bundles:
        relative = Path(bundle) / "Contents" / "MacOS" / executable
        for root in roots:
            found.append(root / relative)
    return found


def _windows_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA"):
        value = os.environ.get(var)
        if not value:
            continue
        path = Path(value)
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(path)
    if not roots:
        roots = [Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)")]
    return roots


def _from_firefox_registry() -> Path | None:
    import winreg

    key_path = r"SOFTWARE\Mozilla\Mozilla Firefox"
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    hives = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
    for hive in hives:
        for view in views:
            access = winreg.KEY_READ | view
            try:
                with winreg.OpenKey(hive, key_path, 0, access) as key:
                    version, _ = winreg.QueryValueEx(key, "CurrentVersion")
                main = rf"{key_path}\{version}\Main"
                with winreg.OpenKey(hive, main, 0, access) as key:
                    exe, _ = winreg.QueryValueEx(key, "PathToExe")
            except OSError:
                continue
            path = Path(exe)
            if path.is_file():
                return path
    return None


def _from_app_paths(exe_name: str) -> Path | None:
    import winreg

    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    hives = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    for hive in hives:
        for view in views:
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as key:
                    exe, _ = winreg.QueryValueEx(key, "")
            except OSError:
                continue
            path = Path(exe)
            if path.is_file():
                return path
    return None


def _windows_candidates(spec: BinarySpec) -> list[Path]:
    found: list[Path] = []
    if spec.use_firefox_registry:
        registered = _from_firefox_registry()
        if registered:
            found.append(registered)
    for exe_name in spec.windows_app_paths:
        registered = _from_app_paths(exe_name)
        if registered:
            found.append(registered)
    for root in _windows_roots():
        for relative in spec.windows_subpaths:
            found.append(root / Path(relative))
    return found


def locate_binary(spec: BinarySpec) -> Path:
    """Return the executable for ``spec``, or raise with an actionable message."""
    found = _from_env(spec)
    if found:
        return found

    if is_macos():
        for candidate in _macos_candidates(spec):
            if candidate.is_file():
                return candidate
        raise _missing(spec)

    if is_windows():
        for candidate in _windows_candidates(spec):
            if candidate.is_file():
                return candidate
        raise _missing(spec)

    for name in spec.path_names:
        which = shutil.which(name)
        if which:
            return Path(which)
    raise _missing(spec)


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
