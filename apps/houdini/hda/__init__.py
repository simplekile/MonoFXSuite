# HDA-related Python: callbacks, menu generation, helpers referenced from HDAs.
#
# Important: Do not hard-import modules that require Houdini's `hou` here.
# This package should be importable in plain Python (for unit tests / scripts).

__all__ = ["anim_loader_simple", "anim_publish_loader", "character_loader"]

# Keep lightweight modules importable everywhere.
from apps.houdini.hda import anim_loader_simple  # noqa: E402

# Houdini-only modules: best-effort import (safe outside Houdini).
try:  # pragma: no cover
    from apps.houdini.hda import anim_publish_loader, character_loader  # noqa: F401,E402
except Exception:
    # Outside Houdini, `hou` isn't available; callers can import these modules
    # only when running inside Houdini.
    pass
