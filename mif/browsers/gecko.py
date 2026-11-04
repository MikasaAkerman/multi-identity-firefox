"""Firefox backend.

Profile state lives in ``user.js``, regenerated on every launch so the conf
always wins over ``about:config``. The web-visible timezone is not a pref:
the launcher exports ``TZ`` and Firefox reads it through ICU.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..binpath import BinarySpec, is_windows, locate_binary
from ..config import TEMPLATES_DIR, Identity
from ..tz import Resolution
from .base import Notice

TEMPLATE = TEMPLATES_DIR / "user.js.tpl"

FIREFOX_SPEC = BinarySpec(
    key="firefox",
    display_name="Firefox",
    env_vars=("MIF_FIREFOX_BIN", "FIREFOX_BIN"),
    macos_bundles=(("Firefox.app", "firefox"),),
    windows_app_paths=(),
    windows_subpaths=("Mozilla Firefox/firefox.exe",),
    path_names=("firefox",),
    use_firefox_registry=True,
)


def pref_string(value: str) -> str:
    """Escape a string for use inside a user_pref("...") literal."""
    return json.dumps(value)[1:-1]


def _geo_block(identity: Identity) -> str:
    if not (identity.geo_lat and identity.geo_lon):
        return "// No GEO_LAT/GEO_LON set; the Geolocation API is left untouched."

    # Firefox expects the Google Geolocation API response shape. Serving it from
    # a data: URL keeps the coordinates fixed without any network lookup, which
    # matters now that Mozilla Location Service is shut down.
    payload = json.dumps(
        {
            "location": {"lat": float(identity.geo_lat), "lng": float(identity.geo_lon)},
            "accuracy": 100.0,
        },
        separators=(",", ":"),
    )
    url = pref_string("data:application/json," + payload)
    return "\n".join(
        [
            "// Pin the Geolocation API to this identity's coordinates.",
            "// Firefox tries a platform provider first (CoreLocation, Windows",
            "// Location, GeoClue) and only falls through to the network provider when",
            "// none is active, so each one is switched off below. The switches for",
            "// other platforms are simply ignored. geo.provider.testing then forces",
            "// the network provider even if a platform one is still somehow enabled.",
            'user_pref("geo.provider.testing", true);',
            f'user_pref("geo.provider.network.url", "{url}");',
            'user_pref("geo.provider.use_corelocation", false);',
            'user_pref("geo.provider.ms-windows-location", false);',
            'user_pref("geo.provider.use_geoclue", false);',
        ]
    )


def _fpp_blocks(identity: Identity) -> tuple[str, str]:
    if identity.fingerprint_protection:
        summary = (
            "The finer-grained\n"
            "// fingerprintingProtection below covers similar ground while leaving\n"
            "// the timezone and locale alone."
        )
        block = "\n".join(
            [
                'user_pref("privacy.fingerprintingProtection", true);',
                'user_pref("privacy.fingerprintingProtection.overrides",'
                ' "+AllTargets,-JSDateTimeUTC,-JSLocale");',
            ]
        )
        return summary, block
    return (
        "FINGERPRINT_PROTECTION is off for this identity.",
        'user_pref("privacy.fingerprintingProtection", false);',
    )


def _platform_block() -> str:
    if not is_windows():
        return ""
    return "\n".join(
        [
            "",
            "// Keep taskbar windows grouped per profile rather than all under Firefox.",
            'user_pref("taskbar.grouping.useprofile", true);',
        ]
    )


def _timezone_note(resolution: Resolution) -> str:
    if not resolution.supported:
        return (
            f"TIMEZONE={resolution.requested} is not expressible through TZ on "
            "Windows; this profile reports the host timezone."
        )
    if resolution.substituted:
        return (
            f"TIMEZONE={resolution.requested} is applied on Windows as "
            f"{resolution.value}, the closest value Firefox accepts there."
        )
    return f"Effective timezone: {resolution.value}."


def _proxy_block(identity: Identity) -> str:
    lines = ["// BEGIN GENERATED PROXY BLOCK"]
    if identity.proxy_type == "none":
        lines.append('user_pref("network.proxy.type", 0);')
    elif identity.proxy_type == "http":
        lines += [
            'user_pref("network.proxy.type", 1);',
            f'user_pref("network.proxy.http", "{identity.proxy_host}");',
            f'user_pref("network.proxy.http_port", {identity.proxy_port});',
            f'user_pref("network.proxy.ssl", "{identity.proxy_host}");',
            f'user_pref("network.proxy.ssl_port", {identity.proxy_port});',
            'user_pref("network.proxy.socks", "");',
            'user_pref("network.proxy.socks_port", 0);',
            'user_pref("network.proxy.socks_remote_dns", false);',
            'user_pref("network.proxy.no_proxies_on", "");',
        ]
    elif identity.proxy_type == "socks5":
        lines += [
            'user_pref("network.proxy.type", 1);',
            'user_pref("network.proxy.http", "");',
            'user_pref("network.proxy.http_port", 0);',
            'user_pref("network.proxy.ssl", "");',
            'user_pref("network.proxy.ssl_port", 0);',
            f'user_pref("network.proxy.socks", "{identity.proxy_host}");',
            f'user_pref("network.proxy.socks_port", {identity.proxy_port});',
            'user_pref("network.proxy.socks_version", 5);',
            'user_pref("network.proxy.socks_remote_dns", true);',
            'user_pref("network.proxy.no_proxies_on", "");',
        ]

    if identity.proxy_type != "none":
        lines += [
            "// A dead proxy must fail closed rather than fall back to a direct"
            " connection.",
            'user_pref("network.proxy.failover_direct", false);',
        ]
    lines.append("// END GENERATED PROXY BLOCK")
    return "\n".join(lines)


def render(identity: Identity, resolution: Resolution) -> str:
    fpp_summary, fpp_block = _fpp_blocks(identity)
    replacements = {
        "__LANGUAGE__": identity.language,
        "__LOCALE__": identity.locale,
        "__DOWNLOAD_DIR__": pref_string(str(identity.download_dir)),
        "__TIMEZONE_NOTE__": _timezone_note(resolution),
        "__GEO_BLOCK__": _geo_block(identity),
        "__FPP_BLOCK__": fpp_block,
        "__FPP_SUMMARY__": fpp_summary,
        "__PLATFORM_BLOCK__": _platform_block(),
        "__PROXY_BLOCK__": _proxy_block(identity),
    }
    text = TEMPLATE.read_text()
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def write(identity: Identity, resolution: Resolution) -> None:
    identity.ensure_dirs()
    (identity.profile_dir / "user.js").write_text(render(identity, resolution))


class GeckoBrowser:
    key = "firefox"
    display_name = "Firefox"
    engine = "gecko"

    def locate(self) -> Path:
        return locate_binary(FIREFOX_SPEC)

    def prepare(self, identity: Identity, resolution: Resolution) -> None:
        write(identity, resolution)

    def command(
        self, identity: Identity, binary: Path, extra_args: list[str]
    ) -> list[str]:
        command = [str(binary), "-no-remote"]
        if not is_windows():
            # -new-instance is Unix-only; passing it on Windows is not supported.
            command.append("-new-instance")
        command += ["-profile", str(identity.profile_dir)]
        command += extra_args
        return command

    def notices(self, identity: Identity) -> list[Notice]:
        return []

    def geo_summary(self, identity: Identity) -> str:
        if identity.geo_lat:
            return f"{identity.geo_lat},{identity.geo_lon}"
        return "not pinned"

    def fingerprint_summary(self, identity: Identity) -> str:
        if identity.fingerprint_protection:
            return "on"
        return "off"
