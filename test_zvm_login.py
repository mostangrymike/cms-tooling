"""Offline credential and login tests; no network or real credentials."""
import json
import os
from pathlib import Path
import tempfile
import types
import unittest

from test_zvm_mcp import FakeEmulator, buffer, screen
from zvm_credentials import CredentialError, FileCredentialProvider, import_legacy, store_new, validate
from zvm_mcp import Session
from test_zvm_fixtures import recorded_screen


class CredentialTests(unittest.TestCase):
    def test_roundtrip_and_exclusive_create(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "credentials.json"
            creds = validate("testuser", "S3cret")
            store_new(path, creds)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(FileCredentialProvider(path).load().userid, "TESTUSER")
            self.assertNotIn("S3cret", repr(creds))
            with self.assertRaises(CredentialError):
                store_new(path, creds)

    def test_unsafe_file_symlink_and_malformed_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            path.write_text('{"userid":"TESTUSER","password":"S3cret"}')
            path.chmod(0o644)
            with self.assertRaises(CredentialError):
                FileCredentialProvider(path).load()
            path.chmod(0o600)
            link = Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(CredentialError):
                FileCredentialProvider(link).load()
            path.write_text('malformed S3cret')
            try:
                FileCredentialProvider(path).load()
            except CredentialError as exc:
                self.assertNotIn("S3cret", str(exc))

    def test_ast_import_never_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.py"
            path.write_text('USER="TESTUSER"\nPASSWORD="S3cret"\nraise RuntimeError("must not execute")\n')
            self.assertEqual(import_legacy(path).password, "S3cret")

    def test_credential_action_escapes_rejected(self):
        for password in ('a\\n', 'a"b', 'abc\n', 'a b', '123456789'):
            with self.subTest(password=password), self.assertRaises(CredentialError):
                validate("TESTUSER", password)


class LoginEmulator(FakeEmulator):
    def __init__(self, outcome="cms_ready"):
        captured = recorded_screen("login_form")
        rows = list(captured["rows"])
        flat = list("".join(rows))
        attrs = {}
        for f in captured["fields"]:
            attr = (0x20 if f["protected"] else 0) | (0x10 if f["numeric"] else 0) | (0x0c if f["nondisplay"] else 0)
            attrs[f["attribute_offset"]] = f"{attr:02x}"
            if not f["protected"]:
                for n in range(f["length"]):
                    flat[(f["start_offset"] + n) % 1920] = " "
        super().__init__(["".join(flat[i:i+80]) for i in range(0, 1920, 80)])
        self.buffer = buffer(attrs)
        self.cursor = (19, 16)
        self.outcome = outcome
        self.entered = False

    def exec_command(self, action):
        text = action.decode()
        if text.startswith("MoveCursor("):
            self.cursor = tuple(map(int, text[11:-1].split(',')))
        if text == "Enter":
            self.entered = True
            if self.outcome == "cms_ready":
                self.rows = screen("Ready;")
            elif self.outcome == "cp_read":
                self.rows = screen("RECONNECTED", "CP READ")
            elif self.outcome == "vm_read":
                self.rows = screen("LOGON AT 14:00:00", "VM READ")
            elif self.outcome == "rejected":
                self.rows = screen("HCPLON288E LOGON was unsuccessful")
        result = super().exec_command(action)
        if text == "Snap(Status)":
            result.data = [f"U F U C(127.0.0.1) I 2 24 80 {self.cursor[0]} {self.cursor[1]} 0x0 -".encode()]
        return result


class LoginTests(unittest.TestCase):
    def session(self, outcome="cms_ready"):
        fake = LoginEmulator(outcome)
        provider = types.SimpleNamespace(load=lambda: validate("TESTUSER", "S3cret"))
        session = Session(factory=lambda: fake, allow_login=True, credential_provider=provider)
        session.connect("0200@")
        return session, fake

    def test_default_cannot_login(self):
        self.assertFalse(Session().login()["ok"])

    def test_login_once_in_verified_fields_no_general_input(self):
        session, fake = self.session()
        result = session.login()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["outcome"], "cms_ready_observed")
        self.assertEqual(fake.calls.count("Enter"), 1)
        self.assertNotIn("S3cret", json.dumps(result))
        self.assertNotIn("TESTUSER", json.dumps(result))
        self.assertFalse(session.send("Enter")["ok"])
        self.assertIsNone(result["cms_command_complete"])
        self.assertFalse(any(x in fake.calls for x in ("Clear", "EraseInput", 'String("BEGIN")')))

    def test_cp_read_stops_without_begin(self):
        session, fake = self.session("cp_read")
        result = session.login()
        self.assertEqual(result["outcome"], "cp_read_observed")
        self.assertEqual(fake.calls.count("Enter"), 1)

    def test_cp_read_change_is_observed_even_when_wait_times_out(self):
        from py3270 import CommandError
        session, fake = self.session("cp_read")
        original = fake.exec_command
        def delayed(action):
            if action.startswith(b"Wait(") and b"Output" in action:
                raise CommandError("Wait(): Timed out")
            return original(action)
        fake.exec_command = delayed
        result = session.login(timeout=1)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["outcome"], "cp_read_observed")

    def test_vm_read_is_a_stop_not_cms_ready(self):
        session, fake = self.session("vm_read")
        result = session.login()
        self.assertEqual(result["outcome"], "vm_read_observed")
        self.assertTrue(result["guest_logon_observed"])
        self.assertEqual(fake.calls.count("Enter"), 1)
        self.assertIsNone(result["cms_command_complete"])

    def test_recorded_live_vm_read_classification(self):
        from zvm_mcp import classify
        self.assertEqual(classify(recorded_screen("vm_read")["rows"])["state"], "vm_read")

    def test_rejection_is_not_retried(self):
        session, fake = self.session("rejected")
        result = session.login()
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "login_rejected")
        self.assertEqual(fake.calls.count("Enter"), 1)

    def test_wrong_field_layout_blocks_credentials(self):
        session, fake = self.session()
        fake.buffer = buffer()  # Wrong form, even though labels are present.
        result = session.login()
        self.assertFalse(result["ok"])
        self.assertFalse(any(x.startswith("String") or x == "Enter" for x in fake.calls))

    def test_preexisting_userid_blocks_overwrite(self):
        session, fake = self.session()
        fake.rows[19] = fake.rows[19][:16] + "EXISTING" + fake.rows[19][24:]
        self.assertFalse(session.login()["ok"])
        self.assertFalse(any(x.startswith("String") for x in fake.calls))

    def test_missing_credentials_no_enter(self):
        session, fake = self.session()
        session.credential_provider = FileCredentialProvider("/does-not-exist/zvm.json")
        self.assertFalse(session.login()["ok"])
        self.assertNotIn("Enter", fake.calls)

    def test_failure_evidence_redacts_credentials(self):
        session, fake = self.session()
        fake.fail_action = 'String("S3cret")'
        result = session.login()
        self.assertFalse(result["ok"])
        self.assertNotIn("S3cret", json.dumps(result))
        self.assertNotIn("TESTUSER", json.dumps(result))
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
