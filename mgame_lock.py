"""Flock exclusivo compartido para escrituras cortas y para el restore.

El lock vive en un archivo hermano (`<target>.lock`), no en el JSON: el
reemplazo atómico cambia el inodo y un flock sobre el JSON no sobreviviría.

`acquire(..., blocking=False)` devuelve el string `"busy"` si otro titular lo
tiene. No es reentrante: el mismo hilo no debe tomar dos veces el mismo lock.
"""
import errno
import fcntl
import os


class LockBusy(Exception):
    """El lock está tomado. `acquire` no bloqueante devuelve `"busy"` y no la lanza."""


class Held:
    def __init__(self, fh):
        self._fh = fh

    def release(self):
        fh = self._fh
        self._fh = None
        if fh is None:
            return
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def lock_path(target):
    return target + ".lock"


def acquire(target, blocking=True):
    """Toma un flock exclusivo. Si `blocking` es falso y está ocupado, devuelve `"busy"`."""
    path = lock_path(target)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")
    flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
    try:
        fcntl.flock(fh.fileno(), flags)
    except OSError as exc:
        fh.close()
        if not blocking and exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
            return "busy"
        raise
    return Held(fh)


class exclusive:
    """`with exclusive(target):` toma el lock en modo bloqueante y lo suelta al salir."""

    def __init__(self, target):
        self._target = target
        self._held = None

    def __enter__(self):
        held = acquire(self._target, blocking=True)
        if held == "busy":  # no debería: el modo bloqueante espera
            raise LockBusy(self._target)
        self._held = held
        return held

    def __exit__(self, *exc):
        if self._held is not None:
            self._held.release()
            self._held = None
        return False
