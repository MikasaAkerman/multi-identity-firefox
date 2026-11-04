"""Per-identity desktop launchers.

macOS gets an .app bundle, Windows gets a .lnk shortcut. Both end up calling
``mif launch <Identity>`` rather than the browser directly, because the
timezone has to be placed in the environment before the browser starts and
neither an .app bundle nor a shortcut can do that by itself.
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

from .binpath import is_macos, is_windows
from .browsers import get as get_browser
from .config import APPS_DIR, ROOT, Identity, MifError

_INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>{name}</string>
  <key>CFBundleDisplayName</key><string>{name}</string>
  <key>CFBundleIdentifier</key><string>{bundle_id}</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundlePackageType</key><string>APPL</string>
{icon}</dict>
</plist>
"""

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


def launcher_label(identity: Identity) -> str:
    browser = get_browser(identity.browser)
    return f"{browser.display_name} - {identity.name}"


def launcher_path(identity: Identity) -> Path:
    suffix = ".lnk" if is_windows() else ".app"
    return APPS_DIR / f"{launcher_label(identity)}{suffix}"


def _identity_from_launcher(path: Path) -> str | None:
    """Identity name encoded in ``"<Browser> - <Name>.app"``.

    Names may themselves contain hyphens (``US-West``), so the split is on
    the last ``" - "`` and the name must match in full.
    """
    mark = " - "
    stem = path.stem
    if mark not in stem:
        return None
    return stem.rsplit(mark, 1)[1]


def _python_for_launcher() -> Path:
    """pythonw.exe where available, so the shortcut does not flash a console."""
    executable = Path(sys.executable)
    if is_windows():
        windowless = executable.with_name("pythonw.exe")
        if windowless.is_file():
            return windowless
    return executable


def _bundle_icon(binary: Path) -> Path | None:
    resources = binary.parent.parent / "Resources"
    if not resources.is_dir():
        return None
    icons = [path for path in resources.glob("*.icns") if path.is_file()]
    if not icons:
        return None
    preferred = {f"{binary.name}.icns", "app.icns"}
    for icon in icons:
        if icon.name in preferred:
            return icon
    return max(icons, key=lambda path: path.stat().st_size)


def _create_macos_app(identity: Identity, binary: Path) -> Path:
    app = launcher_path(identity)
    macos_dir = app / "Contents" / "MacOS"
    resource_dir = app / "Contents" / "Resources"
    macos_dir.mkdir(parents=True)
    resource_dir.mkdir(parents=True)

    launcher = macos_dir / "launcher"
    python = shlex.quote(str(_python_for_launcher()))
    launcher.write_text(
        "#!/bin/bash\n"
        f"cd {shlex.quote(str(ROOT))}\n"
        f"exec {python} -m mif launch {shlex.quote(identity.name)} \"$@\"\n"
    )
    launcher.chmod(0o755)

    icon_entry = ""
    icon = _bundle_icon(binary)
    if icon is not None:
        shutil.copyfile(icon, resource_dir / "app.icns")
        icon_entry = "  <key>CFBundleIconFile</key><string>app</string>\n"

    browser = get_browser(identity.browser)
    slug = re.sub(r"[^a-z0-9]", "", identity.name.lower())
    label = launcher_label(identity)
    (app / "Contents" / "Info.plist").write_text(
        _INFO_PLIST.format(
            name=label,
            bundle_id=f"local.browseridentity.{browser.key}.{slug}",
            icon=icon_entry,
        )
    )
    return app


def _create_windows_shortcut(identity: Identity, binary: Path) -> Path:
    link = launcher_path(identity)
    target = _python_for_launcher()
    args = f'-m mif launch "{identity.name}"'
    label = launcher_label(identity)

    env = dict(os.environ)
    env.update(
        {
            "MIF_LNK_PATH": str(link),
            "MIF_LNK_TARGET": str(target),
            "MIF_LNK_ARGS": args,
            "MIF_LNK_WORKDIR": str(ROOT),
            "MIF_LNK_ICON": f"{binary},0",
            "MIF_LNK_DESC": label,
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
    # Drop a launcher left over from a previous browser choice for this name.
    remove(identity.name)
    binary = get_browser(identity.browser).locate()
    if is_macos():
        return _create_macos_app(identity, binary)
    if is_windows():
        return _create_windows_shortcut(identity, binary)
    raise MifError(f"No launcher backend for platform {sys.platform!r}")


def remove(name: str) -> None:
    if not APPS_DIR.is_dir():
        return
    for path in list(APPS_DIR.iterdir()):
        if path.suffix not in (".app", ".lnk"):
            continue
        if _identity_from_launcher(path) != name:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def prune_installed(
    destination: Path, source_names: set[str], identity_names: set[str]
) -> None:
    """Drop renamed launchers from a dedicated install folder.

    Switching an identity's browser changes the launcher filename. The Desktop
    is shared with the user's own shortcuts, so only the Browser Identities
    folders are cleaned.
    """
    if destination.name != "Browser Identities" or not destination.is_dir():
        return
    for path in list(destination.iterdir()):
        if path.suffix not in (".app", ".lnk") or path.name in source_names:
            continue
        if _identity_from_launcher(path) not in identity_names:
            continue
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
