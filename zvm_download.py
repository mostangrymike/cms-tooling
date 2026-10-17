"""Read-only native CMS records to immutable snapshots in a local Git worktree."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import time
import zlib

from zvm_commands import RunnerBridge

SOURCE = Path(__file__).with_name('ZMCPGET.EXEC')
MAX_BYTES = 1048576


def file_id(filename, filetype, filemode):
    values = (filename, filetype, filemode)
    if not all(isinstance(v, str) for v in values):
        raise ValueError('File identifiers must be strings')
    fn, ft, fm = (v.upper() for v in values)
    if not all(re.fullmatch(r'[A-Z0-9@$]{1,8}', v) for v in (fn, ft)) or not re.fullmatch(r'[A-Z][0-9]?', fm):
        raise ValueError('Use literal 1..8 character filename/type and an explicit filemode; no wildcards or options')
    return fn, ft, fm


def reader_command(command):
    if not isinstance(command, str) or any(ord(c) < 32 or ord(c) > 126 for c in command):
        raise ValueError('Reader command must be printable ASCII')
    parts = command.upper().split()
    if len(parts) != 4 or parts[0] not in {'FILEMETA', 'FILEREAD'}:
        raise ValueError('Reader accepts only FILEMETA or FILEREAD with a literal file identifier')
    return ' '.join((parts[0], *file_id(*parts[1:])))


def metadata(records, requested):
    fn, ft, fm = requested
    matches = []
    for record in records:
        parts = record.split()
        if len(parts) >= 10 and parts[:2] == [fn, ft] and re.fullmatch(r'[A-Z][0-9]', parts[2]):
            if not (parts[2] == fm or (len(fm) == 1 and parts[2][0] == fm)):
                raise ValueError('Metadata filemode does not match the requested file')
            if parts[3] not in {'F', 'V'} or not all(p.isdecimal() for p in parts[4:7]):
                raise ValueError('Unsupported record format or malformed LISTFILE metadata')
            lrecl, count, blocks = map(int, parts[4:7])
            if not 0 <= lrecl <= 4096 or not 0 <= count <= 4096 or (parts[3] == 'F' and
                    (lrecl * count > MAX_BYTES or (lrecl == 0 and count > 0))):
                raise ValueError('CMS file exceeds supported capture limits')
            matches.append({'filename': fn, 'filetype': ft, 'filemode': parts[2],
                'recfm': parts[3], 'lrecl': lrecl, 'record_count': count, 'blocks': blocks,
                'date': parts[7], 'time': parts[8], 'disk_label': parts[9],
                'listfile_record': record})
    if len(matches) != 1:
        raise ValueError('Expected exactly one unambiguous LISTFILE LABEL metadata record')
    return matches[0]


def native_records(result, meta):
    if not (result.get('ok') and result.get('cms_rc') == 0 and result.get('integrity_verified')
            and result.get('output_complete') and result.get('cms_command_complete')):
        raise ValueError('File capture did not complete successfully')
    if result.get('redaction_applied'):
        raise ValueError('File contains locally known credentials; no source snapshot will be written')
    if result.get('encoding') != 'cp037':
        raise ValueError('Unsupported native encoding')
    records = [record.encode('cp037') for record in result['records']]
    raw = b''.join(records)
    if (len(records) != meta['record_count'] or len(records) != result['record_count']
            or len(raw) != result['byte_count'] or len(raw) > MAX_BYTES
            or f'{zlib.adler32(raw):08x}' != result['adler32']):
        raise ValueError('Native records do not match metadata and verified capture')
    if any(len(r) != meta['lrecl'] if meta['recfm'] == 'F' else len(r) > meta['lrecl'] for r in records):
        raise ValueError('Captured record lengths do not match CMS RECFM/LRECL')
    if meta['recfm'] == 'V' and records and max(map(len, records)) != meta['lrecl']:
        raise ValueError('Variable file maximum record length does not match CMS metadata')
    return records


def git_root_for(destination):
    """Refuse symlink paths and destinations outside a real Git working tree."""
    root = Path(destination).expanduser().absolute()
    if '..' in root.parts:
        raise ValueError('Download root must not contain parent traversal')
    for part in (root, *root.parents):
        if part.is_symlink():
            raise ValueError('Download root must not traverse symlinks')
    existing = root
    while not existing.exists():
        existing = existing.parent
    if not existing.is_dir():
        raise ValueError('Download root parent is not a directory')
    p = subprocess.run(['git', '-C', str(existing), 'rev-parse', '--show-toplevel'],
                       capture_output=True, text=True, timeout=5, check=False)
    if p.returncode:
        raise ValueError('Download root must be inside an existing local Git worktree')
    worktree = Path(p.stdout.strip()).resolve()
    if not root.is_relative_to(worktree):
        raise ValueError('Download root is outside the Git worktree')
    return root, worktree


def save_snapshot(root, worktree, meta, records, evidence):
    raw = b''.join(records)
    digest = hashlib.sha256(raw).hexdigest()
    # All path components below the configured root are generated internally.
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or root.resolve() != root:
        raise ValueError('Download root changed during capture')
    directory = root / ('snapshot-' + secrets.token_hex(12))
    directory.mkdir(mode=0o700)  # Exclusive: never replace a previous snapshot.
    try:
        payload = directory / 'records.ebcdic'
        with payload.open('xb') as handle:
            handle.write(raw)
        text_records = [r.decode('cp037') for r in records]
        editable = all(all(c.isprintable() or c == '\t' for c in r) for r in text_records)
        text_path = None
        if editable:
            text_path = directory / (meta['filename'] + '.' + meta['filetype'])
            with text_path.open('x', encoding='utf-8', newline='\n') as handle:
                handle.write(''.join(r + '\n' for r in text_records))
        manifest = {'schema': 'zvm-cms-source-snapshot-v1', 'complete': True,
            'cms': meta, 'encoding': 'cp037', 'record_lengths': list(map(len, records)),
            'byte_count': len(raw), 'sha256': digest,
            'records_sha256': [hashlib.sha256(r).hexdigest() for r in records],
            'text_file': text_path.name if text_path else None,
            'text_preserves_trailing_blanks': True, 'verification': evidence,
            'consistency': 'matching metadata before/after and two identical native reads; not an atomic host snapshot'}
        with (directory / 'manifest.json').open('x', encoding='utf-8') as handle:
            json.dump(manifest, handle, indent=2)
            handle.write('\n')
        # Verify bytes and record boundaries from the published local files.
        if payload.read_bytes() != raw or sum(manifest['record_lengths']) != len(raw):
            raise ValueError('Local snapshot byte verification failed')
        return {'snapshot_directory': str(directory), 'manifest': str(directory / 'manifest.json'),
            'native_file': str(payload), 'text_file': str(text_path) if text_path else None,
            'git_worktree': str(worktree), 'git_relative_directory': directory.relative_to(worktree).as_posix(),
            'sha256': digest, 'record_count': len(records), 'byte_count': len(raw),
            'cms': meta, 'local_files_replaced': False, 'host_source_modified': False,
            'download_complete': True, 'integrity_verified': True, 'atomic_host_snapshot': False}
    except BaseException:
        shutil.rmtree(directory)
        raise


class SourceDownloader:
    def __init__(self, session, root=None, runner_name=None):
        self.session = session
        self.root = root
        self.reader = RunnerBridge(session, runner_name, source=SOURCE, policy=reader_command)

    def download(self, filename, filetype, filemode, create_runner=False, timeout=300):
        s = self.session
        with s.lock:
            evidence = []
            try:
                if not s.allow_downloads or not s.allow_commands or not self.root:
                    raise ValueError('Source downloads require --allow-downloads, --allow-commands and --download-root')
                requested = file_id(filename, filetype, filemode)
                if type(timeout) is not int or not 30 <= timeout <= 300 or type(create_runner) is not bool:
                    raise ValueError('timeout must be 30..300 seconds and create_runner must be boolean')
                root, worktree = git_root_for(self.root)
                deadline = time.monotonic() + timeout
                if not self.reader.verified:
                    prepared = self.reader.prepare(create=create_runner,
                        timeout=min(60, max(1, int(deadline - time.monotonic()))))
                    if not prepared['ok']:
                        return {'ok': False, 'download_complete': False, 'stage': 'prepare_reader', **prepared}
                    evidence.append({'stage': 'prepare_reader', **prepared})
                elif create_runner:
                    raise ValueError('A reader is already verified; no new helper will be created')

                def capture(verb, identity):
                    remaining = int(deadline - time.monotonic())
                    if remaining < 1:
                        raise ValueError('Download deadline exceeded')
                    result = self.reader.run(' '.join((verb, *identity)), min(300, remaining))
                    if not result.get('ok') or result.get('cms_rc') != 0 or not result.get('output_complete') or not result.get('integrity_verified'):
                        evidence.append({'stage': verb, **result})
                        raise ValueError('Read-only file capture failed; see sanitized evidence')
                    if result.get('redaction_applied'):
                        raise ValueError('Capture contains locally known credentials; no source snapshot will be written')
                    evidence.append({'stage': verb, **{k: result[k] for k in
                        ('request_id', 'cms_rc', 'record_count', 'byte_count', 'adler32', 'frames_verified', 'output_complete', 'integrity_verified')}})
                    return result

                before = metadata(capture('FILEMETA', requested)['records'], requested)
                # Pin the returned numeric mode; never silently search another disk.
                actual = (before['filename'], before['filetype'], before['filemode'])
                first = native_records(capture('FILEREAD', actual), before)
                second = native_records(capture('FILEREAD', actual), before)
                after = metadata(capture('FILEMETA', actual)['records'], actual)
                if before != after or first != second:
                    raise ValueError('CMS file changed during capture; no source snapshot will be written')
                return {'ok': True, 'reader': self.reader.name,
                        **save_snapshot(root, worktree, before, first, evidence)}
            except Exception as exc:
                return {'ok': False, 'download_complete': False, 'message': s.redact(str(exc)),
                        'reader': self.reader.name, 'evidence': evidence}
