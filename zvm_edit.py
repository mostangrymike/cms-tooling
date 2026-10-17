"""Offline CMS source edit workspaces and review-only upload plans. No terminal API."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat

from zvm_download import MAX_BYTES, file_id, git_root_for, metadata

MAX_RECORDS = 4096
MAX_TEXT = 4 * MAX_BYTES + MAX_RECORDS


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return (json.dumps(data, sort_keys=True, indent=2) + '\n').encode('utf-8')


def read_file(path, limit):
    """Bounded regular-file reads; never follow symlinks or block on FIFOs."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('Expected a bounded regular source artifact')
        with os.fdopen(fd, 'rb') as handle:
            fd = None
            data = handle.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Source artifact exceeds its size limit')
        return data
    finally:
        if fd is not None:
            os.close(fd)


def records_from(raw, lengths):
    if (not isinstance(lengths, list) or len(lengths) > MAX_RECORDS
            or any(type(n) is not int or not 0 <= n <= 4096 for n in lengths)
            or sum(lengths) != len(raw) or len(raw) > MAX_BYTES):
        raise ValueError('Invalid native record boundaries')
    result = []
    offset = 0
    for length in lengths:
        result.append(raw[offset:offset + length])
        offset += length
    return result


def validate_manifest(manifest_bytes, raw):
    m = json.loads(manifest_bytes)
    if m.get('schema') != 'zvm-cms-source-snapshot-v1' or m.get('complete') is not True or m.get('encoding') != 'cp037':
        raise ValueError('Unsupported or incomplete source snapshot')
    cms = m['cms']
    identity = file_id(cms['filename'], cms['filetype'], cms['filemode'])
    if len(identity[2]) != 2 or metadata([cms['listfile_record']], identity) != cms:
        raise ValueError('Snapshot CMS metadata is inconsistent')
    records = records_from(raw, m['record_lengths'])
    if (m['sha256'] != sha(raw) or m['byte_count'] != len(raw)
            or cms['record_count'] != len(records)
            or m['records_sha256'] != [sha(record) for record in records]):
        raise ValueError('Snapshot hashes or counts do not match native records')
    if any(len(r) != cms['lrecl'] if cms['recfm'] == 'F' else len(r) > cms['lrecl'] for r in records):
        raise ValueError('Snapshot record lengths do not match RECFM/LRECL')
    if cms['recfm'] == 'V' and records and max(map(len, records)) != cms['lrecl']:
        raise ValueError('Snapshot variable maximum length differs from metadata')
    return m, records


def text_records(records, fixed=False):
    result = []
    for record in records:
        text = record.decode('cp037')
        if not all(c.isprintable() or c == '\t' for c in text):
            raise ValueError('Binary/control-containing records cannot use the text editor')
        result.append(text.rstrip(' ') if fixed else text)
    return result


def encode_edit(text_bytes, cms):
    text = text_bytes.decode('utf-8')
    if text and not text.endswith('\n'):
        raise ValueError('Editable text must end with LF; an empty file represents zero records')
    lines = text[:-1].split('\n') if text else []
    if len(lines) > MAX_RECORDS:
        raise ValueError('Edited source exceeds 4096 records')
    records = []
    for number, line in enumerate(lines, 1):
        if not all(c.isprintable() or c == '\t' for c in line):
            raise ValueError(f'Record {number} contains controls or a non-LF line separator')
        try:
            record = line.encode('cp037', errors='strict')
        except UnicodeEncodeError:
            raise ValueError(f'Record {number} contains characters outside cp037') from None
        if len(record) > cms['lrecl']:
            raise ValueError(f'Record {number} exceeds original LRECL {cms["lrecl"]}; no truncation allowed')
        if cms['recfm'] == 'F':
            record = record.ljust(cms['lrecl'], b'\x40')
        records.append(record)
    if sum(map(len, records)) > MAX_BYTES:
        raise ValueError('Edited source exceeds 1 MiB')
    return records


class SourceEdits:
    def __init__(self, session):
        self.session = session

    def context(self):
        s = self.session
        if not s.allow_local_edits or not s.downloader.root:
            raise ValueError('Local edits require --allow-local-edits and --download-root')
        # Local operations must redact credentials even without any host login.
        if s.credential_provider is not None:
            credentials = s.credential_provider.load()
            s.secrets.update((credentials.userid, credentials.password))
        return git_root_for(s.downloader.root)

    def reject_credentials(self, *texts):
        for text in texts:
            if self.session.redact(text) != text:
                raise ValueError('Source artifact contains credentials; no edit artifact will be written')

    @staticmethod
    def identifier(value, prefix):
        if not isinstance(value, str) or not re.fullmatch(prefix + r'-[0-9a-f]{24}', value):
            raise ValueError('Use an exact generated snapshot/edit identifier, not a path')
        return value

    def snapshot(self, root, snapshot):
        self.identifier(snapshot, 'snapshot')
        directory = root / snapshot
        git_root_for(directory)
        manifest_bytes = read_file(directory / 'manifest.json', 2 * MAX_BYTES)
        raw = read_file(directory / 'records.ebcdic', MAX_BYTES)
        manifest, records = validate_manifest(manifest_bytes, raw)
        self.reject_credentials(manifest_bytes.decode('utf-8'), raw.decode('cp037'))
        return manifest_bytes, raw, manifest, records

    @staticmethod
    def write(directory, name, data):
        with (directory / name).open('xb') as handle:
            handle.write(data)

    def prepare(self, snapshot):
        with self.session.lock:
            directory = None
            try:
                root, worktree = self.context()
                source_manifest, raw, manifest, records = self.snapshot(root, snapshot)
                cms = manifest['cms']
                lines = text_records(records, fixed=cms['recfm'] == 'F')
                editable = ''.join(line + '\n' for line in lines).encode('utf-8')
                # Prove removing visual F-record padding is reversible.
                if encode_edit(editable, cms) != records:
                    raise ValueError('Editable representation is not lossless')
                parent = root / 'edits'
                git_root_for(parent)
                parent.mkdir(exist_ok=True)
                edit_id = 'edit-' + secrets.token_hex(12)
                new_directory = parent / edit_id
                new_directory.mkdir(mode=0o700)
                directory = new_directory
                (directory / 'working').mkdir(mode=0o700)
                filename = cms['filename'] + '.' + cms['filetype']
                definition = {'schema': 'zvm-cms-local-edit-v1', 'snapshot': snapshot,
                    'source_manifest_sha256': sha(source_manifest), 'base_sha256': sha(raw),
                    'base_record_lengths': list(map(len, records)), 'cms': cms,
                    'editable_file': 'working/' + filename, 'encoding': 'cp037',
                    'text_convention': 'LF-terminated records; F records padded with native blanks; V trailing blanks preserved'}
                self.write(directory, 'baseline.ebcdic', raw)
                self.write(directory, 'baseline-manifest.json', source_manifest)
                self.write(directory / 'working', filename, editable)
                self.write(directory, 'edit.json', canonical(definition))
                return {'ok': True, 'edit_id': edit_id, 'editable_file': str(directory / 'working' / filename),
                    'definition': str(directory / 'edit.json'), 'base_sha256': sha(raw),
                    'record_count': len(records), 'cms': cms, 'git_worktree': str(worktree),
                    'host_operations_performed': False, 'upload_authorized': False}
            except Exception as exc:
                if directory is not None and directory.exists():
                    shutil.rmtree(directory)
                return {'ok': False, 'message': self.session.redact(str(exc)), 'host_operations_performed': False}

    def plan(self, edit_id):
        with self.session.lock:
            directory = None
            try:
                root, worktree = self.context()
                self.identifier(edit_id, 'edit')
                edit = root / 'edits' / edit_id
                git_root_for(edit)
                definition_bytes = read_file(edit / 'edit.json', 2 * MAX_BYTES)
                d = json.loads(definition_bytes)
                if d.get('schema') != 'zvm-cms-local-edit-v1' or d.get('encoding') != 'cp037':
                    raise ValueError('Unsupported edit definition')
                source_manifest, raw, manifest, original = self.snapshot(root, d['snapshot'])
                cms = manifest['cms']
                filename = cms['filename'] + '.' + cms['filetype']
                if (d['source_manifest_sha256'] != sha(source_manifest) or d['base_sha256'] != sha(raw)
                        or d['base_record_lengths'] != manifest['record_lengths'] or d['cms'] != cms
                        or d['editable_file'] != 'working/' + filename
                        or read_file(edit / 'baseline.ebcdic', MAX_BYTES) != raw
                        or read_file(edit / 'baseline-manifest.json', 2 * MAX_BYTES) != source_manifest):
                    raise ValueError('Original snapshot or edit baseline changed; recreate the local edit')
                git_root_for(edit / 'working')
                editable = read_file(edit / 'working' / filename, MAX_TEXT)
                text = editable.decode('utf-8')
                self.reject_credentials(definition_bytes.decode('utf-8'), text)
                proposed = encode_edit(editable, cms)
                candidate = b''.join(proposed)
                lengths = list(map(len, proposed))
                old_text = text_records(original, fixed=cms['recfm'] == 'F')
                new_text = text_records(proposed, fixed=cms['recfm'] == 'F')
                diff = ''.join(difflib.unified_diff([r + '\n' for r in old_text],
                    [r + '\n' for r in new_text], fromfile='original/' + filename,
                    tofile='proposed/' + filename)).encode('utf-8')
                changes = [{'operation': tag, 'old_start': a + 1, 'old_count': b - a,
                    'new_start': c + 1, 'new_count': e - c} for tag, a, b, c, e in
                    difflib.SequenceMatcher(a=original, b=proposed, autojunk=False).get_opcodes() if tag != 'equal']
                self.reject_credentials(candidate.decode('cp037'))
                plan = {'schema': 'zvm-cms-upload-review-v1', 'edit_id': edit_id,
                    'source_snapshot': d['snapshot'], 'source_manifest_sha256': sha(source_manifest),
                    'edit_definition_sha256': sha(definition_bytes), 'edited_text_sha256': sha(editable),
                    'expected_original': {'cms': cms, 'sha256': sha(raw), 'record_lengths': list(map(len, original))},
                    'proposed': {'filename': cms['filename'], 'filetype': cms['filetype'], 'filemode': cms['filemode'],
                        'recfm': cms['recfm'], 'lrecl': cms['lrecl'] if cms['recfm'] == 'F' else max(lengths, default=0),
                        'record_count': len(proposed), 'record_lengths': lengths, 'byte_count': len(candidate),
                        'sha256': sha(candidate), 'records_sha256': [sha(r) for r in proposed]},
                    'changed': original != proposed, 'record_changes': changes, 'diff_sha256': sha(diff),
                    'upload_implemented': False, 'upload_authorized': False,
                    'required_before_any_future_upload': ['explicit authorization for this exact CMS target and candidate hash',
                        'protected target/disk policy check', 'fresh native source and metadata revalidation against expected_original',
                        'verified rollback and staged candidate design; no assumed atomic compare-and-swap',
                        'post-write complete native readback and build/test verification'],
                    'host_operations_performed': False}
                plan_id = 'plan-' + secrets.token_hex(12)
                new_directory = edit / plan_id
                new_directory.mkdir(mode=0o700)
                directory = new_directory
                self.write(directory, 'candidate.ebcdic', candidate)
                self.write(directory, 'source.diff', diff)
                plan_bytes = canonical(plan)
                self.write(directory, 'plan.json', plan_bytes)
                if read_file(directory / 'candidate.ebcdic', MAX_BYTES) != candidate:
                    raise ValueError('Local candidate verification failed')
                return {'ok': True, 'edit_id': edit_id, 'plan_id': plan_id,
                    'plan_file': str(directory / 'plan.json'), 'plan_sha256': sha(plan_bytes),
                    'diff_file': str(directory / 'source.diff'), 'diff_bytes': len(diff),
                    'candidate_file': str(directory / 'candidate.ebcdic'), 'candidate_sha256': sha(candidate),
                    'base_sha256': sha(raw), 'changed': plan['changed'], 'record_changes': changes,
                    'record_count': len(proposed), 'cms': cms, 'git_worktree': str(worktree),
                    'upload_implemented': False, 'upload_authorized': False, 'host_operations_performed': False}
            except Exception as exc:
                if directory is not None and directory.exists():
                    shutil.rmtree(directory)
                return {'ok': False, 'message': self.session.redact(str(exc)),
                        'upload_authorized': False, 'host_operations_performed': False}
