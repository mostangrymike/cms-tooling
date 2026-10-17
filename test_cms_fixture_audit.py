"""Offline retained-fixture audit and exact failed-reader recovery boundaries."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import validate_cms_fixture as fixture
import validate_cms_fixture_audit as audit
from test_cms_fixture import FakeAdapter, completed
from cms_edit import canonical, sha


TOKEN = '91CDA5088C6974C7'


def boundary():
    rows = [' ' * 80 for _ in range(24)]
    rows[8] = f'ZM1 {TOKEN} F 660 ACK'
    rows[9] = 'Ready(00012); T=2.21/3.48'
    return {'state': 'cms_ready', 'connected': True, 'keyboard': 'U',
            'field_layout_error': None, 'rows': rows,
            'cursor': {'row': 23, 'column': 1, 'protected': False},
            'fields': [{'row': 23, 'column': 1, 'length': 139, 'empty': True,
                        'protected': False, 'nondisplay': False}]}


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()

    def previous(self):
        declared = fixture.contract()
        steps = [{'step': name, 'state': 'complete', 'result': {}} for name in (
            'explicit source recovery and verify', 'candidate reapply and native readback',
            'build candidate', 'test candidate', 'native output ZTQUAL ASSEMBLE A1',
            'native output ZTQUAL TEXT A1')]
        steps[2]['result'] = completed(['CMSCLNK: built ZTQUAL MODULE mode PLAIN'])
        steps[3]['result'] = completed(['ZTQUAL CANDIDATE PASS 43'])
        for index, role in ((0, 'baseline'), (1, 'candidate')):
            steps[index]['result'] = {'ok': True, 'download_complete': True,
                                     'integrity_verified': True, 'sha256': declared[role + '_sha256']}
        for step in steps[4:]:
            step['result'] = {'sha256': sha(b'output')}
        steps.append({'step': 'native output ZTQUAL LISTING A1', 'state': 'failed'})
        return {'contract': declared, 'contract_sha256': sha(canonical(declared)),
                'steps': steps, 'last_download': {'evidence': [{
                    'stage': 'FILEREAD', 'error_type': 'CaptureError',
                    'message': 'Capture deadline exceeded; partial output is not a complete command result',
                    'output_complete': False, 'request_id': TOKEN, 'frames_verified': 660}]}}

    def journal(self, name):
        declared = fixture.contract()
        journal = fixture.Journal(self.folder / name, declared, sha(canonical(declared)))
        self.addCleanup(journal.file.close)
        return journal

    def adapter(self, fault=None):
        adapter = FakeAdapter(self.folder, fault)
        for target, role in ((fixture.TARGET, 'candidate'), (fixture.BACKUP, 'baseline')):
            adapter.files[target] = fixture.native_source(fixture.read_file(
                fixture.ROOT / f'fixtures/qualification/{role}/ZTQUAL.C', 8192))
        return adapter

    def test_offline_default_has_no_terminal(self):
        result = subprocess.run([sys.executable, '-B', str(fixture.ROOT / 'validate_cms_fixture_audit.py')],
                                capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        self.assertFalse(data['host_operations_performed'])
        self.assertTrue(data['recovery_requires_separate_approval'])

    def test_prior_journal_requires_exact_hash_complete_build_and_exact_failure(self):
        prior = self.previous()
        path = self.folder / 'prior.json'
        def check(data):
            raw = canonical(data)
            path.write_bytes(raw)
            return audit.prior_run(path, sha(raw))
        self.assertEqual(check(prior)[1:], (TOKEN, 660))
        with self.assertRaises(ValueError):
            audit.prior_run(path, '0' * 64)
        for change in ('failed_build', 'bad_rc', 'missing_marker', 'wrong_pending', 'wrong_failure', 'bad_contract'):
            data = copy.deepcopy(prior)
            if change == 'failed_build': data['steps'][2]['state'] = 'failed'
            if change == 'bad_rc': data['steps'][2]['result']['cms_rc'] = 12
            if change == 'missing_marker': data['steps'][3]['result']['records'] = []
            if change == 'wrong_pending': data['steps'][-1]['step'] = 'build candidate'
            if change == 'wrong_failure': data['last_download']['evidence'][-1]['output_complete'] = True
            if change == 'bad_contract': data['contract']['target'] = 'GITC26 C G1'
            with self.subTest(change=change), self.assertRaises(ValueError): check(data)

    def test_exact_failure_boundary_refuses_ambiguous_or_nonempty_input(self):
        self.assertTrue(audit.failed_boundary(boundary(), TOKEN, 660))
        for change in ('nonce', 'sequence', 'ready', 'order', 'other_frame', 'input', 'locked', 'layout'):
            screen = boundary()
            if change == 'nonce': screen['rows'][8] = 'ZM1 AAAAAAAAAAAAAAAA F 660 ACK'
            if change == 'sequence': screen['rows'][8] = f'ZM1 {TOKEN} F 661 ACK'
            if change == 'ready': screen['rows'][9] = 'Ready;'
            if change == 'order': screen['rows'][7], screen['rows'][9] = screen['rows'][9], ''
            if change == 'other_frame': screen['rows'][6] = f'ZM1 {TOKEN} D 659 DATA'
            if change == 'input': screen['fields'][0]['empty'] = False
            if change == 'locked': screen['keyboard'] = 'L'
            if change == 'layout': screen['field_layout_error'] = 'invalid'
            with self.subTest(change=change): self.assertFalse(audit.failed_boundary(screen, TOKEN, 660))

    def test_audit_never_writes_builds_tests_or_recovers(self):
        adapter = self.adapter()
        journal = self.journal('success')
        with patch('builtins.print'):
            audit.audit(adapter, journal, self.previous())
        self.assertTrue(journal.data['passed'])
        self.assertFalse(journal.data['host_file_writes'])
        self.assertFalse(journal.data['build_or_test_repeated'])
        self.assertFalse(journal.data['replacement_safe'])
        self.assertFalse(journal.data['production_qualified'])
        self.assertEqual([x for x in adapter.calls if x in ('BUILD', 'TEST') or x.startswith('put ')], [])
        self.assertEqual(adapter.calls[-1], 'FILEDEFS')

    def test_completed_outputs_are_retained_without_repeating_native_reads(self):
        adapter = self.adapter()
        retained = {target: {'reused_local_evidence': True, 'fresh_host_read': False}
                    for target in fixture.OUTPUTS[:-1]}
        journal = self.journal('retain')
        journal.data['output_helper_creation_requested'] = True
        with patch('builtins.print'):
            audit.audit(adapter, journal, self.previous(), retained)
        self.assertTrue(journal.data['passed'])
        self.assertTrue(journal.data['host_file_writes'])
        self.assertFalse(journal.data['fixture_file_writes'])
        for target in retained:
            self.assertNotIn('download ' + target, adapter.calls)
        self.assertIn('download ZTQUAL MODULE A1', adapter.calls)

    def test_every_audit_failure_stops_without_retry_or_cleanup(self):
        adapter = self.adapter()
        with patch('builtins.print'):
            audit.audit(adapter, self.journal('probe'), self.previous())
            for index in range(1, len(adapter.calls) + 1):
                failed = self.adapter(index)
                journal = self.journal('failure-' + str(index))
                with self.subTest(index=index), self.assertRaises(ValueError):
                    audit.audit(failed, journal, self.previous())
                self.assertEqual(failed.calls, adapter.calls[:index])
                self.assertFalse(journal.data['passed'])

    def test_recovery_sends_exactly_one_clear_and_fixed_probe(self):
        before = boundary()
        empty = boundary()
        empty['state'] = 'unknown'
        empty['rows'] = [' ' * 80 for _ in range(24)]
        ready = copy.deepcopy(empty)
        ready['state'] = 'cms_ready'
        ready['rows'][:3] = ['QUERY CMSLEVEL', 'CMS Level 27, Service Level 1302', 'Ready; T=0.01/0.01']
        session = Mock()
        session.snapshot.side_effect = [before, before, empty, ready]
        session._run.side_effect = lambda name, function, timeout: {'ok': True, **function()}
        result = audit.recover_failed_reader(session, TOKEN, 660)
        self.assertFalse(result['prior_capture_complete'])
        self.assertEqual(session.command.call_args_list, [unittest.mock.call('MoveCursor(22,0)'), unittest.mock.call('Clear')])
        session.runner._input.assert_called_once_with('QUERY CMSLEVEL')

    def test_recovery_refuses_before_input_and_stops_after_unexpected_clear_state(self):
        for initial in (True, False):
            session = Mock()
            screen = boundary()
            screen['state'] = 'more'
            session.snapshot.side_effect = [screen] if initial else [boundary(), boundary(), screen]
            session._run.side_effect = lambda name, function, timeout: {'ok': True, **function()}
            with self.assertRaises(ValueError): audit.recover_failed_reader(session, TOKEN, 660)
            session.runner._input.assert_not_called()
            self.assertEqual(session.command.call_count, 0 if initial else 2)

    def test_changed_disk_inventory_and_filedefs_refused(self):
        for kind in ('disk', 'inventory', 'filedefs'):
            adapter = self.adapter()
            command, action = adapter.command, adapter.action
            def altered_command(text, **kwargs):
                if kind == 'disk' and text == 'QUERY DISK': return completed(['OTHER 191 A R/W'])
                if kind == 'inventory' and text == 'LISTFILE ZTQUAL * A': return completed([fixture.TARGET])
                return command(text, **kwargs)
            adapter.command = altered_command
            if kind == 'filedefs': adapter.action = lambda *a: completed(['SYSIN DISK SECRET C A1'])
            with patch('builtins.print'), self.subTest(kind=kind), self.assertRaises(ValueError):
                audit.audit(adapter, self.journal(kind), self.previous())


if __name__ == '__main__':
    unittest.main()
