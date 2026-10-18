"""Offline tests. No test in this module connects to a network endpoint."""
import json
import threading
import time
import types
import unittest
import queue
import ast
from pathlib import Path
import subprocess
import sys
from test_cms_fixtures import recorded_screen

from cms_mcp import (Session, PipeApp, Emulator, classify, field_layout,
                     sanitize_rows, create_server)


def screen(text="Ready;", bottom=""):
    rows = [" " * 80 for _ in range(24)]
    rows[0] = text.ljust(80)
    rows[-1] = bottom.ljust(80)
    return rows


def buffer(attrs=None):
    cells = ["20"] * 1920
    for offset, attr in (attrs or {0: "20", 1760: "00", 1840: "20"}).items():
        cells[offset] = f"SF(c0={attr})"
    return [" ".join(cells[n:n + 80]) for n in range(0, 1920, 80)]


class FakeEmulator:
    def __init__(self, rows=None):
        self.rows = rows or screen()
        self.buffer = buffer()
        self.calls = []
        self.fail_action = None
        self.active = 0
        self.max_active = 0
        self.is_terminated = False
        self.app = types.SimpleNamespace(deadline=0, stderr=bytearray(), close=self.close)
        self.closed = False

    def close(self):
        self.closed = True

    def exec_command(self, action):
        action = action.decode()
        self.calls.append(action)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.001)  # Test-only scheduling aid to detect missing locks.
            if action == self.fail_action:
                raise TimeoutError("synthetic deadline")
            data = {"Snap(Status)": ["U F U C(127.0.0.1) I 2 24 80 22 1 0x0 -"],
                    "Snap(Ascii)": self.rows, "Snap(ReadBuffer)": self.buffer}.get(action, [])
            return types.SimpleNamespace(data=[x.encode() for x in data])
        finally:
            self.active -= 1


class ClassificationTests(unittest.TestCase):
    def test_states_and_precedence(self):
        for text, bottom, expected in [
            ("z/VM ONLINE", "", "logo"), ("LOGON USERID", "", "login"),
            ("HHC01027I Hercules version 4.7.0", "", "logo"),
            ("Enter your password:", "", "password"), ("PASSWORD", "", "password"),
            ("Ready;", "CP READ", "cp_read"), ("Ready;", "", "cms_ready"),
            ("Ready;", "VM READ", "cms_ready"),
            ("Ready;", "MORE...", "more"), ("Ready;", "HOLDING", "holding"),
            ("XEDIT filename", "", "xedit"), ("arbitrary", "", "unknown"),
        ]:
            with self.subTest(expected=expected):
                result = classify(screen(text, bottom))
                self.assertEqual(result["state"], expected)
                self.assertIsNone(result["cms_command_complete"])

    def test_recorded_failed_login(self):
        self.assertEqual(classify(recorded_screen("failed_login")["rows"])["state"], "login")

    def test_live_captured_hercules_banner(self):
        captured = recorded_screen("hercules_banner")
        result = classify(captured["rows"])
        self.assertEqual(result["state"], "logo")
        self.assertEqual(result["screen_kind"], "hercules_banner")
        self.assertTrue(all(f["protected"] for f in captured["fields"]))
        self.assertEqual(captured["cursor"], {"row": 1, "column": 1, "protected": True})

    def test_zvm_guest_reconnect_banner_is_distinct_from_hercules_console(self):
        rows = [" " * 80 for _ in range(24)]
        rows[1] = "15:40:37 z/VM Version 6 Release 3.0, Service Level 1302".ljust(80)
        rows[5] = "15:40:37 RECONNECTED AT 15:40:37 EST SATURDAY 10/17/26".ljust(80)
        rows[23] = ("VM READ" + " " * 133).ljust(80)
        result = classify(rows)
        self.assertEqual(result["state"], "vm_read")
        self.assertEqual(result["screen_kind"], "zvm_guest_banner")

    def test_hercules_running_banner_is_observational_vm_running(self):
        rows = [" " * 80 for _ in range(24)]
        rows[0] = "Hercules Version  : 4.7.0".ljust(80)
        rows[23] = "RUNNING   ********".ljust(80)
        result = classify(rows)
        self.assertEqual(result["state"], "vm_running")
        self.assertEqual(result["screen_kind"], "hercules_banner")

    def test_stale_password_banner_with_exact_guest_vm_read_refines_to_startup(self):
        rows = screen()
        rows[0] = "Hercules Version  : 4.7.0".ljust(80)
        rows[7] = "ENTER PASSWORD (IT WILL NOT APPEAR WHEN TYPED):".ljust(80)
        rows[13] = "LOGON AT 15:11:45 EST SATURDAY 10/17/26".ljust(80)
        rows[23] = (" " * 60 + "VM READ VMACCOUNT").ljust(80)
        fake = FakeEmulator(rows)
        fake.buffer = buffer({0: "20", 1759: "00", 1899: "20", 1919: "20"})
        fake.cursor = (22, 0)
        session = Session(factory=lambda: fake)
        result = session.connect("auto")["screen"]
        self.assertEqual(result["state"], "vm_read")
        self.assertIn("vm_read", result["indicators"])
        editable = [field for field in result["fields"] if not field["protected"]]
        self.assertEqual(len(editable), 1)
        self.assertTrue(editable[0]["empty"])
        self.assertNotIn("VMACCOUNT", json.dumps(result))


class CapturedLoginTests(unittest.TestCase):
    def test_combined_login_form_is_not_password_prompt(self):
        captured = recorded_screen("login_form")
        self.assertEqual(classify(captured["rows"])["state"], "login")
        editable = [field for field in captured["fields"] if not field["protected"]]
        self.assertEqual([(f["row"], f["column"], f["length"], f["nondisplay"]) for f in editable],
                         [(20, 17, 8, False), (21, 17, 8, True), (23, 17, 123, False)])
        self.assertEqual(captured["cursor"], {"row": 20, "column": 17, "protected": False})


class RedactionTests(unittest.TestCase):
    def test_logon_diagnostic_does_not_mask_next_row_or_timestamp(self):
        rows = screen("LOGON TESTUSER")
        rows[1] = "z/VM Version 6 Release 3.0".ljust(80)
        rows[2] = "LOGON AT 14:00:00 EST".ljust(80)
        safe = sanitize_rows(rows, field_layout(buffer()), {"TESTUSER"})
        self.assertIn("z/VM Version 6 Release 3.0", safe[1])
        self.assertIn("LOGON AT 14:00:00 EST", safe[2])

    def test_cp_read_identifier_is_masked_but_state_remains_visible(self):
        rows = screen()
        rows[23] = "CP READ   VMACCOUNT".ljust(80)
        safe = sanitize_rows(rows, field_layout(buffer()), set())
        self.assertIn("CP READ", safe[23])
        self.assertIn("*********", safe[23])
        self.assertNotIn("VMACCOUNT", json.dumps(safe))

    def test_vm_read_and_running_identifiers_are_masked(self):
        rows = screen()
        rows[22] = "VM READ VMACCOUNT".ljust(80)
        rows[23] = "RUNNING VMACCOUNT".ljust(80)
        safe = sanitize_rows(rows, field_layout(buffer()), set())
        self.assertIn("VM READ", safe[22])
        self.assertIn("RUNNING", safe[23])
        self.assertNotIn("VMACCOUNT", json.dumps(safe))

    def test_attributes_and_wrapped_field(self):
        fields = field_layout(buffer({5: "20", 1900: "0c"}))
        self.assertTrue(fields[1]["nondisplay"])
        self.assertEqual(fields[1]["length"], 24)
        rows = screen("SECRET")
        safe = sanitize_rows(rows, fields, set())
        self.assertEqual(safe[0][:5], "*****")
        self.assertEqual(safe[-1][-19:], "*" * 19)

    def test_hidden_password_and_geometry(self):
        fields = field_layout(buffer({0: "20", 80: "0c", 160: "20"}))
        rows = screen("Enter password:")
        rows[1] = "HOSTSECRET".ljust(80)
        safe = sanitize_rows(rows, fields, set(), password=True)
        self.assertNotIn("HOSTSECRET", json.dumps(safe))
        self.assertEqual(len(safe), 24)
        self.assertTrue(all(len(row) == 80 for row in safe))

    def test_known_and_inline_credentials(self):
        rows = screen("LOGON USER MYSECRET")
        safe = sanitize_rows(rows, field_layout(buffer()), {"MYSECRET"})
        self.assertNotIn("MYSECRET", json.dumps(safe))

    def test_bad_buffer_fails_closed(self):
        with self.assertRaises(ValueError):
            field_layout(["SF(c0=20) 00"])
        self.assertEqual(sanitize_rows(screen("secret"), [], set(), layout_ok=False), ["*" * 80] * 24)

    def test_partially_typed_input_is_masked(self):
        rows = screen()
        rows[22] = " partialsec".ljust(80)
        safe = sanitize_rows(rows, field_layout(buffer()), {"partialsecret"})
        self.assertNotIn("partialsec", "".join(safe))


class SessionTests(unittest.TestCase):
    def make_session(self, allow=True):
        fake = FakeEmulator()
        session = Session(allow_input=allow, factory=lambda: fake)
        return session, fake

    @staticmethod
    def startup_fixture(state):
        rows = [" " * 80 for _ in range(24)]
        rows[0] = "LOGON *****".ljust(80)
        rows[1] = "z/VM Version 6 Release 3.0".ljust(80)
        rows[5] = "RECONNECTED AT 14:03:34".ljust(80)
        rows[23] = ("CP READ" if state == "cp_read" else "VM READ").ljust(80)
        return {"state": state, "rows": rows,
                "fields": [{"protected": False, "row": 23, "column": 1, "length": 139,
                            "nondisplay": False, "empty": True}],
                "connected": True, "keyboard": "U", "field_layout_error": None,
                "cursor": {"row": 23, "column": 1, "protected": False}}

    def test_startup_cp_read_sends_begin_once_then_only_observes(self):
        session = Session(allow_startup=True)
        session.em = types.SimpleNamespace(app=types.SimpleNamespace(deadline=0))
        cp_read = self.startup_fixture("cp_read")
        blank = self.startup_fixture("unknown")
        blank["rows"][6] = "BEGIN".ljust(80)
        blank["rows"][23] = "RUNNING ********".ljust(80)
        screens = iter([cp_read, cp_read, blank])
        calls = []
        session.snapshot = lambda: next(screens)
        session.command = lambda action: calls.append(action)
        session._wait_output = lambda seconds: True

        result = session.startup()

        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "startup_transition_observed")
        self.assertEqual(result["actions"], ["BEGIN", "Enter"])
        self.assertEqual(calls.count('String("BEGIN")'), 1)
        self.assertEqual(calls.count("Enter"), 1)

    def test_startup_vm_read_sends_one_enter_and_stops_at_cp_read(self):
        session = Session(allow_startup=True)
        session.em = types.SimpleNamespace(app=types.SimpleNamespace(deadline=0))
        vm_read = self.startup_fixture("vm_read")
        cp_read = self.startup_fixture("cp_read")
        screens = iter([vm_read, vm_read, cp_read])
        calls = []
        session.snapshot = lambda: next(screens)
        session.command = lambda action: calls.append(action)
        session._wait_output = lambda seconds: True

        result = session.startup()

        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "startup_transition_observed")
        self.assertEqual(result["actions"], ["Enter"])
        self.assertNotIn('String("BEGIN")', calls)
        self.assertEqual(calls.count("Enter"), 1)

    def test_startup_offline_and_explicit_device(self):
        session, fake = self.make_session()
        create_server(session)
        self.assertFalse(fake.calls)
        self.assertEqual(session.status()["state"], "disconnected")
        self.assertFalse(session.connect("3272")["ok"])
        self.assertFalse(fake.calls)

    def test_connect_only_and_persistence(self):
        session, fake = self.make_session()
        result = session.connect("0200@")
        self.assertTrue(result["ok"])
        self.assertEqual(fake.calls[0], "Connect(0200@127.0.0.1:3271)")
        self.assertTrue(all(not x.startswith(("String", "Enter", "Clear")) for x in fake.calls))
        self.assertFalse(session.connect("0200@")["ok"])
        self.assertFalse(fake.closed)
        self.assertTrue(session.screen()["ok"])
        self.assertEqual(result["screen"]["cursor"]["row"], 23)
        session.disconnect()
        self.assertTrue(fake.closed)
        self.assertTrue(fake.is_terminated)
        self.assertNotIn("LOGOFF", fake.calls)

    def test_screen_can_wait_for_host_output_without_sending_input(self):
        session, fake = self.make_session()
        session.connect("0200@")
        result = session.screen(wait_output=True, timeout=3)
        self.assertTrue(result["ok"])
        self.assertTrue(result["wait_output_observed"])
        tail = fake.calls[-(1 + 1 + 4):]
        self.assertIn("Ascii", fake.calls)
        self.assertIn("Wait(3,Output)", fake.calls)
        self.assertLess(fake.calls.index("Ascii", len(fake.calls) - 8),
                        fake.calls.index("Wait(3,Output)", len(fake.calls) - 8))
        self.assertTrue(all(not x.startswith(("String", "Enter", "Clear")) for x in tail))

    def test_rejected_device_is_a_connection_failure_without_input(self):
        session, fake = self.make_session()
        fake.rows = screen("HHC01030I Connection rejected, device 0200 unavailable")
        result = session.connect("0200@")
        self.assertFalse(result["ok"])
        self.assertIn("terminal selector 0200@", result["message"])
        self.assertIn("Connection rejected", result["last_screen"]["rows"][0])
        self.assertTrue(result["session_preserved"])
        self.assertFalse(result["session_terminated"])
        self.assertFalse(fake.closed)
        self.assertIsNotNone(session.em)
        self.assertFalse(any(action.startswith(("String", "Enter", "Clear"))
                             for action in fake.calls))

    def test_terminal_pool_group_and_default_selection(self):
        for default, requested, expected in [
            ("0200@", None, "0200@127.0.0.1:3271"),
            ("auto", None, "127.0.0.1:3271"),
            ("0200@", "auto", "127.0.0.1:3271"),
            ("auto", "020a@", "020A@127.0.0.1:3271"),
            ("0200@", "codex@", "CODEX@127.0.0.1:3271"),
        ]:
            with self.subTest(default=default, requested=requested):
                fake = FakeEmulator()
                session = Session(factory=lambda: fake, default_device=default)
                result = session.connect(requested)
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["endpoint"], expected)
                self.assertEqual(fake.calls[0], f"Connect({expected})")
                self.assertFalse(any(x.startswith(("String", "Enter", "Clear")) for x in fake.calls))
                session.disconnect()

    def test_terminal_selector_cannot_change_host_or_inject_actions(self):
        for value in ["", "3272", "AUTO", "auto@elsewhere", "0200@127.0.0.1",
                      "0200@)\nEnter", "A,B@", "A\\B@", "12345@", "LONGGROUP@", 123, True]:
            with self.subTest(value=value):
                session, fake = self.make_session()
                self.assertFalse(session.connect(value)["ok"])
                self.assertFalse(fake.calls)
        for value in [True, "10", 0, 31]:
            session, fake = self.make_session()
            self.assertFalse(session.connect("auto", value)["ok"])
            self.assertFalse(fake.calls)

    def test_observation_only(self):
        session, fake = self.make_session(False)
        self.assertFalse(session.send("Enter")["ok"])
        self.assertFalse(fake.calls)

    def test_action_injection_and_parameter_validation(self):
        session, fake = self.make_session()
        for kwargs in [dict(action="Transfer"), dict(action="String", text="a\nEnter"),
                       dict(action="String", text=r"a\n"), dict(action="PF", number=25),
                       dict(action="PA", number=0), dict(action="MoveCursor", row=0, column=1),
                       dict(action="Enter", text="unexpected"), dict(action="Enter", wait="unlock")]:
            with self.subTest(kwargs=kwargs):
                self.assertFalse(session.send(**kwargs)["ok"])
        self.assertFalse(fake.calls)

    def test_string_is_separate_from_enter_and_secret_redacted(self):
        session, fake = self.make_session()
        session.connect("0200@")
        result = session.send("String", text='secret"value', sensitive=True)
        self.assertTrue(result["ok"])
        self.assertIn('String("secret\\"value")', fake.calls)
        self.assertNotIn("Enter", fake.calls)
        self.assertIsNone(result["cms_command_complete"])
        fake.rows = screen('secret"value')
        self.assertNotIn('secret\\"value', json.dumps(session.screen()))

    def test_deadline_preserves_connected_screen_and_session(self):
        session, fake = self.make_session()
        session.connect("0200@")
        fake.fail_action = "Enter"
        result = session.send("Enter")
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["last_screen"]["rows"]), 24)
        self.assertEqual(result["error_type"], "TimeoutError")
        self.assertTrue(any(item.get("error_type") == "TimeoutError" for item in result["trace"]))
        self.assertTrue(result["session_preserved"])
        self.assertFalse(result["session_terminated"])
        self.assertFalse(fake.closed)
        self.assertIsNotNone(session.em)

    def test_buffer_deadline_is_not_hidden(self):
        session, fake = self.make_session()
        session.connect("0200@")
        fake.fail_action = "Snap(ReadBuffer)"
        self.assertFalse(session.screen()["ok"])
        self.assertTrue(fake.closed)

    def test_serialization(self):
        session, fake = self.make_session()
        session.connect("0200@")
        threads = [threading.Thread(target=session.screen) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(fake.max_active, 1)
        # Snapshot actions must remain contiguous across callers.
        reads = fake.calls[2:]
        self.assertEqual(reads, ["Snap(Save)", "Snap(Status)", "Snap(Ascii)", "Snap(ReadBuffer)"] * 6)

    def test_actual_s3270_offline_transport_and_snapshot(self):
        # Starts a local process with no hostname; makes NO network connection.
        session = Session(factory=lambda: Emulator(app=PipeApp()))
        session.em = session.factory()
        try:
            self.assertEqual(session.em.app.sp.args[1:],
                             ["-model", "2", "-clear", "aidWait", "-clear", "trace"])
            # Check effective safety settings, not just accepted CLI syntax.
            self.assertEqual(session.em.exec_command(b"Set(aidWait)").data, [b"false"])
            self.assertEqual(session.em.exec_command(b"Set(trace)").data, [b"false"])
            result = session.screen()
            self.assertTrue(result["ok"], result)
            self.assertFalse(result["screen"]["connected"])
            self.assertIsNone(result["screen"]["field_layout_error"])
        finally:
            session.disconnect()

    def test_pipe_read_deadline(self):
        app = PipeApp.__new__(PipeApp)
        app.output = queue.Queue()
        app.deadline = time.monotonic() - 1
        with self.assertRaises(TimeoutError):
            app.readline()

    def test_output_wait_armed_before_action_and_not_completion(self):
        session, fake = self.make_session()
        session.connect("0200@")
        result = session.send("Enter", wait="output", timeout=2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["synchronization"], "host_output_observed")
        self.assertIsNone(result["cms_command_complete"])
        sent = fake.calls.index("Enter")
        self.assertEqual(fake.calls[sent - 1], "Ascii")
        self.assertEqual(fake.calls[sent + 1], "Wait(2,Output)")
        self.assertFalse(any(call.startswith("Snap(Wait") for call in fake.calls))


class ValidatorTests(unittest.TestCase):
    def test_validators_have_no_optimization_dependent_checks(self):
        for path in Path(__file__).parent.glob('validate_cms_*.py'):
            with self.subTest(validator=path.name):
                self.assertFalse(any(isinstance(node, ast.Assert)
                                     for node in ast.walk(ast.parse(path.read_text()))))

    def test_protocol_validator_checks_all_gates_under_optimized_python(self):
        program = '''
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import validate_cms_mcp as validator

@asynccontextmanager
async def stdio(params):
    yield None, None

async def exercise(bad_tool=None):
    calls = []
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.initialize.return_value = SimpleNamespace(protocolVersion='test')
    client.list_tools.return_value = SimpleNamespace(
        tools=[SimpleNamespace(name=name) for name in validator.EXPECTED])
    async def call(name, args):
        calls.append(name)
        data = {'ok': name == bad_tool, 'replacement_safe': False}
        if name == 'cms_status':
            data.update(state='disconnected', input_enabled=False)
        return SimpleNamespace(isError=False, structuredContent=data)
    client.call_tool.side_effect = call
    with patch.object(validator, 'stdio_client', stdio), patch.object(validator, 'ClientSession', return_value=client):
        try:
            result = await validator.validate()
        except RuntimeError:
            if bad_tool is None:
                raise
        else:
            if bad_tool is not None:
                raise RuntimeError('Validator accepted an enabled gate: ' + bad_tool)
            if set(calls) != validator.EXPECTED - {'cms_connect'}:
                raise RuntimeError('Validator skipped tool calls')
            if not result['offline_local_edits_rejected']:
                raise RuntimeError('Missing rejection evidence')

async def main():
    await exercise()
    for name in validator.EXPECTED - {'cms_connect', 'cms_status', 'cms_disconnect'}:
        await exercise(name)
asyncio.run(main())
'''
        for options in ([], ['-O']):
            with self.subTest(options=options):
                result = subprocess.run([sys.executable, '-B', *options, '-c', program],
                    cwd=Path(__file__).parent, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
