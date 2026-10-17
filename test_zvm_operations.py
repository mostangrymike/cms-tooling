"""Offline transaction review binding, dependency and authority regression tests."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from zvm_download import metadata, save_snapshot
from zvm_mcp import Session
from zvm_operations import literal_file


class OperationPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        self.root = self.repo / 'sources'
        self.session = Session(allow_local_edits=True, download_root=self.root,
                               factory=Mock(side_effect=AssertionError('No terminal allowed')))
        self.prepare_source()

    def prepare_source(self, name='TEST', mode='A1'):
        meta = metadata([f'{name} EXEC {mode} F 80 1 1 01/01/00 00:00:00 FIXTURE'], (name, 'EXEC', mode))
        out = save_snapshot(self.root, self.repo, meta, ['/* ORIGINAL */'.ljust(80).encode('cp037')], [])
        self.snapshot = Path(out['snapshot_directory']).name
        self.edit = self.session.edits.prepare(self.snapshot)
        Path(self.edit['editable_file']).write_bytes(b'/* CHANGED */\n')
        self.source = self.session.edits.plan(self.edit['edit_id'])
        self.assertTrue(self.source['ok'], self.source)
        self.target = f'{name} EXEC {mode}'
        self.recipe = {'steps': [{'name': 'probe', 'command': ['EXEC', name],
            'inputs': [self.target], 'outputs': [{'file': 'RESULT DATA A1', 'policy': 'create_only'}],
            'expected_rc': 0, 'expect': ['EXPECTED MARKER']}],
            'writer_exclusion': {'owner': 'operator', 'procedure': 'Stop other writers during the reviewed window',
                                 'evidence_ref': 'operator-record-1', 'disk': mode},
            'rollback': {'snapshot': self.snapshot, 'sha256': self.source['base_sha256'],
                         'target': self.target, 'procedure': 'Restore only under separate exact authorization'}}

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, recipe=None, plan_hash=None):
        result = self.session.operations.plan(self.edit['edit_id'], self.source['plan_id'],
            plan_hash or self.source['plan_sha256'], self.recipe if recipe is None else recipe)
        self.session.factory.assert_not_called()
        self.assertIsNone(self.session.em)
        return result

    def test_complete_review_is_hashed_and_never_authorizes_execution(self):
        result = self.plan()
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['review_complete'])
        self.assertFalse(result['execution_authorized'])
        self.assertFalse(result['execution_implemented'])
        self.assertFalse(result['host_operations_performed'])
        self.assertFalse(result['replacement_safe'])
        raw = Path(result['operation_file']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), result['operation_sha256'])
        receipt = json.loads(raw)
        self.assertEqual(receipt['source_plan_sha256'], self.source['plan_sha256'])
        self.assertEqual(receipt['candidate']['sha256'], self.source['candidate_sha256'])
        self.assertFalse(receipt['writer_exclusion_verified'])
        self.assertIn('command_semantics_not_verified', receipt['blocking_conditions'])

    def test_incomplete_recipe_reports_missing_inputs(self):
        result = self.plan({})
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['review_complete'])
        self.assertEqual(result['missing_inputs'], ['build_test_recipe', 'operator_writer_exclusion_procedure', 'rollback_procedure'])
        recipe = copy.deepcopy(self.recipe)
        recipe['steps'][0]['inputs'] = []
        self.assertIn('source_not_consumed_by_recipe', self.plan(recipe)['missing_inputs'])

    def test_wrong_plan_hash_and_unsafe_identifiers_do_not_write(self):
        self.assertFalse(self.plan(plan_hash='0' * 64)['ok'])
        for value in ('../outside', 'edit-INVALID'):
            result = self.session.operations.plan(value, self.source['plan_id'], self.source['plan_sha256'], {})
            self.assertFalse(result['ok'])
        self.assertEqual(list(self.root.glob('edits/*/operation-*')), [])

    def test_modified_artifacts_are_refused_without_new_manifest(self):
        edit_dir = Path(self.edit['definition']).parent
        snapshot_dir = self.root / self.snapshot
        for path in (Path(self.source['candidate_file']), Path(self.source['diff_file']),
                     Path(self.edit['editable_file']), edit_dir / 'baseline.ebcdic',
                     edit_dir / 'baseline-manifest.json', snapshot_dir / 'manifest.json'):
            with self.subTest(artifact=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b'CHANGED')
                self.assertFalse(self.plan()['ok'])
                path.write_bytes(original)
        self.assertEqual(list(edit_dir.glob('operation-*')), [])

    def test_duplicate_outputs_and_input_overwrite_are_refused(self):
        for output in ('TEST EXEC A1', 'RESULT DATA G1', 'ZM123456 EXEC A1', 'ZV123456 EXEC A1'):
            recipe = copy.deepcopy(self.recipe)
            recipe['steps'][0]['outputs'][0]['file'] = output
            self.assertFalse(self.plan(recipe)['ok'])
        recipe = copy.deepcopy(self.recipe)
        recipe['steps'][0]['outputs'] *= 2
        self.assertFalse(self.plan(recipe)['ok'])

    def test_dependency_order_and_external_input_hashes(self):
        recipe = copy.deepcopy(self.recipe)
        recipe['steps'].append({'name': 'consume', 'command': ['EXEC', 'CHECK'],
            'inputs': ['RESULT DATA A1'], 'outputs': [], 'expected_rc': 0, 'expect': ['DONE']})
        self.assertTrue(self.plan(recipe)['ok'])
        recipe['steps'].reverse()
        self.assertFalse(self.plan(recipe)['ok'])
        recipe = copy.deepcopy(self.recipe)
        recipe['steps'][0]['inputs'].append('EXTERNAL DATA D1')
        result = self.plan(recipe)
        self.assertIn('input_hash:EXTERNAL DATA D1', result['missing_inputs'])
        recipe['input_hashes'] = {'EXTERNAL DATA D1': 'a' * 64}
        self.assertTrue(self.plan(recipe)['review_complete'])

    def test_injection_and_administrative_commands_are_refused(self):
        for command in (['CP', 'IPL', 'CMS'], ['ERASE', 'TEST'], ['EXEC', 'TEST#LOGOFF'],
                        ['EXEC', 'TEST\n'], ['EXEC', '*'], ['EXEC TEST'], ['EXEC', 'A|B'], ['EXEC', '"TEST"'],
                        ['EXEC', 'X' * 64, 'Y' * 64, 'Z' * 64]):
            recipe = copy.deepcopy(self.recipe)
            recipe['steps'][0]['command'] = command
            self.assertFalse(self.plan(recipe)['ok'])

    def test_invalid_recipe_shapes_and_boolean_rc_are_refused(self):
        for key, value in (('expected_rc', True), ('inputs', ['TEST EXEC A']),
                           ('outputs', [{'file': 'RESULT DATA A1', 'policy': 'replace'}]),
                           ('expect', ['UNSAFE\nMARKER']), ('name', '../step')):
            recipe = copy.deepcopy(self.recipe)
            recipe['steps'][0][key] = value
            self.assertFalse(self.plan(recipe)['ok'])
        self.assertFalse(self.plan({'arbitrary': 'value'})['ok'])

    def test_writer_scope_and_rollback_binding_must_match(self):
        for section, key, value in (('writer_exclusion', 'disk', 'G1'),
                                    ('rollback', 'target', 'OTHER EXEC A1'),
                                    ('rollback', 'sha256', '0' * 64)):
            recipe = copy.deepcopy(self.recipe)
            recipe[section][key] = value
            self.assertFalse(self.plan(recipe)['ok'])

    def test_helper_and_protected_disk_sources_remain_blocked(self):
        for name, mode in (('ZM123456', 'A1'), ('TEST', 'G1')):
            self.prepare_source(name, mode)
            result = self.plan()
            self.assertTrue(result['ok'], result)
            self.assertIn('protected_source_target', result['blocking_conditions'])
            self.assertFalse(result['execution_authorized'])

    def test_credentials_in_recipe_are_not_written_or_returned(self):
        self.session.secrets.add('PRIVATEVALUE')
        recipe = copy.deepcopy(self.recipe)
        recipe['writer_exclusion']['procedure'] = 'PRIVATEVALUE'
        result = self.plan(recipe)
        self.assertFalse(result['ok'])
        self.assertNotIn('PRIVATEVALUE', json.dumps(result))

    def test_failure_cleans_only_new_directory_and_preserves_prior_review(self):
        previous = self.plan()
        original = Path(previous['operation_file']).read_bytes()
        with patch.object(self.session.edits, 'write', side_effect=PermissionError('synthetic write failure')):
            self.assertFalse(self.plan()['ok'])
        self.assertEqual(Path(previous['operation_file']).read_bytes(), original)
        self.assertEqual(len(list(Path(self.edit['definition']).parent.glob('operation-*'))), 1)

    def test_collision_preserves_previous_manifest(self):
        with patch('zvm_operations.secrets.token_hex', return_value='0' * 24):
            previous = self.plan()
            raw = Path(previous['operation_file']).read_bytes()
            self.assertFalse(self.plan()['ok'])
            self.assertEqual(Path(previous['operation_file']).read_bytes(), raw)

    def test_disabled_planner_has_no_local_or_terminal_effect(self):
        self.session.allow_local_edits = False
        self.assertFalse(self.plan()['ok'])
        self.assertEqual(list(self.root.glob('edits/*/operation-*')), [])

    def test_file_ids_are_literal_and_numeric(self):
        self.assertEqual(literal_file('test exec a1'), 'TEST EXEC A1')
        for value in ('TEST EXEC A', '* EXEC A1', 'TOOLONGID EXEC A1', 'TEST EXEC A1 EXTRA',
                      'TEST\nEXEC A1', 'TEST\tEXEC A1'):
            with self.assertRaises(ValueError):
                literal_file(value)


if __name__ == '__main__':
    unittest.main()
