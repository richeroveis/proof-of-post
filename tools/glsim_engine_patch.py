"""GLSim engine patch: mark cached contract root classes for storage.

On the class-cache HIT path GLSim calls `gltest.direct.loader._allocate_contract`,
which runs `_storage_build(contract_cls, {})` directly on the root contract class.
That builder requires the class to carry `__gl_allow_storage__`, the marker that
`Contract.__init_subclass__` normally applies via `generate_storage`. When the
cached class is reused across transactions the marker can be missing, so every
node reverts with:

    class is not marked for usage within storage, ... @allow_storage

`apply_engine_patch()` rebinds the name GLSim actually calls (`glsim.engine
._allocate_contract`) so that, before building storage, the root class is marked
exactly the way `generate_storage`/`allow_storage` would mark it. This changes no
contract source and does not modify installed packages; it is applied in-process
for the GLSim server only.
"""

import glsim.engine as _engine

_MARKER = "__gl_allow_storage__"

_orig_allocate = _engine._allocate_contract


class _NoCache(dict):
    """Dict that never reports a hit: every lookup re-runs the fresh import path.

    GLSim's class-cache reuse (`_allocate_contract` on a cached root class) is
    incompatible with the pinned GenVM std-lib instance protocol and reverts with
    "... object has no attribute '_instance'". Forcing a cache miss routes every
    deploy through the proven `deploy_contract` fresh-import path (the engine
    clears the SDK contract registry before each import, so re-import is safe).
    """

    def get(self, key, default=None):  # noqa: D401
        return None


def _patched_allocate(contract_cls, vm, *args, **kwargs):
    try:
        if not hasattr(contract_cls, _MARKER):
            from genlayer.py.storage._internal.generate import allow_storage

            allow_storage(contract_cls)
    except Exception:
        # If the SDK isn't importable here, fall through to the original path.
        pass
    return _orig_allocate(contract_cls, vm, *args, **kwargs)


_orig_init = _engine.SimEngine.__init__


def _patched_init(self, *args, **kwargs):
    _orig_init(self, *args, **kwargs)
    self._class_cache = _NoCache()
    self._code_hash_cache = _NoCache()


def apply_engine_patch():
    _engine._allocate_contract = _patched_allocate
    _engine.SimEngine.__init__ = _patched_init
    return _patched_allocate
