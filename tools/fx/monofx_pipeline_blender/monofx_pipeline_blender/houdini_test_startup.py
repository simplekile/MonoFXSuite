"""Houdini startup script of the add-on's Test in Houdini (``houdini.exe -foreground houdini_test_startup.py``).

Runs inside Houdini, never inside Blender (the add-on does not import it). It hands over to the suite's
``apps.houdini.publish_preview``: from ``MONOFX_TEST_SUITE`` when set (a suite checkout), else Houdini's MonoFX
package, else ``MONOFX_SUITE``. What to open is in ``MONOFX_TEST_KIND`` / ``MONOFX_TEST_PATH``.
"""

import os
import sys


def _use_root(root):
    for p in (os.path.join(root, "packages", "monofx_pipeline_common", "src"), root):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in [m for m in sys.modules if m in ("apps", "tools") or m.startswith(("apps.", "tools."))]:
        del sys.modules[name]  # a suite imported before (the package's) would win otherwise


def _suite_module():
    explicit = os.environ.get("MONOFX_TEST_SUITE")
    roots = [explicit] if explicit else []
    roots += [None, os.environ.get("MONOFX_SUITE")]  # None: what Houdini's MonoFX package put on the path
    reason = ""
    for root in roots:
        if root is not None:
            if not os.path.isdir(os.path.join(root, "apps", "houdini")):
                continue
            _use_root(root)
        try:
            from apps.houdini import publish_preview

            return publish_preview, ""
        except ImportError as exc:
            reason = str(exc)
    return None, reason


_mod, _why = _suite_module()
if _mod is None:
    import hou

    msg = ("MonoFX test: this Houdini's MonoFX Suite has no Test in Houdini (missing, or older than the Blender "
           "add-on). Run MonoFXSuite_Setup.exe for this Houdini.")
    print(msg, _why)
    try:
        hou.ui.setStatusMessage(msg, hou.severityType.Error)
    except Exception:
        pass
else:
    _mod.main()
