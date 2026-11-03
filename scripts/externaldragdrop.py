"""
Houdini hook for files dragged in from the OS file browser (found on HOUDINI_PATH/scripts).

Returning False hands the drop back to Houdini, which opens any file as a scene; MonoFX does
that only for Houdini's own files (.hip, .hda). See apps/houdini/drag_drop.py for what each
context creates.
"""

import os
import traceback

_HOUDINI_EXTS = (".hip", ".hipnc", ".hiplc", ".hda", ".hdanc", ".hdalc", ".otl", ".otlnc", ".otllc")


def dropAccept(file_list):
    try:
        from apps.houdini import drag_drop
        return drag_drop.handle_drop(list(file_list))
    except Exception:
        traceback.print_exc()
        # Even on an error, never let Houdini open a texture or geo file as a scene
        return not all(os.path.splitext(f)[1].lower() in _HOUDINI_EXTS for f in file_list)
