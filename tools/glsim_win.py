"""Start GLSim with the Windows stdin-injection workaround applied.

GLSim's execution engine reuses gltest.direct.loader's `deploy_contract`, which
injects the message via fd 0 and then immediately `os.unlink`s the temp file.
On Windows that unlink raises WinError 32 (file still held by fd 0), so every
transaction reverts. We rebind the loader's `_inject_message_to_fd0` (deferred
unlink) before starting the server, then hand control to glsim's CLI main().

Usage:
    python tools/glsim_win.py --port 4000 --validators 5
"""

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.win_stdin_patch import apply  # noqa: E402
from tools.glsim_engine_patch import apply_engine_patch  # noqa: E402

apply()
apply_engine_patch()

from glsim.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
