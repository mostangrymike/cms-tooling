"""Offline native comparison rejects mismatches without promoting authority."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_zvm_operations as fixtures
from zvm_download import metadata, save_snapshot
from zvm_edit import sha
from zvm_native_review import compare_snapshot


class NativeReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OperationPlanTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.operation = self.fixture.plan()
        self.original = self.fixture.root / self.fixture.snapshot

    def compare(self, snapshot=None, role='baseline', **kwargs):
        snapshot = self.original if snapshot is None else snapshot
        result = compare_snapshot(self.fixture.session.edits, self.fixture.edit['edit_id'],
            self.operation['operation_id'], self.operation['operation_sha256'], snapshot.name,
            sha((snapshot / 'manifest.json').read_bytes()), role, **kwargs)
        self.fixture.session.factory.assert_not_called()
        self.assertIsNone(self.fixture.session.em)
        return result

    def snapshot(self, text='/* ORIGINAL */', target='TEST EXEC A1', recfm='F', width=80,
                 date='01/01/00', label='FIXTURE', records=None):
        if records is None:
            records = [text.encode('cp037').ljust(width, b'\x40')]
        meta = metadata([f'{target} {recfm} {width} {len(records)} 1 {date} 00:00:00 {label}'], tuple(target.split()))
        saved = save_snapshot(self.fixture.root, self.fixture.repo, meta, records, [])
        return Path(saved['snapshot_directory'])

    def test_baseline_equality_preserves_all_host_blockers(self):
        result = self.compare()
        self.assertTrue(result['local_comparison_passed'])
        for key in ('execution_authorized', 'execution_implemented', 'replacement_safe',
                    'host_operations_performed', 'host_provenance_verified',
                    'fresh_host_baseline_verified', 'writer_exclusion_verified', 'backup_recovery_qualified'):
            self.assertIs(result[key], False)
        self.assertEqual(result['blocking_conditions'], json.loads(Path(self.operation['operation_file']).read_bytes())['blocking_conditions'])

    def test_disposable_c_fixture_baseline_edit_candidate_and_backup(self):
        sources = Path(__file__).parent / 'fixtures' / 'qualification'
        baseline = (sources / 'baseline' / 'ZTQUAL.C').read_bytes()
        candidate = (sources / 'candidate' / 'ZTQUAL.C').read_bytes()
        def native(text):
            lines = text.decode('ascii').splitlines()
            self.assertTrue(all(len(line) <= 63 for line in lines))
            return [line.ljust(80).encode('cp037') for line in lines]
        before = self.snapshot(target='ZTQUAL C A1', records=native(baseline))
        self.fixture.edit = self.fixture.session.edits.prepare(before.name)
        Path(self.fixture.edit['editable_file']).write_bytes(candidate)
        self.fixture.source = self.fixture.session.edits.plan(self.fixture.edit['edit_id'])
        self.assertTrue(self.fixture.source['ok'])
        recipe = {'steps': [
            {'name': 'build', 'command': ['CMSCLNK', 'ZTQUAL', 'PLAIN'],
             'inputs': ['ZTQUAL C A1'], 'outputs': [], 'expected_rc': 0,
             'expect': ['CMSCLNK: built ZTQUAL MODULE mode PLAIN']},
            {'name': 'test', 'command': ['ZTQUAL'], 'inputs': ['ZTQUAL C A1'],
             'outputs': [], 'expected_rc': 0, 'expect': ['ZTQUAL CANDIDATE PASS 43']}],
            'writer_exclusion': {'owner': 'synthetic', 'procedure': 'No host evidence',
                                 'evidence_ref': 'synthetic-only', 'disk': 'A1'},
            'rollback': {'snapshot': before.name, 'sha256': self.fixture.source['base_sha256'],
                         'target': 'ZTQUAL C A1', 'procedure': 'No live recovery authority'}}
        self.operation = self.fixture.plan(recipe)
        self.assertTrue(self.operation['ok'])
        self.assertTrue(self.compare(before)['local_comparison_passed'])
        after = self.snapshot(target='ZTQUAL C A1', records=native(candidate))
        result = self.compare(after, 'candidate')
        self.assertEqual(result['native_sha256'], self.fixture.source['candidate_sha256'])
        self.assertIn('output_inventory_not_verified', result['blocking_conditions'])
        backup = self.snapshot(target='ZTQBACK C A1', records=native(baseline))
        self.assertTrue(self.compare(backup, 'backup', backup_target='ZTQBACK C A1')['local_comparison_passed'])

    def test_candidate_and_restore_match_bytes_despite_new_timestamps(self):
        candidate = self.snapshot('/* CHANGED */', date='01/02/00')
        self.assertTrue(self.compare(candidate, 'candidate')['local_comparison_passed'])
        restored = self.snapshot(date='01/03/00')
        self.assertTrue(self.compare(restored, 'restored')['local_comparison_passed'])
        with self.assertRaises(ValueError):
            self.compare(restored, 'baseline')

    def test_original_cannot_pass_as_candidate_or_candidate_as_original(self):
        with self.assertRaises(ValueError):
            self.compare(role='candidate')
        candidate = self.snapshot('/* CHANGED */')
        for role in ('baseline', 'restored'):
            with self.subTest(role=role), self.assertRaises(ValueError):
                self.compare(candidate, role)

    def test_backup_requires_exact_distinct_unprotected_id(self):
        backup = self.snapshot(target='ZTBACK EXEC A1')
        self.assertTrue(self.compare(backup, 'backup', backup_target='ZTBACK EXEC A1')['local_comparison_passed'])
        for target in (None, 'TEST EXEC A1', 'RESULT DATA A1', 'ZM123456 EXEC A1',
                       'ZV123456 EXEC A1', 'ZTBACK EXEC G1', '../X EXEC A1'):
            with self.subTest(target=target), self.assertRaises((ValueError, TypeError)):
                self.compare(backup, 'backup', backup_target=target)
        with self.assertRaises(ValueError):
            self.compare(backup, 'backup', backup_target='OTHER EXEC A1')
        with self.assertRaises(ValueError):
            self.compare(backup_target='ZTBACK EXEC A1')

    def test_backup_cannot_alias_an_external_input(self):
        recipe = copy.deepcopy(self.fixture.recipe)
        recipe['input_hashes'] = {'ZTBACK EXEC A1': 'a' * 64}
        self.operation = self.fixture.plan(recipe)
        with self.assertRaises(ValueError):
            self.compare(self.snapshot(target='ZTBACK EXEC A1'), 'backup', backup_target='ZTBACK EXEC A1')

    def test_changed_identity_format_label_and_bytes_are_rejected(self):
        for kwargs in ({'target': 'OTHER EXEC A1'}, {'target': 'TEST EXEC G1'},
                       {'recfm': 'V'}, {'label': 'OTHER'}, {'text': 'ALTERED'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.compare(self.snapshot(**kwargs), 'restored')

    def test_equal_concatenated_bytes_with_different_record_boundaries_fail(self):
        # Independently valid F40 snapshot, same 80 native bytes as original.
        raw = (self.original / 'records.ebcdic').read_bytes()
        changed = self.snapshot(width=40, records=[raw[:40], raw[40:]])
        self.assertEqual((changed / 'records.ebcdic').read_bytes(), raw)
        with self.assertRaises(ValueError):
            self.compare(changed, 'restored')

    def test_wrong_manifest_hash_stale_operation_and_raw_tampering_fail(self):
        args = [self.fixture.session.edits, self.fixture.edit['edit_id'],
            self.operation['operation_id'], self.operation['operation_sha256'],
            self.original.name, '0' * 64, 'baseline']
        with self.assertRaises(ValueError):
            compare_snapshot(*args)
        path = Path(self.fixture.edit['editable_file'])
        text = path.read_bytes()
        path.write_bytes(b'/* LATER */\n')
        with self.assertRaises(ValueError):
            self.compare()
        path.write_bytes(text)
        (self.original / 'records.ebcdic').write_bytes(b'X' * 80)
        with self.assertRaises(ValueError):
            self.compare()

    def test_protected_and_incomplete_operations_and_disabled_edits_fail(self):
        self.fixture.session.allow_local_edits = False
        with self.assertRaises(ValueError):
            self.compare()
        self.fixture.session.allow_local_edits = True
        self.operation = self.fixture.plan({})
        with self.assertRaises(ValueError):
            self.compare()
        self.fixture.prepare_source('ZM123456', 'A1')
        self.operation = self.fixture.plan()
        self.original = self.fixture.root / self.fixture.snapshot
        with self.assertRaises(ValueError):
            self.compare()

    def test_symlink_and_credential_snapshot_are_rejected(self):
        other = self.snapshot()
        self.fixture.session.secrets.add('ORIGINAL')
        with self.assertRaises(ValueError):
            self.compare(other)
        self.fixture.session.secrets.clear()
        manifest = other / 'manifest.json'
        raw = manifest.read_bytes()
        target = other / 'other.json'
        target.write_bytes(raw)
        manifest.unlink()
        manifest.symlink_to(target)
        with self.assertRaises((ValueError, OSError)):
            self.compare(other)

    def test_comparison_never_mutates_local_artifacts(self):
        def inventory():
            return {str(p): sha(p.read_bytes()) for p in self.fixture.root.rglob('*') if p.is_file()}
        before = inventory()
        self.compare()
        self.assertEqual(before, inventory())

    def test_cli_json_success_and_secret_free_failure(self):
        command = [sys.executable, '-B', str(Path(__file__).with_name('zvm_native_review.py')),
            '--root', str(self.fixture.root), '--edit-id', self.fixture.edit['edit_id'],
            '--operation-id', self.operation['operation_id'], '--operation-sha256', self.operation['operation_sha256'],
            '--snapshot-id', self.original.name, '--snapshot-manifest-sha256',
            sha((self.original / 'manifest.json').read_bytes()), '--role', 'baseline']
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), self.compare())
        command[command.index('--snapshot-id') + 1] = 'PRIVATEINPUT'
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('PRIVATEINPUT', result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)['local_comparison_passed'])


if __name__ == '__main__':
    unittest.main()
