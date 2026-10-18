"""Offline regression tests for the narrowly authorized CMS startup boundary."""
import unittest

from py3270 import CommandError
from test_cms_mcp import FakeEmulator, buffer, screen
from cms_mcp import Session
from test_cms_fixtures import recorded_screen


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
        self.attrs = attrs
        self.buffer = buffer(attrs)
        self.cursor = (22, 0)
        self.fresh = fresh
        self.change = change

    def exec_command(self, action):
        if action.startswith(b"MoveCursor("):
            self.cursor = tuple(map(int, action.decode()[11:-1].split(',')))
        if action == b'String("b")':
            self.rows[22] = "b" + self.rows[22][1:]
            self.attrs = {offset: f"{int(value, 16) | (1 if offset == 1759 else 0):02x}"
                          for offset, value in self.attrs.items()}
            self.buffer = buffer(self.attrs)
            self.cursor = (22, 1)
        if action == b"Enter" and self.change:
            self.rows = screen("Ready;")
        if action.startswith(b"Wait(") and b"Output" in action and not self.fresh:
            self.calls.append(action.decode())
            raise CommandError("Wait(): Timed out")
        result = super().exec_command(action)
        if action == b"Snap(Status)":
            result.data = [f"U F U C(127.0.0.1) I 2 24 80 {self.cursor[0]} {self.cursor[1]} 0x0 -".encode()]
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

    def test_exact_hercules_vm_read_without_logon_line_can_continue_once(self):
        s, fake = self.session()
        fake.rows[0] = "Hercules Version  : 4.7.0".ljust(80)
        fake.rows[5] = " " * 80
        result = s.startup()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["actions"], ["Enter"])
        self.assertEqual(fake.calls.count("Enter"), 1)
        self.assertFalse(any(call.startswith("String") for call in fake.calls))

    def test_explicit_vm_begin_types_one_b_then_enters_once(self):
        s, fake = self.session()
        fake.rows[0] = "Hercules Version  : 4.7.0".ljust(80)
        fake.rows[5] = " " * 80
        result = s.startup(begin_vm=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["actions"], ["b", "Enter"])
        self.assertEqual(fake.calls.count('String("b")'), 1)
        self.assertEqual(fake.calls.count("Enter"), 1)
        self.assertFalse(any(call.startswith("String") and call != 'String("b")' for call in fake.calls))

    def test_explicit_vm_begin_verifies_redacted_input_internally(self):
        s, fake = self.session()
        s.secrets.add("LOCAL")
        fake.rows[0] = "Hercules Version  : 4.7.0".ljust(80)
        fake.rows[5] = " " * 80
        result = s.startup(begin_vm=True)
        self.assertTrue(result["ok"], result)
        typed = result["snapshots"][2]
        self.assertEqual(typed["state"], "vm_read")
        self.assertNotIn("_expected_input_matches", typed)
        self.assertEqual(typed["rows"][22], "*" * 80)
        self.assertEqual(result["actions"], ["b", "Enter"])

    def test_explicit_vm_begin_refuses_cp_read(self):
        s, fake = self.session("cp_read")
        result = s.startup(begin_vm=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "vm_begin_requires_vm_read")
        self.assertFalse(any(call.startswith("String") or call == "Enter" for call in fake.calls))

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

    def test_hold_arriving_during_field_recheck_stops_without_any_aid(self):
        for indicator in ('MORE...', 'HOLDING'):
            s, fake = self.session()
            original = fake.exec_command
            def transition(action):
                if action == b'MoveCursor(22,0)':
                    fake.rows[-1] = (' ' * 60 + indicator).ljust(80)
                return original(action)
            fake.exec_command = transition
            result = s.startup(verify_cms=True)
            self.assertFalse(result['ok'], result)
            self.assertEqual(result['outcome'], 'startup_page_hold_observed')
            self.assertEqual(result['actions'], [])
            self.assertNotIn('Enter', fake.calls)
            self.assertNotIn('Clear', fake.calls)
            self.assertFalse(any(call.startswith('String') for call in fake.calls))
            s.disconnect()

    def test_hold_after_reconnect_begin_is_observed_without_automatic_clear(self):
        s, fake = self.session('cp_read')
        fake.change = False
        original = fake.exec_command
        def transition(action):
            result = original(action)
            if action == b'Enter':
                fake.rows[-1] = (' ' * 60 + 'MORE...').ljust(80)
            return result
        fake.exec_command = transition
        result = s.startup(verify_cms=True)
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['outcome'], 'startup_page_hold_observed')
        self.assertEqual(result['actions'], ['BEGIN', 'Enter'])
        self.assertEqual(fake.calls.count('Enter'), 1)
        self.assertNotIn('Clear', fake.calls)
        s.disconnect()

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

    def test_running_after_begin_stops_after_one_startup_dispatch(self):
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
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["outcome"], "startup_transition_observed")
        self.assertEqual(result["actions"], ["BEGIN", "Enter"])
        self.assertEqual(fake.calls.count("Enter"), 1)
        self.assertEqual(progress["waits"], 1)

    def test_recorded_reconnect_running_blank_is_cms_command_ready(self):
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
        self.assertEqual(result["outcome"], "cms_ready_observed")
        self.assertEqual(result["actions"], ["BEGIN", "Enter"])
        self.assertEqual(result["screen"]["state"], "cms_ready")
        self.assertEqual(result["actions"], ["BEGIN", "Enter"])
        self.assertEqual(fake.calls.count("Enter"), 1)

    def test_same_running_screen_without_our_begin_is_refused(self):
        s, fake = self.session()
        fake.rows[-1] = fake.rows[-1].replace("VM READ", "RUNNING")
        fake.rows[6] = "BEGIN".ljust(80)
        self.assertFalse(s.startup()["ok"])
        self.assertNotIn("Enter", fake.calls)

    def test_fixed_readonly_probe_guard_and_response(self):
        from diagnose_cms import probe_boundary, probe
        from cms_mcp import host_display
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
        with patch("diagnose_cms.probe", return_value={"ok": False, "outcome": "guarded"}) as query:
            self.assertFalse(s.startup()["ok"])
            query.assert_not_called()
            self.assertFalse(s.startup(verify_cms=True)["ok"])
            query.assert_called_once()

    def test_bare_cms_reconnect_probe_accepts_only_exact_observed_shape(self):
        import copy
        from diagnose_cms import probe_boundary
        captured = recorded_screen('cms_boundary')
        captured['actions'] = ['BEGIN', 'Enter']
        rows = captured['screen']['rows']
        rows[1] = 'z/VM Version 6 Release 3.0'.ljust(80)
        rows[6] = 'BEGIN'.ljust(80)
        rows[7:22] = [' ' * 80] * 15
        rows[8] = 'CMS'.ljust(80)
        self.assertTrue(probe_boundary(captured))
        observed_transition = copy.deepcopy(captured)
        observed_transition['outcome'] = 'startup_transition_observed'
        self.assertTrue(probe_boundary(observed_transition))
        for row, text in ((6, 'SOMETHING ELSE'), (8, 'Application input'), (10, 'unrelated output')):
            changed = copy.deepcopy(captured)
            changed['screen']['rows'][row] = text.ljust(80)
            self.assertFalse(probe_boundary(changed))
        unrelated_running = recorded_screen('reconnect_running')
        unrelated_running['actions'] = ['BEGIN', 'Enter']
        unrelated_running['outcome'] = 'startup_transition_observed'
        self.assertFalse(probe_boundary(unrelated_running))
        changed = copy.deepcopy(captured)
        changed['screen']['fields'][0]['empty'] = False
        self.assertFalse(probe_boundary(changed))

    def test_fixed_probe_accepts_cms_banner_after_exact_unmarked_vm_read(self):
        import copy
        from diagnose_cms import probe_boundary
        from test_cms_fixtures import recorded_screen
        initial = recorded_screen('vm_read')
        initial.update({'state': 'vm_read', 'connected': True, 'keyboard': 'U',
                        'field_layout_error': None})
        initial['fields'][0]['empty'] = True
        initial['screen_kind'] = 'hercules_banner'
        initial['rows'][0] = 'Hercules Version  : 4.7.0'.ljust(80)
        initial['rows'][5] = ' ' * 80
        cms = recorded_screen('cms_boundary')
        target = cms['screen']
        target['rows'][0] = 'Hercules Version  : 4.7.0'.ljust(80)
        target['rows'][5] = ' ' * 80
        target['rows'][6] = ' ' * 80
        result = {'actions': ['b', 'Enter'], 'outcome': 'startup_transition_observed',
                  'snapshots': [initial], 'screen': target}
        self.assertTrue(probe_boundary(result))
        unrelated = copy.deepcopy(result)
        unrelated['snapshots'][0]['fields'][0]['empty'] = False
        self.assertFalse(probe_boundary(unrelated))

    def test_fixed_probe_accepts_exact_zvm_guest_reconnect_begin(self):
        import copy
        from diagnose_cms import probe_boundary
        initial = recorded_screen('vm_read')
        initial.update({'state':'vm_read','screen_kind':'zvm_guest_banner',
                        'connected':True,'keyboard':'U','field_layout_error':None})
        initial['rows'][1] = '15:40:37 z/VM Version 6 Release 3.0, Service Level 1302'.ljust(80)
        initial['rows'][5] = '15:40:37 RECONNECTED AT 15:40:37 EST SATURDAY 10/17/26'.ljust(80)
        initial['rows'][23] = ('VM READ').ljust(80)
        initial['fields'][0].update({'row':23,'column':1,'length':139,
                                     'nondisplay':False,'empty':True})
        target = recorded_screen('cms_boundary')['screen']
        target['screen_kind'] = 'zvm_guest_banner'
        target['rows'][1] = '15:40:37 z/VM Version 6 Release 3.0, Service Level 1302'.ljust(80)
        target['rows'][5] = '15:40:37 RECONNECTED AT 15:40:37 EST SATURDAY 10/17/26'.ljust(80)
        result = {'actions':['b','Enter'],'outcome':'startup_transition_observed',
                  'snapshots':[initial],'screen':target}
        self.assertTrue(probe_boundary(result))
        unrelated = copy.deepcopy(result)
        unrelated['screen']['rows'][8] = 'ANOTHER APPLICATION'.ljust(80)
        self.assertFalse(probe_boundary(unrelated))


if __name__ == "__main__":
    unittest.main()
