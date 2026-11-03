# Drag & Drop — settings for files dropped into Houdini (apps/houdini/drag_drop.py).
# run() imports the Qt window lazily: the drop handler reads prefs on every drop without Qt.


def run() -> None:
    from tools.fx.drag_drop.controller import run as _run

    _run()


__all__ = ["run"]
