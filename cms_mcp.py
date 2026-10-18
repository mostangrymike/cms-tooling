"""Local, explicit-connect z/VM terminal MCP server. No host commands on startup."""
from __future__ import annotations

import argparse
from collections import deque
import atexit
import logging
import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Literal

from py3270 import Emulator, CommandError
from cms_credentials import FileCredentialProvider
from cms_capture import any_cms_command, mask_frames, readonly_command

logging.getLogger("py3270").disabled = True

ROWS, COLS = 24, 80
HOST_ENDPOINT = "127.0.0.1:3271"


def device_selector(value):
    """Only a terminal selector is configurable; the host/port stay fixed."""
    if value == "auto":
        return value
    if isinstance(value, str) and re.fullmatch(r"(?:[0-9A-Fa-f]{4}|[A-Za-z][A-Za-z0-9]{0,7})@", value):
        return value.upper()
    raise ValueError("device must be auto, a four-hex-digit address with @, or a 1..8 alphanumeric group name with @")


def classify(rows: list[str]) -> dict:
    """Heuristics report observations, never command completion."""
    text = "\n".join(rows).upper()
    patterns = [
        ("login", r"USERID\s*===>[\s\S]*PASSWORD\s*===>"),
        ("password", r"(?:ENTER|TYPE|YOUR|LOGON).*PASSWORD|PASSWORD\s*[:=]|^\s*PASSWORD\s*$"),
        ("xedit", r"\bXEDIT\b|\*\*\* TOP OF FILE \*\*\*|\*\*\* END OF FILE \*\*\*"),
        ("holding", r"\bHOLDING\b"), ("more", r"\bMORE\.\.\.|\bMORE\s*$"),
        ("cp_read", r"\bCP READ\b"),
        ("cms_ready", r"^\s*READY(?:\(-?[0-9]+\))?;"),
        ("vm_read", r"\bVM READ\b"),
        # Retain a preliminary RUNNING classification until snapshot() can
        # combine it with guest-banner and input-field evidence.
        ("vm_running", r"\bRUNNING\s+[A-Z0-9*#@._-]+\s*$"),
        ("login", r"LOGON USERID|HCPLON\d+[A-Z]|ENTER.*LOGON"),
        ("logo", r"Z/VM ONLINE|HERCULES VERSION(?:\s*:|\s+\d)"),
    ]
    matches = [name for name, pattern in patterns if re.search(pattern, text, re.M)]
    if "HERCULES VERSION" in text:
        screen_kind = "hercules_banner"
    elif (re.search(r"Z/VM VERSION 6 RELEASE 3\.0", text)
          and re.search(r"\b(?:LOGON AT|RECONNECTED AT)\b", text)):
        screen_kind = "zvm_guest_banner"
    else:
        screen_kind = "guest_or_unknown"
    return {"state": matches[0] if matches else "unknown", "indicators": matches,
            "screen_kind": screen_kind,
            "cms_command_complete": None, "classification": "heuristic"}


def field_layout(lines: list[str]) -> list[dict]:
    """Parse SF attributes without ever returning field contents or raw hex."""
    starts = []
    pos = 0
    for token in " ".join(lines).split():
        if token.startswith("SA("):
            continue
        if token.startswith("SF("):
            m = re.search(r"c0=([0-9a-fA-F]{2})", token)
            if not m:
                raise ValueError("Field attribute missing c0")
            attr = int(m[1], 16)
            starts.append((pos, attr))
        elif not re.fullmatch(r"[0-9a-fA-F]{2,8}|-|GE\([0-9a-fA-F]{2}\)", token):
            raise ValueError("Unrecognized buffer token; contents withheld")
        pos += 1
    if pos != ROWS * COLS:
        raise ValueError(f"Expected 1920 screen positions, got {pos}")
    fields = []
    for i, (start, attr) in enumerate(starts):
        end = starts[(i + 1) % len(starts)][0]
        fields.append({"attribute_offset": start, "start_offset": (start + 1) % pos,
                       "length": (end - start - 1) % pos,
                       "row": (start + 1) % pos // COLS + 1,
                       "column": (start + 1) % COLS + 1,
                       "protected": bool(attr & 0x20), "numeric": bool(attr & 0x10),
                       "nondisplay": attr & 0x0C == 0x0C, "modified": bool(attr & 1)})
    return fields


def sanitize_rows(rows: list[str], fields: list[dict], secrets: set[str],
                  password: bool = False, layout_ok: bool = True) -> list[str]:
    flat = list("".join(rows))
    if not layout_ok or (secrets and not fields):
        return ["*" * COLS for _ in range(ROWS)]
    for field in fields:
        if field["nondisplay"] or ((password or secrets) and not field["protected"]):
            for n in range(field["length"]):
                flat[(field["start_offset"] + n) % len(flat)] = "*"
    text = "".join(flat)
    # Every input string is treated as potentially secret, including across rows.
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            text = re.sub(re.escape(secret), lambda m: "*" * len(m[0]), text, flags=re.I)
    # Protect credentials already present when attaching to a screen.
    rows = [text[i:i + COLS] for i in range(0, ROWS * COLS, COLS)]
    # Match inline passwords within one physical row, never the next row's
    # version banner or the ordinary 'LOGON AT <time>' diagnostic.
    safe_rows = []
    for row in rows:
        row = re.sub(r"(?i)(\bLOGON[ \t]+(?!AT(?:[ \t]|$))\S+[ \t]+)(\S+)",
                     lambda m: m[1] + "*" * len(m[2]), row)
        # CP READ may display an account/session identifier after the state.
        row = re.sub(r"(?i)(\b(?:CP READ|VM READ|RUNNING)[ \t]+)([A-Z0-9$#@._-]+)",
                     lambda m: m[1] + "*" * len(m[2]), row)
        safe_rows.append(row)
    return safe_rows


def host_display(screen):
    """Compare host-controlled display only, excluding local input and keyboard."""
    flat = list("".join(screen["rows"]))
    for field in screen["fields"]:
        if not field["protected"]:
            for n in range(field["length"]):
                flat[(field["start_offset"] + n) % 1920] = " "
    return "".join(flat)


class PipeApp:
    """py3270 application transport with deadlines and drained stderr.

    py3270's ordinary pipe readline is unbounded. A reader thread and queue keep
    emulator faults from hanging MCP. A timeout poisons the session; no retries.
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


class Session:
    def __init__(self, allow_input=False, factory=None, allow_login=False, credential_provider=None, allow_startup=False,
                 allow_commands=False, runner_name=None, allow_downloads=False,
                 download_root=None, download_runner_name=None, allow_local_edits=False,
                 allow_create_only_upload=False, allow_query_links=False, allow_arbitrary_commands=False,
                 allow_uploads=False, upload_root=None, default_device="0200@"):
        self.lock = threading.RLock()
        self.em = None
        self.default_device = device_selector(default_device)
        self.allow_input = allow_input
        self.allow_login = allow_login
        self.allow_startup = allow_startup
        self.allow_commands = allow_commands
        self.allow_arbitrary_commands = allow_arbitrary_commands
        self.allow_downloads = allow_downloads
        self.allow_uploads = allow_uploads
        self.upload_root = upload_root
        self.allow_local_edits = allow_local_edits
        self.allow_create_only_upload = allow_create_only_upload
        self.allow_query_links = allow_query_links
        self.completed_capture_token = None
        # Completed frames can remain visible across several short commands.
        # Only this live terminal's fully verified captures enter the history.
        self.completed_capture_tokens = deque(maxlen=128)
        self.capture_token = None
        self._protocol_rows = []
        from cms_commands import RunnerBridge
        self.runner = RunnerBridge(self, runner_name,
                                   policy=any_cms_command if allow_arbitrary_commands else readonly_command)
        from cms_link_query import LinkQuery
        self.link_query = LinkQuery(self)
        from cms_download import SourceDownloader
        self.downloader = SourceDownloader(self, download_root, download_runner_name)
        self.credential_provider = credential_provider
        self.factory = factory or (lambda: Emulator(app=PipeApp()))
        self.secrets = set()
        self.last_screen = None
        self.trace = []
        from cms_edit import SourceEdits
        self.edits = SourceEdits(self)
        from cms_upload import CreateOnlyUploader
        self.uploader = CreateOnlyUploader(self)
        from cms_upload import FileUploader
        self.file_uploader = FileUploader(self, upload_root)
        from cms_operations import OperationPlans
        self.operations = OperationPlans(self)

    def redact(self, text):
        for secret in sorted(self.secrets, key=len, reverse=True):
            text = re.sub(re.escape(secret), "<REDACTED>", text, flags=re.I)
        text = re.sub(r"(?i)(\bLOGON[ \t]+(?!AT(?:[ \t]|$))\S+[ \t]+)\S+", r"\1<REDACTED>", text)
        return text

    def command(self, action):
        label = ("String(<REDACTED>)" if action.startswith("String(") else
                 "HexString(<REDACTED>)" if action.startswith("HexString(") else action)
        entry = {"action": label}
        self.trace.append(entry)
        try:
            cmd = self.em.exec_command(action.encode("ascii"))
            data = [line.decode("utf-8", errors="replace") for line in cmd.data]
            entry["result"] = "ok"
            # Buffer evidence is represented by the sanitized screen/field map.
            if "ReadBuffer" not in action and "Ascii" not in action:
                entry["data"] = [self.redact(line) for line in data]
            return data
        except Exception as exc:
            entry["result"] = "error"
            entry["error_type"] = type(exc).__name__
            raise

    def snapshot(self, _expected_input=None):
        self.command("Snap(Save)")
        status = self.command("Snap(Status)")[0]
        parts = status.split()
        if len(parts) < 10 or parts[6:8] != ["24", "80"]:
            raise RuntimeError("Unexpected screen dimensions or malformed terminal status")
        rows = self.command("Snap(Ascii)")
        if len(rows) != ROWS or any(len(row) > COLS for row in rows):
            raise RuntimeError("Incomplete 24x80 screen capture")
        rows = [row.ljust(COLS) for row in rows]
        self._protocol_rows = rows if self.capture_token is not None else []
        fields = []
        layout_error = None
        try:
            fields = field_layout(self.command("Snap(ReadBuffer)"))
        except (TimeoutError, BrokenPipeError):
            raise
        except Exception as exc:
            layout_error = type(exc).__name__ + ": field layout unavailable; screen masked"
        observed = classify(rows)
        raw_flat = "".join(rows)
        for field in fields:
            field["empty"] = not any(raw_flat[(field["start_offset"] + n) % 1920].strip()
                                     for n in range(field["length"]))
        # After a CP LOGON password is accepted, Hercules can retain the
        # password instruction in the banner while the guest has already
        # reached its VM READ startup prompt. Refine only this exact empty,
        # visible, row-23 startup field shape with a fresh LOGON/RECONNECTED
        # marker; all other password screens remain password screens.
        editable = [field for field in fields if not field["protected"]]
        vm_read_startup = (observed["state"] == "password"
            and observed["screen_kind"] == "hercules_banner"
            and "VM READ" in rows[23].upper() and "CP READ" not in rows[23].upper()
            and re.search(r"\b(?:LOGON AT|RECONNECTED AT)\b", "\n".join(rows), re.I)
            and parts[0] == "U" and layout_error is None and len(editable) == 1
            and (editable[0]["row"], editable[0]["column"], editable[0]["length"],
                 editable[0]["nondisplay"], editable[0]["empty"]) == (23, 1, 139, False, True))
        if vm_read_startup:
            observed["state"] = "vm_read"
            observed["indicators"] = [item for item in observed["indicators"] if item != "password"]
        # A z/VM guest reconnect banner can leave CMS at its command field.
        # RUNNING is the CMS command-ready state; VM READ is a separate
        # running-program input state. Recognize only the observed z/VM 6.3
        # reconnect screen with one fresh, empty command field.
        zvm_reconnect_cms_ready = (observed["state"] == "vm_running"
            and observed["screen_kind"] == "zvm_guest_banner"
            and re.search(r"\bRECONNECTED AT\b", "\n".join(rows), re.I)
            and "RUNNING" in rows[-1].upper()
            and parts[0] == "U" and layout_error is None and len(editable) == 1
            and (editable[0]["row"], editable[0]["column"], editable[0]["length"],
                 editable[0]["nondisplay"], editable[0]["empty"])
                    == (23, 1, 139, False, True)
            and not re.search(r"\b(?:VM READ|CP READ)\b", "\n".join(rows), re.I))
        if zvm_reconnect_cms_ready:
            observed["state"] = "cms_ready"
            observed["indicators"] = [item for item in observed["indicators"] if item != "vm_running"]
            if "cms_ready" not in observed["indicators"]:
                observed["indicators"].append("cms_ready")
        safe = sanitize_rows(rows, fields, self.secrets, observed["state"] == "password",
                             layout_error is None)
        safe = mask_frames(safe)
        result = {"rows": safe, "row_count": ROWS, "column_count": COLS,
                  "coordinate_origin": 1, "cursor": {"row": int(parts[8]) + 1,
                  "column": int(parts[9]) + 1, "protected": parts[2] == "P"},
                  "keyboard": parts[0], "formatted": parts[1] == "F",
                  "connected": parts[3].startswith("C("), "emulator_mode": parts[4],
                  "terminal_status": status, "fields": fields,
                  "field_layout_error": layout_error, "input_enabled": self.allow_input,
                  "login_enabled": self.allow_login,
                  "startup_enabled": self.allow_startup,
                  "readonly_commands_enabled": self.allow_commands and not self.allow_arbitrary_commands,
                  "arbitrary_commands_enabled": self.allow_commands and self.allow_arbitrary_commands,
                  "downloads_enabled": self.allow_downloads,
                  "uploads_enabled": self.allow_uploads,
                  "local_edits_enabled": self.allow_local_edits,
                  "create_only_upload_enabled": self.allow_create_only_upload,
                  "query_links_enabled": self.allow_query_links,
                  "capture_active": self.capture_token is not None,
                  **observed}
        # Internal startup verification only: report a boolean, never the
        # unprotected field value. Public screen rows remain redacted.
        if _expected_input is not None:
            editable = [field for field in fields if not field["protected"]]
            matches = (len(editable) == 1 and len(_expected_input) <= editable[0]["length"]
                and "".join(raw_flat[(editable[0]["start_offset"] + n) % 1920]
                            for n in range(editable[0]["length"])
                    ) == _expected_input + " " * (editable[0]["length"] - len(_expected_input)))
            result["_expected_input_matches"] = bool(matches)
        self.last_screen = result
        return result

    def _stop(self):
        # Source verification belongs to this terminal session.
        self.runner.verified = False
        self.runner.completed_token = None
        self.downloader.reader.verified = False
        self.downloader.reader.completed_token = None
        self.completed_capture_token = None
        self.completed_capture_tokens.clear()
        if self.em is not None:
            try:
                # Closing our dedicated process only; never send LOGOFF or Clear.
                self.em.app.close()
            finally:
                self.em.is_terminated = True
                self.em = None

    def _run(self, operation, function, timeout=10):
        with self.lock:
            self.trace = []
            if self.em is not None:
                self.em.app.deadline = time.monotonic() + timeout
            try:
                return {"ok": True, **function()}
            except Exception as exc:
                # An unbounded/partial pipe reply cannot safely be reused.
                evidence = {"operation": operation, "error_type": type(exc).__name__,
                            "message": self.redact(str(exc)), "trace": self.trace,
                            "last_screen": self.last_screen}
                if self.em is not None:
                    if not isinstance(exc, (TimeoutError, BrokenPipeError)):
                        try:
                            self.em.app.deadline = time.monotonic() + 2
                            evidence["failure_screen"] = self.snapshot()
                        except Exception:
                            evidence["failure_screen_unavailable"] = True
                    app = self.em.app
                    self._stop()
                    evidence["emulator_stderr"] = self.redact(bytes(app.stderr).decode("utf-8", "replace"))
                    evidence["session_terminated"] = True
                return {"ok": False, **evidence}

    def connect(self, device: str | None = None, timeout=10):
        with self.lock:
            try:
                selector = device_selector(self.default_device if device is None else device)
            except ValueError as exc:
                return {"ok": False, "message": str(exc)}
            if type(timeout) is not int or not 1 <= timeout <= 30:
                return {"ok": False, "message": "timeout must be an integer in 1..30"}
            if self.em is not None:
                return {"ok": False, "message": "Session already exists; disconnect explicitly before reconnecting"}
            return self._connect(timeout, selector)

    def _connect(self, timeout, selector):
        def work():
            endpoint = HOST_ENDPOINT if selector == "auto" else selector + HOST_ENDPOINT
            self.em = self.factory()
            self.em.app.deadline = time.monotonic() + timeout
            self.command(f"Connect({endpoint})")
            self.command(f"Wait({timeout},3270Mode)")
            screen = self.snapshot()
            if any("CONNECTION REJECTED" in row.upper() for row in screen["rows"]):
                raise RuntimeError(f"Hercules rejected the connection for terminal selector {selector}")
            return {"endpoint": endpoint, "device_selector": selector, "screen": screen}
        return self._run("connect", work, timeout)

    def screen(self, wait_output=False, timeout=5):
        if type(wait_output) is not bool or type(timeout) is not int or not 1 <= timeout <= 10:
            return {"ok": False, "message": "wait_output must be boolean and timeout must be 1..10"}
        return self._run("screen", lambda: self._screen(wait_output, timeout), timeout + 1)

    def _screen(self, wait_output=False, timeout=5):
        if self.em is None:
            raise RuntimeError("No session; call cms_connect explicitly")
        output_observed = None
        if wait_output:
            # Arm the event-driven wait with an ASCII read; this sends no AID/key.
            self.command("Ascii")
            output_observed = self._wait_output(timeout)
        return {"screen": self.snapshot(), "wait_output_observed": output_observed}

    def status(self):
        with self.lock:
            if self.em is None:
                return {"ok": True, "connected": False, "state": "disconnected",
                        "input_enabled": self.allow_input, "login_enabled": self.allow_login,
                        "startup_enabled": self.allow_startup,
                        "readonly_commands_enabled": self.allow_commands and not self.allow_arbitrary_commands,
                        "arbitrary_commands_enabled": self.allow_commands and self.allow_arbitrary_commands,
                        "downloads_enabled": self.allow_downloads,
                        "uploads_enabled": self.allow_uploads,
                        "local_edits_enabled": self.allow_local_edits,
                        "create_only_upload_enabled": self.allow_create_only_upload,
                        "query_links_enabled": self.allow_query_links,
                        "cms_command_complete": None}
            return self.screen()

    @staticmethod
    def _login_layout(screen):
        expected = [(20, 17, 8, False), (21, 17, 8, True), (23, 17, 123, False)]
        fields = [f for f in screen["fields"] if not f["protected"]]
        actual = [(f["row"], f["column"], f["length"], f["nondisplay"]) for f in fields]
        rows = screen["rows"]
        if (screen["state"] != "login" or screen["field_layout_error"] is not None
                or not screen["connected"] or screen["emulator_mode"] != "I"
                or actual != expected or any(f["modified"] for f in fields)
                or "USERID" not in rows[19][:16] or "PASSWORD" not in rows[20][:16]
                or "COMMAND" not in rows[22][:16]):
            raise RuntimeError("Login form or field attributes differ from verified layout; no credentials submitted")
        return fields

    @staticmethod
    def _blank_vm_read_input(screen):
        rows = screen.get("rows", [])
        fields = [f for f in screen.get("fields", []) if not f["protected"]]
        labelled_vm_read = "VM READ" in rows[-1].upper() and "CP READ" not in rows[-1].upper()
        return (screen.get("state") == "vm_read"
                and screen.get("screen_kind") in {"hercules_banner", "zvm_guest_banner"}
                and screen.get("connected") and screen.get("keyboard") == "U"
                and screen.get("field_layout_error") is None and len(rows) == 24
                and len(fields) == 1
                and (fields[0]["row"], fields[0]["column"], fields[0]["length"],
                     fields[0]["nondisplay"], fields[0]["empty"])
                    == (23, 1, 139, False, True)
                and labelled_vm_read)

    @staticmethod
    def _runner_protocol_visible(screen):
        """A startup continuation must not consume a visible capture exchange."""
        return any(re.match(r"^\s*(?:ZM1|ZA1)\s+[0-9A-F]{16}\b", row)
                   for row in screen.get("rows", []))

    @staticmethod
    def _cp_input_field(screen, nondisplay=False, require_cursor=True):
        fields = [f for f in screen.get("fields", []) if not f["protected"]]
        return (screen.get("connected") and screen.get("keyboard") == "U"
                and screen.get("field_layout_error") is None
                and (not require_cursor or screen.get("cursor") == {
                    "row": 23, "column": 1, "protected": False})
                and len(fields) == 1 and fields[0]["row"] == 23
                and fields[0]["column"] == 1 and fields[0]["length"] == 139
                and fields[0]["nondisplay"] is nondisplay and fields[0]["empty"])

    @classmethod
    def _cp_logon_boundary(cls, screen, require_cursor=False):
        rows = screen.get("rows", [])
        text = "\n".join(rows).upper()
        menu = (rows[1].strip() == "Enter one of the following commands:"
                and re.match(r"\s*LOGON userid\b.*\bLOGON VMUSER1\)", rows[3], re.I)
                and rows[5].strip() == "LOGOFF")
        hercules_cp = (screen.get("screen_kind") == "hercules_banner"
                       and "DEVICE NUMBER" in text and "SUBCHANNEL" in text)
        return (screen.get("state") == "cp_read" and len(rows) == 24
                and cls._cp_input_field(screen, nondisplay=False,
                                        require_cursor=require_cursor)
                and "CP READ" in rows[23].upper() and (menu or hercules_cp)
                and not re.search(r"\b(?:RECONNECTED AT|LOGON AT)\b", text, re.I))

    @classmethod
    def _cp_password_prompt(cls, screen):
        rows = screen.get("rows", [])
        return (screen.get("state") == "password" and len(rows) == 24
                and cls._cp_input_field(screen, nondisplay=True)
                and re.search(r"\bPASSWORD\b", "\n".join(rows), re.I)
                and "CP READ" in rows[23].upper())

    def _cp_logon_maint(self, before, deadline):
        """One locally credentialed LOGON MAINT from the exact CP menu, no retries."""
        snapshots = [before]
        if not self._cp_logon_boundary(before):
            return {"ok": False, "outcome": "cp_logon_boundary_not_verified",
                    "submitted": False, "snapshots": snapshots,
                    "screen": before, "retry_performed": False,
                    "cms_command_complete": None}
        credentials = self.credential_provider.load()
        self.secrets.update({credentials.userid, credentials.password})
        if credentials.userid != "MAINT":
            return {"ok": False, "outcome": "cp_logon_userid_not_maint",
                    "submitted": False, "snapshots": snapshots,
                    "screen": before, "retry_performed": False,
                    "cms_command_complete": None}

        self.command("MoveCursor(22,0)")
        check = self.snapshot()
        snapshots.append(check)
        if (not self._cp_logon_boundary(check, require_cursor=True)
                or host_display(check) != host_display(before)):
            return {"ok": False, "outcome": "cp_logon_boundary_changed",
                    "submitted": False, "snapshots": snapshots,
                    "screen": check, "retry_performed": False,
                    "cms_command_complete": None}

        self.command('String("LOGON MAINT")')
        self.command("Ascii")
        self.command("Enter")
        submitted = True
        password_submitted = False
        previous = check
        while time.monotonic() < deadline:
            remaining = max(1, min(3, int(deadline - time.monotonic())))
            fresh = self._wait_output(remaining)
            after = self.snapshot()
            fresh = fresh or host_display(after) != host_display(previous)
            previous = after
            snapshots.append(after)
            text = "\n".join(after["rows"]).upper()
            if re.search(r"HCPLON\d+E|INVALID PASSWORD|INCORRECT PASSWORD|LOGON.*UNSUCCESSFUL", text):
                return {"ok": False, "outcome": "login_rejected", "submitted": submitted,
                        "password_submitted": password_submitted, "screen": after,
                        "snapshots": snapshots, "retry_performed": False,
                        "cms_command_complete": None}
            if fresh and self._cp_password_prompt(after):
                if password_submitted:
                    return {"ok": False, "outcome": "cp_password_reprompted",
                            "submitted": submitted, "password_submitted": True,
                            "screen": after, "snapshots": snapshots,
                            "retry_performed": False, "cms_command_complete": None}
                self.command("MoveCursor(22,0)")
                password_check = self.snapshot()
                snapshots.append(password_check)
                if (not self._cp_password_prompt(password_check)
                        or host_display(password_check) != host_display(after)):
                    return {"ok": False, "outcome": "cp_password_boundary_changed",
                            "submitted": submitted, "password_submitted": False,
                            "screen": password_check, "snapshots": snapshots,
                            "retry_performed": False, "cms_command_complete": None}
                self.command('String("' + credentials.password + '")')
                self.command("Ascii")
                self.command("Enter")
                password_submitted = True
                previous = password_check
                continue
            if (fresh and after["state"] in {"cp_read", "vm_read", "cms_ready"}
                    and re.search(r"\bRECONNECTED AT\b|\bLOGON AT\b", text)):
                return {"ok": True, "outcome": after["state"] + "_observed",
                        "submitted": submitted, "password_submitted": password_submitted,
                        "screen": after, "snapshots": snapshots,
                        "retry_performed": False,
                        "guest_logon_observed": True, "cms_command_complete": None}
            self.command("Ascii")
        return {"ok": False, "outcome": "cp_logon_transition_timeout",
                "submitted": submitted, "password_submitted": password_submitted,
                "screen": previous, "snapshots": snapshots,
                "retry_performed": False, "cms_command_complete": None}

    def _wait_output(self, seconds):
        try:
            self.command(f"Wait({seconds},Output)")
            return True
        except CommandError as exc:
            if "timed out" in str(exc).lower():
                return False
            raise

    def login(self, timeout=30):
        with self.lock:
            if not self.allow_login or self.credential_provider is None:
                return {"ok": False, "message": "Login requires --allow-login and a local credential provider"}
            if type(timeout) is not int or not 1 <= timeout <= 45:
                return {"ok": False, "message": "Login timeout must be 1..45 seconds"}

            def work():
                if self.em is None:
                    raise RuntimeError("Connect explicitly before login")
                deadline = time.monotonic() + timeout
                snapshots = []
                submitted = False
                before = self.snapshot()
                snapshots.append(before)
                # The Hercules welcome screen can precede the guest form.
                while before["state"] == "logo" and time.monotonic() < deadline:
                    self.command("Ascii")
                    self._wait_output(max(1, min(3, int(deadline - time.monotonic()))))
                    before = self.snapshot()
                    snapshots.append(before)
                if before["state"] in {"cms_ready", "vm_read"}:
                    return {"outcome": "existing_session_observed", "submitted": False,
                            "screen": before, "cms_command_complete": None}
                if before["state"] == "cp_read":
                    if re.search(r"\bRECONNECTED AT\b|\bLOGON AT\b",
                                 "\n".join(before["rows"]), re.I):
                        return {"outcome": "existing_session_observed", "submitted": False,
                                "screen": before, "cms_command_complete": None}
                    return self._cp_logon_maint(before, deadline)
                self._login_layout(before)
                # Reject existing form input using the field state captured
                # before screen sanitization. A prior login can leave secrets
                # in this session's redactor, which masks every editable field
                # in public screen rows even when those fields are empty.
                editable = {field["row"]: field for field in before["fields"]
                            if not field["protected"]}
                if any(not editable[row]["empty"] for row in (20, 21, 23)):
                    raise RuntimeError("Login form contains existing input; refusing to replace it")
                credentials = self.credential_provider.load()
                self.secrets.update({credentials.userid, credentials.password})
                for row, value, hidden in [(20, credentials.userid, False), (21, credentials.password, True)]:
                    self.command(f"MoveCursor({row - 1},16)")
                    current = self.snapshot()
                    field = next((f for f in current["fields"] if f["row"] == row and f["column"] == 17), None)
                    if (not field or field["protected"] or field["nondisplay"] != hidden
                            or field["length"] != 8 or current["state"] != "login"
                            or current["cursor"] != {"row": row, "column": 17, "protected": False}):
                        raise RuntimeError("Login field changed before credential input; login aborted")
                    self.command('String("' + value + '")')
                self.command("Ascii")
                self.command("Enter")
                submitted = True
                previous = current
                while time.monotonic() < deadline:
                    remaining = max(1, min(3, int(deadline - time.monotonic())))
                    fresh = self._wait_output(remaining)
                    after = self.snapshot()
                    # Output can arrive after a Wait timeout or be consumed by
                    # re-arming Ascii. Changed protected text is host evidence;
                    # editable input and keyboard unlock are deliberately excluded.
                    fresh = fresh or host_display(after) != host_display(previous)
                    previous = after
                    snapshots.append(after)
                    text = "\n".join(after["rows"]).upper()
                    if re.search(r"HCPLON\d+E|INVALID PASSWORD|INCORRECT PASSWORD|LOGON.*UNSUCCESSFUL", text):
                        return {"ok": False, "outcome": "login_rejected", "submitted": submitted,
                                "screen": after, "snapshots": snapshots, "retry_performed": False}
                    if fresh and after["state"] in {"cms_ready", "cp_read", "vm_read", "more", "holding"}:
                        return {"outcome": after["state"] + "_observed", "submitted": submitted,
                                "screen": after, "snapshots": snapshots, "retry_performed": False,
                                "guest_logon_observed": bool(re.search(r"\bLOGON AT\b|\bRECONNECTED\b", text)),
                                "cms_command_complete": None}
                    # Re-arm only after reading the observed screen. No scrolling,
                    # repeated Enter, BEGIN, LOGON command, or password retry.
                    self.command("Ascii")
                return {"ok": False, "outcome": "login_transition_timeout", "submitted": submitted,
                        "screen": self.last_screen, "snapshots": snapshots, "retry_performed": False}
            return self._run("login", work, timeout + 2)

    def startup(self, timeout=30, verify_cms=False, begin_vm=False):
        """Continue a verified startup read with one blank Enter or explicit VM begin."""
        with self.lock:
            if not self.allow_startup:
                return {"ok": False, "message": "Startup continuation requires --allow-startup"}
            if type(timeout) is not int or not 1 <= timeout <= 45:
                return {"ok": False, "message": "Startup timeout must be 1..45 seconds"}
            if type(begin_vm) is not bool:
                return {"ok": False, "message": "begin_vm must be boolean"}

            def work():
                if self.em is None:
                    raise RuntimeError("Connect and inspect/login before startup continuation")
                deadline = time.monotonic() + timeout
                current = self.snapshot()
                snapshots = [current]
                actions = []
                if self._runner_protocol_visible(current):
                    return {"ok": False, "outcome": "startup_runner_protocol_visible",
                            "screen": current, "snapshots": snapshots, "actions": actions,
                            "cms_command_complete": None}
                if current["state"] == "cms_ready":
                    return {"outcome": "cms_ready_already_observed", "screen": current,
                            "actions": [], "cms_command_complete": None}
                while time.monotonic() < deadline:
                    state = current["state"]
                    if begin_vm and state != "vm_read":
                        return {"ok": False, "outcome": "vm_begin_requires_vm_read",
                                "screen": current, "actions": actions, "snapshots": snapshots,
                                "cms_command_complete": None}
                    if state in {'more', 'holding'}:
                        return {'ok': False, 'outcome': 'startup_page_hold_observed',
                                'screen': current, 'actions': actions, 'snapshots': snapshots,
                                'cms_command_complete': None}
                    rows = "\n".join(current["rows"]).upper()
                    fields = [f for f in current["fields"] if not f["protected"]]
                    logon_marker = re.search(r"\bLOGON AT\b|\bRECONNECTED AT\b", rows)
                    blank_vm_read = self._blank_vm_read_input(current)
                    if (state not in {"vm_read", "cp_read"}
                            or not current["connected"] or current["field_layout_error"] is not None
                            or current["keyboard"] != "U" or len(fields) != 1
                            or (fields[0]["row"], fields[0]["column"], fields[0]["length"]) != (23, 1, 139)
                            or fields[0]["nondisplay"] or not fields[0]["empty"]
                            or not logon_marker and not blank_vm_read):
                        return {"ok": False, "outcome": "startup_boundary_not_verified", "screen": current,
                                "snapshots": snapshots, "actions": actions, "cms_command_complete": None}
                    # The single, blank CMS startup input is established from the
                    # recorded logon screen. Never clear or replace existing text.
                    self.command("MoveCursor(22,0)")
                    check = self.snapshot()
                    snapshots.append(check)
                    if self._runner_protocol_visible(check):
                        return {"ok": False, "outcome": "startup_runner_protocol_visible",
                                "screen": check, "snapshots": snapshots, "actions": actions,
                                "cms_command_complete": None}
                    target = [f for f in check["fields"] if not f["protected"]]
                    if (check['state'] == 'cms_ready' and self.runner.input_field(check)
                            and host_display(check) != host_display(current)):
                        # CMS can reach Ready while we recheck a startup field.
                        # Observe it without sending the now-unnecessary AID.
                        return {'outcome': 'cms_ready_observed', 'screen': check,
                                'actions': actions, 'snapshots': snapshots,
                                'cms_command_complete': None}
                    if check['state'] in {'more', 'holding'}:
                        # A reconnect can expose pending held output while the
                        # startup field is being checked. Capture and stop;
                        # startup authority never includes clearing that page.
                        return {'ok': False, 'outcome': 'startup_page_hold_observed',
                                'screen': check, 'actions': actions, 'snapshots': snapshots,
                                'cms_command_complete': None}
                    if (check["state"] != state or check["cursor"] != {"row": 23, "column": 1, "protected": False}
                            or target != fields
                            or blank_vm_read and (not self._blank_vm_read_input(check)
                                                  or host_display(check) != host_display(current))
                            or begin_vm and host_display(check) != host_display(current)):
                        raise RuntimeError("Startup field changed before input; continuation aborted")
                    if state == "cp_read":
                        self.command('String("BEGIN")')
                        actions.append("BEGIN")
                    elif begin_vm:
                        self.command('String("b")')
                        typed = self.snapshot(_expected_input="b")
                        input_matches = typed.pop("_expected_input_matches", False)
                        snapshots.append(typed)
                        if self._runner_protocol_visible(typed):
                            return {"ok": False, "outcome": "startup_runner_protocol_visible",
                                    "screen": typed, "snapshots": snapshots, "actions": actions,
                                    "cms_command_complete": None}
                        typed_fields = [f for f in typed["fields"] if not f["protected"]]
                        if (typed["state"] != "vm_read" or typed["keyboard"] != "U"
                                or typed["field_layout_error"] is not None or len(typed_fields) != 1
                                or (typed_fields[0]["row"], typed_fields[0]["column"], typed_fields[0]["length"])
                                    != (23, 1, 139)
                                or typed_fields[0]["nondisplay"] or typed_fields[0]["empty"]
                                or not input_matches
                                or typed["cursor"] != {"row": 23, "column": 2, "protected": False}
                                or host_display(typed) != host_display(check)):
                            return {"ok": False, "outcome": "vm_begin_input_not_verified",
                                    "screen": typed, "actions": actions, "snapshots": snapshots,
                                    "cms_command_complete": None}
                        actions.append("b")
                    self.command("Ascii")
                    self.command("Enter")
                    actions.append("Enter")
                    # Only fresh host output can establish the post-action state.
                    while time.monotonic() < deadline:
                        fresh = self._wait_output(max(1, min(3, int(deadline - time.monotonic()))))
                        previous = current
                        current = self.snapshot()
                        fresh = fresh or host_display(current) != host_display(previous)
                        snapshots.append(current)
                        if fresh and current["state"] == "cms_ready":
                            return {"outcome": "cms_ready_observed", "screen": current, "actions": actions,
                                    "snapshots": snapshots, "cms_command_complete": None}
                        if current["state"] in {"more", "holding"}:
                            return {"ok": False, "outcome": "startup_page_hold_observed", "screen": current,
                                    "actions": actions, "snapshots": snapshots, "cms_command_complete": None}
                        if fresh and current["state"] != state:
                            break
                        self.command("Ascii")
                    if current["state"] != state:
                        return {"ok": False, "outcome": "startup_transition_observed", "screen": current,
                                "snapshots": snapshots, "actions": actions, "cms_command_complete": None}
                    break
                return {"ok": False, "outcome": "startup_transition_timeout", "screen": current,
                        "snapshots": snapshots, "actions": actions, "cms_command_complete": None}
            result = self._run("startup", work, timeout + 2)
            if (verify_cms and not result["ok"] and self.em is not None
                    and result.get('outcome') != 'startup_page_hold_observed'):
                from diagnose_cms import probe
                verified = probe(self, result, host_display)
                return {**verified, "startup": result}
            return result

    def send(self, action, text=None, number=None, row=None, column=None,
             sensitive=False, wait="none", timeout=5):
        # Validate before touching a session. No arbitrary action strings/macros.
        with self.lock:
            try:
                if not self.allow_input:
                    raise ValueError("Observation-only server; input requires --allow-input and operator authorization")
                if not 1 <= timeout <= 30:
                    raise ValueError("timeout must be 1..30 seconds")
                if wait not in {"none", "output"}:
                    raise ValueError("wait must be none or output; unlock never proves CMS completion")
                simple = {"Enter", "Clear", "Home", "Tab", "BackTab", "EraseInput", "Reset"}
                if action == "String":
                    if not isinstance(text, str) or not 1 <= len(text) <= 1920:
                        raise ValueError("String requires 1..1920 printable ASCII characters")
                    if any(ord(c) < 32 or ord(c) > 126 for c in text) or "\\" in text:
                        raise ValueError("String rejects controls, non-ASCII, and backslash action escapes")
                    self.secrets.add(text)
                    # Also redact inline credentials individually from future screens.
                    if sensitive or re.match(r"(?i)^\s*LOGON\s", text):
                        self.secrets.update(text.split())
                    command = 'String("' + text.replace('"', '\\"') + '")'
                elif action in {"PF", "PA"}:
                    if type(number) is not int or not 1 <= number <= (24 if action == "PF" else 3):
                        raise ValueError("PF requires 1..24; PA requires 1..3")
                    command = f"{action}({number})"
                elif action == "MoveCursor":
                    if type(row) is not int or type(column) is not int or not 1 <= row <= 24 or not 1 <= column <= 80:
                        raise ValueError("MoveCursor requires row 1..24, column 1..80")
                    command = f"MoveCursor({row - 1},{column - 1})"
                elif action in simple:
                    command = action
                else:
                    raise ValueError("Unsupported terminal action")
                if action != "String" and (text is not None or sensitive):
                    raise ValueError("text/sensitive apply only to String")
                if action not in {"PF", "PA"} and number is not None:
                    raise ValueError("number applies only to PF/PA")
                if action != "MoveCursor" and (row is not None or column is not None):
                    raise ValueError("row/column apply only to MoveCursor")
            except ValueError as exc:
                return {"ok": False, "operation": "send", "error_type": "ValidationError", "message": str(exc)}

            def work():
                if self.em is None:
                    raise RuntimeError("No session; call cms_connect explicitly")
                before = self.snapshot()
                if action == "String" and (before["state"] == "password" or
                        any(f["nondisplay"] for f in before["fields"])):
                    self.secrets.update(text.split())
                if wait == "output":
                    # Arm Wait(Output) before the action so early host output
                    # is observed. Snap(Wait,...,Output) crashes s3270 4.5ga6
                    # in snap_save on this host when the guest updates a banner.
                    self.command("Ascii")
                self.command(command)
                synchronization = "action_returned"
                if wait == "output":
                    self.command(f"Wait({timeout},Output)")
                    synchronization = "host_output_observed"
                return {"action": action, "synchronization": synchronization,
                        "cms_command_complete": None, "before": before, "screen": self.snapshot()}
            return self._run("send", work, timeout + 2)

    def disconnect(self):
        with self.lock:
            existed = self.em is not None
            self._stop()
            self.secrets.clear()
            self.last_screen = None
            self.capture_token = None
            self._protocol_rows = []
            self.runner.verified = False
            return {"ok": True, "connected": False, "terminated": existed}


def create_server(session):
    from contextlib import asynccontextmanager
    from mcp.server.fastmcp import FastMCP

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield {}
        finally:
            session.disconnect()

    server = FastMCP("ibm-cms", lifespan=lifespan,
                    instructions="Explicit-connect z/VM terminal. Inspect screen/fields before input. "
                    "Never infer CMS completion from keyboard unlock. Input needs operator authorization.")

    @server.tool()
    def cms_connect(device: str | None = None, timeout: int = 10) -> dict:
        """Connect to fixed TN3270 127.0.0.1:3271. Device: auto, 0200@, or GROUP@.

        Omit device to use server --device (default 0200@). Auto selects an
        available Hercules terminal. Group names are 1..8 alphanumeric characters
        starting with a letter. Connection sends no login input.
        """
        return session.connect(device, timeout)

    @server.tool()
    def cms_screen(wait_output: bool = False, timeout: int = 5) -> dict:
        """Read a complete sanitized screen; optionally wait for host output without sending input."""
        return session.screen(wait_output, timeout)

    @server.tool()
    def cms_status() -> dict:
        """Observe logo/login/password/CP READ/VM READ/running/CMS Ready/MORE/HOLDING/XEDIT/unknown; no completion claim."""
        return session.status()

    @server.tool()
    def cms_send(action: Literal["String", "Enter", "Clear", "PF", "PA", "Home", "Tab", "BackTab", "EraseInput", "Reset", "MoveCursor"],
                 text: str | None = None, number: int | None = None,
                 row: int | None = None, column: int | None = None, sensitive: bool = False,
                 wait: Literal["none", "output"] = "none", timeout: int = 5) -> dict:
        """Send ONE authorized terminal action. String does not press Enter. Coordinates are 1-based.

        Requires --allow-input. Never send LOGON/passwords/commands without operator authorization.
        wait=output only observes host output, never command completion. No macros or transfers.
        Tool arguments may be retained by the MCP client: do not pass passwords through Codex.
        """
        return session.send(action, text, number, row, column, sensitive, wait, timeout)

    @server.tool()
    def cms_login(timeout: int = 30) -> dict:
        """Perform one locally credentialed login through a verified guest form or CP MAINT menu.

        Requires --allow-login and --credential-file. Takes no credential arguments.
        The CP route accepts only the exact command menu or Hercules CP READ banner
        and userid MAINT, sends LOGON MAINT once, and responds once only to a
        verified nondisplay password field. No retries, Clear, BEGIN, CMS commands
        or transfers.
        """
        return session.login(timeout)

    @server.tool()
    def cms_startup(timeout: int = 30, verify_cms: bool = False,
                    begin_vm: bool = False) -> dict:
        """Continue verified startup with one Enter, CP BEGIN, or explicit VM b.

        Requires --allow-startup. Verifies startup provenance and exact field
        layout. Normally sends one blank Enter at VM READ, or BEGIN and Enter at
        CP READ. begin_vm=True instead types exactly lowercase b at an empty VM
        READ field, verifies that one-character input, then presses Enter once.
        Never clears input, repeats keys blindly, runs arbitrary commands or
        transfers files. Returns CMS Ready only after fresh host output.
        verify_cms=True authorizes one fixed read-only QUERY CMSLEVEL probe if
        the recorded blank CMS prompt follows startup without a Ready message.
        """
        return session.startup(timeout, verify_cms, begin_vm)

    @server.tool()
    def cms_prepare_runner(create: bool = False) -> dict:
        """Verify a configured runner, or explicitly create one new randomly named EXEC on A.

        Requires --allow-commands. create=true creates only an absent ZMxxxxxx
        EXEC A using Exist=keep, then verifies its source by round-trip download.
        Never replaces or erases a CMS file. Retains the helper for reuse.
        """
        with session.lock:
            return session.runner.prepare(create)

    @server.tool()
    def cms_command(command: str, timeout: int = 120) -> dict:
        """Run a CMS command and capture complete records with its actual CMS-stage RC.

        Requires --allow-commands and a source-verified runner. --allow-arbitrary-commands
        removes the read-only allowlist while retaining one-line printable input,
        complete nonce-correlated output, byte counts, checksums, acknowledgements
        and actual CMS return codes. The wrapper reserves | and # for capture
        framing; interactive/full-screen commands cannot return a complete result.
        """
        with session.lock:
            return session.runner.run(command, timeout)

    @server.tool()
    def cms_query_links(vaddr: str, timeout: int = 120) -> dict:
        """Run CP QUERY LINKS for one virtual address; this observes links, not a lock."""
        with session.lock:
            return session.link_query.query(vaddr, timeout)

    @server.tool()
    def cms_download(filename: str, filetype: str, filemode: str,
                     create_runner: bool = False, timeout: int = 300) -> dict:
        """Download one literal CMS file into a new snapshot under the configured local Git worktree.

        Requires --allow-downloads, --allow-commands and --download-root. No host
        source edits, erasure or replacement. Captures native records twice and
        verifies metadata, lengths, checksums and equality before writing local
        bytes, record metadata and optional UTF-8 text preserving trailing blanks.
        A configured reader helper is source-verified first. Explicit
        create_runner=true may create ONE new unique reader EXEC on A; never
        replaces helpers. No arbitrary local destination or Git commit/staging.
        """
        return session.downloader.download(filename, filetype, filemode, create_runner, timeout)

    @server.tool()
    def cms_edit_prepare(snapshot: str) -> dict:
        """Create a LOCAL editable workspace from a downloaded snapshot identifier.

        Requires --allow-local-edits and --download-root. Validates original
        hashes/record boundaries and preserves a pinned baseline. Returns a
        working file for Codex to edit locally. No host connection, credentials
        in arguments, Git staging/commit, CMS command or source upload.
        """
        return session.edits.prepare(snapshot)

    @server.tool()
    def cms_edit_plan(edit_id: str) -> dict:
        """Validate a local edit and write a complete diff and review-only upload plan.

        Rechecks original snapshot/baseline hashes. Strict cp037; rejects overlong
        records, ambiguous line endings, binary text and credentials. F records
        are padded without truncation; V trailing blanks remain significant.
        Emits candidate native bytes, record lengths, base/candidate hashes and
        required future upload checks. Does not authorize or implement an upload.
        """
        return session.edits.plan(edit_id)

    @server.tool()
    def cms_operation_plan(edit_id: str, plan_id: str, plan_sha256: str, recipe: dict) -> dict:
        """Create a LOCAL review-only replacement/build manifest; never execute it.

        Requires --allow-local-edits and --download-root. Revalidates the exact
        source plan, snapshot, baseline, working file, candidate and diff. Recipe
        steps declare command-token lists, inputs, create-only outputs, expected
        RCs and output markers. Optional writer_exclusion and rollback details
        remain unverified operator statements. Missing inputs and execution
        blockers are returned explicitly. No host connection, replacement,
        build, cleanup or execution authorization is performed.
        """
        return session.operations.plan(edit_id, plan_id, plan_sha256, recipe)

    @server.tool()
    def cms_upload_create_only(edit_id: str, plan_id: str, plan_sha256: str,
                               target: str, candidate_sha256: str, timeout: int = 120) -> dict:
        """Create one explicitly named disposable ZVxxxxxx EXEC A1 and verify exact readback.

        Requires --allow-create-only-upload, a verified read-only runner, an
        exact changed fixed-80 plan, the exact candidate hash and an absent
        target. Refuses every existing target and every protected name. This
        creates a CMS file; it never replaces or erases one. The scratch file
        is retained for explicit later cleanup. The create/readback sequence is
        serialized in this session but is not atomic against other CMS sessions.
        """
        return session.uploader.upload(edit_id, plan_id, plan_sha256, target, candidate_sha256, timeout)

    @server.tool()
    def cms_upload_file(source_path: str, filename: str, filetype: str, filemode: str,
                        mode: Literal["ascii", "binary"] = "ascii",
                        recfm: Literal["fixed", "variable", "undefined"] = "fixed",
                        lrecl: int | None = 80, overwrite_existing: bool = False,
                        timeout: int = 120) -> dict:
        """Upload a local file to one exact CMS file ID, without a per-call approval prompt.

        Requires --allow-uploads, --upload-root, and a source-verified command
        runner. source_path is relative to the configured local Git worktree.
        Existing targets require overwrite_existing=true. ASCII fixed records
        are space-padded to LRECL; binary mode sends the supplied bytes. Transfer
        completion and target presence are verified; target content is not read
        back by this generic path. The target presence check is not atomic against
        other CMS sessions. Use cms_download for verified native readback.
        """
        with session.lock:
            return session.file_uploader.upload(source_path, filename, filetype, filemode,
                mode=mode, recfm=recfm, lrecl=lrecl,
                overwrite_existing=overwrite_existing, timeout=timeout)

    @server.tool()
    def cms_disconnect() -> dict:
        """Terminate only this server's dedicated s3270 process; sends no LOGOFF or CMS command."""
        return session.disconnect()

    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", type=device_selector, default="0200@",
                        help="Default terminal selector: auto, four hex digits plus @, or GROUP@")
    parser.add_argument("--allow-input", action="store_true", help="Enable explicitly authorized terminal input")
    parser.add_argument("--allow-login", action="store_true", help="Enable one-shot local-credential login only")
    parser.add_argument("--allow-startup", action="store_true", help="Enable verified logon/startup continuation only")
    parser.add_argument("--credential-file", help="Path to owner-only JSON credentials; no values in MCP arguments")
    parser.add_argument("--allow-commands", action="store_true", help="Enable correlated CMS command capture")
    parser.add_argument("--allow-arbitrary-commands", action="store_true",
                        help="Remove the CMS read-only command allowlist; keep framed, complete-output capture")
    parser.add_argument("--allow-query-links", action="store_true",
                        help="Enable an isolated, exact-command CP QUERY LINKS helper")
    parser.add_argument("--runner-name", help="Reuse a ZMxxxxxx EXEC A after source verification")
    parser.add_argument("--allow-downloads", action="store_true", help="Enable verified read-only source downloads")
    parser.add_argument("--download-root", help="Snapshot destination inside an existing local Git worktree")
    parser.add_argument("--download-runner-name", help="Reuse a separate ZMxxxxxx file reader after source verification")
    parser.add_argument("--allow-local-edits", action="store_true", help="Enable offline local source editing and review-only plans")
    parser.add_argument("--allow-create-only-upload", action="store_true",
                        help="Enable explicit create-only fixed-80 source upload/readback validation")
    parser.add_argument("--allow-uploads", action="store_true", help="Enable explicit CMS DFT file uploads")
    parser.add_argument("--upload-root", help="Local upload source root inside a Git worktree")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, stream=__import__("sys").stderr)
    # py3270 DEBUG logs contain raw commands and buffer hex. Disable at source.
    logging.getLogger("py3270").disabled = True
    if args.allow_login and not args.credential_file:
        parser.error("--allow-login requires --credential-file")
    if args.allow_arbitrary_commands and not args.allow_commands:
        parser.error("--allow-arbitrary-commands requires --allow-commands")
    if args.allow_uploads and not args.upload_root:
        parser.error("--allow-uploads requires --upload-root")
    session = Session(allow_input=args.allow_input, allow_login=args.allow_login,
                      credential_provider=FileCredentialProvider(args.credential_file) if args.credential_file else None,
                      allow_startup=args.allow_startup, allow_commands=args.allow_commands, runner_name=args.runner_name,
                      allow_arbitrary_commands=args.allow_arbitrary_commands,
                      allow_downloads=args.allow_downloads, download_root=args.download_root,
                      allow_uploads=args.allow_uploads, upload_root=args.upload_root,
                      download_runner_name=args.download_runner_name, allow_local_edits=args.allow_local_edits,
                      allow_create_only_upload=args.allow_create_only_upload,
                      allow_query_links=args.allow_query_links, default_device=args.device)
    atexit.register(session.disconnect)
    create_server(session).run(transport="stdio")


if __name__ == "__main__":
    main()
