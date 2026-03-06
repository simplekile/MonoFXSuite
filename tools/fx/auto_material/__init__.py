# Auto Material Builder — scan textures, auto-detect naming, create Karma materials in Solaris.

from tools.fx.auto_material.controller import run


def reload_and_run() -> None:
    """Reload all modules then run. Use during development to pick up code changes without restarting Houdini."""
    import importlib
    import tools.fx.auto_material.config as _cfg
    import tools.fx.auto_material.logic as _logic
    import tools.fx.auto_material.ui as _ui
    import tools.fx.auto_material.controller as _ctrl
    import apps.houdini.solaris_adapter as _sa

    importlib.reload(_cfg)
    importlib.reload(_logic)
    importlib.reload(_sa)
    importlib.reload(_ui)
    importlib.reload(_ctrl)
    _ctrl.run()


__all__ = ["run", "reload_and_run"]
