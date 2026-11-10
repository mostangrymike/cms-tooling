"""Guarded runner provisioning and read-only, complete CMS command capture."""
from pathlib import Path
import re
import secrets
import tempfile
import time

from cms_capture import Capture, CaptureError, frames, readonly_command

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
        self.max_timeout = 900
        self.resolved_failed_capture_tokens = set()
        self.failed_capture_observation_only = False
        self.recovery_observation_count = 0

    @staticmethod
    def input_field_shape(screen):
        fields = [f for f in screen["fields"] if not f["protected"]]
        return (screen["connected"] and screen["field_layout_error"] is None
                and len(fields) == 1
                and (fields[0]["row"], fields[0]["column"], fields[0]["length"]) == (23, 1, 139)
                and fields[0].get("empty") and not fields[0]["nondisplay"])

    @classmethod
    def input_field(cls, screen):
        return cls.input_field_shape(screen) and screen["keyboard"] == "U"

    def _await_input_field(self, screen, allow_vm_read=False, expected_ack=None, timeout=5):
        """Wait briefly for a locked REXX PULL field to unlock without losing its ACK boundary."""
        from cms_mcp import host_display

        allowed_states = {"cms_ready", "vm_running"}
        if allow_vm_read:
            allowed_states.add("vm_read")
            if (not isinstance(expected_ack, tuple) or len(expected_ack) != 2
                    or not isinstance(expected_ack[1], int) or expected_ack[1] < 0
                    or self.session.capture_token != expected_ack[0]):
                raise CaptureError("Runner ACK is not bound to a verified active frame")
        if (screen.get("state") not in allowed_states
                or not self.input_field_shape(screen)):
            raise CaptureError("Command/ack input field is not verified empty and writable")
        initial_state = screen["state"]
        initial_display = host_display(screen)
        deadline = time.monotonic() + timeout
        current = screen
        while not self.input_field(current):
            display_changed = host_display(current) != initial_display
            if (current.get("state") != initial_state
                    or not self.input_field_shape(current)
                    or display_changed and not allow_vm_read):
                raise CaptureError("Command/ack screen changed while waiting for keyboard unlock")
            if time.monotonic() >= deadline:
                raise CaptureError("Command/ack input field remained locked")
            self.session._wait_output(1)
            current = self.session.snapshot()
        return current

    def _input(self, text, allow_vm_read=False):
        s = self.session
        expected_ack = None
        if allow_vm_read:
            match = re.fullmatch(r"ZA1 ([0-9A-F]{16}) ([0-9]+)", text)
            if not match:
                raise CaptureError("Only a numbered runner ACK may use the VM READ input field")
            expected_ack = (match[1], int(match[2]))
        before = self._await_input_field(s.snapshot(), allow_vm_read=allow_vm_read,
                                         expected_ack=expected_ack)
        s.command("MoveCursor(22,0)")
        check = self._await_input_field(s.snapshot(), allow_vm_read=allow_vm_read,
                                        expected_ack=expected_ack)
        from cms_mcp import host_display
        if (check["cursor"] != {"row": 23, "column": 1, "protected": False}
                or check["state"] != before["state"]
                or host_display(check) != host_display(before)):
            raise CaptureError("Input cursor or field changed; no text submitted")
        if (not isinstance(text, str) or not text or len(text) > 139
                or any(ord(char) < 32 or ord(char) > 126 for char in text)):
            raise CaptureError("Input must be one printable ASCII line that fits the CMS field")
        if re.fullmatch(r"[A-Z0-9 @$*%]+", text):
            s.command('String("' + text + '")')
        else:
            # HexString avoids x3270 String's C-style backslash escapes and
            # quoted-action parsing for arbitrary CMS command punctuation.
            try:
                encoded = text.encode("cp037").hex().upper()
            except UnicodeEncodeError:
                raise CaptureError("CMS command contains a character not representable in the configured EBCDIC code page") from None
            s.command("HexString(" + encoded + ")")
        s.command("Ascii")
        s.command("Enter")

    def _ready_boundary(self):
        s = self.session
        screen = s.snapshot()
        ready_prompt = (screen.get("state") == "cms_ready"
                        and any(ready_rc(row) is not None for row in screen.get("rows", [])))
        if not self.input_field(screen) or not ready_prompt:
            raise CaptureError(
                "Establish a fresh CMS Ready prompt before command or transfer execution")
        # Never mistake an interrupted runner's old Ready prompt for a shell.
        completed = {*s.completed_capture_tokens, self.completed_token, s.completed_capture_token,
                     *self.resolved_failed_capture_tokens}
        for row in screen["rows"]:
            match = re.search(r"ZM1 ([0-9A-F]{16}) [BRDZF] ", row)
            if match and match[1] not in completed:
                raise CaptureError("Unresolved runner output is present; refusing a new command")
        return screen

    def resolve_failed_capture(self, token, resume_arbitrary_commands=False):
        """Resolve only a visible, terminal F-ACK failure; never complete its capture.

        The operation is observation-only. It records that the failed helper is
        no longer waiting at the CMS prompt so that bounded reconciliation can
        proceed. Output and the original command result remain incomplete. By
        default, follow-up commands remain restricted to the read-only allowlist.
        """
        s = self.session
        if not s.caps.commands:
            return {"ok": False, "message": "Command recovery requires --allow-commands"}
        if not isinstance(token, str) or not re.fullmatch(r"[0-9A-F]{16}", token):
            return {"ok": False, "message": "Supply the exact uppercase 16-hex failed request token"}
        if type(resume_arbitrary_commands) is not bool:
            return {"ok": False, "message": "resume_arbitrary_commands must be boolean"}
        if resume_arbitrary_commands and not s.caps.arbitrary_commands:
            return {"ok": False, "message": "Arbitrary CMS commands are not enabled for this server"}
        if resume_arbitrary_commands and (token not in self.resolved_failed_capture_tokens
                                          or self.recovery_observation_count < 1):
            return {"ok": False, "message": "Resolve the failed capture and complete a read-only observation before resuming arbitrary commands"}

        def candidate(screen):
            if (screen.get("state") != "cms_ready" or not self.input_field(screen)
                    or screen.get("capture_active")):
                return False
            rows = screen.get("rows", [])
            protocol = []
            for index, row in enumerate(rows):
                match = re.search(r"ZM1 ([0-9A-F]{16}) ([BRDZF]) ([0-9]+)(?: (.*))?$", row.strip())
                if match:
                    protocol.append((index, match[1], match[2], match[3], match[4] or ""))
                elif re.search(r"\bZA1 [0-9A-F]{16} \d+\b", row):
                    return False
            if (len(protocol) != 1 or protocol[0][1:] != (token, "F", "0", "ACK")):
                return False
            ready = [(index, ready_rc(row)) for index, row in enumerate(rows)
                     if ready_rc(row) is not None]
            return len(ready) == 1 and ready[0][1] == 12 and protocol[0][0] < ready[0][0]

        def observed_ready(screen):
            if (screen.get("state") != "cms_ready" or not self.input_field(screen)
                    or screen.get("capture_active")):
                return False
            capture_token = s.completed_capture_token
            if capture_token is None or capture_token not in s.completed_capture_tokens:
                return False
            rows = screen.get("rows", [])
            known = {*s.completed_capture_tokens, self.completed_token,
                     s.completed_capture_token, *self.resolved_failed_capture_tokens}
            markers = []
            for index, row in enumerate(rows):
                match = re.search(r"ZM1 ([0-9A-F]{16}) ([BRDZF]) ([0-9]+)(?: (.*))?$", row.strip())
                if match:
                    if match[1] not in known:
                        return False
                    if match[1] == capture_token and match[2] == "Z" and match[4] == "DONE":
                        markers.append(index)
                else:
                    ack = re.fullmatch(r"\s*ZA1 ([0-9A-F]{16}) ([0-9]+)\s*", row)
                    if ack and (ack[1] != capture_token
                                or self.completed_token != capture_token):
                        return False
            ready = [(index, ready_rc(row)) for index, row in enumerate(rows)
                     if ready_rc(row) is not None]
            visible_completion = (len(markers) == 1
                                 and any(index > markers[0] for index, _ in ready))
            # PA2 can clear the terminal row containing Z DONE after the bridge
            # has already accepted it. Preserve that in-memory token/Ready
            # correlation so a stable Ready screen can still resolve recovery.
            remembered_completion = (self.completed_token == capture_token
                                     and s.capture_token is None and bool(ready))
            return visible_completion or remembered_completion

        def work():
            first = s.snapshot()
            failed_boundary = candidate(first)
            observed_boundary = resume_arbitrary_commands and observed_ready(first)
            if not failed_boundary and not observed_boundary:
                return {"ok": False, "outcome": "failed_capture_boundary_not_verified",
                        "screen": first, "output_complete": False,
                        "cms_command_complete": False}
            second = s.snapshot()
            stable_boundary = (candidate(second) if failed_boundary else observed_ready(second))
            if (not stable_boundary or first["rows"] != second["rows"]
                    or first.get("terminal_status") != second.get("terminal_status")):
                return {"ok": False, "outcome": "failed_capture_screen_not_stable",
                        "screen": second, "output_complete": False,
                        "cms_command_complete": False}
            self.resolved_failed_capture_tokens.add(token)
            self.failed_capture_observation_only = not resume_arbitrary_commands
            if not resume_arbitrary_commands:
                self.recovery_observation_count = 0
            return {"outcome": ("failed_capture_resolved_commands_resumed"
                                if resume_arbitrary_commands else
                                "failed_capture_resolved_for_observation_only"),
                    "request_id": token, "cms_rc": 12,
                    "output_complete": False, "integrity_verified": False,
                    "cms_command_complete": False,
                    "arbitrary_commands_enabled": not self.failed_capture_observation_only,
                    "screen": second}

        return s._run("resolve_failed_capture", work, timeout=10)

    def restart_runner(self, token):
        """Clear a stable failed-ack fence and require source verification again.

        This is an in-session protocol recovery, not a VM or MCP process restart.
        It sends no terminal input and never treats the failed output as complete.
        """
        s = self.session
        if not s.caps.commands:
            return {"ok": False, "message": "Command recovery requires --allow-commands"}
        if not isinstance(token, str) or not re.fullmatch(r"[0-9A-F]{16}", token):
            return {"ok": False, "message": "Supply the exact uppercase 16-hex failed request token"}

        def failed_ack_boundary(screen):
            if (screen.get("state") != "cms_ready" or not self.input_field(screen)
                    or (screen.get("capture_active") and s.capture_token != token)):
                return None
            protocol = []
            ready = []
            for index, row in enumerate(screen.get("rows", [])):
                match = re.fullmatch(
                    r"\s*ZM1 ([0-9A-F]{16}) F ([0-9]{1,6}) ACK\s*", row)
                if match:
                    protocol.append((index, match[1], int(match[2])))
                elif "ZM1 " in row or re.search(r"\bZA1 [0-9A-F]{16} [0-9]+\b", row):
                    return None
                rc = ready_rc(row)
                if rc is not None:
                    ready.append((index, rc))
            if (len(protocol) != 1 or protocol[0][1] != token or len(ready) != 1
                    or ready[0][1] != 12 or protocol[0][0] >= ready[0][0]):
                return None
            return protocol[0][2]

        def work():
            first = s.snapshot()
            sequence = failed_ack_boundary(first)
            if sequence is None:
                return {"ok": False, "outcome": "runner_restart_boundary_not_verified",
                        "screen": first, "output_complete": False,
                        "cms_command_complete": False}
            second = s.snapshot()
            if (failed_ack_boundary(second) != sequence or first["rows"] != second["rows"]
                    or first.get("terminal_status") != second.get("terminal_status")):
                return {"ok": False, "outcome": "runner_restart_screen_not_stable",
                        "screen": second, "output_complete": False,
                        "cms_command_complete": False}

            self.resolved_failed_capture_tokens.add(token)
            self.failed_capture_observation_only = True
            self.recovery_observation_count = 0
            self.verified = False
            self.completed_token = None
            s.capture_token = None
            s._protocol_rows = []
            s.completed_capture_token = None
            return {"outcome": "runner_recovery_reset",
                    "request_id": token, "failed_sequence": sequence, "cms_rc": 12,
                    "output_complete": False, "integrity_verified": False,
                    "cms_command_complete": False, "cms_input_sent": False,
                    "runner_verified": False, "source_verification_required": True,
                    "arbitrary_commands_enabled": False,
                    "next_step": "Call cms_prepare_runner to verify the helper source."}

        return s._run("restart_runner", work, timeout=10)

    def _simple(self, command, deadline):
        """Internal fixed read-only observations; require echoed command and Ready RC.

        Used by helper STATE preconditions and the fixed compiler diagnostic.
        This is not a public or general command dispatch interface.
        """
        from cms_mcp import host_display
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
                self.session.command("PA(2)")
            else:
                self.session._wait_output(1)
        raise CaptureError("Bootstrap STATE did not return correlated Ready/RC evidence")

    def _transfer(self, action, allow_unready=False):
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
        # Startup or transfer output may fill the 3270 display and leave a
        # MORE.../HOLDING notice. IBM defines Clear or PA2 as the request for
        # the next page; Enter would only hold the current page. PA2 preserves
        # the input area while clearing output. Advance only a newly observed,
        # formatted MORE/HOLDING page, and wait through any transient buffer.
        from cms_mcp import host_display
        deadline = time.monotonic() + 90
        fresh = False
        advanced_pages = set()
        while time.monotonic() < deadline:
            after = s.snapshot()
            fresh = fresh or host_display(after) != host_display(before)
            if (after.get("formatted") and after.get("field_layout_error") is None
                    and after.get("state") in {"more", "holding"}):
                page = host_display(after)
                if page not in advanced_pages:
                    if len(advanced_pages) >= 64:
                        raise CaptureError("Transfer synchronization exceeded the 64-page limit")
                    advanced_pages.add(page)
                    s.command("PA(2)")
                    s._wait_output(1)
                    continue
            prompts = [ready_rc(row) for row in after["rows"] if ready_rc(row) is not None]
            if fresh and after["state"] == "cms_ready" and self.input_field(after) and prompts and prompts[-1] == 0:
                candidate_display = host_display(after)
                s._wait_output(1)
                stable = s.snapshot()
                stable_prompts = [ready_rc(row) for row in stable["rows"] if ready_rc(row) is not None]
                if (stable.get("formatted") and stable.get("field_layout_error") is None
                        and stable["state"] == "cms_ready" and self.input_field(stable)
                        and stable_prompts and stable_prompts[-1] == 0
                        and host_display(stable) == candidate_display):
                    return {"ready_verified": True, "screen": stable}
            fresh = s._wait_output(1) or fresh
        if allow_unready:
            return {"ready_verified": False, "screen": s.snapshot()}
        suffix = " after paging output" if advanced_pages else ""
        raise CaptureError(f"Transfer finished, but fresh CMS Ready and command field are unverified{suffix}")

    def prepare(self, create=False, timeout=240):
        s = self.session
        if type(timeout) is not int or not 1 <= timeout <= 240:
            return {"ok": False, "message": "Runner preparation timeout must be 1..240 seconds"}
        if not s.caps.commands:
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
            self.name = name  # Retain the candidate identity even if transfer/verification fails.
            with tempfile.TemporaryDirectory(prefix="cms_mcp_") as directory:
                local = Path(directory) / "runner.exec"
                downloaded = Path(directory) / "received.exec"
                local.write_text(source, encoding="ascii")
                if created:
                    # Use the host-side DFT no-replace guard for this random
                    # candidate. A CMS STATE check is useful evidence but may
                    # itself be trapped behind MORE output; Exist=keep makes
                    # DFT fail rather than replace if the name already exists.
                    sent = self._transfer(
                        f'Transfer(Direction=send,"HostFile={name} EXEC A",LocalFile={local},Host=vm,Mode=ascii,Exist=keep,Recfm=fixed,Lrecl=80,BufferSize=2048)',
                        allow_unready=True)
                    if not sent["ready_verified"]:
                        return {"ok": False, "runner": name, "fileid": f"{name} EXEC A",
                                "created": False, "host_file_may_exist": True,
                                "source_verified": False, "ready_verified": False,
                                "message": "Create-only transfer returned, but CMS Ready is unverified; helper was not executed",
                                "screen": sent["screen"]}
                # For an already configured helper, a read-only native receive
                # is itself the existence check and source verification. Avoid
                # a CMS STATE command before this transfer: a reconnect banner
                # can leave line-mode paging that prevents correlated STATE/RC
                # capture even though the exact Ready input field is writable.
                transfer_state = self._transfer(
                    f'Transfer(Direction=receive,"HostFile={name} EXEC A",LocalFile={downloaded},Host=vm,Mode=ascii,Cr=add,Exist=keep,BufferSize=2048)',
                    allow_unready=True)
                if not downloaded.is_file():
                    raise CaptureError("Runner round-trip download is missing")
                expected = [line.rstrip() for line in source.splitlines()]
                actual = [line.rstrip() for line in downloaded.read_text(encoding="ascii").splitlines()]
                if actual != expected:
                    raise CaptureError("Runner round-trip source verification failed; helper retained, not executed")
            self.verified = True
            if not transfer_state["ready_verified"]:
                return {"ok": False, "runner": name, "fileid": f"{name} EXEC A",
                        "source_verified": True, "ready_verified": False,
                        "message": "Runner source matches, but CMS Ready and command field are unverified",
                        "screen": transfer_state["screen"]}
            return {"runner": name, "fileid": f"{name} EXEC A", "created": created,
                    "source_verified": True, "ready_verified": True, "existing_files_replaced": False,
                    "host_output_files_created": False, "retained_on_host": True}
        result = s._run("prepare_runner", work, timeout=timeout)
        if not result["ok"] and self.bootstrap_evidence is not None:
            result["bootstrap"] = self.bootstrap_evidence
        if not result["ok"] and self.name is not None and not result.get("source_verified"):
            result.update({"runner": self.name, "retained_on_host_if_created": True, "source_verified": False})
        return result

    def run(self, command, timeout=120):
        s = self.session
        try:
            command = self.policy(command)
            if self.failed_capture_observation_only:
                readonly_command(command)
            if (type(self.max_timeout) is not int or self.max_timeout not in (300, 600, 900)
                    or type(timeout) is not int or not 1 <= timeout <= self.max_timeout):
                raise ValueError("Command timeout exceeds the configured standard/audit deadline")
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}
        if not s.caps.commands or not self.verified:
            return {"ok": False, "message": "Enable read-only commands and verify a runner with cms_prepare_runner first"}
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
                        s.command("PA(2)")
                        page_cleared = True
                        s._wait_output(1)
                        snap = s.snapshot()
                        if time.monotonic() >= deadline:
                            raise CaptureError("Paging did not return to a writable protocol input")
                    self._input(f"ZA1 {token} {expected}", allow_vm_read=True)
                    if capture.complete:
                        previous = snap
                        while time.monotonic() < deadline:
                            fresh = s._wait_output(1)
                            done = s.snapshot()
                            fresh = fresh or done["rows"] != previous["rows"]
                            previous = done
                            ready_rows = [i for i, row in enumerate(done["rows"]) if ready_rc(row) == 0]
                            frame_rows = [i for i, row in enumerate(done["rows"]) if f"ZM1 {token} " in row]
                            ack_text = f"ZA1 {token} {expected}"
                            ack_rows = [i for i, row in enumerate(done["rows"])
                                        if row.strip() == ack_text]
                            ack_return = (len(ack_rows) == 1
                                          and any(index > ack_rows[0] for index in ready_rows))
                            if (fresh and done["state"] == "cms_ready" and self.input_field(done)
                                    and ready_rows and (page_cleared or ack_return or
                                    (frame_rows and max(ready_rows) > max(frame_rows)))):
                                self.completed_token = token
                                s.completed_capture_token = token
                                s.completed_capture_tokens.append(token)
                                if self.failed_capture_observation_only:
                                    self.recovery_observation_count += 1
                                s.capture_token = None
                                return {"command": "<submitted; input omitted from diagnostics>",
                                        "request_id": token, "runner": self.name,
                                        **capture.result(s.redact), "cms_command_complete": True,
                                        "screen": done, "snapshots": [snapshots[0], done],
                                        "frames_verified": capture.next_seq,
                                        "screens_observed": len(snapshots)}
                            if done["state"] in {"more", "holding"}:
                                s.command("PA(2)")
                                page_cleared = True
                        raise CaptureError("All records verified, but wrapper return to CMS Ready is unverified")
                elif any(seq > expected for seq in available):
                    raise CaptureError("A numbered output frame was lost")
                elif snap["state"] in {"more", "holding"}:
                    s.command("PA(2)")
                else:
                    s._wait_output(1)
            raise CaptureError("Capture deadline exceeded; partial output is not a complete command result")
        command_was_known_secret = command in s.secrets
        if not command_was_known_secret:
            # Mask command echoes in every screen and captured record produced
            # while this dispatch is active; input is never copied to output.
            s.secrets.add(command)
        try:
            result = s._run("cms_command", work, timeout + 2)
        finally:
            if not command_was_known_secret:
                s.secrets.discard(command)
        if not result["ok"]:
            result.update({"request_id": token, "runner": self.name, "output_complete": False,
                           "cms_command_complete": False, "host_runner_may_be_waiting": True,
                           "frames_verified": capture.next_seq, "records_received": len(capture.records),
                           "snapshots": snapshots})
        return result
