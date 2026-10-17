"""Local artifact binding and exhaustive symbolic transaction stop tests."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_zvm_operations as fixtures
from zvm_edit import canonical, sha
from zvm_rehearsal import checkpoints, rehearse


class RehearsalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OperationPlanTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.operation = self.fixture.plan()
        self.assertTrue(self.operation['ok'], self.operation)
        self.path = Path(self.operation['operation_file'])
        self.receipt = json.loads(self.path.read_bytes())

    def run_model(self, **kwargs):
        result = rehearse(self.fixture.session.edits, self.fixture.edit['edit_id'],
            self.operation['operation_id'], self.operation['operation_sha256'], **kwargs)
        self.fixture.session.factory.assert_not_called()
        self.assertIsNone(self.fixture.session.em)
        for scenario in result['scenarios']:
            self.assertTrue(scenario['synthetic_only'])
            for key in ('host_operations_performed', 'execution_authorized', 'execution_implemented',
                        'replacement_safe', 'host_state_observed', 'automatic_recovery_attempted'):
                self.assertIs(scenario[key], False)
            self.assertEqual(scenario['actual_steps_executed'], 0)
            self.assertEqual(scenario['operation_sha256'], self.operation['operation_sha256'])
            self.assertEqual(scenario['blocking_conditions'], self.receipt['blocking_conditions'])
        return result

    def test_success_is_explicitly_synthetic_and_does_not_clear_host_gates(self):
        result = self.run_model()['scenarios'][0]
        self.assertEqual(result['outcome'], 'rehearsal_complete')
        self.assertEqual(result['modeled_target_state'], 'candidate_verified')
        self.assertEqual(result['modeled_completed_steps'], ['probe'])
        self.assertEqual(result['modeled_verified_outputs'], ['RESULT DATA A1'])
        self.assertEqual(result['modeled_outputs_at_risk'], [])
        self.assertTrue(all(event['synthetic_result'] == 'assumed_success' for event in result['events']))

    def test_every_fault_stops_at_exact_checkpoint_without_later_events(self):
        points = checkpoints(self.receipt)
        suite = self.run_model(all_faults=True)
        self.assertEqual(len(suite['scenarios']), len(points) + 1)
        for index, result in enumerate(suite['scenarios'][1:]):
            with self.subTest(fault=points[index]):
                self.assertEqual(result['outcome'], 'stopped')
                self.assertEqual(result['stopped_at'], points[index])
                self.assertEqual([e['checkpoint'] for e in result['events']], points[:index + 1])
                self.assertEqual(result['events'][-1]['synthetic_result'], 'failure')
                self.assertTrue(result['operator_action_required'])
                self.assertTrue(result['evidence_retention_required'])

    def test_prewrite_failures_do_not_model_a_write_or_dispatch(self):
        for fault in checkpoints(self.receipt)[:6]:
            with self.subTest(fault=fault):
                result = self.run_model(fault=fault)['scenarios'][0]
                self.assertEqual(result['modeled_target_state'], 'original_unmodified')
                self.assertFalse(result['modeled_target_may_have_changed'])
                self.assertEqual(result['modeled_outputs_at_risk'], [])
                self.assertEqual(result['modeled_completed_steps'], [])

    def test_transfer_and_readback_failures_preserve_uncertainty(self):
        for fault, state in [('replacement_transfer', 'unknown_or_partial'),
                             ('candidate_readback', 'candidate_unverified'),
                             ('after_readback', 'candidate_verified')]:
            result = self.run_model(fault=fault)['scenarios'][0]
            self.assertEqual(result['modeled_target_state'], state)
            self.assertTrue(result['modeled_target_may_have_changed'])
            self.assertEqual(result['modeled_completed_steps'], [])

    def test_step_faults_retain_possible_outputs_without_claiming_success(self):
        for boundary in ('dispatch', 'rc', 'markers', 'outputs'):
            result = self.run_model(fault='step:probe:' + boundary)['scenarios'][0]
            self.assertEqual(result['modeled_target_state'], 'candidate_verified')
            self.assertEqual(result['modeled_outputs_at_risk'], ['RESULT DATA A1'])
            self.assertEqual(result['modeled_completed_steps'], [])
            self.assertEqual(result['modeled_verified_outputs'], [])

    def test_multistep_failure_never_dispatches_a_later_step(self):
        recipe = copy.deepcopy(self.fixture.recipe)
        recipe['steps'].append({'name': 'test', 'command': ['EXEC', 'CHECK'],
            'inputs': ['RESULT DATA A1'], 'outputs': [{'file': 'CHECK DATA A1', 'policy': 'create_only'}],
            'expected_rc': 4, 'expect': ['VERIFIED']})
        operation = self.fixture.plan(recipe)
        result = rehearse(self.fixture.session.edits, self.fixture.edit['edit_id'],
            operation['operation_id'], operation['operation_sha256'], fault='step:probe:rc')['scenarios'][0]
        self.assertNotIn('CHECK DATA A1', result['modeled_outputs_at_risk'])
        result = rehearse(self.fixture.session.edits, self.fixture.edit['edit_id'],
            operation['operation_id'], operation['operation_sha256'], fault='step:test:markers')['scenarios'][0]
        self.assertEqual(result['modeled_completed_steps'], ['probe'])
        self.assertEqual(result['modeled_verified_outputs'], ['RESULT DATA A1'])
        self.assertEqual(result['modeled_outputs_at_risk'], ['CHECK DATA A1'])

    def test_final_checks_can_fail_after_all_steps_without_auto_restore(self):
        for fault in ('final_ready', 'final_inventory'):
            result = self.run_model(fault=fault)['scenarios'][0]
            self.assertEqual(result['modeled_completed_steps'], ['probe'])
            self.assertEqual(result['outcome'], 'stopped')
            self.assertTrue(result['operator_action_required'])

    def test_receipt_tampering_even_with_new_hash_is_rejected(self):
        for field, value in [('target', 'OTHER EXEC A1'), ('review_complete', False),
                             ('execution_authorized', True), ('blocking_conditions', []),
                             ('candidate', {'sha256': 'f' * 64}), ('unexpected', 'extra')]:
            receipt = copy.deepcopy(self.receipt)
            receipt[field] = value
            raw = canonical(receipt)
            self.path.write_bytes(raw)
            with self.subTest(field=field), self.assertRaises((ValueError, KeyError)):
                rehearse(self.fixture.session.edits, self.fixture.edit['edit_id'],
                         self.operation['operation_id'], sha(raw))
        self.path.write_bytes(canonical(self.receipt))

    def test_stale_working_source_candidate_baseline_and_recipe_are_rejected(self):
        files = [Path(self.fixture.edit['editable_file']), Path(self.fixture.source['candidate_file']),
                 Path(self.fixture.edit['definition']).parent / 'baseline.ebcdic', self.path]
        for path in files:
            original = path.read_bytes()
            path.write_bytes(original + b'X')
            with self.subTest(file=path.name), self.assertRaises(ValueError):
                self.run_model()
            path.write_bytes(original)

    def test_noncanonical_and_duplicate_key_receipts_are_refused(self):
        raw = self.path.read_bytes()
        variants = [json.dumps(self.receipt).encode(),
                    raw.replace(b'{', b'{"execution_authorized":true,', 1)]
        for variant in variants:
            self.path.write_bytes(variant)
            with self.subTest(variant=variant[:40]), self.assertRaises(ValueError):
                rehearse(self.fixture.session.edits, self.fixture.edit['edit_id'],
                         self.operation['operation_id'], sha(variant))
        self.path.write_bytes(raw)

    def test_recipe_changes_require_a_new_exact_operation_hash(self):
        receipt = copy.deepcopy(self.receipt)
        receipt['recipe']['steps'][0]['expected_rc'] = 4
        self.path.write_bytes(canonical(receipt))
        with self.assertRaises(ValueError):
            self.run_model()

    def test_unsafe_ids_and_operation_hashes_are_refused(self):
        for edit, operation, digest in [('../outside', self.operation['operation_id'], 'a' * 64),
                (self.fixture.edit['edit_id'], '../outside', 'a' * 64),
                (self.fixture.edit['edit_id'], self.operation['operation_id'], 'A' * 64)]:
            with self.subTest(edit=edit, operation=operation), self.assertRaises(ValueError):
                rehearse(self.fixture.session.edits, edit, operation, digest)

    def test_retained_scratch_source_is_not_a_rehearsal_fixture(self):
        self.fixture.prepare_source('ZV123456', 'A1')
        operation = self.fixture.plan()
        with self.assertRaises(ValueError):
            rehearse(self.fixture.session.edits, self.fixture.edit['edit_id'],
                     operation['operation_id'], operation['operation_sha256'])

    def test_incomplete_and_protected_reviews_are_not_rehearsal_fixtures(self):
        for name, mode, recipe in [('TEST', 'A1', {}), ('ZM123456', 'A1', None),
                                   ('TEST', 'G1', None)]:
            self.fixture.prepare_source(name, mode)
            operation = self.fixture.plan(recipe)
            with self.subTest(name=name, mode=mode), self.assertRaises(ValueError):
                rehearse(self.fixture.session.edits, self.fixture.edit['edit_id'],
                         operation['operation_id'], operation['operation_sha256'])

    def test_wrong_hash_unknown_fault_and_conflicting_options_are_rejected(self):
        with self.assertRaises(ValueError):
            rehearse(self.fixture.session.edits, self.fixture.edit['edit_id'],
                     self.operation['operation_id'], '0' * 64)
        for kwargs in ({'fault': 'unknown'}, {'fault': 'before_write', 'all_faults': True}):
            with self.assertRaises(ValueError):
                self.run_model(**kwargs)

    def test_disabled_local_edits_and_symlinks_are_rejected(self):
        self.fixture.session.allow_local_edits = False
        with self.assertRaises(ValueError):
            self.run_model()
        self.fixture.session.allow_local_edits = True
        original = self.path.read_bytes()
        other = self.path.with_name('other.json')
        other.write_bytes(original)
        self.path.unlink()
        self.path.symlink_to(other)
        with self.assertRaises((ValueError, OSError)):
            self.run_model()

    def test_rehearsal_changes_no_local_artifact(self):
        root = self.fixture.root
        before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        first = self.run_model(all_faults=True)
        self.assertEqual(first, self.run_model(all_faults=True))
        after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_cli_emits_json_matrix_and_does_not_leak_invalid_input(self):
        command = [sys.executable, '-B', str(Path(__file__).with_name('zvm_rehearsal.py')),
            '--root', str(self.fixture.root), '--edit-id', self.fixture.edit['edit_id'],
            '--operation-id', self.operation['operation_id'], '--operation-sha256', self.operation['operation_sha256'],
            '--all-faults']
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), self.run_model(all_faults=True))
        command[command.index('--operation-sha256') + 1] = 'PRIVATEINPUT'
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('PRIVATEINPUT', result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)['ok'])


if __name__ == '__main__':
    unittest.main()
