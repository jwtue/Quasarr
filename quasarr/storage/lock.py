import os
import tempfile
import time
from functools import wraps

from filelock import FileLock

from quasarr.providers.log import trace

_locks = {}


def get_lock(name) -> FileLock:
    if name not in _locks:
        _locks[name] = FileLock(
            os.path.join(tempfile.gettempdir(), f"quasarr_{name}.lock")
        )
    return _locks[name]


def with_lock(lock: FileLock, timeout=-1):
    """Serialize calls to the decorated function across processes.

    lock:    FileLock acquired via get_lock(name)
    timeout: seconds to wait; -1 = wait forever, 0 = fail immediately
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            with lock.acquire(timeout=timeout):
                delta = time.monotonic() - start
                trace(
                    f"acquiring lock for '{os.path.basename(lock.lock_file)}' took {delta * 1000:.3f}ms"
                )
                return fn(*args, **kwargs)

        return wrapper

    return decorator
