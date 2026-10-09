"""Local conftest for direct-mode tests.

Installs the Windows stdin-injection workaround (see tools/win_stdin_patch.py)
so that `os.unlink` on the dup2'd temp file is deferred to process exit. Without
this, every deploy fails on Windows with PermissionError / WinError 32.
"""

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.win_stdin_patch import apply  # noqa: E402

apply()
