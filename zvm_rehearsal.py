"""Offline transaction failure rehearsal. No host adapter, command execution or writes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from zvm_download import MAX_BYTES, git_root_for
from zvm_edit import canonical, read_file, sha
from zvm_operations import exact_hash, operation_receipt, review_source


def load_review(edits, edit_id, operation_id, operation_sha256):
    """Rebind an exact operation receipt to all current local review artifacts."""
    edits.identifier(edit_id, 'edit')
    edits.identifier(operation_id, 'operation')
    exact_hash(operation_sha256)
    root, _ = edits.context()
    directory = root / 'edits' / edit_id / operation_id
    git_root_for(directory)
    raw = read_file(directory / 'operation.json', 2 * MAX_BYTES)
    if sha(raw) != operation_sha256:
        raise ValueError('Operation review hash does not match')
    receipt = json.loads(raw)
    if len(canonical(receipt['recipe'])) > 65536:
        raise ValueError('Recipe exceeds 64 KiB')
    _, worktree, _, source = review_source(edits, edit_id, receipt['source_plan_id'],
                                         receipt['source_plan_sha256'])
    expected = operation_receipt(source, edit_id, receipt['source_plan_id'],
                                 receipt['source_plan_sha256'], receipt['recipe'], worktree)
    # Byte comparison also rejects duplicate JSON keys and noncanonical forms.
    if canonical(expected) != raw:
        raise ValueError('Operation manifest differs from the revalidated local review')
    if not expected['review_complete']:
        raise ValueError('Complete recipe, writer-exclusion and rollback statements are required for rehearsal')
    if 'protected_source_target' in expected['blocking_conditions']:
        raise ValueError('Protected source targets cannot be used as transaction rehearsal fixtures')
    edits.reject_credentials(raw.decode())
    return expected


def checkpoints(receipt):
    """Ordered synthetic checks. These names are never host commands."""
    points = ['writer_exclusion', 'fresh_baseline', 'backup_readback',
              'external_input_hashes', 'output_absence', 'before_write',
              'replacement_transfer', 'candidate_readback', 'after_readback']
    for step in receipt['recipe']['steps']:
        points.extend('step:' + step['name'] + ':' + boundary for boundary in
                      ('dispatch', 'rc', 'markers', 'outputs'))
    return points + ['final_ready', 'final_inventory']


def model(receipt, operation_sha256, fault=None):
    """A symbolic fail-stop model, not an executor or a host observation.

    Every non-failing boundary is an explicit synthetic assumption. A failure
    records uncertainty and stops immediately, with no retry or automatic restore.
    """
    points = checkpoints(receipt)
    if fault is not None and fault not in points:
        raise ValueError('Unknown rehearsal fault checkpoint')
    report = {'schema': 'zvm-cms-transaction-rehearsal-v1',
        'operation_sha256': operation_sha256, 'target': receipt['target'],
        'baseline_sha256': receipt['expected_original']['sha256'],
        'candidate_sha256': receipt['candidate']['sha256'],
        'synthetic_only': True, 'host_operations_performed': False,
        'execution_authorized': False, 'execution_implemented': False,
        'replacement_safe': False, 'host_state_observed': False,
        'actual_steps_executed': 0, 'automatic_recovery_attempted': False,
        'blocking_conditions': list(receipt['blocking_conditions']),
        'injected_fault': fault, 'events': [], 'modeled_target_state': 'original_unmodified',
        'modeled_outputs_at_risk': [], 'modeled_verified_outputs': [],
        'modeled_completed_steps': [], 'outcome': 'stopped', 'stopped_at': None}
    for point in points:
        if point == 'replacement_transfer':
            report['modeled_target_state'] = 'unknown_or_partial'
        elif point == 'candidate_readback':
            report['modeled_target_state'] = 'candidate_unverified'
        if point.startswith('step:'):
            _, name, boundary = point.split(':')
            step = next(step for step in receipt['recipe']['steps'] if step['name'] == name)
            if boundary == 'dispatch':
                report['modeled_outputs_at_risk'].extend(output['file'] for output in step['outputs'])
        report['events'].append({'checkpoint': point,
                                  'synthetic_result': 'failure' if point == fault else 'assumed_success'})
        if point == fault:
            report['stopped_at'] = point
            report['operator_action_required'] = True
            break
        if point == 'candidate_readback':
            report['modeled_target_state'] = 'candidate_verified'
        if point.startswith('step:') and boundary == 'outputs':
            report['modeled_completed_steps'].append(name)
            outputs = [output['file'] for output in step['outputs']]
            report['modeled_verified_outputs'].extend(outputs)
            report['modeled_outputs_at_risk'] = [file for file in report['modeled_outputs_at_risk'] if file not in outputs]
    else:
        report['outcome'] = 'rehearsal_complete'
        report['operator_action_required'] = False
    report['modeled_target_may_have_changed'] = report['modeled_target_state'] != 'original_unmodified'
    # This is an evidence checklist, not fabricated host evidence.
    report['required_real_evidence'] = ['fresh_native_baseline_and_metadata',
        'verified_native_backup', 'operator_writer_exclusion_and_exact_write_authority',
        'candidate_native_readback', 'nonce_correlated_step_output_and_rc',
        'declared_output_inventory', 'fresh_final_ready_boundary']
    report['evidence_retention_required'] = True
    report['recovery_policy'] = 'Stop; retain evidence and possible partial files. No retry, restore, cleanup or continuation without separate review and authority.'
    return report


def rehearse(edits, edit_id, operation_id, operation_sha256, all_faults=False, fault=None):
    if all_faults and fault is not None:
        raise ValueError('Choose one fault or the full failure matrix')
    receipt = load_review(edits, edit_id, operation_id, operation_sha256)
    scenarios = [None, *checkpoints(receipt)] if all_faults else [fault]
    return {'schema': 'zvm-cms-rehearsal-suite-v1', 'synthetic_only': True,
        'operation_sha256': operation_sha256, 'host_operations_performed': False,
        'execution_authorized': False, 'execution_implemented': False,
        'replacement_safe': False,
        'scenarios': [model(receipt, operation_sha256, scenario) for scenario in scenarios]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--edit-id', required=True)
    parser.add_argument('--operation-id', required=True)
    parser.add_argument('--operation-sha256', required=True)
    faults = parser.add_mutually_exclusive_group()
    faults.add_argument('--fault', help='Exact synthetic checkpoint name')
    faults.add_argument('--all-faults', action='store_true')
    args = parser.parse_args()
    # Session supplies the existing guarded local artifact reader. No factory is
    # called, emulator started, connection made, or server capability enabled.
    from zvm_mcp import Session
    session = Session(allow_local_edits=True, download_root=args.root)
    try:
        result = rehearse(session.edits, args.edit_id, args.operation_id,
                          args.operation_sha256, args.all_faults, args.fault)
    except Exception as exc:
        print(json.dumps({'ok': False, 'error_type': type(exc).__name__,
                          'synthetic_only': True, 'host_operations_performed': False}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
