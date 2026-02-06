"""
Profiles module for SWE-smith.

This module contains repository profiles for different programming languages
and provides a global registry for accessing all profiles.
"""

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

__all__ = ["RepoProfile", "registry"]
