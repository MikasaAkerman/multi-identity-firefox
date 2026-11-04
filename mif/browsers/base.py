"""The browser backend interface.

Each identity names a browser in its conf. The matching backend knows how to
find the executable, materialise that browser's per-profile settings, and
build the command line. Callers (setup, launch, status) stay browser-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import Identity
from ..tz import Resolution


@dataclass(frozen=True)
class Notice:
    """A capability gap to print from ``setup`` and ``status``.

    ``kind`` is ``info`` when the profile still does something sensible, and
    ``warning`` when a requested setting is silently dropped.
    """

    kind: str
    message: str


class Browser(Protocol):
    key: str
    display_name: str
    engine: str

    def locate(self) -> Path:
        """Return the browser executable, or raise ``MifError``."""

    def prepare(self, identity: Identity, resolution: Resolution) -> None:
        """Write the profile files this browser needs before it starts."""

    def command(
        self, identity: Identity, binary: Path, extra_args: list[str]
    ) -> list[str]:
        """Argv for one launch, without the arm64 wrapper or the TZ env."""

    def notices(self, identity: Identity) -> list[Notice]:
        """Standing limitations for this identity, not launch-time failures."""

    def geo_summary(self, identity: Identity) -> str:
        """Short description of how geolocation is applied."""

    def fingerprint_summary(self, identity: Identity) -> str:
        """Short description of how fingerprint protection is applied."""
