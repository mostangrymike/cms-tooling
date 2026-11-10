"""Narrow terminal transport contract shared by the s3270 and TNZ backends.

``Session`` needs only a byte-oriented command channel, a mutable response
deadline, raw stderr for diagnostics, a liveness check, a close operation, and
a termination flag.  Keeping that surface small lets offline tests replace the
transport with a scripted object, and lets a new backend join without editing
the session or the screen layer.

``S3270Terminal`` adapts py3270's ``Emulator`` plus the bounded ``PipeApp``;
``TnzEmulator`` from ``tnz_transport`` already implements the same contract.
``conformance_errors`` is the shared structural check used by the tests.
"""
from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import time
from typing import Protocol, runtime_checkable

from py3270 import Emulator
from tnz_transport import TnzEmulator


@runtime_checkable
class CommandResult(Protocol):
    """The single response member ``Session.command`` reads."""

    data: list[bytes]


@runtime_checkable
class Terminal(Protocol):
    """Everything ``Session`` may assume about a connected transport."""

    deadline: float
    stderr: object
    is_terminated: bool

    def exec_command(self, action: bytes) -> CommandResult:
        """Run one command sequence and return its response lines."""

    def alive(self) -> bool:
        """True while the transport can still serve a command."""

    def close(self) -> int | None:
        """Release the transport; callers must not use it afterwards."""


class PipeApp:
    """py3270 application transport with deadlines and drained stderr.

    py3270's ordinary pipe readline is unbounded. A reader thread and queue keep
    emulator faults from hanging MCP. After a timeout, Session attempts one
    bounded screen capture to resynchronize before deciding whether to stop it.
    """
    def __init__(self):
        executable = shutil.which("s3270")
        if not executable:
            raise RuntimeError("s3270 not found on PATH")
        self.sp = subprocess.Popen(
            # -clear works on both distro 4.1 and newer 4.5 emulators;
            # older versions reject assignment syntax in -set arguments.
            [executable, "-model", "2", "-clear", "aidWait", "-clear", "trace"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.output = queue.Queue()
        self.stderr = bytearray()
        self.deadline = time.monotonic() + 15
        self.reply = []
        self.closed = False
        self.threads = [threading.Thread(target=self._read_stdout, daemon=True),
                        threading.Thread(target=self._read_stderr, daemon=True)]
        for thread in self.threads:
            thread.start()

    def _read_stdout(self):
        while True:
            line = self.sp.stdout.readline()
            self.output.put(line)
            if not line:
                break

    def _read_stderr(self):
        while True:
            chunk = self.sp.stderr.read(4096)
            if not chunk:
                break
            self.stderr.extend(chunk)

    def connect(self, host):
        return False

    def write(self, data):
        self.reply = []
        if self.closed or self.sp.poll() is not None:
            raise RuntimeError("s3270 process is no longer running")
        self.sp.stdin.write(data)
        self.sp.stdin.flush()

    def readline(self):
        try:
            line = self.output.get(timeout=max(0.001, self.deadline - time.monotonic()))
        except queue.Empty:
            raise TimeoutError("s3270 response deadline exceeded") from None
        if not line:
            raise RuntimeError("s3270 closed its output pipe")
        self.reply.append(line.decode("utf-8", errors="replace").rstrip("\r\n"))
        return line

    def close(self):
        if self.closed:
            return self.sp.poll()
        self.closed = True
        if self.sp.poll() is None:
            self.sp.terminate()
            try:
                self.sp.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.sp.kill()
                self.sp.wait(timeout=2)
        for thread in self.threads:
            thread.join(timeout=1)
        for stream in (self.sp.stdin, self.sp.stdout, self.sp.stderr):
            stream.close()
        return self.sp.returncode


class S3270Terminal:
    """py3270 ``Emulator`` and ``PipeApp`` behind the ``Terminal`` contract."""

    def __init__(self, app=None):
        self.app = app if app is not None else PipeApp()
        self.emulator = Emulator(app=self.app)
        self.is_terminated = False

    @property
    def deadline(self):
        return self.app.deadline

    @deadline.setter
    def deadline(self, value):
        self.app.deadline = value

    @property
    def stderr(self):
        return self.app.stderr

    def exec_command(self, action):
        return self.emulator.exec_command(action)

    def alive(self):
        process = getattr(self.app, "sp", None)
        return process is None or process.poll() is None

    def close(self):
        try:
            return self.app.close()
        finally:
            self.is_terminated = True
            # Keep py3270's destructor from trying to quit a closed pipe.
            self.emulator.is_terminated = True


def terminal(transport: str) -> Terminal:
    """Build the transport named on the command line."""
    if transport == "s3270":
        return S3270Terminal()
    if transport == "tnz":
        return TnzEmulator()
    raise ValueError("transport must be s3270 or tnz")


def conformance_errors(candidate) -> list[str]:
    """Name every ``Terminal`` member a candidate is missing, without calling it."""
    errors = []
    for name in ("deadline", "stderr", "is_terminated"):
        if not hasattr(candidate, name):
            errors.append(f"missing attribute: {name}")
    for name in ("exec_command", "alive", "close"):
        if not callable(getattr(candidate, name, None)):
            errors.append(f"missing method: {name}")
    return errors
