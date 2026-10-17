"""Exact retained MODULE native reader, independent of source edit/download limits."""
from __future__ import annotations

import json
from pathlib import Path
import re
import secrets
import time
import zlib

from cms_commands import RunnerBridge
from cms_download import git_root_for
from cms_edit import read_file, sha

TARGET = 'ZTQUAL MODULE A1'
SOURCE = Path(__file__).with_name('ZMCPOUT.EXEC')


def policy(command):
    if command not in ('FILEMETA ' + TARGET, 'FILEREAD ' + TARGET):
        raise ValueError('Only exact retained ZTQUAL MODULE A1 reads are supported')
    return command


def module_metadata(records):
    matching = [row for row in records if row.split()[:2] == ['ZTQUAL', 'MODULE']]
    if len(matching) != 1:
        raise ValueError('Exact MODULE metadata missing or ambiguous')
    parts = matching[0].split()
    if len(parts) != 10 or parts[:6] != ['ZTQUAL', 'MODULE', 'A1', 'V', '52312', '3'] or parts[9] != 'MNT191':
        raise ValueError('MODULE geometry/identity differs from the observed V52312/3 fixture')
    if not parts[6].isdecimal():
        raise ValueError('Malformed MODULE block count')
    return {'filename': 'ZTQUAL', 'filetype': 'MODULE', 'filemode': 'A1',
            'recfm': 'V', 'lrecl': 52312, 'record_count': 3, 'blocks': int(parts[6]),
            'date': parts[7], 'time': parts[8], 'disk_label': parts[9],
            'listfile_record': matching[0]}


def unpack(result):
    if (result.get('ok') is not True or result.get('cms_rc') != 0
            or result.get('output_complete') is not True or result.get('integrity_verified') is not True
            or result.get('cms_command_complete') is not True or result.get('redaction_applied')
            or result.get('encoding') != 'cp037'):
        raise ValueError('Complete unredacted native MODULE capture required')
    records = [row.encode('cp037') for row in result['records']]
    packed = b''.join(records)
    if (not records or len(records) != result['record_count'] or len(packed) != result['byte_count']
            or f'{zlib.adler32(packed):08x}' != result['adler32']):
        raise ValueError('Packed native MODULE checksum/count mismatch')
    match = re.fullmatch(r'ZMO1 3 ([0-9]{1,5}) ([0-9]{1,5}) ([0-9]{1,5})', result['records'][0])
    if not match:
        raise ValueError('Native MODULE logical-record layout missing')
    lengths = list(map(int, match.groups()))
    raw = b''.join(records[1:])
    if (max(lengths) != 52312 or sum(lengths) != len(raw)
            or any(not 0 <= length <= 52312 for length in lengths)
            or any(len(record) != 4096 for record in records[1:-1])
            or not 1 <= len(records[-1]) <= 4096):
        raise ValueError('Native MODULE chunk/record boundaries differ')
    offset = 0
    original = []
    for length in lengths:
        original.append(raw[offset:offset + length])
        offset += length
    return original


def retained_outputs(path, expected, prior_hash=None):
    """Revalidate the completed local native outputs; never call them fresh reads."""
    raw = read_file(path, 64 * 1048576)
    if sha(raw) != expected:
        raise ValueError('Completed-output journal hash differs')
    journal = json.loads(raw)
    from cms_edit import canonical, validate_manifest
    if prior_hash is not None and journal.get('prior_evidence_sha256') != prior_hash:
        raise ValueError('Completed outputs belong to a different prior fixture run')
    if sha(canonical(journal['contract'])) != journal['contract_sha256']:
        raise ValueError('Completed-output contract hash differs')
    from validate_cms_fixture import contract
    current = contract()
    if any(journal['contract'].get(key) != current[key] for key in
           ('target', 'backup', 'baseline_sha256', 'candidate_sha256')):
        raise ValueError('Completed outputs belong to a different fixture contract')
    results = {}
    for ft in ('ASSEMBLE', 'TEXT', 'LISTING'):
        target = f'ZTQUAL {ft} A1'
        steps = [step for step in journal['steps'] if step['step'] == 'audit native output ' + target]
        if len(steps) != 1 or steps[0]['state'] != 'complete':
            raise ValueError('Prior completed native output missing')
        result = steps[0]['result']
        manifest_raw = read_file(Path(result['manifest']), 2 * 1048576)
        native = read_file(Path(result['native_file']), 1048576)
        manifest, _ = validate_manifest(manifest_raw, native)
        if (result.get('ok') is not True or result.get('download_complete') is not True
                or result.get('integrity_verified') is not True
                or sha(manifest_raw) != result['manifest_sha256'] or sha(native) != result['sha256']
                or ' '.join(manifest['cms'][k] for k in ('filename', 'filetype', 'filemode')) != target
                or manifest['cms']['disk_label'] != 'MNT191'):
            raise ValueError('Retained native output identity/hash differs')
        results[target] = {**result, 'reused_local_evidence': True, 'fresh_host_read': False}
    return results


class ModuleReader:
    def __init__(self, session, root, name=None):
        self.s = session
        self.root = root
        self.reader = RunnerBridge(session, name=name, source=SOURCE, policy=policy)
        self.reader.max_timeout = 600

    def download(self):
        from validate_cms_fixture import command_ok
        s = self.s
        evidence = []
        directory = None
        with s.lock:
            try:
                if not s.allow_downloads or not s.allow_commands or not self.reader.verified:
                    raise ValueError('MODULE reader must be explicitly source-verified first')
                root, worktree = git_root_for(self.root)
                deadline = time.monotonic() + 1500
                def capture(verb):
                    remaining = int(deadline - time.monotonic())
                    if remaining < 1:
                        raise ValueError('MODULE audit deadline exceeded')
                    result = self.reader.run(verb + ' ' + TARGET, min(600, remaining))
                    evidence.append({'stage': verb, **result})
                    command_ok(result)
                    return result
                before = module_metadata(capture('FILEMETA')['records'])
                first = unpack(capture('FILEREAD'))
                second = unpack(capture('FILEREAD'))
                after = module_metadata(capture('FILEMETA')['records'])
                if before != after or first != second:
                    raise ValueError('Native MODULE changed during capture')
                raw = b''.join(first)
                root.mkdir(parents=True, exist_ok=True)
                if root.is_symlink() or root.resolve() != root:
                    raise ValueError('Output root changed during capture')
                directory = root / ('output-' + secrets.token_hex(12))
                directory.mkdir(mode=0o700)
                native = directory / 'records.ebcdic'
                with native.open('xb') as handle:
                    handle.write(raw)
                manifest = {'schema': 'cms-fixed-fixture-output-v1', 'complete': True,
                    'cms': before, 'encoding': 'cp037', 'record_lengths': list(map(len, first)),
                    'sha256': sha(raw), 'byte_count': len(raw),
                    'records_sha256': [sha(record) for record in first],
                    'consistency': 'two identical native reads and matching metadata; not atomic',
                    'source_editing_supported': False}
                manifest_path = directory / 'manifest.json'
                with manifest_path.open('x') as handle:
                    json.dump(manifest, handle, indent=2)
                    handle.write('\n')
                if native.read_bytes() != raw:
                    raise ValueError('Local native output verification failed; retain partial output')
                return {'ok': True, 'download_complete': True, 'integrity_verified': True,
                        'sha256': sha(raw), 'cms': before, 'record_count': len(first), 'byte_count': len(raw),
                        'manifest': str(manifest_path), 'manifest_sha256': sha(manifest_path.read_bytes()),
                        'native_file': str(native), 'snapshot_directory': str(directory),
                        'record_lengths': list(map(len, first)), 'atomic_host_snapshot': False,
                        'source_editing_supported': False, 'host_source_modified': False,
                        'evidence': [{k: item[k] for k in ('stage', 'request_id', 'cms_rc',
                            'record_count', 'byte_count', 'adler32', 'frames_verified',
                            'output_complete', 'integrity_verified')} for item in evidence]}
            except Exception as exc:
                return {'ok': False, 'download_complete': False, 'message': s.redact(str(exc)),
                        'reader': self.reader.name, 'evidence': evidence,
                        'partial_local_output': str(directory) if directory else None}
