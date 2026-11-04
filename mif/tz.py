"""Timezone handling, and the Windows restrictions that shape it.

Both engines derive the page-visible timezone from the TZ environment
variable, which ICU reads on POSIX. Any IANA name works there.

On Windows the two engines diverge:

- Firefox's SpiderMonkey only accepts TZ values that pass
  ``IsOlsonCompatibleWindowsTimeZoneId`` in ``js/src/vm/DateTime.cpp``, a
  hard-coded whitelist. Anything else is silently ignored.
- Chromium-based browsers do not read TZ at all. ICU's ``uprv_tzname`` on
  Win32 calls ``uprv_detectWindowsTimeZone()`` and never ``getenv("TZ")``,
  so every zone would silently show the host timezone.

Unusable zones are therefore refused before a profile is launched, unless
the identity opts in with ``TIMEZONE_FALLBACK="host"``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .binpath import is_windows
from .config import MifError

# The exact set SpiderMonkey accepts for TZ on Windows.
WINDOWS_TZ_WHITELIST = frozenset(
    {
        "EST5EDT",
        "CST6CDT",
        "MST7MDT",
        "PST8PDT",
        "GMT+0",
        "GMT-0",
        "GMT0",
        "UCT",
        "UTC",
        "GMT",
    }
)

# Only zones whose DST rules genuinely match the US ones the POSIX aliases
# imply. America/Phoenix and friends are deliberately absent: they observe no
# DST, so MST7MDT would shift them by an hour for half the year.
IANA_TO_WINDOWS = {
    "America/Los_Angeles": "PST8PDT",
    "America/Vancouver": "PST8PDT",
    "America/Tijuana": "PST8PDT",
    "America/Denver": "MST7MDT",
    "America/Edmonton": "MST7MDT",
    "America/Chicago": "CST6CDT",
    "America/Winnipeg": "CST6CDT",
    "America/New_York": "EST5EDT",
    "America/Toronto": "EST5EDT",
    "UTC": "UTC",
    "Etc/UTC": "UTC",
    "Etc/GMT": "UTC",
    "GMT": "UTC",
}


@dataclass(frozen=True)
class Resolution:
    """How one identity's timezone will actually be applied."""

    requested: str
    value: str | None
    supported: bool
    substituted: bool

    @property
    def summary(self) -> str:
        if not self.supported:
            return f"{self.requested} -> unsupported on Windows (host timezone)"
        if self.substituted:
            return f"{self.requested} -> {self.value}"
        return self.requested


def resolve(
    timezone: str, engine: str = "gecko", *, windows: bool | None = None
) -> Resolution:
    """Work out the TZ value to export for a requested IANA zone.

    ``engine`` is ``gecko`` or ``chromium``. The Windows whitelist applies
    only to Firefox; Chromium cannot express any zone through TZ there.
    ``windows`` overrides platform detection so the rule can be checked on
    other hosts.
    """
    if engine not in ("gecko", "chromium"):
        raise MifError(f"unknown browser engine {engine!r}")
    if windows is None:
        windows = is_windows()

    if not windows:
        return Resolution(timezone, timezone, supported=True, substituted=False)

    if engine == "chromium":
        return Resolution(timezone, None, supported=False, substituted=False)

    if timezone in WINDOWS_TZ_WHITELIST:
        return Resolution(timezone, timezone, supported=True, substituted=False)

    mapped = IANA_TO_WINDOWS.get(timezone)
    if mapped:
        return Resolution(
            timezone, mapped, supported=True, substituted=mapped != timezone
        )

    return Resolution(timezone, None, supported=False, substituted=False)


def unsupported_message(
    name: str, resolution: Resolution, engine: str = "gecko"
) -> str:
    fallback = (
        "  To accept the host timezone for this identity anyway, add\n"
        f'  TIMEZONE_FALLBACK="host" to identities/{name}.conf.'
    )
    if engine == "chromium":
        return (
            f"{name}: TIMEZONE={resolution.requested!r} cannot be applied on Windows.\n"
            "  Chromium-based browsers ignore TZ there and read the timezone from\n"
            "  the system, so this profile would silently report the machine's own\n"
            "  timezone to websites.\n"
            + fallback
        )
    return (
        f"{name}: TIMEZONE={resolution.requested!r} cannot be applied on Windows.\n"
        "  Firefox only honours a fixed set of TZ values there, so this profile\n"
        "  would silently report the machine's own timezone to websites.\n"
        f"  Mappable zones: {', '.join(sorted(IANA_TO_WINDOWS))}.\n"
        + fallback
    )
