"""
Profiles module for SWE-smith.

This module contains repository profiles for different programming languages
and provides a global registry for accessing all profiles.
"""

from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules

from .base import RepoProfile, registry

# Auto-import all profile modules to populate the registry
from . import c
from . import cpp
from . import csharp
from . import java
from . import javascript
from . import php
from . import python
from . import golang
from . import rust
# Phase 1: Added TypeScript support (2026-02-03)
from . import typescript


def _import_generated_profiles() -> None:
    """Auto-load generated profiles (if any) to populate registry."""
    generated_dir = Path(__file__).resolve().parent / "generated"
    if not generated_dir.exists():
        return

    package_name = f"{__name__}.generated"
    for mod in iter_modules([str(generated_dir)]):
        if mod.ispkg or mod.name.startswith("_"):
            continue
        try:
            import_module(f"{package_name}.{mod.name}")
        except Exception as exc:
            # Keep startup resilient even if one generated profile is invalid.
            print(f"[swesmith.profiles] Skip generated profile {mod.name}: {exc}")


_import_generated_profiles()

__all__ = ["RepoProfile", "registry"]
