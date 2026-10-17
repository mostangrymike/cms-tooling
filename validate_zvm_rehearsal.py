"""Validate the offline failure matrix on an isolated disposable local fixture."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from zvm_download import metadata, save_snapshot
from zvm_edit import canonical, sha
from zvm_mcp import Session
from zvm_rehearsal import checkpoints, load_review


def validate():
    def no_terminal():
        raise AssertionError('Rehearsal must never create a terminal')

    with tempfile.TemporaryDirectory(prefix='zvm_rehearsal_') as temp:
        repo = Path(temp).resolve()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        root = repo / 'sources'
        session = Session(allow_local_edits=True, download_root=root, factory=no_terminal)
        meta = metadata(['DEMO EXEC A1 F 80 1 1 01/01/00 00:00:00 FIXTURE'], ('DEMO', 'EXEC', 'A1'))
        snapshot = save_snapshot(root, repo, meta, ['/* ORIGINAL */'.ljust(80).encode('cp037')], [])
        snapshot_id = Path(snapshot['snapshot_directory']).name
        edit = session.edits.prepare(snapshot_id)
        if not edit['ok']:
            raise ValueError('Fixture edit preparation failed')
        Path(edit['editable_file']).write_bytes(b'/* SYNTHETIC CANDIDATE */\n')
        plan = session.edits.plan(edit['edit_id'])
        recipe = {'steps': [
            {'name': 'build', 'command': ['EXEC', 'DEMOBLD'], 'inputs': ['DEMO EXEC A1'],
             'outputs': [{'file': 'DEMO TEXT A1', 'policy': 'create_only'}], 'expected_rc': 0, 'expect': ['BUILT']},
            {'name': 'test', 'command': ['EXEC', 'DEMOTEST'], 'inputs': ['DEMO TEXT A1'],
             'outputs': [], 'expected_rc': 0, 'expect': ['PASS']}],
            'writer_exclusion': {'owner': 'synthetic-fixture', 'procedure': 'Synthetic assumption only',
                                 'evidence_ref': 'no-host-evidence', 'disk': 'A1'},
            'rollback': {'snapshot': snapshot_id, 'sha256': plan['base_sha256'], 'target': 'DEMO EXEC A1',
                         'procedure': 'No real restore authority; synthetic fixture only'}}
        operation = session.operations.plan(edit['edit_id'], plan['plan_id'], plan['plan_sha256'], recipe)
        if not operation['ok']:
            raise ValueError('Fixture operation preparation failed')
        receipt = load_review(session.edits, edit['edit_id'], operation['operation_id'], operation['operation_sha256'])
        before = {str(p.relative_to(root)): sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
        run = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('zvm_rehearsal.py')),
            '--root', str(root), '--edit-id', edit['edit_id'], '--operation-id', operation['operation_id'],
            '--operation-sha256', operation['operation_sha256'], '--all-faults'],
            capture_output=True, text=True, timeout=45, check=True)
        suite = json.loads(run.stdout)
        points = checkpoints(receipt)
        scenarios = suite['scenarios']
        checks = {
            'complete_matrix': len(scenarios) == len(points) + 1,
            'synthetic_success': scenarios[0]['outcome'] == 'rehearsal_complete',
            'exact_fail_stops': all(s['outcome'] == 'stopped' and s['stopped_at'] == point
                and [e['checkpoint'] for e in s['events']] == points[:index + 1]
                and s['operator_action_required'] is True
                for index, (point, s) in enumerate(zip(points, scenarios[1:]))),
            'no_host_or_authority_claims': all(s['synthetic_only'] is True
                and all(s[key] is False for key in ('host_operations_performed', 'execution_authorized',
                    'execution_implemented', 'replacement_safe', 'host_state_observed', 'automatic_recovery_attempted'))
                and s['actual_steps_executed'] == 0 for s in scenarios),
            'operation_hash_pinned': all(s['operation_sha256'] == operation['operation_sha256'] for s in scenarios),
            'host_gates_preserved': all(s['blocking_conditions'] == receipt['blocking_conditions'] for s in scenarios),
            'evidence_retention_required': all(s['evidence_retention_required'] is True for s in scenarios),
            'local_artifacts_unchanged': before == {str(p.relative_to(root)): sha(p.read_bytes())
                for p in root.rglob('*') if p.is_file()},
            'parent_still_disconnected': session.em is None,
        }
        return {'schema': 'zvm-cms-rehearsal-validation-v1', 'passed': all(checks.values()),
                'verification': checks, 'scenario_count': len(scenarios),
                'host_operations_performed': False, 'synthetic_only': True,
                'suite': suite, 'suite_sha256': sha(canonical(suite)),
                'temporary_fixture_retained': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = validate()
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
