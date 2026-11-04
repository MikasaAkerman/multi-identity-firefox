"""Cross-platform core for multi-identity browser profiles.

The shell scripts under bin/ are thin wrappers around this package so that
macOS and Windows share one implementation.
"""

__all__ = ["MifError"]

from .config import MifError
