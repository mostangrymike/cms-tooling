"""Offline regression tests for the narrowly authorized CMS startup boundary."""
import unittest

from py3270 import CommandError
from test_zvm_mcp import FakeEmulator, buffer, screen
from zvm_mcp import Session
from test_zvm_fixtures import recorded_screen


class StartupEmulator(FakeEmulator):
    def __init__(self, initial="vm_read", fresh=True, change=True):
        captured = recorded_screen("vm_read")
        flat = list("".join(captured["rows"]))
        attrs = {}
        for f in captured["fields"]:
            attr = (0x20 if f["protected"] else 0) | (0x01 if f["modified"] else 0)
            attrs[f["attribute_offset"]] = f"{attr:02x}"
            if not f["protected"]:
                for n in range(f["length"]):
                    flat[(f["start_offset"] + n) % 1920] = " "
        rows = ["".join(flat[i:i+80]) for i in range(0, 1920, 80)]
        if initial == "cp_read":
            rows[0] = "RECONNECTED".ljust(80)
            rows[-1] = rows[-1].replace("VM READ", "CP READ")
        super().__init__(rows)
        self.buffer = buffer(attrs)
        self.fresh = fresh
        self.change = change

    def exec_command(self, action):
        if action == b"Enter" and self.change:
            self.rows = screen("Ready;")
        if action.startswith(b"Wait(") and b"Output" in action and not self.fresh:
            self.calls.append(action.decode())
            raise CommandError("Wait(): Timed out")
        result = super().exec_command(action)
        if action == b"Snap(Status)":
            result.data = [b"U F U C(127.0.0.1) I 2 24 80 22 0 0x0 -"]
        return result


class StartupTests(unittest.TestCase):
    def session(self, initial="vm_read", fresh=True):
        fake = StartupEmulator(initial, fresh)
        s = Session(factory=lambda: fake, allow_startup=True)
        s.connect("0200@")
        return s, fake

    def test_default_disabled(self):
        self.assertFalse(Session().startup()["ok"])

    def test_vm_read_one_enter_then_fresh_ready(self):
        s, fake = self.session()
        result = s.startup()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["outcome"], "cms_ready_observed")
        self.assertEqual(result["actions"], ["Enter"])
        self.assertEqual(fake.calls.count("Enter"), 1)
        self.assertFalse(any(c.startswith("String") for c in fake.calls))
        self.assertIsNone(result["cms_command_complete"])
        self.assertFalse(s.send("Enter")["ok"])

    def test_reconnected_cp_read_only_begin(self):
        s, fake = self.session("cp_read")
        result = s.startup()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["actions"], ["BEGIN", "Enter"])
        self.assertEqual([c for c in fake.calls if c.startswith("String")], ['String("BEGIN")'])

    def test_ready_arriving_during_field_recheck_sends_no_startup_input(self):
        s, fake = self.session()
        original = fake.exec_command
        def transition(action):
            if action == b'MoveCursor(22,0)':
                fake.rows = screen('Ready;')
            return original(action)
        fake.exec_command = transition
        result = s.startup()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['outcome'], 'cms_ready_observed')
        self.assertEqual(result['actions'], [])
        self.assertNotIn('Enter', fake.calls)
        self.assertFalse(any(call.startswith('String') for call in fake.calls))

    def test_unrelated_vm_read_refused(self):
        s, fake = self.session()
        fake.rows = screen("An application waiting for input", "VM READ")
        result = s.startup()
        self.assertFalse(result["ok"])
        self.assertNotIn("Enter", fake.calls)

    def test_existing_input_refused_even_when_redacted(self):
        s, fake = self.session()
        fake.rows[22] = "DO NOT SUBMIT".ljust(80)
        s.secrets.add("LOCAL")
        result = s.startup()
        self.assertFalse(result["ok"])
        self.assertNotIn("Enter", fake.calls)

    def test_wrong_layout_refused(self):
        s, fake = self.session()
        fake.buffer = buffer()
        self.assertFalse(s.startup()["ok"])
        self.assertNotIn("Enter", fake.calls)

    def test_ready_without_fresh_output_is_not_success(self):
        s, fake = self.session("cp_read", fresh=False)
        fake.change = False
        fake.rows[0] = "Ready; old prompt above the current startup read".ljust(80)
        result = s.startup(timeout=1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "startup_transition_timeout")
        self.assertEqual(fake.calls.count("Enter"), 1)

    def test_host_screen_change_after_wait_timeout_is_observed(self):
        s, fake = self.session(fresh=False)
        result = s.startup(timeout=1)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["outcome"], "cms_ready_observed")

    def test_running_between_begin_and_vm_read_is_observed_passively(self):
        s, fake = self.session("cp_read")
        original = fake.exec_command
        progress = {"enters": 0, "waits": 0}
        def transition(action):
            if action == b"Enter":
                progress["enters"] += 1
                fake.change = progress["enters"] > 1
                result = original(action)
                if progress["enters"] == 1:
                    fake.rows[-1] = fake.rows[-1].replace("CP READ", "RUNNING")
                return result
            if action.startswith(b"Wait(") and b"Output" in action and progress["enters"] == 1:
                progress["waits"] += 1
                if progress["waits"] == 2:
                    fake.rows[-1] = fake.rows[-1].replace("RUNNING", "VM READ")
            return original(action)
        fake.exec_command = transition
        result = s.startup()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["actions"], ["BEGIN", "Enter", "Enter"])
        self.assertEqual(progress["waits"], 2)

    def test_recorded_reconnect_running_blank_requires_our_begin(self):
        s, fake = self.session("cp_read")
        captured = recorded_screen("reconnect_running")
        flat = list("".join(captured["rows"]))
        for f in captured["fields"]:
            if not f["protected"]:
                for n in range(f["length"]):
                    flat[(f["start_offset"] + n) % 1920] = " "
        running = ["".join(flat[i:i+80]) for i in range(0,1920,80)]
        original = fake.exec_command
        progress = {"enters": 0}
        def transition(action):
            if action == b"Enter":
                progress["enters"] += 1
                result = original(action)
                if progress["enters"] == 1:
                    fake.rows = running
                return result
            return original(action)
        fake.exec_command = transition
        result = s.startup()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["actions"], ["BEGIN", "Enter", "Enter"])

    def test_same_running_screen_without_our_begin_is_refused(self):
        s, fake = self.session()
        fake.rows[-1] = fake.rows[-1].replace("VM READ", "RUNNING")
        fake.rows[6] = "BEGIN".ljust(80)
        self.assertFalse(s.startup()["ok"])
        self.assertNotIn("Enter", fake.calls)

    def test_fixed_readonly_probe_guard_and_response(self):
        from diagnose_zvm_cms import probe_boundary, probe
        from zvm_mcp import host_display
        captured = recorded_screen("cms_boundary")
        self.assertTrue(probe_boundary(captured))
        self.assertFalse(probe_boundary({**captured, "actions": []}))
        s, fake = self.session()
        flat = list("".join(captured["screen"]["rows"]))
        for n in range(1760,1899):
            flat[n] = " "
        fake.rows = ["".join(flat[i:i+80]) for i in range(0,1920,80)]
        original = fake.exec_command
        def response(action):
            result = original(action)
            if action == b"Enter":
                fake.rows = screen("CMS Level 26, Service Level 1302")
                fake.rows[1] = "Ready;".ljust(80)
            return result
        fake.exec_command = response
        result = probe(s, captured, host_display)
        self.assertTrue(result["ok"], result)
        self.assertEqual([x for x in fake.calls if x.startswith("String")], ['String("QUERY CMSLEVEL")'])
        self.assertEqual(fake.calls.count("Enter"), 1)

    def test_probe_only_runs_with_explicit_verification_option(self):
        from unittest.mock import patch
        s, fake = self.session()
        fake.rows = screen("Unrelated application", "VM READ")
        with patch("diagnose_zvm_cms.probe", return_value={"ok": False, "outcome": "guarded"}) as query:
            self.assertFalse(s.startup()["ok"])
            query.assert_not_called()
            self.assertFalse(s.startup(verify_cms=True)["ok"])
            query.assert_called_once()


if __name__ == "__main__":
    unittest.main()
