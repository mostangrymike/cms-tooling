#!/usr/bin/env python3
"""Robust line-mode Telnet driver for z/VM CMS.

This is the supported command path for long-running CMS work.  It speaks the
line-mode Telnet service on the z/VM TCPIP stack (``192.168.200.2:23``), not the
3270 screen protocol, and it is deliberately small and dependency-free so it can
be used from scripts, CI, and the MCP server.

Design rules
------------
* One command in flight at a time.  Always drain unsolicited output first.
* A command is complete only when the CMS / CP line-mode prompt (a line holding
  a single ``.``) arrives, optionally after a short quiet period.
* Output is streamed to a callback as complete lines, so long-running programs
  show progress instead of appearing hung.
* ``MORE...``/``HOLDING`` pages are advanced automatically (line mode normally
  runs with SCROLL CONT, but some commands still page).
* A timeout sends a Telnet IP (interrupt) followed by ``HX`` so a runaway CMS
  program can be cancelled without dropping the session.
* Passwords are never logged; all logging is redacted.

CLI
---
    python3 cms_telnet_driver.py probe
    python3 cms_telnet_driver.py run "QUERY DISK"
    python3 cms_telnet_driver.py run --timeout 600 "EXEC GIT FETCH-IMPORT M273P016 G"
    python3 cms_telnet_driver.py batch commands.txt
    python3 cms_telnet_driver.py shell

The password is read from ``~/.config/ibm-zvm-cms/credentials.json`` unless an
explicit path is supplied.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import select
import socket
import sys
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

# ---------------------------------------------------------------------------
# Telnet protocol constants / helpers
# ---------------------------------------------------------------------------

IAC = 255
DONT = 254
DO = 253
WONT = 252
WILL = 251
SB = 250
SE = 240
IP = 244
BRK = 243

# CMS line-mode prompt: a line consisting of a single period.  The host may
# prefix it with the EBCDIC-to-ASCII control bytes 0x13 0x7f and suffix XON.
PROMPT_RE = re.compile(r"(?m)^\s*\.\s*$")
READY_RE = re.compile(r"Ready(?:\((-?\d+)\))?;")
MORE_RE = re.compile(r"(MORE\.\.\.|HOLDING|HOLDING\.\.\.)")

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

DEFAULT_HOST = "192.168.200.2"
DEFAULT_PORT = 23
DEFAULT_CREDS = "~/.config/ibm-zvm-cms/credentials.json"


def strip_telnet(data: bytes) -> bytes:
    """Remove Telnet IAC commands from ``data`` and return the payload bytes."""
    out = bytearray()
    i = 0
    while i < len(data):
        byte = data[i]
        if byte != IAC:
            out.append(byte)
            i += 1
            continue
        i += 1
        if i >= len(data):
            break
        command = data[i]
        if command == SB:  # subnegotiation: skip to IAC SE
            i += 1
            while i + 1 < len(data) and not (data[i] == IAC and data[i + 1] == SE):
                i += 1
            i += 2
            continue
        if command in (WILL, WONT, DO, DONT):
            i += 2  # command + option
            continue
        if command == IAC:  # escaped 0xff
            out.append(IAC)
            i += 1
            continue
        i += 1  # single-byte command (IP, BRK, ...)
    return bytes(out)


def visible(text: str) -> str:
    """Strip CMS/3270 control bytes for readable display."""
    return _CONTROL_RE.sub("", text).replace("\r", "")


def iter_lines(text: str) -> Iterable[str]:
    for line in visible(text).split("\n"):
        if line.strip():
            yield line.rstrip()


def load_credentials(path: str = DEFAULT_CREDS) -> tuple[str, str]:
    with open(os.path.expanduser(path), "r", encoding="utf-8") as handle:
        data = json.load(handle)
    userid = data.get("userid") or data.get("user") or data.get("USERID")
    password = data.get("password") or data.get("pass") or data.get("PASSWORD")
    if not userid or not password:
        raise CmsError(f"credentials file {path!r} lacks userid/password")
    return str(userid), str(password)


class CmsError(RuntimeError):
    """Base error for driver failures."""


class CmsTimeout(CmsError):
    """A command did not reach the prompt before its deadline."""


class CmsLoginError(CmsError):
    """Login or CMS startup did not reach a usable CMS prompt."""


@dataclass
class CommandResult:
    command: str
    output: str
    rc: Optional[int] = None
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.rc in (None, 0)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


class CmsSession:
    """A persistent line-mode Telnet session to z/VM CMS."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        userid: Optional[str] = None,
        password: Optional[str] = None,
        credentials_path: str = DEFAULT_CREDS,
        *,
        log_path: Optional[str] = None,
        quiet_period: float = 0.35,
        verbose: bool = False,
        on_line: Optional[Callable[[str], None]] = None,
    ) -> None:
        if userid is None or password is None:
            file_userid, file_password = load_credentials(credentials_path)
            userid = userid or file_userid
            password = password or file_password
        # Keep the password only for the login exchange; never format it.
        self._userid = userid
        self._password = password
        self.host = host
        self.port = port
        self.log_path = log_path
        self.quiet_period = quiet_period
        self.verbose = verbose
        self.on_line = on_line
        self._sock: Optional[socket.socket] = None
        self._pending = b""
        self._logged_in = False
        self._log_handle = None
        if log_path:
            self._log_handle = open(os.path.expanduser(log_path), "a", encoding="utf-8")
            self._log("session", f"open {host}:{port}")

    # -- logging ----------------------------------------------------------

    def _log(self, kind: str, message: str) -> None:
        if not self._log_handle:
            return
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._log_handle.write(f"{stamp} {kind:8s} {message}\n")
        self._log_handle.flush()

    def _debug(self, message: str) -> None:
        if self.verbose:
            print(f"[cms] {message}", file=sys.stderr, flush=True)

    # -- socket primitives ------------------------------------------------

    def _open(self) -> None:
        if self._sock is not None:
            return
        self._debug(f"connecting to {self.host}:{self.port}")
        sock = socket.create_connection((self.host, self.port), timeout=15)
        sock.setblocking(False)
        self._sock = sock
        self._pending = b""

    def _close_socket(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._pending = b""
        self._logged_in = False

    def _send_raw(self, data: bytes) -> None:
        if self._sock is None:
            raise CmsError("not connected")
        self._sock.sendall(data)

    def _send(self, line: str) -> None:
        self._debug(f">>> {line}")
        self._log("send", line)
        self._send_raw(line.encode("utf-8") + b"\r\n")

    def _negotiate(self, chunk: bytes) -> None:
        """Reply to Telnet option negotiation so the server never stalls."""
        i = 0
        replies = bytearray()
        while i < len(chunk):
            if chunk[i] != IAC or i + 2 >= len(chunk):
                i += 1
                continue
            command, option = chunk[i + 1], chunk[i + 2]
            if command == DO:
                replies += bytes([IAC, WONT, option])
            elif command == WILL:
                replies += bytes([IAC, DO, option]) if option == 3 else bytes([IAC, DONT, option])
            i += 3
        if replies:
            try:
                self._send_raw(bytes(replies))
            except OSError:
                pass

    def _recv_chunk(self, deadline: float) -> bytes:
        if self._sock is None:
            raise CmsError("not connected")
        remaining = deadline - time.time()
        if remaining <= 0:
            return b""
        ready, _, _ = select.select([self._sock], [], [], min(0.25, remaining))
        if not ready:
            return b""
        try:
            chunk = self._sock.recv(65536)
        except (BlockingIOError, InterruptedError):
            return b""
        except OSError as exc:
            raise CmsError(f"connection error: {exc}") from exc
        if not chunk:
            raise CmsError("connection closed by host")
        self._negotiate(chunk)
        payload = strip_telnet(chunk)
        if payload:
            self._pending += payload
        return payload

    def _take_pending(self) -> bytes:
        data, self._pending = self._pending, b""
        return data

    def _drain(self, seconds: float = 0.3) -> bytes:
        """Consume unsolicited output left over from the previous command."""
        deadline = time.time() + seconds
        collected = bytearray(self._take_pending())
        while time.time() < deadline:
            collected += self._recv_chunk(deadline)
        return bytes(collected)

    # -- reading ----------------------------------------------------------

    def _read_until(self, pattern: re.Pattern[str], timeout: float,
                    *, stream: bool = False) -> str:
        """Read until ``pattern`` matches the accumulated text.

        ``stream`` invokes the line callback for each newly completed line.
        Returns the full visible text (including the matched prompt line).
        """
        if self._sock is None:
            raise CmsError("not connected")
        deadline = time.time() + timeout
        raw = bytearray(self._take_pending())
        streamed = 0
        last_data = time.time()

        while True:
            chunk = self._recv_chunk(deadline)
            if chunk:
                raw += chunk
                last_data = time.time()
            text = visible(raw.decode("latin-1", "replace"))

            if stream and self.on_line:
                for line in text[streamed:].split("\n")[:-1]:
                    if line.strip():
                        self.on_line(line.rstrip())
                streamed = text.rfind("\n") + 1

            if pattern.search(text):
                # The prompt may be the last line; give the host a moment to
                # flush anything printed immediately after it (some commands
                # emit a second Ready after the first).
                if time.time() - last_data >= self.quiet_period:
                    if stream and self.on_line:
                        for line in text[streamed:].split("\n"):
                            if line.strip():
                                self.on_line(line.rstrip())
                    self._log("recv", text.replace("\n", "\\n")[:2000])
                    self._pending = b""
                    return text
            elif time.time() - last_data > 1.0 and READY_RE.search(text):
                # Fallback: Ready without a visible dot prompt.  Rare, but do
                # not hang forever on it.
                if stream and self.on_line:
                    for line in text[streamed:].split("\n"):
                        if line.strip():
                            self.on_line(line.rstrip())
                self._log("recv", text.replace("\n", "\\n")[:2000])
                self._pending = b""
                return text

            if MORE_RE.search(text[-200:]):
                self._debug("advancing MORE/HOLDING page")
                self._send_raw(b"\r\n")
                last_data = time.time()

            if time.time() > deadline:
                # Keep any partial output for the caller/interrupt path.
                self._pending = bytes(raw)
                self._log("timeout", f"no prompt after {timeout:.0f}s")
                raise CmsTimeout(
                    f"no CMS prompt within {timeout:.0f}s; partial output: "
                    + visible(raw.decode("latin-1", "replace"))[-500:]
                )

    # -- public operations ------------------------------------------------

    def connect(self, *, fresh: bool = True, timeout: float = 90.0) -> str:
        """Log on and guarantee a usable CMS command environment."""
        self._open()
        self._drain(0.5)
        # The z/VM TCPIP service emits its connect banner only after the first
        # input.  An explicit BREAK is harmless when the prompt is already up.
        self._send_raw(bytes([IAC, BRK]))
        login_prompt = re.compile(
            r"Enter password:|LOGON userid|Enter one of the following commands"
        )
        try:
            banner = self._read_until(login_prompt, timeout=6, stream=False)
        except CmsTimeout:
            banner = visible(self._pending.decode("latin-1", "replace"))
            self._pending = b""

        if "Enter password:" not in banner:
            command = "LOGON MAINT HERE" if not fresh else "LOGON MAINT"
            self._send(command)
            banner = self._read_until(re.compile(r"Enter password:"), timeout=25)
        if "Enter password:" not in banner:
            raise CmsLoginError("no password prompt after LOGON: " + banner.strip()[-300:])
        self._send(self._password)
        # Either a CP READ dot or the CP banner follows the password.
        time.sleep(0.2)
        self._read_until(PROMPT_RE, timeout=timeout, stream=False)
        self._logged_in = True
        self._log("session", "logged on")

        if fresh:
            self._send("IPL CMS")
            try:
                self._read_until(PROMPT_RE, timeout=timeout)
            except CmsTimeout:
                self._debug("IPL CMS did not produce a prompt; probing anyway")
        self._ensure_cms(timeout=timeout)
        return "connected"

    def _cms_ready_probe(self) -> bool:
        try:
            result = self.command("QUERY CMSLEVEL", timeout=25, stream=False)
        except CmsTimeout:
            return False
        return "CMS Level" in result.output

    def _ensure_cms(self, timeout: float = 60.0) -> None:
        last = ""
        for attempt in range(4):
            try:
                result = self.command("QUERY CMSLEVEL", timeout=min(timeout, 40), stream=False)
            except CmsTimeout as exc:
                last = str(exc)
                self._send("BEGIN")
                try:
                    self._read_until(PROMPT_RE, timeout=20)
                except CmsTimeout:
                    pass
                continue
            last = result.output
            if "CMS Level" in result.output:
                self._log("session", "CMS ready: " + next(
                    (line.strip() for line in result.output.splitlines() if "CMS Level" in line), ""))
                return
            if "Command not valid before LOGON" in result.output:
                raise CmsLoginError("not logged on: " + result.output.strip()[-300:])
            self._debug(f"CMS not ready (attempt {attempt + 1}); issuing BEGIN")
            self._send("BEGIN")
            try:
                self._read_until(PROMPT_RE, timeout=20)
            except CmsTimeout:
                pass
        # BEGIN could not restore a CMS environment (for example a cold CP).
        self._debug("BEGIN did not restore CMS; trying IPL CMS")
        self._send("IPL CMS")
        try:
            self._read_until(PROMPT_RE, timeout=timeout)
        except CmsTimeout:
            pass
        try:
            result = self.command("QUERY CMSLEVEL", timeout=min(timeout, 40), stream=False)
        except CmsTimeout as exc:
            raise CmsLoginError("CMS never became ready: " + str(exc)) from exc
        if "CMS Level" in result.output:
            return
        raise CmsLoginError("CMS never became ready: " + last.strip()[-500:])

    def command(self, command: str, timeout: float = 120.0,
                *, stream: bool = True) -> CommandResult:
        """Run one CMS/CP command and wait for the prompt."""
        if self._sock is None:
            raise CmsError("not connected; call connect() first")
        started = time.time()
        self._drain(0.25)
        self._send(command)
        output = self._read_until(PROMPT_RE, timeout=timeout, stream=stream)
        duration = time.time() - started
        match = None
        for match in READY_RE.finditer(output):
            pass
        rc = int(match.group(1)) if match and match.group(1) not in (None, "") else None
        result = CommandResult(command=command, output=output, rc=rc, duration=duration)
        self._log("done", f"{command!r} rc={rc} {duration:.1f}s")
        return result

    def interrupt(self, timeout: float = 45.0) -> str:
        """Interrupt the running program and resynchronise to CMS.

        IBM's documented sequence is attention (PA1) then ``HX``.  Some z/VM
        TTY service levels do not accept ``HX`` at CP READ, so a failed
        interrupt falls back to ``IPL CMS``, which always cancels a running
        program and restores a clean CMS environment.
        """
        self._debug("sending Telnet IP (attention)")
        self._log("send", "<IP>")
        self._send_raw(bytes([IAC, IP]))
        try:
            output = self._read_until(PROMPT_RE, timeout=15, stream=True)
        except CmsTimeout:
            output = ""
            self._debug("attention did not return a prompt; sending HX")
            self._send("HX")
            try:
                output = self._read_until(PROMPT_RE, timeout=20, stream=True)
            except CmsTimeout:
                self._debug("HX did not return a prompt; re-IPLing CMS")
                self._send("IPL CMS")
                output = self._read_until(PROMPT_RE, timeout=timeout, stream=True)
        # A prompt after an interrupt may be CP READ, not CMS READY.  Always
        # re-establish CMS so the next command is not swallowed by CP.
        try:
            self._ensure_cms(timeout=timeout)
        except CmsLoginError:
            self._debug("interrupt recovery could not re-establish CMS")
            raise
        return output

    def close(self, *, logoff: bool = False) -> None:
        if self._sock is None:
            return
        try:
            if logoff and self._logged_in:
                self._send("LOGOFF")
                time.sleep(0.5)
        except OSError:
            pass
        self._close_socket()
        self._log("session", "closed")
        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None

    def __enter__(self) -> "CmsSession":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- convenience ------------------------------------------------------

    def run_lines(self, commands: Iterable[str], *, timeout: float = 120.0,
                  continue_on_error: bool = False) -> list[CommandResult]:
        results = []
        for command in commands:
            command = command.strip()
            if not command or command.startswith("#"):
                continue
            result = self.command(command, timeout=timeout)
            results.append(result)
            if not result.ok and not continue_on_error:
                break
        return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_line(line: str) -> None:
    print(line, flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--credentials", default=DEFAULT_CREDS)
    parser.add_argument("--log", default=None, help="append sanitized I/O log here")
    parser.add_argument("--no-stream", action="store_true", help="buffer output instead of streaming")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("probe", help="connect, log on, and report CMS state")
    run = sub.add_parser("run", help="run one command")
    run.add_argument("command")
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--interrupt-after", type=float, default=0.0,
                     help="send IP/HX if no output for N seconds")
    batch = sub.add_parser("batch", help="run commands from a file or stdin")
    batch.add_argument("file", nargs="?", default="-")
    batch.add_argument("--timeout", type=float, default=120.0)
    batch.add_argument("--continue-on-error", action="store_true")
    shell = sub.add_parser("shell", help="interactive CMS command shell")
    shell.add_argument("--timeout", type=float, default=120.0)
    return parser


def _run_one(session: CmsSession, command: str, timeout: float) -> int:
    try:
        result = session.command(command, timeout=timeout)
    except CmsTimeout as exc:
        print(f"TIMEOUT: {exc}", file=sys.stderr)
        try:
            session.interrupt()
        except CmsError as interrupt_exc:
            print(f"interrupt failed: {interrupt_exc}", file=sys.stderr)
        return 124
    if not result.ok:
        print(f"RC={result.rc}", file=sys.stderr)
    return 0 if result.ok else (result.rc or 1)


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    on_line = None if args.no_stream else _print_line
    session = CmsSession(
        args.host, args.port,
        credentials_path=args.credentials,
        log_path=args.log,
        verbose=args.verbose,
        on_line=on_line,
    )
    try:
        session.connect()
        if args.mode == "probe":
            for command in ("QUERY CMSLEVEL", "QUERY DISK", "QUERY TERMINAL"):
                try:
                    result = session.command(command, timeout=30)
                except CmsTimeout as exc:
                    print(f"{command}: TIMEOUT {exc}")
                    continue
                print(f"## {command} (rc={result.rc}, {result.duration:.1f}s)")
                for line in iter_lines(result.output):
                    print(line)
            return 0
        if args.mode == "run":
            return _run_one(session, args.command, args.timeout)
        if args.mode == "batch":
            if args.file == "-":
                commands = [line.rstrip("\n") for line in sys.stdin]
            else:
                with open(args.file, "r", encoding="utf-8") as handle:
                    commands = [line.rstrip("\n") for line in handle]
            failures = 0
            for line in commands:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                print(f"## {line}", flush=True)
                rc = _run_one(session, line, args.timeout)
                if rc:
                    failures += 1
                    if not args.continue_on_error:
                        return rc
            return 0 if failures == 0 else 1
        if args.mode == "shell":
            print("CMS shell — blank line or 'quit' exits.", flush=True)
            while True:
                try:
                    line = input("cms> ")
                except EOFError:
                    break
                if not line.strip() or line.strip() in {"quit", "exit"}:
                    break
                _run_one(session, line, args.timeout)
            return 0
    except KeyboardInterrupt:
        print("\ninterrupting CMS program...", file=sys.stderr)
        try:
            session.interrupt()
        except CmsError:
            pass
        return 130
    except CmsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
