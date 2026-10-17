"""Guarded runner provisioning and read-only, complete CMS command capture."""
from pathlib import Path
import re
import secrets
import tempfile
import time

from zvm_capture import Capture, CaptureError, frames, readonly_command

SOURCE = Path(__file__).with_name("ZMCPRUN.EXEC")


def ready_rc(row):
    m = re.fullmatch(r"\s*Ready(?:\((-?[0-9]+)\))?;(?:\s+\((-?[0-9]+)\))?.*", row, re.I)
    return int(m[1] or m[2] or "0") if m else None


class RunnerBridge:
    def __init__(self, session, name=None, source=SOURCE, policy=readonly_command):
        if name is not None and not re.fullmatch(r"ZM[0-9A-F]{6}", name):
            raise ValueError("Runner name must be ZM followed by six uppercase hex digits")
        self.session = session
        self.name = name
        self.verified = False
        self.completed_token = None
        self.source = source
        self.policy = policy
        self.bootstrap_evidence = None
        self.max_timeout = 300

    @staticmethod
    def input_field(screen):
        fields = [f for f in screen["fields"] if not f["protected"]]
        return (screen["connected"] and screen["keyboard"] == "U"
                and screen["field_layout_error"] is None and len(fields) == 1
                and (fields[0]["row"], fields[0]["column"], fields[0]["length"]) == (23, 1, 139)
                and fields[0].get("empty") and not fields[0]["nondisplay"])

    def _input(self, text):
        s = self.session
        before = s.snapshot()
        if not self.input_field(before):
            raise CaptureError("Command/ack input field is not verified empty and writable")
        s.command("MoveCursor(22,0)")
        check = s.snapshot()
        if not self.input_field(check) or check["cursor"] != {"row": 23, "column": 1, "protected": False}:
            raise CaptureError("Input cursor or field changed; no text submitted")
        if not re.fullmatch(r"[A-Z0-9 @$*%]+", text):
            raise CaptureError("Invalid internal command or acknowledgement")
        s.command('String("' + text + '")')
        s.command("Ascii")
        s.command("Enter")

    def _ready_boundary(self):
        s = self.session
        screen = s.snapshot()
        if screen["state"] != "cms_ready" or not self.input_field(screen):
            raise CaptureError("Establish CMS Ready and an empty input field before command execution")
        # Never mistake an interrupted runner's old Ready prompt for a shell.
        completed = {*s.completed_capture_tokens, self.completed_token, s.completed_capture_token}
        for row in screen["rows"]:
            match = re.search(r"ZM1 ([0-9A-F]{16}) [BRDZF] ", row)
            if match and match[1] not in completed:
                raise CaptureError("Unresolved runner output is present; refusing a new command")
        return screen

    def _simple(self, command, deadline):
        """Internal fixed read-only observations; require echoed command and Ready RC.

        Used by helper STATE preconditions and the fixed compiler diagnostic.
        This is not a public or general command dispatch interface.
        """
        from zvm_mcp import host_display
        readonly_command(command)
        before = self._ready_boundary()
        # A repeated visible echo cannot be distinguished from this dispatch
        # before the host responds. Fail before input instead of reusing its RC.
        if any(row.strip().upper() == command for row in before['rows']):
            raise CaptureError("Prior matching STATE echo is still visible; fresh completion cannot be established")
        self._input(command)
        cleared_echo_page = None
        held_pages = set()
        evidence = []
        self.bootstrap_evidence = {"command": command, "snapshots": evidence}
        while time.monotonic() < deadline:
            snap = self.session.snapshot()
            evidence.append(snap)
            positions = [i for i, row in enumerate(snap["rows"]) if row.strip().upper() == command]
            # Re-locate the echo on EVERY snapshot. Remembering a boolean across
            # scans can select an older Ready ABOVE a newly echoed command.
            start = max(positions) + 1 if positions else None
            console = host_display(snap)[:22 * 80]
            if start is None and cleared_echo_page is not None and console != cleared_echo_page:
                start = 0
            if start is not None and snap['state'] == 'cms_ready' and self.input_field(snap):
                visible = [i for i in range(start, 22) if snap['rows'][i].strip()]
                if visible and ready_rc(snap['rows'][visible[-1]]) is not None:
                    rc = ready_rc(snap['rows'][visible[-1]])
                    self.bootstrap_evidence["rc"] = rc
                    return {"rc": rc, "snapshots": evidence}
            if snap["state"] in {"more", "holding"}:
                if not positions and cleared_echo_page is None:
                    raise CaptureError('Paging appeared before the bootstrap command echo')
                page = console
                if page in held_pages:
                    self.session._wait_output(1)
                    continue
                if len(held_pages) >= 64:
                    raise CaptureError('Bootstrap observation exceeded the 64-page capture limit')
                held_pages.add(page)
                if positions:
                    cleared_echo_page = console
                self.session.command("Clear")
            else:
                self.session._wait_output(1)
        raise CaptureError("Bootstrap STATE did not return correlated Ready/RC evidence")

    def _transfer(self, action):
        # AidWait=false is needed for terminal synchronization, but also makes
        # Transfer() asynchronous. Temporarily block on the emulator's transfer
        # completion; a transport failure poisons the process and is not retried.
        s = self.session
        before = s.snapshot()
        if not self.input_field(before):
            raise CaptureError("Transfer command field is not verified empty and writable")
        s.command("MoveCursor(22,0)")
        check = s.snapshot()
        if not self.input_field(check) or check["cursor"] != {"row": 23, "column": 1, "protected": False}:
            raise CaptureError("Transfer input cursor or field changed")
        s.command("Ascii")
        s.command("Set(AidWait,true)")
        result = s.command(action)
        s.command("Set(AidWait,false)")
        # DFT completion precedes CMS restoring its line-mode command field.
        # Starting another Transfer immediately can lose the command prefix.
        from zvm_mcp import host_display
        deadline = time.monotonic() + 10
        fresh = False
        while time.monotonic() < deadline:
            after = s.snapshot()
            fresh = fresh or host_display(after) != host_display(before)
            prompts = [ready_rc(row) for row in after["rows"] if ready_rc(row) is not None]
            if fresh and after["state"] == "cms_ready" and self.input_field(after) and prompts and prompts[-1] == 0:
                return result
            fresh = s._wait_output(1) or fresh
        raise CaptureError("Transfer finished, but fresh CMS Ready and command field are unverified")

    def prepare(self, create=False, timeout=60):
        s = self.session
        if type(timeout) is not int or not 1 <= timeout <= 60:
            return {"ok": False, "message": "Runner preparation timeout must be 1..60 seconds"}
        if not s.allow_commands:
            return {"ok": False, "message": "Read-only commands require --allow-commands"}
        if self.name is None and not create:
            return {"ok": False, "message": "No runner configured; explicit create=true is required to create a new EXEC"}
        def work():
            source = self.source.read_text(encoding="ascii")
            if any(len(line) > 80 for line in source.splitlines()):
                raise CaptureError("Runner source exceeds the fixed-80 transfer format")
            self._ready_boundary()
            created = self.name is None
            name = self.name or "ZM" + secrets.token_hex(3).upper()
            state = self._simple(f"STATE {name} EXEC A", time.monotonic() + 15)
            if state["rc"] != (28 if created else 0):
                raise CaptureError("Runner filename is not absent/existing as required; no replacement allowed")
            self.name = name  # Retain the candidate identity even if transfer/verification fails.
            with tempfile.TemporaryDirectory(prefix="zvm_mcp_") as directory:
                local = Path(directory) / "runner.exec"
                downloaded = Path(directory) / "received.exec"
                local.write_text(source, encoding="ascii")
                if created:
                    self._transfer(f'Transfer(Direction=send,"HostFile={name} EXEC A",LocalFile={local},Host=vm,Mode=ascii,Exist=keep,Recfm=fixed,Lrecl=80,BufferSize=2048)')
                self._transfer(f'Transfer(Direction=receive,"HostFile={name} EXEC A",LocalFile={downloaded},Host=vm,Mode=ascii,Cr=add,Exist=keep,BufferSize=2048)')
                if not downloaded.is_file():
                    raise CaptureError("Runner round-trip download is missing")
                expected = [line.rstrip() for line in source.splitlines()]
                actual = [line.rstrip() for line in downloaded.read_text(encoding="ascii").splitlines()]
                if actual != expected:
                    raise CaptureError("Runner round-trip source verification failed; helper retained, not executed")
            self.verified = True
            return {"runner": name, "fileid": f"{name} EXEC A", "created": created,
                    "source_verified": True, "existing_files_replaced": False,
                    "host_output_files_created": False, "retained_on_host": True}
        result = s._run("prepare_runner", work, timeout=timeout)
        if not result["ok"] and self.bootstrap_evidence is not None:
            result["bootstrap"] = self.bootstrap_evidence
        if not result["ok"] and self.name is not None:
            result.update({"runner": self.name, "retained_on_host_if_created": True, "source_verified": False})
        return result

    def run(self, command, timeout=120):
        s = self.session
        try:
            command = self.policy(command)
            if (type(self.max_timeout) is not int or self.max_timeout not in (300, 600)
                    or type(timeout) is not int or not 1 <= timeout <= self.max_timeout):
                raise ValueError("Command timeout exceeds the configured standard/audit deadline")
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}
        if not s.allow_commands or not self.verified:
            return {"ok": False, "message": "Enable read-only commands and verify a runner with zvm_prepare_runner first"}
        token = secrets.token_hex(8).upper()
        capture = Capture(token)
        snapshots = []
        def work():
            self._ready_boundary()
            s.capture_token = token
            self._input(f"EXEC {self.name} {token} {command}")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                snap = s.snapshot()
                # Keep diagnostic pages, but never raw native hex payload.
                if not snapshots or snap["rows"] != snapshots[-1]["rows"]:
                    snapshots.append(snap)
                available = frames(s._protocol_rows, token)
                for seq in sorted(available):
                    if seq < capture.next_seq:
                        capture.accept(available[seq])
                expected = capture.next_seq
                if expected in available:
                    capture.accept(available[expected])
                    page_cleared = False
                    while snap["state"] in {"more", "holding"}:
                        s.command("Clear")
                        page_cleared = True
                        s._wait_output(1)
                        snap = s.snapshot()
                        if time.monotonic() >= deadline:
                            raise CaptureError("Paging did not return to a writable protocol input")
                    self._input(f"ZA1 {token} {expected}")
                    if capture.complete:
                        previous = snap
                        while time.monotonic() < deadline:
                            fresh = s._wait_output(1)
                            done = s.snapshot()
                            fresh = fresh or done["rows"] != previous["rows"]
                            previous = done
                            ready_rows = [i for i, row in enumerate(done["rows"]) if ready_rc(row) == 0]
                            frame_rows = [i for i, row in enumerate(done["rows"]) if f"ZM1 {token} " in row]
                            if (fresh and done["state"] == "cms_ready" and self.input_field(done)
                                    and ready_rows and (page_cleared or
                                    (frame_rows and max(ready_rows) > max(frame_rows)))):
                                self.completed_token = token
                                s.completed_capture_token = token
                                s.completed_capture_tokens.append(token)
                                s.capture_token = None
                                return {"command": command, "request_id": token, "runner": self.name,
                                        **capture.result(s.redact), "cms_command_complete": True,
                                        "screen": done, "snapshots": [snapshots[0], done],
                                        "frames_verified": capture.next_seq,
                                        "screens_observed": len(snapshots)}
                            if done["state"] in {"more", "holding"}:
                                s.command("Clear")
                                page_cleared = True
                        raise CaptureError("All records verified, but wrapper return to CMS Ready is unverified")
                elif any(seq > expected for seq in available):
                    raise CaptureError("A numbered output frame was lost")
                elif snap["state"] in {"more", "holding"}:
                    s.command("Clear")
                else:
                    s._wait_output(1)
            raise CaptureError("Capture deadline exceeded; partial output is not a complete command result")
        result = s._run("readonly_command", work, timeout + 2)
        if not result["ok"]:
            result.update({"request_id": token, "runner": self.name, "output_complete": False,
                           "cms_command_complete": False, "host_runner_may_be_waiting": True,
                           "frames_verified": capture.next_seq, "records_received": len(capture.records),
                           "snapshots": snapshots})
        return result
