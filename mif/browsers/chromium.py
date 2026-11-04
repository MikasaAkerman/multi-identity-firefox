"""Chrome, Edge, Brave and Chromium.

These four share one implementation. Isolation is a distinct
``--user-data-dir``. Proxy, WebRTC and ``navigator.languages`` are command-line
switches, so they still apply on a launch where the Preferences file could not
be rewritten. Geolocation, download directory and DNS prefetch cannot be set
from the command line; those go into ``Default/Preferences`` and are merged
back in on every cold start.

Chromium has no preference that pins Geolocation coordinates. When an identity
sets ``GEO_LAT`` / ``GEO_LON``, the profile denies the permission instead, so
the page sees no position rather than the machine's real one.

``-AppleLanguages (<locale>)`` is intentionally not passed on macOS. Chrome
treats the parenthesised value as a second navigation target (headless exits
with "Multiple targets are not supported"), and the ``-AppleLanguages=<locale>``
form does not change the UI or ``Intl`` locale. ``--lang`` is ignored there
too. ``navigator.languages`` still follows the identity, via ``--accept-lang``
and ``intl.accept_languages``. The UI and ``Intl`` default locale stay on the
host language.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

from ..binpath import BinarySpec, is_macos, is_windows, locate_binary
from ..config import Identity
from ..tz import Resolution
from .base import Notice

# These keys are ordinary profile preferences. They are not in Chromium's
# tracked-pref set (homepage, default search, extensions, startup URLs), so
# rewriting them does not invalidate the Secure Preferences MAC.
_GEO_PATH = ("profile", "default_content_setting_values", "geolocation")
_PREDICTION_PATH = ("net", "network_prediction_options")
_WEBRTC_PATH = ("webrtc", "ip_handling_policy")

# Chromium's NetworkPredictionOptions::NETWORK_PREDICTION_NEVER.
_PREDICTION_NEVER = 2
# content_settings::CONTENT_SETTING_BLOCK.
_GEO_BLOCK = 2
_WEBRTC_PROXY_ONLY = "disable_non_proxied_udp"


def _spec(
    key: str,
    display_name: str,
    bundle: str,
    executable: str,
    *,
    subpaths: tuple[str, ...],
    path_names: tuple[str, ...],
    app_paths: tuple[str, ...] = (),
) -> BinarySpec:
    return BinarySpec(
        key=key,
        display_name=display_name,
        env_vars=(f"MIF_{key.upper()}_BIN",),
        macos_bundles=((bundle, executable),),
        windows_app_paths=app_paths,
        windows_subpaths=subpaths,
        path_names=path_names,
    )


CHROME_SPEC = _spec(
    "chrome",
    "Chrome",
    "Google Chrome.app",
    "Google Chrome",
    app_paths=("chrome.exe",),
    subpaths=("Google/Chrome/Application/chrome.exe",),
    path_names=("google-chrome", "chrome"),
)
EDGE_SPEC = _spec(
    "edge",
    "Edge",
    "Microsoft Edge.app",
    "Microsoft Edge",
    app_paths=("msedge.exe",),
    subpaths=("Microsoft/Edge/Application/msedge.exe",),
    path_names=("microsoft-edge", "msedge"),
)
BRAVE_SPEC = _spec(
    "brave",
    "Brave",
    "Brave Browser.app",
    "Brave Browser",
    app_paths=("brave.exe",),
    subpaths=("BraveSoftware/Brave-Browser/Application/brave.exe",),
    path_names=("brave-browser", "brave"),
)
# No App Paths lookup: chrome.exe there belongs to Google Chrome.
CHROMIUM_SPEC = _spec(
    "chromium",
    "Chromium",
    "Chromium.app",
    "Chromium",
    subpaths=("Chromium/Application/chrome.exe",),
    path_names=("chromium",),
)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _posix_lock_held(lock: Path) -> bool:
    """True when ``SingletonLock`` belongs to a live browser.

    The symlink text is ``hostname-pid``. A crash leaves the symlink behind;
    treating that as "running" would skip the Preferences update forever,
    and the browser would then save the old settings back on its next exit.
    """
    if not os.path.lexists(lock):
        return False
    try:
        target = os.readlink(lock)
    except OSError:
        return True
    host, separator, pid_text = target.strip().rpartition("-")
    if not separator or not pid_text.isdigit():
        return True
    if host and host != socket.gethostname():
        return True
    return _pid_alive(int(pid_text))


def _windows_lock_held(lock: Path) -> bool:
    """True when ``lockfile`` is currently locked by a live browser.

    Chromium range-locks the file for the life of the process and does not
    always delete it after a crash, so existence alone is not "running".
    """
    if not lock.exists():
        return False
    import msvcrt

    try:
        handle = os.open(lock, os.O_RDWR | getattr(os, "O_BINARY", 0))
    except OSError:
        return True
    try:
        try:
            msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
        except OSError:
            return True
        msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
        return False
    finally:
        os.close(handle)


def profile_in_use(profile_dir: Path) -> bool:
    if is_windows():
        return _windows_lock_held(profile_dir / "lockfile")
    return _posix_lock_held(profile_dir / "SingletonLock")


def _ensure_dict(node: dict, key: str) -> dict:
    child = node.get(key)
    if not isinstance(child, dict):
        child = {}
        node[key] = child
    return child


def _set_path(tree: dict, keys: tuple[str, ...], value: object) -> None:
    node = tree
    for key in keys[:-1]:
        node = _ensure_dict(node, key)
    node[keys[-1]] = value


def _pop_path(tree: dict, keys: tuple[str, ...]) -> None:
    node = tree
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            return
        node = child
    node.pop(keys[-1], None)


def apply_preferences(prefs: dict, identity: Identity) -> None:
    """Merge the keys this project owns into a Preferences object.

    Other keys (extensions, window placement, cookies metadata) are left
    alone. Geolocation is removed again when the identity stops requesting
    it, so a later edit of the conf actually releases the permission.
    """
    _set_path(prefs, ("intl", "accept_languages"), identity.language)
    download_dir = str(identity.download_dir)
    _set_path(prefs, ("download", "default_directory"), download_dir)
    _set_path(prefs, ("download", "directory_upgrade"), True)
    _set_path(prefs, ("download", "prompt_for_download"), False)
    _set_path(prefs, ("savefile", "default_directory"), download_dir)
    _set_path(prefs, _PREDICTION_PATH, _PREDICTION_NEVER)
    _set_path(prefs, _WEBRTC_PATH, _WEBRTC_PROXY_ONLY)
    if identity.geo_lat and identity.geo_lon:
        _set_path(prefs, _GEO_PATH, _GEO_BLOCK)
    else:
        _pop_path(prefs, _GEO_PATH)


def _read_preferences(path: Path) -> dict | None:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    try:
        parsed = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _write_preferences(path: Path, prefs: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".mif-tmp")
    temporary.write_text(json.dumps(prefs, indent=2) + "\n")
    temporary.replace(path)


class ChromiumBrowser:
    engine = "chromium"

    def __init__(self, spec: BinarySpec) -> None:
        self.spec = spec

    @property
    def key(self) -> str:
        return self.spec.key

    @property
    def display_name(self) -> str:
        return self.spec.display_name

    def locate(self) -> Path:
        return locate_binary(self.spec)

    def prepare(self, identity: Identity, resolution: Resolution) -> None:
        # ``resolution`` is applied by exporting TZ around the process, which
        # is the only timezone mechanism Chromium honours (and only on POSIX).
        del resolution
        identity.ensure_dirs()
        if profile_in_use(identity.profile_dir):
            print(
                f"note: {identity.name} is running; Preferences were left unchanged.",
                file=sys.stderr,
            )
            return

        default_dir = identity.profile_dir / "Default"
        path = default_dir / "Preferences"
        prefs = _read_preferences(path)
        if prefs is None:
            print(
                f"warning: {path} is not a JSON object; Preferences were left unchanged.",
                file=sys.stderr,
            )
            return
        apply_preferences(prefs, identity)
        _write_preferences(path, prefs)
        # An empty sentinel, same as passing --no-first-run. Harmless if the
        # flag is what actually suppresses the first-run flow.
        first_run = identity.profile_dir / "First Run"
        if not first_run.exists():
            first_run.write_text("")

    def command(
        self, identity: Identity, binary: Path, extra_args: list[str]
    ) -> list[str]:
        command = [
            str(binary),
            f"--user-data-dir={identity.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if identity.language:
            command.append(f"--accept-lang={identity.language}")
        # --lang sets the UI locale on Windows and Linux. macOS ignores it and
        # takes the locale from Cocoa; see the module docstring.
        if identity.locale and not is_macos():
            command.append(f"--lang={identity.locale}")
        if identity.proxy_type == "none":
            # Match Firefox's network.proxy.type=0: direct, not the system proxy.
            command.append("--no-proxy-server")
        else:
            scheme = "socks5" if identity.proxy_type == "socks5" else "http"
            command.append(
                f"--proxy-server={scheme}://{identity.proxy_host}:{identity.proxy_port}"
            )
            # SOCKS5 already resolves remotely; this additionally stops the
            # local stub resolver. The proxy host itself stays resolvable.
            command.append(
                "--host-resolver-rules="
                f"MAP * ~NOTFOUND , EXCLUDE {identity.proxy_host}"
            )
        # Same posture as Firefox's unconditional ice.proxy_only: host
        # addresses must not leak around the proxy, and without a proxy
        # WebRTC does not fall back to a direct path either.
        command.append(
            f"--force-webrtc-ip-handling-policy={_WEBRTC_PROXY_ONLY}"
        )
        command += extra_args
        return command

    def notices(self, identity: Identity) -> list[Notice]:
        notes: list[Notice] = []
        if identity.geo_lat:
            notes.append(
                Notice(
                    "info",
                    "Geolocation coordinates cannot be pinned; the permission "
                    "is denied instead.",
                )
            )
        if self.key == "brave":
            notes.append(
                Notice(
                    "info",
                    "Brave Shields keep their default fingerprint randomization; "
                    "FINGERPRINT_PROTECTION is not a separate switch.",
                )
            )
        elif identity.fingerprint_protection:
            notes.append(
                Notice(
                    "warning",
                    "FINGERPRINT_PROTECTION has no effect; this browser has no "
                    "native fingerprinting protection switch.",
                )
            )
        return notes

    def geo_summary(self, identity: Identity) -> str:
        if identity.geo_lat:
            return "denied (chromium cannot pin)"
        return "not pinned"

    def fingerprint_summary(self, identity: Identity) -> str:
        if self.key == "brave":
            return "brave shields (default)"
        if identity.fingerprint_protection:
            return "unavailable"
        return "off"


CHROMIUM_BROWSERS = (
    ChromiumBrowser(CHROME_SPEC),
    ChromiumBrowser(EDGE_SPEC),
    ChromiumBrowser(BRAVE_SPEC),
    ChromiumBrowser(CHROMIUM_SPEC),
)
