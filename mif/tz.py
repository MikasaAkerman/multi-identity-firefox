"""Timezone handling, and the Windows restriction that shapes it.

Firefox derives the page-visible timezone from the TZ environment variable.
On POSIX any IANA name works. On Windows SpiderMonkey only accepts TZ values
that pass ``IsOlsonCompatibleWindowsTimeZoneId`` in ``js/src/vm/DateTime.cpp``,
which is a hard-coded whitelist. Anything else is silently ignored and the
host timezone is used instead, so unmappable zones have to be caught before a
profile is ever launched.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ffpath import is_windows

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


def resolve(timezone: str, *, windows: bool | None = None) -> Resolution:
    """Work out the TZ value to export for a requested IANA zone."""
    if windows is None:
        windows = is_windows()

    if not windows:
        return Resolution(timezone, timezone, supported=True, substituted=False)

    if timezone in WINDOWS_TZ_WHITELIST:
        return Resolution(timezone, timezone, supported=True, substituted=False)

    mapped = IANA_TO_WINDOWS.get(timezone)
    if mapped:
        return Resolution(
            timezone, mapped, supported=True, substituted=mapped != timezone
        )

    return Resolution(timezone, None, supported=False, substituted=False)


def unsupported_message(name: str, resolution: Resolution) -> str:
    return (
        f"{name}: TIMEZONE={resolution.requested!r} cannot be applied on Windows.\n"
        "  Firefox only honours a fixed set of TZ values there, so this profile\n"
        "  would silently report the machine's own timezone to websites.\n"
        f"  Mappable zones: {', '.join(sorted(IANA_TO_WINDOWS))}.\n"
        "  To accept the host timezone for this identity anyway, add\n"
        f'  TIMEZONE_FALLBACK="host" to identities/{name}.conf.'
    )
