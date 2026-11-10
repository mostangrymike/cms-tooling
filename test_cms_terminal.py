"""Contract tests for the shared terminal transport.

The session must depend on ``cms_terminal.Terminal`` only.  These tests drive a
session through a scripted terminal that deliberately has no ``.app`` escape
hatch, and they check both packaged backends against the same structural
contract without opening a network connection.
"""
import types
import unittest

from cms_mcp import Session
from cms_terminal import (S3270Terminal, Terminal, conformance_errors, terminal)
from tnz_transport import TnzEmulator

ROWS, COLS = 24, 80


def buffer(attrs=None):
    cells = ["20"] * (ROWS * COLS)
    for offset, attr in (attrs or {0: "20", 1760: "00", 1840: "20"}).items():
        cells[offset] = f"SF(c0={attr})"
    return [" ".join(cells[n:n + COLS]) for n in range(0, ROWS * COLS, COLS)]


class StubApp:
    """Minimal PipeApp shape; never starts a process."""

    def __init__(self):
        self.deadline = 0
        self.stderr = bytearray(b"diagnostic\n")
        self.sp = types.SimpleNamespace(poll=lambda: None)
        self.closed = 0

    def close(self):
        self.closed += 1
        return 0


class ScriptedTerminal:
    """Implements exactly the Terminal contract and nothing else."""

    def __init__(self):
        self.deadline = 0
        self.stderr = bytearray()
        self.is_terminated = False
        self.closed = False
        self.rows = [" " * COLS for _ in range(ROWS)]
        self.rows[0] = "Ready;".ljust(COLS)
        self.calls = []

    def exec_command(self, action):
        command = action.decode("ascii")
        self.calls.append(command)
        data = {"Snap(Status)": ["U F U C(127.0.0.1) I 2 24 80 22 1 0x0 -"],
                "Snap(Ascii)": self.rows,
                "Snap(ReadBuffer)": buffer()}.get(command, [])
        return types.SimpleNamespace(data=[line.encode() for line in data])

    def alive(self):
        return not self.closed

    def close(self):
        self.closed = True


class ProtocolTests(unittest.TestCase):
    def test_scripted_terminal_satisfies_the_runtime_protocol(self):
        self.assertIsInstance(ScriptedTerminal(), Terminal)

    def test_conformance_names_every_missing_member(self):
        errors = conformance_errors(types.SimpleNamespace(deadline=0))
        for expected in ("missing attribute: stderr", "missing attribute: is_terminated",
                         "missing method: exec_command", "missing method: alive",
                         "missing method: close"):
            self.assertIn(expected, errors)

    def test_conforming_terminal_has_no_errors(self):
        self.assertEqual(conformance_errors(ScriptedTerminal()), [])

    def test_unknown_transport_is_rejected(self):
        with self.assertRaises(ValueError):
            terminal("telnet")


class SessionContractTests(unittest.TestCase):
    def test_session_runs_through_a_terminal_without_an_app_attribute(self):
        scripted = ScriptedTerminal()
        session = Session(factory=lambda: scripted)
        result = session.connect("0200@")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["screen"]["state"], "cms_ready")
        self.assertIsNone(result["screen"]["cms_command_complete"])
        self.assertIn("Connect(0200@127.0.0.1:3271)", scripted.calls)
        self.assertIn("Snap(Ascii)", scripted.calls)
        session.disconnect()
        self.assertTrue(scripted.closed)
        self.assertTrue(scripted.is_terminated)


class S3270TerminalTests(unittest.TestCase):
    def test_conforms_and_forwards_the_protocol_members(self):
        app = StubApp()
        s3270 = S3270Terminal(app=app)
        try:
            self.assertEqual(conformance_errors(s3270), [])
            self.assertIsInstance(s3270, Terminal)
            s3270.deadline = 42.0
            self.assertEqual(app.deadline, 42.0)
            self.assertIs(s3270.stderr, app.stderr)
            self.assertTrue(s3270.alive())
            app.sp.poll = lambda: 1
            self.assertFalse(s3270.alive())
            self.assertEqual(s3270.close(), 0)
            self.assertTrue(s3270.is_terminated)
            self.assertTrue(s3270.emulator.is_terminated)
        finally:
            s3270.emulator.is_terminated = True

    def test_close_is_idempotent_through_the_app(self):
        app = StubApp()
        s3270 = S3270Terminal(app=app)
        s3270.close()
        s3270.close()
        self.assertEqual(app.closed, 2)


class TnzTerminalTests(unittest.TestCase):
    def test_conforms_and_tracks_connection_state(self):
        tnz = terminal("tnz")
        try:
            self.assertEqual(conformance_errors(tnz), [])
            self.assertIsInstance(tnz, Terminal)
            self.assertFalse(tnz.alive())
            tnz.transport.session = types.SimpleNamespace(seslost=False,
                                                         close=lambda: None)
            self.assertTrue(tnz.alive())
            tnz.transport.session.seslost = True
            self.assertFalse(tnz.alive())
            tnz.transport.session = None
        finally:
            tnz.close()
        self.assertTrue(tnz.is_terminated)


if __name__ == "__main__":
    unittest.main()
