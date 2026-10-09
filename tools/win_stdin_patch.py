"""Windows stdin-injection workaround for the gltest direct harness.

The harness's `_inject_message_to_fd0` replaces process stdin (fd 0) with a
temp file via `os.dup2` and then immediately `os.unlink`s that path. On Windows
the file is still held open by fd 0, so `os.unlink` raises PermissionError /
WinError 32 and every deploy fails.

`apply()` rebinds only the cleanup timing: the message is built and injected
identically, but temp-file deletion is deferred to process exit (after the
harness restores stdin). No installed package file is modified; the module-level
function is rebound in-process for the current interpreter only.

Shared by:
  - tests/direct/conftest.py (pytest direct-mode runner process)
  - tools/glsim_win.py (the GLSim server process, which reuses the same loader)
"""

import atexit
import os
import tempfile

import gltest.direct.loader as _loader

_pending_unlink: list = []


def _deferred_unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _patched_inject(vm):
    try:
        from genlayer.py import calldata
        from genlayer.py.types import Address
    except ImportError:
        return

    sender_addr = vm.sender
    if isinstance(sender_addr, bytes):
        sender_addr = Address(sender_addr)
    contract_addr = vm._contract_address
    if isinstance(contract_addr, bytes):
        contract_addr = Address(contract_addr)
    origin_addr = vm.origin
    if isinstance(origin_addr, bytes):
        origin_addr = Address(origin_addr)

    message_data = {
        "contract_address": contract_addr,
        "sender_address": sender_addr,
        "origin_address": origin_addr,
        "stack": [],
        "value": vm._value,
        "datetime": vm._datetime,
        "is_init": False,
        "chain_id": vm._chain_id,
        "entry_kind": 0,
        "entry_data": b"",
        "entry_stage_data": None,
    }

    encoded = calldata.encode(message_data)

    fd, path = tempfile.mkstemp()
    try:
        os.write(fd, encoded)
        os.lseek(fd, 0, os.SEEK_SET)
        original_stdin = os.dup(0)
        vm._original_stdin_fd = original_stdin
        os.dup2(fd, 0)
    finally:
        os.close(fd)

    # Defer removal until process exit, once stdin has been restored.
    _pending_unlink.append(path)
    atexit.register(_deferred_unlink, path)


def apply():
    """Install the deferred-unlink patch in the current process."""
    _loader._inject_message_to_fd0 = _patched_inject
    return _patched_inject
