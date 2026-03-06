# Houdini adapter — thin layer for MonoFX tools.
# Only this package may import hou.

from apps.houdini.bootstrap import ensure_pipeline_path, run_bootstrap

__all__ = ["ensure_pipeline_path", "run_bootstrap"]
