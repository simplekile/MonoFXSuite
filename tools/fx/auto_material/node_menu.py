"""
Right-click menu on a Material Library in /stage (OPmenu.xml at the suite root): MonoFX ›
Update materials to latest / Open in Auto Material. Acts on every Material Library selected,
plus the one clicked. Results go to Houdini's status bar, never a modal dialog.
"""

from __future__ import annotations

from typing import Any


def is_material_library(kwargs: dict) -> bool:
    """Menu context: the clicked node is a Material Library in /stage."""
    node = kwargs.get("node")
    try:
        return node.type().name() == "materiallibrary" and node.parent().path() == "/stage"
    except Exception:
        return False


def _target_nodes(kwargs: dict) -> list[Any]:
    import hou

    node = kwargs["node"]
    selected = [n for n in hou.selectedNodes()
                if n.type().name() == "materiallibrary" and n.parent() == node.parent()]
    return selected if node in selected else [node]


def _status(text: str, warning: bool = False) -> None:
    import hou

    hou.ui.setStatusMessage(f"MonoFX Auto Material: {text}",
                            severity=hou.severityType.Warning if warning else hou.severityType.Message)


def update_to_latest(kwargs: dict) -> None:
    import hou

    import apps.houdini.solaris_adapter as sa
    from tools.fx.auto_material import updater

    nodes = _target_nodes(kwargs)
    stage = nodes[0].parent()
    known = {lib.path: lib for lib in updater.scene_libraries(sa, stage)}
    skipped = [n.name() for n in nodes if n.path() not in known]
    libs = [known[n.path()] for n in nodes if n.path() in known]
    todo = [lib for lib in libs if lib.needs_update]
    if not todo:
        why = "not built by Auto Material" if not libs else "already at the latest publish"
        _status(f"{', '.join(n.name() for n in nodes)}: {why}", warning=not libs)
        return

    def progress(i: int, lib: Any) -> None:
        op.updateLongProgress((i - 1) / len(todo), f"Updating {lib.name} {i}/{len(todo)}")

    try:
        with hou.InterruptableOperation("MonoFX Auto Material", long_operation_name="Updating materials",
                                        open_interrupt_dialog=True) as op:
            _created, updated, notes = updater.update_libraries(sa, stage, todo, progress=progress)
    except hou.OperationInterrupted:
        _status("update cancelled; Ctrl+Z takes back what was done", warning=True)
        return
    text = f"updated {len(updated)} material(s) in {', '.join(lib.name for lib in todo)}"
    if skipped:
        text += f" · skipped {', '.join(skipped)} (not built by Auto Material)"
    if notes:
        text += f" · {len(notes)} note(s): {notes[0]}"
    _status(text, warning=bool(skipped or notes))


def open_in_window(kwargs: dict) -> None:
    from PySide6.QtWidgets import QApplication

    path = kwargs["node"].path()
    for w in QApplication.topLevelWidgets():
        if w.objectName() == "AutoMaterialWindow" and w.isVisible() and hasattr(w, "open_library"):
            w.raise_()
            w.activateWindow()
            w.open_library(path)
            return
    from tools.fx.auto_material import controller

    controller.run(focus=path)
