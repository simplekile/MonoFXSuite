# MONO Grooming: lock-based hair grooming for Houdini (one HDA + a Qt panel). Spec: docs/plans/grooming_v0_1.md


def run() -> None:
    """The shelf tool's entry. Looked up on every call: a name bound at import would keep running the
    controller's old code after a reload (importlib.reload makes new functions, not new code in old ones)."""
    from tools.fx.grooming import controller

    controller.run()


def reload_and_run() -> None:
    """Reload all modules then run. Use during development to pick up code changes without restarting Houdini."""
    import importlib
    import tools.fx.grooming.config as _cfg
    import tools.fx.grooming.model as _model
    import tools.fx.grooming.logic as _logic
    import tools.fx.grooming.controller as _ctrl
    import tools.fx.grooming.ui as _ui

    importlib.reload(_cfg)
    importlib.reload(_model)
    importlib.reload(_logic)
    importlib.reload(_ctrl)
    importlib.reload(_ui)
    _ctrl.run()  # run() reloads apps.houdini.grooming_adapter itself


__all__ = ["run", "reload_and_run"]
