"""Per-identity desktop launchers.

macOS gets an .app bundle, Windows gets a .lnk shortcut. Both end up calling
``mif launch <Identity>`` rather than Firefox directly, because the timezone
has to be placed in the environment before the browser starts and neither an
.app bundle nor a shortcut can do that by itself.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import APPS_DIR, ROOT, Identity, MifError
from .ffpath import firefox_binary, is_macos, is_windows

_INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Firefox - {name}</string>
  <key>CFBundleDisplayName</key><string>Firefox - {name}</string>
  <key>CFBundleIdentifier</key><string>{bundle_id}</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundlePackageType</key><string>APPL</string>
</dict>
</plist>
"""


def launcher_path(identity: Identity) -> Path:
    suffix = ".lnk" if is_windows() else ".app"
    return APPS_DIR / f"Firefox - {identity.name}{suffix}"


def _python_for_launcher() -> Path:
    """pythonw.exe where available, so the shortcut does not flash a console."""
    executable = Path(sys.executable)
    if is_windows():
        windowless = executable.with_name("pythonw.exe")
        if windowless.is_file():
            return windowless
    return executable


def _create_macos_app(identity: Identity) -> Path:
    app = launcher_path(identity)
    if app.exists():
        shutil.rmtree(app)
    macos_dir = app / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    (app / "Contents" / "Resources").mkdir(parents=True)

    launcher = macos_dir / "launcher"
    python = shlex.quote(str(_python_for_launcher()))
    launcher.write_text(
        "#!/bin/bash\n"
        f'cd {shlex.quote(str(ROOT))}\n'
        f'exec {python} -m mif launch {shlex.quote(identity.name)} "$@"\n'
    )
    launcher.chmod(0o755)

    slug = re.sub(r"[^a-z0-9]", "", identity.name.lower())
    (app / "Contents" / "Info.plist").write_text(
        _INFO_PLIST.format(
            name=identity.name, bundle_id=f"local.browseridentity.firefox.{slug}"
        )
    )
    return app


_PS_CREATE_SHORTCUT = """
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($env:MIF_LNK_PATH)
$link.TargetPath = $env:MIF_LNK_TARGET
$link.Arguments = $env:MIF_LNK_ARGS
$link.WorkingDirectory = $env:MIF_LNK_WORKDIR
$link.IconLocation = $env:MIF_LNK_ICON
$link.Description = $env:MIF_LNK_DESC
$link.Save()
"""


def _create_windows_shortcut(identity: Identity) -> Path:
    link = launcher_path(identity)
    if link.exists():
        link.unlink()

    target = _python_for_launcher()
    args = f'-m mif launch "{identity.name}"'

    env = dict(os.environ)
    env.update(
        {
            "MIF_LNK_PATH": str(link),
            "MIF_LNK_TARGET": str(target),
            "MIF_LNK_ARGS": args,
            "MIF_LNK_WORKDIR": str(ROOT),
            "MIF_LNK_ICON": f"{firefox_binary()},0",
            "MIF_LNK_DESC": f"Firefox - {identity.name}",
        }
    )

    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "shortcut.ps1"
        script.write_text(_PS_CREATE_SHORTCUT)
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            env=env,
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        raise MifError(
            f"Could not create shortcut for {identity.name}:\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return link


def create(identity: Identity) -> Path:
    APPS_DIR.mkdir(parents=True, exist_ok=True)
    if is_macos():
        return _create_macos_app(identity)
    if is_windows():
        return _create_windows_shortcut(identity)
    raise MifError(f"No launcher backend for platform {sys.platform!r}")


def remove(name: str) -> None:
    for suffix in (".app", ".lnk"):
        path = APPS_DIR / f"Firefox - {name}{suffix}"
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def install_destinations() -> list[Path]:
    """Where `mif install` should place copies of the launchers."""
    if is_macos():
        return [Path.home() / "Applications" / "Browser Identities"]
    if is_windows():
        appdata = os.environ.get("APPDATA")
        destinations = [Path.home() / "Desktop"]
        if appdata:
            destinations.append(
                Path(appdata)
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Browser Identities"
            )
        return destinations
    return []
