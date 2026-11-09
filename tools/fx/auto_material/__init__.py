# Auto Material Builder — scan textures, auto-detect naming, create Karma materials in Solaris.


def run(focus: str | None = None) -> None:
    """The shelf tool's entry. Looked up on every call: a name bound at import would keep running the
    controller's old code after a reload (importlib.reload makes new functions, not new code in old ones)."""
    from tools.fx.auto_material import controller

    controller.run(focus)


def reload_and_run() -> None:
    """Reload all modules then run. Use during development to pick up code changes without restarting Houdini."""
    import importlib
    import tools.fx.auto_material.config as _cfg
    import tools.fx.auto_material.logic as _logic
    import tools.fx.auto_material.updater as _updater
    import tools.fx.auto_material.ui as _ui
    import tools.fx.auto_material.controller as _ctrl
    import apps.houdini.solaris_adapter as _sa

    importlib.reload(_cfg)
    importlib.reload(_logic)
    importlib.reload(_sa)
    importlib.reload(_updater)
    importlib.reload(_ui)
    importlib.reload(_ctrl)
    _ctrl.run()


__all__ = ["run", "reload_and_run"]
