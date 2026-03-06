# Copy this file to your Houdini scripts folder as 123.py
# so it runs when Houdini starts.
#
# Windows: Documents\houdiniXX.X\scripts\123.py
# macOS/Linux: ~/houdiniXX.X/scripts/123.py
#
# Edit SUITE_ROOT to match your MonoFXSuite path.

import sys
from pathlib import Path

SUITE_ROOT = Path(r"e:\00 Project\Pipeline\MonoFXSuite")
if SUITE_ROOT.is_dir() and str(SUITE_ROOT) not in sys.path:
    sys.path.insert(0, str(SUITE_ROOT))

# Optional: bootstrap (when we add menu/shelf)
# from apps.houdini.bootstrap import run_bootstrap
# run_bootstrap(SUITE_ROOT)
