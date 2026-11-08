"""Small direct-TN3270 transport used by the experimental tnz backend.

This deliberately does not replace the s3270 transport yet.  It exposes the
primitive operations needed by cms_mcp while keeping TN3270 data-stream access
isolated and easy to test: connect, wait for host output, inspect the screen,
send text/AID keys, and close.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from tnz import tnz


@dataclass
class TnzScreen:
    rows: list[str]
    row_count: int
    column_count: int
    cursor_row: int
    cursor_column: int
    keyboard_unlocked: bool


class TnzTransport:
    """Direct TN3270 connection without an s3270 subprocess."""

    def __init__(self, host: str = "127.0.0.1", port: int = 3270,
                 terminal_type: str = "IBM-3278-2-E"):
        self.host = host
        self.port = port
        self.terminal_type = terminal_type
        self.session: Any | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, initializer=self._init_worker)

    @staticmethod
    def _init_worker():
        asyncio.set_event_loop(asyncio.new_event_loop())

    def _run(self, function):
        return self._executor.submit(function).result()

    @property
    def connected(self) -> bool:
        return self.session is not None and not self.session.seslost

    def connect(self, lu_name: str | None = None) -> None:
        def work():
            self.session = tnz.Tnz(name=lu_name)
            if lu_name:
                self.session.lu_name = lu_name
                self.session.use_tn3270e = True
            self.session.terminal_type = self.terminal_type
            self.session.connect(self.host, self.port, secure=False)
            self.session.wait(10)
        self._run(work)

    def wait(self, timeout: float = 10) -> bool:
        if self.session is None:
            raise RuntimeError("TN3270 session is not connected")
        return bool(self._run(lambda: self.session.wait(timeout)))

    def screen(self) -> TnzScreen:
        if self.session is None:
            raise RuntimeError("TN3270 session is not connected")
        def work():
            rows = self.session.scrstr(0, self.session.maxrow * self.session.maxcol - 1)
            return rows, self.session.maxrow, self.session.maxcol, self.session.curadd, not self.session.system_lock_wait
        rows, maxrow, maxcol, curadd, unlocked = self._run(work)
        lines = rows.splitlines()
        if len(lines) == 1 and len(lines[0]) >= maxcol * maxrow:
            lines = [lines[0][i:i + maxcol] for i in range(0, maxcol * maxrow, maxcol)]
        lines = [(line[: maxcol]).ljust(maxcol)
                 for line in lines[: self.session.maxrow]]
        while len(lines) < maxrow:
            lines.append(" " * maxcol)
        return TnzScreen(
            lines, maxrow, maxcol,
            curadd // maxcol + 1, curadd % maxcol + 1, unlocked,
        )

    def text(self, value: str) -> None:
        if self.session is None:
            raise RuntimeError("TN3270 session is not connected")
        self._run(lambda: self.session.key_data(value))

    def enter(self) -> None:
        if self.session is None:
            raise RuntimeError("TN3270 session is not connected")
        self._run(self.session.enter)

    def clear(self) -> None:
        if self.session is None:
            raise RuntimeError("TN3270 session is not connected")
        self._run(self.session.clear)

    def field_attributes(self):
        return self._run(lambda: {address: attr for address, attr in self.session.fields()})

    def close(self) -> None:
        if self.session is not None:
            self._run(self.session.close)
            self.session = None
        self._executor.shutdown(wait=True, cancel_futures=True)


class _CommandResult:
    def __init__(self, data: list[str] | None = None):
        self.data = [line.encode("utf-8") for line in (data or [])]


class TnzEmulator:
    """Small py3270-compatible command surface for Session."""

    def __init__(self, host="127.0.0.1", port=3271, selector="0200@"):
        self.app = self
        self.transport = TnzTransport(host, port)
        self.selector = selector
        self.deadline = 0
        self.stderr = bytearray()
        self.is_terminated = False
        self._saved = None

    def _status(self):
        screen = self.transport.screen()
        return ("U F U C(127.0.0.1) I 2 %d %d %d %d 0x0" %
                (screen.row_count, screen.column_count,
                 screen.cursor_row - 1, screen.cursor_column - 1))

    def _readbuffer(self):
        screen = self.transport.screen()
        chars = "".join(screen.rows).encode("cp037", errors="replace")
        attrs = self.transport.field_attributes()
        tokens = []
        for pos, byte in enumerate(chars):
            if pos in attrs:
                tokens.append("SF(c0=%02x)" % attrs[pos])
            else:
                tokens.append("%02x" % byte)
        return tokens

    def exec_command(self, raw):
        command = raw.decode("ascii") if isinstance(raw, bytes) else str(raw)
        if command.startswith("Connect("):
            endpoint = command[8:-1]
            endpoint = endpoint.split(",", 1)[0].strip('"')
            lu, _, address = endpoint.partition("@")
            host, _, port = address.rpartition(":")
            if not host:
                host, port = lu, address
                lu = None
            self.transport.host = host or "127.0.0.1"
            self.transport.port = int(port or 3270)
            self.transport.connect(lu)
            return _CommandResult(["ok"])
        if command.startswith("Wait("):
            self.transport.wait(10)
            return _CommandResult(["ok"])
        if command == "Snap(Save)":
            self._saved = self.transport.screen()
            return _CommandResult(["ok"])
        if command == "Snap(Status)":
            return _CommandResult([self._status()])
        if command == "Snap(Ascii)":
            screen = self._saved or self.transport.screen()
            return _CommandResult(screen.rows)
        if command == "Snap(ReadBuffer)":
            return _CommandResult(self._readbuffer())
        if command.startswith("String("):
            value = command[8:-1].replace('\\"', '"')
            self.transport.text(value)
            return _CommandResult(["ok"])
        if command == "Enter":
            self.transport.enter()
            return _CommandResult(["ok"])
        if command == "Clear":
            self.transport.clear()
            return _CommandResult(["ok"])
        if command.startswith("MoveCursor("):
            row, col = [int(x) + 1 for x in command[11:-1].split(",")]
            self.transport._run(lambda: self.transport.session.set_cursor_position(row, col))
            return _CommandResult(["ok"])
        if command in {"Ascii", "Reset"}:
            return _CommandResult(["ok"])
        raise RuntimeError("unsupported tnz transport action: " + command)

    def close(self):
        self.transport.close()
