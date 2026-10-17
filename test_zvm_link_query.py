"""Offline tests for the fixed-command, direct-screen CP QUERY LINKS tool."""
import unittest
import copy
from unittest.mock import Mock

from zvm_link_query import LinkQuery, link_query_command
from zvm_mcp import Session
from test_zvm_mcp import FakeEmulator, buffer, screen
from validate_zvm_gdisk import access_gate


class PagingEmulator(FakeEmulator):
    def __init__(self, paged=True):
        super().__init__(screen("Ready;"))
        self.buffer = buffer({0: "20", 1759: "00", 1899: "20"})
        self.queued = ""
        self.paged = paged
        self.page = 0
        self.rows = screen("Ready;")

    def exec_command(self, action):
        text = action.decode()
        if text.startswith('String("'):
            self.queued = text[8:-2]
        elif text == "Enter":
            self.assert_query()
            if self.page == 0:
                self.page = 1
                self.rows = screen("Ready;", "")
                self.rows[8] = self.queued.ljust(80)
                self.rows[9] = "USERA 0191 W".ljust(80)
                self.rows[23] = "MORE..." if self.paged else "Ready; T=0.01/0.01"
                if not self.paged:
                    self.rows[10] = "Ready; T=0.01/0.01".ljust(80)
            elif self.page == 1 and self.paged:
                self.page = 2
                self.rows = screen("Ready;", "")
                self.rows[8] = self.queued.ljust(80)
                self.rows[9] = "USERB 0192 W".ljust(80)
                self.rows[10] = "Ready; T=0.02/0.02".ljust(80)
        elif text == "Clear" and self.page == 1:
            self.page = 2
            self.rows = screen("Ready;", "")
            self.rows[8] = self.queued.ljust(80)
            self.rows[9] = "USERB 0192 W".ljust(80)
            self.rows[10] = "Ready; T=0.02/0.02".ljust(80)
        result = super().exec_command(action)
        if text == "Snap(Status)":
            result.data = [b"U F U C(127.0.0.1) I 2 24 80 22 0 0x0 -"]
        return result

    def assert_query(self):
        assert self.queued == "CP QUERY LINKS 191", self.queued


class LinkQueryTests(unittest.TestCase):
    def disk_observations(self):
        data = {
            'virtual': ['DASD 0600 3390 VMCOM1 R/W 1600 CYL ON DASD 0127 SUBCHANNEL = 001F'],
            'location': ['MAINT 0600 MAINT 0600 3390 VMCOM1 0127 6000 1600'],
            'directory': ['MAINT 0600 MAINT 0600 3390 VMCOM1 0127 6000 1600'],
            'volume': ['DASD 0127 ATTACHED CPVOL 0016 VMCOM1', 'MAINT 0600 R/W',
                       'MAINT 0551 R/O', 'MAINT 02CC R/W', 'MAINT 049E R/O'] +
                ['VMSERVP ' + address + ' R/W' for address in
                 ('0311','0310','0309','0308','0307','0306','0305','0304','0303','0301','0302','0191')],
            'disk': ['MNT191 191 A R/W 175 3390 4096 348 13231-42 18269 31500']}
        return {name: {'ok': True, 'output_complete': True, 'output_rows': rows} for name, rows in data.items()}

    def test_existing_g_access_gate_requires_all_exact_preconditions(self):
        data = self.disk_observations()
        self.assertFalse(access_gate(data, set())['replacement_safe'])
        for name, text in [('virtual', 'DASD 0600 3390 OTHER R/W 1600 CYL ON DASD 0127 SUBCHANNEL = 001F'),
                           ('location', 'MAINT 0600 MAINT 0600 3390 VMCOM1 0127 0 11000'),
                           ('directory', 'OTHER 0600 OTHER 0600 3390 VMCOM1 0127 6000 1600'),
                           ('volume', 'PMAINT 0141 R/W'),
                           ('disk', 'OTHER 601 G R/W 1 3390 4096 1 1 1 1')]:
            changed = copy.deepcopy(data)
            changed[name]['output_rows'].append(text)
            with self.subTest(name=name), self.assertRaises(ValueError):
                access_gate(changed, set())
        data['location']['output_complete'] = False
        with self.assertRaises(ValueError):
            access_gate(data, set())

    def test_existing_g_access_gate_accounts_for_geometry_preserving_redaction(self):
        data = self.disk_observations()
        for result in data.values():
            result['output_rows'] = [row.replace('MAINT', '*****') for row in result['output_rows']]
        self.assertFalse(access_gate(data, {'MAINT'})['writer_exclusion_established'])

    def test_command_accepts_only_a_three_digit_hex_address(self):
        self.assertEqual(link_query_command("19a"), "CP QUERY LINKS 19A")
        for value in ("*", "0191", "19", "191; CP IPL CMS", " cp query links 191 "):
            with self.subTest(value=value), self.assertRaises(ValueError):
                link_query_command(value)

    def test_disabled_and_invalid_queries_never_connect(self):
        factory = Mock(side_effect=AssertionError("must remain offline"))
        session = Session(factory=factory)
        self.assertFalse(session.link_query.query("191")["ok"])
        session.allow_query_links = True
        for value in ("*", "0191", "191; CP IPL CMS"):
            self.assertFalse(session.link_query.query(value)["ok"])
        factory.assert_not_called()

    def test_direct_query_captures_all_pages_and_waits_for_ready_boundary(self):
        fake = PagingEmulator()
        session = Session(factory=lambda: fake, allow_query_links=True)
        session.connect("0200@")
        result = session.link_query.query("191")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["command"], "CP QUERY LINKS 191")
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(result['output_rows'], ['USERA 0191 W', 'USERB 0192 W'])
        self.assertTrue(result["output_complete"])
        self.assertTrue(result["completion_observed"])
        self.assertIsNone(result["cms_command_complete"])
        self.assertFalse(result["replacement_safe"])
        self.assertFalse(result["link_query_is_lock"])
        self.assertEqual(sum(call == "Enter" for call in fake.calls), 1)
        self.assertEqual(sum(call == "Clear" for call in fake.calls), 1)
        self.assertFalse(any("Transfer(" in call for call in fake.calls))
        session.disconnect()

    def test_unpaged_query_requires_echo_and_ready_after_output(self):
        fake = PagingEmulator(paged=False)
        session = Session(factory=lambda: fake, allow_query_links=True)
        session.connect("0200@")
        result = session.link_query.query("191")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["page_count"], 1)
        session.disconnect()

    def test_fixed_g_diagnostics_never_accept_arbitrary_commands(self):
        session = Session(factory=Mock(side_effect=AssertionError('must remain offline')))
        self.assertFalse(session.link_query.inspect_g('virtual')['ok'])
        session.allow_query_links = True
        for query in ('CP LINK * 0600 0600 W', 'FORMAT', 'virtual; IPL CMS', None):
            self.assertFalse(session.link_query.inspect_g(query)['ok'])
        session.factory.assert_not_called()

    def test_each_fixed_g_diagnostic_has_exact_echo_and_fresh_ready(self):
        expected = {'virtual': 'CP QUERY VIRTUAL DASD', 'location': 'CP QUERY MDISK 0600 LOCATION',
            'directory': 'CP QUERY MDISK USERID MAINT 0600 LOCATION DIRECTORY',
            'volume': 'CP QUERY SYSTEM 0127', 'disk': 'QUERY DISK'}
        for query, command in expected.items():
            with self.subTest(query=query):
                fake = PagingEmulator(paged=False)
                fake.assert_query = lambda: self.assertEqual(fake.queued, command)
                session = Session(factory=lambda: fake, allow_query_links=True)
                session.connect('0200@')
                result = session.link_query.inspect_g(query)
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['command'], command)
                self.assertFalse(result['replacement_safe'])
                session.disconnect()

    def test_paged_completion_does_not_require_echo_to_repeat_on_final_page(self):
        class NoRepeatedEcho(PagingEmulator):
            def exec_command(self, action):
                result = super().exec_command(action)
                if self.page == 2:
                    self.rows[8] = ' ' * 80
                return result
        fake = NoRepeatedEcho()
        session = Session(factory=lambda: fake, allow_query_links=True)
        session.connect('0200@')
        result = session.link_query.query('191')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['page_count'], 2)
        session.disconnect()

    def test_repeated_output_events_on_same_hold_do_not_repeat_paging_key(self):
        class StuckHold(PagingEmulator):
            def exec_command(self, action):
                if action == b'Clear':
                    previous = list(self.rows)
                    result = super().exec_command(action)
                    self.rows = previous
                    self.page = 1
                    return result
                return super().exec_command(action)
        fake = StuckHold()
        session = Session(factory=lambda: fake, allow_query_links=True)
        session.connect('0200@')
        calls = 0
        def repeated_event(seconds):
            nonlocal calls
            calls += 1
            if calls > 4:
                raise TimeoutError('Synthetic held output deadline')
            return True
        session._wait_output = repeated_event
        result = session.link_query.query('191')
        self.assertFalse(result['ok'])
        self.assertEqual(sum(call == 'Clear' for call in fake.calls), 1)
        self.assertEqual(sum(call == 'Enter' for call in fake.calls), 1)

    def test_partial_final_page_is_observed_without_an_extra_key(self):
        class PartialFinalPage(PagingEmulator):
            waits = 0
            def exec_command(self, action):
                result = super().exec_command(action)
                if action == b'Clear':
                    self.rows = screen('DASD 0600 output', ' '*60 + 'RUNNING')
                elif action.startswith(b'Wait(') and self.page == 2:
                    self.waits += 1
                    if self.waits == 2:
                        self.rows[1] = 'Ready; T=0.01/0.01'.ljust(80)
                return result
        fake = PartialFinalPage()
        session = Session(factory=lambda: fake, allow_query_links=True)
        session.connect('0200@')
        result = session.link_query.query('191')
        self.assertTrue(result['ok'], result)
        self.assertEqual(sum(call == 'Clear' for call in fake.calls), 1)
        self.assertEqual(sum(call == 'Enter' for call in fake.calls), 1)
        session.disconnect()

    def test_secret_masked_command_echo_still_correlates_without_disclosure(self):
        fake = PagingEmulator(paged=False)
        command = 'CP QUERY MDISK USERID MAINT 0600 LOCATION DIRECTORY'
        fake.assert_query = lambda: self.assertEqual(fake.queued, command)
        session = Session(factory=lambda: fake, allow_query_links=True)
        session.secrets.add('MAINT')
        session.connect('0200@')
        result = session.link_query.inspect_g('directory')
        self.assertTrue(result['ok'], result)
        self.assertNotIn('MAINT', __import__('json').dumps(result))
        session.disconnect()


if __name__ == "__main__":
    unittest.main()
