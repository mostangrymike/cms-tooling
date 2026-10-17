"""Fixed disposable qualification boundaries and fail-stop behavior, offline."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import validate_cms_fixture as fixture
from cms_edit import canonical, sha
from cms_mcp import Session
from cms_download import metadata, save_snapshot


def completed(records=(), rc=0):
    return {'ok': True, 'cms_rc': rc, 'records': list(records), 'output_complete': True,
            'integrity_verified': True, 'cms_command_complete': True, 'redaction_applied': False}


class FakeAdapter:
    def __init__(self, folder, fault=None):
        self.calls = []
        self.files = {}
        self.fault = fault
        self.folder = folder

    def event(self, label):
        self.calls.append(label)
        if len(self.calls) == self.fault:
            raise ValueError('Simulated uncertain host step')

    def command(self, text, rc=0, marker=None):
        self.event(text)
        if text == 'QUERY DISK':
            return completed(['MNT191 191 A R/W 175', 'GCCLIB 29D F R/W 20'])
        if rc == 0 and text == 'LISTFILE ZTQUAL * A':
            return completed([fixture.TARGET, *fixture.OUTPUTS])
        if rc == 0 and text == 'LISTFILE ZTQBACK * A':
            return completed([fixture.BACKUP])
        return completed(rc=rc)

    def action(self, action, marker=None):
        self.event(action)
        return completed([marker] if marker else [])

    def download(self, target, expected=None):
        self.event('download ' + target)
        raw = self.files.get(target, b'output')
        if target in (fixture.TARGET, fixture.BACKUP) and expected != sha(raw):
            raise ValueError('Bad expected hash in fixture model')
        path = self.folder / ('file-' + str(len(self.calls)))
        path.write_bytes(raw)
        return {'ok': True, 'native_file': str(path), 'sha256': sha(raw)}

    def put(self, target, raw, expected_current=None):
        self.event('put ' + target)
        if expected_current and sha(self.files[target]) != expected_current:
            raise ValueError('Prewrite hash mismatch')
        if expected_current is None and target in self.files:
            raise ValueError('Refuse existing create target')
        self.files[target] = raw
        path = self.folder / ('file-' + str(len(self.calls)))
        path.write_bytes(raw)
        return {'ok': True, 'native_file': str(path), 'sha256': sha(raw)}

    def review(self, original, candidate):
        self.event('review')
        return {'ok': True, 'candidate_sha256': sha(candidate)}


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.declared = fixture.contract()
        self.digest = sha(canonical(self.declared))

    def journal(self, name='evidence.json'):
        result = fixture.Journal(self.folder / name, self.declared, self.digest)
        self.addCleanup(result.file.close)
        return result

    def test_offline_cli_never_constructs_terminal(self):
        result = subprocess.run([sys.executable, '-B', str(fixture.ROOT / 'validate_cms_fixture.py')],
                                text=True, capture_output=True, check=True)
        data = json.loads(result.stdout)
        self.assertFalse(data['host_operations_performed'])
        self.assertEqual(data['contract_sha256'], self.digest)
        self.assertFalse(data['contract']['production_qualified'])

    def test_exact_contract_and_recovery_flag_required_before_first_action(self):
        for digest, recovery in [('0' * 64, True), (self.digest, False)]:
            adapter = FakeAdapter(self.folder)
            with self.assertRaises(ValueError):
                fixture.execute(adapter, self.journal('guard-' + str(recovery)), self.declared, digest, recovery)
            self.assertEqual(adapter.calls, [])
        changed = copy.deepcopy(self.declared)
        changed['target'] = 'GITC26 C G1'
        adapter = FakeAdapter(self.folder)
        with self.assertRaises(ValueError):
            fixture.execute(adapter, self.journal(), changed, sha(canonical(changed)), True)
        self.assertEqual(adapter.calls, [])

    def test_success_recovers_then_reapplies_candidate_before_build(self):
        adapter, journal = FakeAdapter(self.folder), self.journal()
        with patch('builtins.print'):
            fixture.execute(adapter, journal, self.declared, self.digest, True)
        self.assertTrue(journal.data['passed'])
        self.assertFalse(journal.data['production_qualified'])
        puts = [call for call in adapter.calls if call.startswith('put ')]
        self.assertEqual(puts, ['put ' + fixture.TARGET, 'put ' + fixture.BACKUP] + ['put ' + fixture.TARGET] * 3)
        self.assertLess(max(i for i, call in enumerate(adapter.calls) if call.startswith('put ')), adapter.calls.index('BUILD'))
        self.assertEqual(sha(adapter.files[fixture.TARGET]), self.declared['candidate_sha256'])
        self.assertEqual(sha(adapter.files[fixture.BACKUP]), self.declared['baseline_sha256'])
        self.assertLess(adapter.calls.index('BUILD'), adapter.calls.index('TEST'))

    def test_every_host_failure_stops_without_retry_restore_or_cleanup(self):
        probe = FakeAdapter(self.folder)
        with patch('builtins.print'):
            fixture.execute(probe, self.journal('success'), self.declared, self.digest, True)
            for index in range(1, len(probe.calls) + 1):
                with self.subTest(index=index):
                    adapter = FakeAdapter(self.folder, fault=index)
                    journal = self.journal('failure-' + str(index))
                    with self.assertRaises(ValueError):
                        fixture.execute(adapter, journal, self.declared, self.digest, True)
                    self.assertEqual(adapter.calls, probe.calls[:index])
                    self.assertFalse(journal.data['passed'])
                    self.assertEqual(journal.data['steps'][-1]['state'], 'failed')
                    self.assertTrue(journal.data['steps'][-1]['host_effects_may_be_partial'])

    def test_preexisting_filedefs_stop_before_source_creation(self):
        adapter, journal = FakeAdapter(self.folder), self.journal()
        adapter.action = Mock(return_value=completed(['SYSIN DISK EXISTING C A1']))
        with patch('builtins.print'), self.assertRaises(ValueError):
            fixture.execute(adapter, journal, self.declared, self.digest, True)
        self.assertFalse(any(call.startswith('put ') for call in adapter.calls))
        self.assertFalse(journal.data['passed'])

    def test_exact_observed_empty_filedefs_message_is_accepted(self):
        adapter, journal = FakeAdapter(self.folder), self.journal()
        original = adapter.action
        def action(name, marker=None):
            if name == 'FILEDEFS':
                adapter.event(name)
                return completed(['DMSFLD324I No user defined FILEDEFs in effect'])
            return original(name, marker)
        adapter.action = action
        with patch('builtins.print'):
            fixture.execute(adapter, journal, self.declared, self.digest, True)
        self.assertTrue(journal.data['passed'])

    def test_reusable_helper_is_fixed_and_source_verified_by_prepare(self):
        adapter = fixture.LiveAdapter(Mock(), self.journal(), reuse_helper=True)
        self.assertEqual(adapter.builder.name, 'ZM000175')
        self.assertFalse(adapter.builder.verified)
        self.assertEqual(adapter.builder.source, fixture.ROOT / 'ZMCPQUAL.EXEC')

    def test_partial_output_bad_rc_redaction_and_wrong_marker_are_rejected(self):
        for change in ({'cms_rc': 12}, {'ok': False}, {'integrity_verified': False},
                       {'output_complete': False}, {'cms_command_complete': False}, {'redaction_applied': True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                fixture.command_ok({**completed(['PASS']), **change}, marker='PASS')
        with self.assertRaises(ValueError):
            fixture.command_ok(completed(['prefix PASS suffix']), marker='PASS')
        self.assertEqual(fixture.command_ok(completed(['PASS ']), marker='PASS')['cms_rc'], 0)

    def test_fixed_action_allowlist_and_host_guard(self):
        for action in ('BUILD', 'TEST', 'FILEDEFS'):
            self.assertEqual(fixture.action_policy(action), action)
        for action in ('BUILD ZTQUAL', 'CMSCLNK GITC26 PLAIN', 'ERASE ZTQUAL C A1', 'build', None):
            with self.assertRaises(ValueError):
                fixture.action_policy(action)
        source = (fixture.ROOT / 'ZMCPQUAL.EXEC').read_text()
        self.assertIn("if extra <> '' then exit 12", source)
        self.assertNotIn('parse upper arg token cmd', source)
        protocol = (fixture.ROOT / 'ZMCPRUN.EXEC').read_text().split('out.0=0\n', 1)[1]
        self.assertEqual(source.split('out.0=0\n', 1)[1], protocol)
        self.assertTrue(all(len(line) <= 80 for line in source.splitlines()))

    def test_journal_reserves_owner_only_evidence_and_preserves_existing_files(self):
        journal = self.journal()
        path = self.folder / 'evidence.json'
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.journal()
        self.assertEqual(path.read_bytes(), before)
        link = self.folder / 'linked'
        link.symlink_to(path)
        with self.assertRaises(OSError):
            fixture.Journal(link, self.declared, self.digest)

    def test_failed_startup_result_is_retained_in_journal(self):
        journal = self.journal()
        result = {'ok': False, 'outcome': 'startup_transition_timeout', 'actions': ['BEGIN', 'Enter']}
        with patch('builtins.print'), self.assertRaises(fixture.StepFailure):
            journal.step('startup', lambda: fixture.require(result))
        self.assertEqual(json.loads((self.folder / 'evidence.json').read_bytes())['steps'][-1]['result'], result)

    def test_real_adapter_refuses_protected_target_and_changed_baseline_before_transfer(self):
        session = Mock()
        adapter = fixture.LiveAdapter(session, self.journal())
        raw = b'\x40' * 80
        for target in ('GITC26 C G1', 'ZM537EF1 EXEC A1', 'ZVF69FE6 EXEC A1'):
            with self.assertRaises(ValueError):
                adapter.put(target, raw)
        adapter.revalidate_review = Mock()
        adapter.download = Mock(side_effect=ValueError('native hash mismatch'))
        with self.assertRaises(ValueError):
            adapter.put(fixture.TARGET, raw, '0' * 64)
        session._run.assert_not_called()
        session.runner._transfer.assert_not_called()

    def test_partial_transfer_failure_has_no_readback_retry_or_restore(self):
        session = Mock()
        session._run.return_value = {'ok': False, 'message': 'Uncertain transfer'}
        adapter = fixture.LiveAdapter(session, self.journal())
        adapter.command = Mock(return_value=completed(rc=28))
        adapter.download = Mock()
        with self.assertRaises(fixture.StepFailure):
            adapter.put(fixture.TARGET, b'\x40' * 80)
        session._run.assert_called_once()
        adapter.command.assert_called_once_with('STATE ' + fixture.TARGET, rc=28)
        adapter.download.assert_not_called()

    def test_first_replacement_rejects_metadata_change_before_transfer(self):
        session = Mock()
        adapter = fixture.LiveAdapter(session, self.journal())
        adapter.revalidate_review = Mock()
        adapter.review_data = {'replaced_once': False, 'original_cms': {'timestamp': 'before'}}
        adapter.download = Mock(return_value={'cms': {'timestamp': 'changed'}})
        with self.assertRaises(ValueError):
            adapter.put(fixture.TARGET, b'\x40' * 80, '0' * 64)
        session._run.assert_not_called()

    def test_existing_backup_refused_before_transfer(self):
        session = Mock()
        session.runner.run.return_value = completed(rc=0)
        adapter = fixture.LiveAdapter(session, self.journal())
        with self.assertRaises(ValueError):
            adapter.put(fixture.BACKUP, b'\x40' * 80)
        session._run.assert_not_called()

    def test_native_source_rejects_crlf_controls_width_and_nonascii(self):
        for payload in (b'int x;\r\n', b'int x;', b'x' * 81 + b'\n', b'\tint x;\n', b'\xff\n'):
            with self.assertRaises((ValueError, UnicodeError)):
                fixture.native_source(payload)

    def test_local_review_pins_edit_and_operation_and_remains_blocked(self):
        subprocess.run(['git', 'init', '-q', str(self.folder)], check=True)
        session = Session(allow_local_edits=True, download_root=self.folder / 'sources', factory=Mock())
        adapter = fixture.LiveAdapter(session, self.journal())
        baseline = fixture.native_source((fixture.ROOT / 'fixtures/qualification/baseline/ZTQUAL.C').read_bytes())
        records = [baseline[i:i+80] for i in range(0, len(baseline), 80)]
        meta = metadata([f'ZTQUAL C A1 F 80 {len(records)} 1 01/01/00 00:00:00 FIXTURE'], ('ZTQUAL', 'C', 'A1'))
        original = save_snapshot(self.folder / 'sources', self.folder, meta, records, [])
        candidate = fixture.native_source((fixture.ROOT / 'fixtures/qualification/candidate/ZTQUAL.C').read_bytes())
        review = adapter.review(original, candidate)
        receipt = json.loads(Path(review['operation']['operation_file']).read_bytes())
        self.assertFalse(receipt['review_complete'])
        self.assertFalse(receipt['execution_authorized'])
        self.assertIn('operator_writer_exclusion_procedure', receipt['missing_inputs'])
        Path(review['edit']['editable_file']).write_bytes(b'int changed;\n')
        with self.assertRaises(ValueError):
            adapter.revalidate_review()
        session.factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
