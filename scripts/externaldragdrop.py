"""
Houdini hook for files dragged in from the OS file browser (found on HOUDINI_PATH/scripts).

Returning False hands the drop back to Houdini, so .hip files and anything MonoFX does not
handle open as usual. See apps/houdini/drag_drop.py for what each context creates.
"""

import traceback


def dropAccept(file_list):
    try:
        from apps.houdini import drag_drop
        return drag_drop.handle_drop(list(file_list))
    except Exception:
        traceback.print_exc()
        return False
