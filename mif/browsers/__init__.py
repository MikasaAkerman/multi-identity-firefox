"""Registry of browser backends, keyed by the conf ``BROWSER`` value."""

from __future__ import annotations

from ..config import BROWSER_KEYS, MifError
from .base import Browser, Notice
from .chromium import CHROMIUM_BROWSERS
from .gecko import GeckoBrowser

_BY_KEY: dict[str, Browser] = {browser.key: browser for browser in (
    GeckoBrowser(),
    *CHROMIUM_BROWSERS,
)}

BROWSERS: dict[str, Browser] = {key: _BY_KEY[key] for key in BROWSER_KEYS}

if set(_BY_KEY) != set(BROWSER_KEYS):
    raise RuntimeError("BROWSER_KEYS and the browser registry disagree")


def get(key: str) -> Browser:
    try:
        return BROWSERS[key]
    except KeyError:
        known = ", ".join(BROWSERS)
        raise MifError(
            f"unsupported BROWSER={key!r} (expected one of {known})"
        ) from None


__all__ = ["BROWSERS", "Browser", "Notice", "get"]
