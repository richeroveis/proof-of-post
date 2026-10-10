"""Local conftest for the ScoreRegistry direct-mode tests.

Installs the Windows stdin-injection workaround shared with the main project
(see tools/win_stdin_patch.py); without it every direct deploy fails on Windows.
"""

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.win_stdin_patch import apply  # noqa: E402

apply()
