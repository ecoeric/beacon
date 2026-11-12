"""Process signalling helpers.

A pid resolved from /proc can exit and be recycled between resolution and ``kill``. Where the
kernel supports it, a pidfd is opened at signal time to pin the identity: ``pidfd_send_signal``
then either hits that exact process or fails because it is gone. Older kernels fall back to
``os.kill`` (the caller has already re-verified the target as closely as it can).
"""

from __future__ import annotations

import os
import signal


def send_signal(pid: int, sig: int = signal.SIGINT) -> str:
    """Send ``sig`` to ``pid``; returns the mechanism used ("pidfd" or "kill")."""
    pidfd_open = getattr(os, "pidfd_open", None)
    pidfd_send_signal = getattr(signal, "pidfd_send_signal", None)
    if pidfd_open is not None and pidfd_send_signal is not None:
        try:
            fd = pidfd_open(pid)
        except OSError:
            fd = None
        if fd is not None:
            try:
                pidfd_send_signal(fd, sig)
            finally:
                os.close(fd)
            return "pidfd"
    os.kill(pid, sig)
    return "kill"
