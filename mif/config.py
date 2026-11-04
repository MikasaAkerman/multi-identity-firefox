"""Identity configuration.

Reads the ``identities/*.conf`` files. The format stays shell-compatible
(``KEY="value"``) so the files remain readable and diffable, but they are
parsed rather than sourced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDENTITIES_DIR = ROOT / "identities"
DATA_DIR = ROOT / "data"
APPS_DIR = ROOT / "apps"
TEMPLATES_DIR = ROOT / "templates"

NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

PROXY_TYPES = ("none", "http", "socks5")
# Kept here, not in mif.browsers, so loading a conf does not import backends.
BROWSER_KEYS = ("firefox", "chrome", "edge", "brave", "chromium")


class MifError(Exception):
    """An error worth showing to the user without a traceback."""


def _parse_value(raw: str) -> str:
    raw = raw.strip()
    if raw[:1] in ('"', "'"):
        quote = raw[0]
        end = raw.find(quote, 1)
        if end == -1:
            raise MifError(f"Unterminated quote in value: {raw}")
        return raw[1:end]
    return raw.split("#", 1)[0].strip()


def _parse_conf(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ASSIGN_RE.match(stripped)
        if not match:
            raise MifError(f"{path.name}:{lineno}: cannot parse line: {stripped}")
        values[match.group(1)] = _parse_value(match.group(2))
    return values


def _as_bool(value: str, default: bool) -> bool:
    if value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Identity:
    """One identity, named after its conf file."""

    name: str
    browser: str = "firefox"
    language: str = "en-US"
    locale: str = "en-US"
    timezone: str = "UTC"
    proxy_type: str = "none"
    proxy_host: str = ""
    proxy_port: str = ""
    geo_lat: str = ""
    geo_lon: str = ""
    fingerprint_protection: bool = True
    temporary: bool = False
    # Windows cannot express every IANA zone through TZ. Setting this to
    # "host" is an explicit acknowledgement that the machine's own timezone
    # will be visible to websites for this identity.
    timezone_fallback: str = ""

    @property
    def profile_dir(self) -> Path:
        # Firefox keeps the original directory so existing profiles stay put.
        # Other browsers get their own user-data-dir beside it.
        if self.browser == "firefox":
            return DATA_DIR / self.name / "profile"
        return DATA_DIR / self.name / f"profile-{self.browser}"

    @property
    def download_dir(self) -> Path:
        return DATA_DIR / self.name / "downloads"

    @property
    def conf_path(self) -> Path:
        return IDENTITIES_DIR / f"{self.name}.conf"

    def ensure_dirs(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def validate(self) -> None:
        if self.browser not in BROWSER_KEYS:
            raise MifError(
                f"{self.name}: unsupported BROWSER={self.browser!r} "
                f"(expected one of {', '.join(BROWSER_KEYS)})"
            )
        if self.proxy_type not in PROXY_TYPES:
            raise MifError(
                f"{self.name}: unsupported PROXY_TYPE={self.proxy_type!r} "
                f"(expected one of {', '.join(PROXY_TYPES)})"
            )
        if self.proxy_type in ("http", "socks5"):
            if not self.proxy_host or not self.proxy_port:
                raise MifError(
                    f"{self.name}: PROXY_TYPE={self.proxy_type} requires "
                    "PROXY_HOST and PROXY_PORT"
                )
            if not self.proxy_port.isdigit():
                raise MifError(
                    f"{self.name}: PROXY_PORT must be numeric, got {self.proxy_port!r}"
                )
        if bool(self.geo_lat) != bool(self.geo_lon):
            raise MifError(f"{self.name}: GEO_LAT and GEO_LON must be set together")
        for label, value in (("GEO_LAT", self.geo_lat), ("GEO_LON", self.geo_lon)):
            if value:
                try:
                    float(value)
                except ValueError:
                    raise MifError(
                        f"{self.name}: {label} must be a number, got {value!r}"
                    ) from None


def validate_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise MifError("Name may contain only A-Z a-z 0-9 . _ -")
    return name


def load_identity(name: str) -> Identity:
    validate_name(name)
    conf = IDENTITIES_DIR / f"{name}.conf"
    if not conf.is_file():
        raise MifError(f"Identity not found: {name}")
    values = _parse_conf(conf)
    browser = values.get("BROWSER", "firefox").strip().lower() or "firefox"
    identity = Identity(
        name=name,
        browser=browser,
        language=values.get("LANGUAGE", "en-US"),
        locale=values.get("LOCALE", "en-US"),
        timezone=values.get("TIMEZONE", "UTC"),
        proxy_type=values.get("PROXY_TYPE", "none") or "none",
        proxy_host=values.get("PROXY_HOST", ""),
        proxy_port=values.get("PROXY_PORT", ""),
        geo_lat=values.get("GEO_LAT", ""),
        geo_lon=values.get("GEO_LON", ""),
        fingerprint_protection=_as_bool(values.get("FINGERPRINT_PROTECTION", ""), True),
        temporary=_as_bool(values.get("TEMPORARY", ""), False),
        timezone_fallback=values.get("TIMEZONE_FALLBACK", "").strip().lower(),
    )
    identity.validate()
    return identity


def all_identities() -> list[Identity]:
    if not IDENTITIES_DIR.is_dir():
        return []
    return [load_identity(p.stem) for p in sorted(IDENTITIES_DIR.glob("*.conf"))]
