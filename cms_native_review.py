"""Compare local native snapshots with a pinned operation. Never access CMS."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from cms_edit import sha
from cms_operations import exact_hash, literal_file
from cms_rehearsal import load_review


def compare_snapshot(edits, edit_id, operation_id, operation_sha256,
                     snapshot_id, snapshot_manifest_sha256, role, backup_target=None):
    """Verify bytes and record layout locally, without trusting host provenance.

    A caller-provided snapshot can be synthetic or stale. A matching comparison
    never establishes a fresh host baseline, backup durability or restore safety.
    """
    if role not in {'baseline', 'backup', 'candidate', 'restored'}:
        raise ValueError('Unknown native comparison role')
    exact_hash(snapshot_manifest_sha256)
    receipt = load_review(edits, edit_id, operation_id, operation_sha256)
    target = receipt['target']
    if role == 'backup':
        target = literal_file(backup_target)
        reserved = {receipt['target'], *receipt['recipe']['input_hashes']}
        for step in receipt['recipe']['steps']:
            reserved.update(step['inputs'])
            reserved.update(output['file'] for output in step['outputs'])
        if (not target.endswith(' A1') or target in reserved
                or re.fullmatch(r'Z[MV][0-9A-F]{6}', target.split()[0])):
            raise ValueError('Backup must use a distinct unprotected A1 file ID outside recipe files')
    elif backup_target is not None:
        raise ValueError('An explicit backup target is valid only for the backup role')
    root, _ = edits.context()
    manifest_bytes, raw, manifest, _ = edits.snapshot(root, snapshot_id)
    if sha(manifest_bytes) != snapshot_manifest_sha256:
        raise ValueError('Snapshot manifest hash differs from the explicit comparison request')
    cms = manifest['cms']
    actual_target = literal_file(' '.join(cms[key] for key in ('filename', 'filetype', 'filemode')))
    original = receipt['expected_original']
    expected = receipt['candidate'] if role == 'candidate' else original
    format_meta = receipt['candidate'] if role == 'candidate' else original['cms']
    if (actual_target != target or manifest['sha256'] != expected['sha256']
            or manifest['record_lengths'] != expected['record_lengths']
            or any(cms[key] != format_meta[key] for key in ('recfm', 'lrecl'))
            or cms['disk_label'] != original['cms']['disk_label']):
        raise ValueError('Snapshot identity, native bytes, record layout or disk label differs from review')
    # Only a prewrite baseline requires unchanged original metadata. Successful
    # writes/restores can change timestamps and allocation while preserving bytes.
    if role == 'baseline' and cms != original['cms']:
        raise ValueError('Baseline metadata differs from the reviewed original')
    return {'schema': 'cms-native-comparison-v1', 'local_comparison_passed': True,
        'role': role, 'target': target, 'operation_target': receipt['target'],
        'operation_sha256': operation_sha256, 'snapshot_id': snapshot_id,
        'snapshot_manifest_sha256': snapshot_manifest_sha256,
        'native_sha256': sha(raw), 'record_lengths': manifest['record_lengths'],
        'byte_count': len(raw), 'host_operations_performed': False,
        'execution_authorized': False, 'execution_implemented': False,
        'replacement_safe': False, 'host_provenance_verified': False,
        'fresh_host_baseline_verified': False, 'writer_exclusion_verified': False,
        'backup_recovery_qualified': False,
        'blocking_conditions': list(receipt['blocking_conditions']),
        'limitation': 'Local artifact equality only; freshness, host provenance, writer exclusion and recovery authority require separate evidence.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--edit-id', required=True)
    parser.add_argument('--operation-id', required=True)
    parser.add_argument('--operation-sha256', required=True)
    parser.add_argument('--snapshot-id', required=True)
    parser.add_argument('--snapshot-manifest-sha256', required=True)
    parser.add_argument('--role', required=True, choices=('baseline', 'backup', 'candidate', 'restored'))
    parser.add_argument('--backup-target')
    parser.add_argument('--credential-file', help='Optional local owner-only file for credential rejection')
    args = parser.parse_args()
    # Construct only the local artifact reader; never start an emulator.
    from cms_mcp import Session
    from cms_credentials import FileCredentialProvider
    provider = FileCredentialProvider(args.credential_file) if args.credential_file else None
    session = Session(allow_local_edits=True, download_root=args.root, credential_provider=provider)
    try:
        result = compare_snapshot(session.edits, args.edit_id, args.operation_id,
            args.operation_sha256, args.snapshot_id, args.snapshot_manifest_sha256,
            args.role, args.backup_target)
    except Exception as exc:
        # Invalid source/JSON may contain secrets. Do not echo exception text.
        print(json.dumps({'local_comparison_passed': False, 'error_type': type(exc).__name__,
                          'host_operations_performed': False, 'execution_authorized': False,
                          'execution_implemented': False, 'replacement_safe': False}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
