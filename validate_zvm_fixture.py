"""Default-off fixed ZTQUAL qualification; never a production executor.

Without --live print a hash-pinned contract and perform no terminal operations.
Every live step is persisted before and after execution. A failed step stops;
there is no automatic retry, restoration or host cleanup.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from zvm_edit import canonical, read_file, sha, validate_manifest

ROOT = Path(__file__).resolve().parent
TARGET = 'ZTQUAL C A1'
BACKUP = 'ZTQBACK C A1'
REUSABLE_HELPER = 'ZM000175'
OUTPUTS = tuple('ZTQUAL ' + ft + ' A1' for ft in ('ASSEMBLE', 'TEXT', 'LISTING', 'MODULE'))
TRANSIENT = ('ZTQUAL WORK A1', 'ZTQUAL SYSUT1 A4', 'ZTQUAL SYSUT2 A4',
             'ZTQUAL SYSUT3 A4', 'ZTQUAL LOADMAP A5', 'LOAD MAP A5')
PINS = {
    'CMSCLNK EXEC F1': '695482209368594b8493506240968aac27e34846922f276bb2f813de4c7b4bee',
    'GCCE EXEC F1': 'd0538a0d1bf0ce83aeffd527dc72394deb4efaeb181d5aee7a960bd104011888',
    'STD380 PARM F1': 'a30a03f46abaec885053c550c1cc2d181a368bd5ca4af59488f63924e06b019d',
}
SHADOWS = tuple(f'{fn} {ft} {mode}'
    for mode in 'ABCDE'
    for fn, ft in (('CMSCLNK', 'EXEC'), ('GCCE', 'EXEC'), ('GCC', 'EXEC'),
                   ('GCC', 'MODULE'), ('STD380', 'PARM'))) + tuple(
    f'ASSEMBLE {ft} {mode}' for mode in 'ABCDEFS' for ft in ('EXEC', 'MODULE')
    if not (mode == 'S' and ft == 'MODULE')) + ('GCC EXEC F',)


def native_source(payload):
    text = payload.decode('ascii')
    if not text.endswith('\n') or '\r' in text:
        raise ValueError('Source must use LF-terminated records')
    lines = text[:-1].split('\n')
    if not lines or any(len(line) > 80 or any(ord(c) < 32 or ord(c) > 126 for c in line) for line in lines):
        raise ValueError('Only printable ASCII F80 fixture source is supported')
    return b''.join(line.ljust(80).encode('cp037') for line in lines)


def contract():
    files = ('validate_zvm_fixture.py', 'ZMCPQUAL.EXEC', 'zvm_commands.py',
        'zvm_capture.py', 'zvm_download.py', 'zvm_edit.py', 'zvm_native_review.py',
        'zvm_operations.py', 'zvm_rehearsal.py', 'zvm_mcp.py', 'zvm_credentials.py', 'diagnose_zvm_cms.py',
        'fixtures/qualification/baseline/ZTQUAL.C', 'fixtures/qualification/candidate/ZTQUAL.C')
    sources = {name: sha(read_file(ROOT / name, 2 * 1048576)) for name in files}
    baseline, candidate = (native_source(read_file(ROOT / f'fixtures/qualification/{role}/ZTQUAL.C', 8192))
                           for role in ('baseline', 'candidate'))
    return {'schema': 'zvm-disposable-fixture-contract-v1', 'target': TARGET, 'backup': BACKUP,
        'reusable_fixed_helper': REUSABLE_HELPER,
        'source_hashes': sources, 'baseline_sha256': sha(baseline), 'candidate_sha256': sha(candidate),
        'installed_source_hashes': PINS, 'persistent_outputs': list(OUTPUTS),
        'required_absent_command_shadows': list(SHADOWS),
        'possible_transient_outputs': list(TRANSIENT),
        'commands': ['CMSCLNK ZTQUAL PLAIN', 'ZTQUAL', 'FILEDEF'],
        'recovery': 'Explicit successful-path source restore from verified backup, then candidate reapply before build',
        'failure_behavior': 'Stop without retry, restore or host cleanup; retain uncertain/partial files',
        'production_qualified': False, 'writer_exclusion_verified': False, 'replacement_safe': False,
        'limitation': 'Fresh disposable namespace only; absence/readback are not atomic and do not exclude other writers. Installed compiler binaries are trusted environment inputs, not independently hashed here.'}


class StepFailure(ValueError):
    def __init__(self, result):
        super().__init__('Step failed; see sanitized step evidence')
        self.result = result


def require(result):
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise StepFailure(result)
    return result


def command_ok(result, rc=0, marker=None):
    require(result)
    if (result.get('cms_rc') != rc or result.get('output_complete') is not True
            or result.get('integrity_verified') is not True or result.get('cms_command_complete') is not True
            or result.get('redaction_applied')):
        raise ValueError('CMS command RC, native integrity or completion unverified')
    if marker and marker not in [line.strip() for line in result['records']]:
        raise ValueError('Expected complete output record missing')
    return result


def action_policy(action):
    if action not in ('BUILD', 'TEST', 'FILEDEFS'):
        raise ValueError('Only fixed disposable actions BUILD, TEST and FILEDEFS')
    return action


class Journal:
    def __init__(self, path, declared, digest):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.file = os.fdopen(fd, 'w')
        self.data = {'contract': declared, 'contract_sha256': digest, 'passed': False,
                     'production_qualified': False, 'replacement_safe': False,
                     'automatic_retry': False, 'automatic_restore': False, 'host_cleanup': False,
                     'steps': []}
        self.persist()

    def persist(self):
        self.file.seek(0)
        json.dump(self.data, self.file, indent=2)
        self.file.write('\n')
        self.file.truncate()
        self.file.flush()
        os.fsync(self.file.fileno())

    def step(self, name, function):
        entry = {'step': name, 'state': 'started', 'host_effects_may_be_partial': True}
        self.data['steps'].append(entry)
        self.persist()
        print(json.dumps({'step': name, 'state': 'started'}), flush=True)
        try:
            if contract() != self.data['contract'] or sha(canonical(self.data['contract'])) != self.data['contract_sha256']:
                raise ValueError('Bound local sources changed; no next step')
            result = function()
            entry.update(state='complete', result=result, host_effects_may_be_partial=False)
            self.persist()
            return result
        except BaseException as exc:
            entry.update(state='failed', error_type=type(exc).__name__)
            if isinstance(exc, StepFailure):
                entry['result'] = exc.result
            self.persist()
            raise


class LiveAdapter:
    def __init__(self, session, journal, reuse_helper=False):
        from zvm_commands import RunnerBridge
        self.s = session
        self.j = journal
        self.builder = RunnerBridge(session, name=REUSABLE_HELPER if reuse_helper else None,
                                    source=ROOT / 'ZMCPQUAL.EXEC', policy=action_policy)
        self.review_data = None

    def command(self, text, rc=0, marker=None):
        result = self.s.runner.run(text, timeout=120)
        self.j.data['last_command'] = result
        self.j.persist()
        return command_ok(result, rc, marker)

    def action(self, action, marker=None):
        result = self.builder.run(action, timeout=300)
        self.j.data['last_action'] = result
        self.j.persist()
        return command_ok(result, marker=marker)

    def download(self, target, expected=None):
        result = self.s.downloader.download(*target.split(), timeout=300)
        self.j.data['last_download'] = result
        self.j.persist()
        require(result)
        manifest_bytes = read_file(Path(result['manifest']), 2 * 1048576)
        raw = read_file(Path(result['native_file']), 1048576)
        manifest, records = validate_manifest(manifest_bytes, raw)
        identity = ' '.join(manifest['cms'][key] for key in ('filename', 'filetype', 'filemode'))
        if identity != target or (expected is not None and sha(raw) != expected):
            raise ValueError('Fresh native snapshot differs from exact target/hash')
        if target in (TARGET, BACKUP) and (manifest['cms']['recfm'] != 'F' or manifest['cms']['lrecl'] != 80):
            raise ValueError('Fixture source/backup record format mismatch')
        if target in (TARGET, BACKUP) and self.review_data:
            if manifest['cms']['disk_label'] != self.review_data['original_cms']['disk_label']:
                raise ValueError('Fixture disk label changed')
        return {**result, 'manifest_sha256': sha(manifest_bytes)}

    def put(self, target, raw, expected_current=None):
        if target not in (TARGET, BACKUP) or len(raw) % 80 or not raw:
            raise ValueError('Only exact fixed80 disposable source/backup transfers are supported')
        # A transfer back to the source must have a fresh native baseline. No
        # send follows a failed check. A different session can still race it.
        if expected_current is None:
            self.command('STATE ' + target, rc=28)
        else:
            if target != TARGET:
                raise ValueError('Backup is create-only')
            self.revalidate_review()
            fresh = self.download(target, expected_current)
            if not self.review_data['replaced_once'] and fresh['cms'] != self.review_data['original_cms']:
                raise ValueError('Original source metadata changed before first replacement')
        text = '\n'.join(raw[i:i+80].decode('cp037') for i in range(0, len(raw), 80)) + '\n'
        if not all(c == '\n' or 32 <= ord(c) <= 126 for c in text):
            raise ValueError('Transfer source is not printable ASCII')
        with tempfile.TemporaryDirectory(prefix='zvm_fixture_') as directory:
            local = Path(directory) / 'source.c'
            local.write_bytes(text.encode('ascii'))
            result = self.s._run('disposable_fixture_transfer', lambda: {
                'transfer_reply': self.s.runner._transfer(f'Transfer(Direction=send,"HostFile={target}",LocalFile={local},Host=vm,Mode=ascii,Exist=keep,Recfm=fixed,Lrecl=80,BufferSize=2048)'),
                'target': target, 'candidate_sha256': sha(raw)}, timeout=90)
            self.j.data['last_transfer'] = result
            self.j.persist()
            require(result)
        result = self.download(target, sha(raw))
        if expected_current is not None:
            self.review_data['replaced_once'] = True
        return result

    def revalidate_review(self):
        from zvm_operations import review_source, operation_receipt
        review = self.review_data
        if not review:
            raise ValueError('Pinned local review required before replacement')
        edit, plan, operation = (review[key] for key in ('edit', 'plan', 'operation'))
        _, worktree, _, source = review_source(self.s.edits, edit['edit_id'], plan['plan_id'], plan['plan_sha256'])
        raw = read_file(Path(operation['operation_file']), 2 * 1048576)
        receipt = json.loads(raw)
        rebound = operation_receipt(source, edit['edit_id'], plan['plan_id'], plan['plan_sha256'], receipt['recipe'], worktree)
        if sha(raw) != operation['operation_sha256'] or canonical(rebound) != raw:
            raise ValueError('Pinned operation changed')
        return operation


def execute(adapter, journal, declared, expected_contract, qualify_recovery):
    """Fixed fail-stop sequence; injectable adapter permits real failure tests."""
    if not qualify_recovery or sha(canonical(declared)) != expected_contract or contract() != declared:
        raise ValueError('Explicit recovery flag and unchanged exact contract required')
    step = journal.step
    baseline = native_source(read_file(ROOT / 'fixtures/qualification/baseline/ZTQUAL.C', 8192))
    candidate = native_source(read_file(ROOT / 'fixtures/qualification/candidate/ZTQUAL.C', 8192))
    def disks():
        result = adapter.command('QUERY DISK')
        rows = [line.split() for line in result['records']]
        if not all(any(row[:4] == expected for row in rows) for expected in
                   (['MNT191', '191', 'A', 'R/W'], ['GCCLIB', '29D', 'F', 'R/W'])):
            raise ValueError('Accessed source/compiler disks differ from audited environment')
        return result
    step('source and compiler disk identity', disks)
    for target in SHADOWS:
        step('command shadow absent ' + target, lambda target=target: adapter.command('STATE ' + target, rc=28))
    for target in ('GCC MODULE F1', 'ASSEMBLE MODULE S2'):
        step('compiler binary present ' + target, lambda target=target: adapter.command('STATE ' + target))
    for target, digest in PINS.items():
        step('pin ' + target, lambda target=target, digest=digest: adapter.download(target, digest))
    for namespace in ('ZTQUAL', 'ZTQBACK'):
        step('namespace absent ' + namespace, lambda namespace=namespace:
             adapter.command(f'LISTFILE {namespace} * A', rc=28))
    step('global map absent', lambda: adapter.command('STATE LOAD MAP A5', rc=28))
    # FILEDEF must be empty before GCCE/ASSEMBLE can safely use defaults. Any
    # unrecognized nonempty output fails closed for operator inspection.
    def empty_filedefs():
        result = adapter.action('FILEDEFS')
        records = [line.strip().upper() for line in result['records'] if line.strip()]
        if records and records not in (['NO FILE DEFINITIONS IN EFFECT'],
                                       ['DMSFLD324I NO USER DEFINED FILEDEFS IN EFFECT']):
            raise ValueError('Existing or unrecognized FILEDEF state; no source write')
        return result
    step('empty FILEDEF before', empty_filedefs)
    original = step('create baseline and native readback', lambda: adapter.put(TARGET, baseline))
    step('local pinned edit review', lambda: adapter.review(original, candidate))
    step('create native backup and verify', lambda: adapter.put(BACKUP, baseline))
    step('candidate replacement and native readback', lambda: adapter.put(TARGET, candidate, sha(baseline)))
    # An explicit qualification exercise, never an exception/failure handler.
    backup = step('fresh native backup before recovery', lambda: adapter.download(BACKUP, sha(baseline)))
    backup_bytes = read_file(Path(backup['native_file']), 1048576)
    if backup_bytes != baseline:
        raise ValueError('Retained backup artifact differs before explicit recovery')
    step('explicit source recovery and verify', lambda: adapter.put(TARGET, backup_bytes, sha(candidate)))
    step('candidate reapply and native readback', lambda: adapter.put(TARGET, candidate, sha(baseline)))
    # Recheck output absence immediately before the only compile. Nothing
    # preexisting may be replaced by GCCE/ASSEMBLE/GENMOD.
    for target in (*OUTPUTS, *TRANSIENT):
        step('prebuild absent ' + target, lambda target=target: adapter.command('STATE ' + target, rc=28))
    step('build candidate', lambda: adapter.action('BUILD', 'CMSCLNK: built ZTQUAL MODULE mode PLAIN'))
    step('test candidate', lambda: adapter.action('TEST', 'ZTQUAL CANDIDATE PASS 43'))
    for target in OUTPUTS:
        step('native output ' + target, lambda target=target: adapter.download(target))
    step('final source', lambda: adapter.download(TARGET, sha(candidate)))
    step('final backup', lambda: adapter.download(BACKUP, sha(baseline)))
    for target in TRANSIENT:
        step('final transient absent ' + target, lambda target=target: adapter.command('STATE ' + target, rc=28))
    def inventory(namespace, expected):
        result = adapter.command(f'LISTFILE {namespace} * A')
        observed = [' '.join(line.split()) for line in result['records'] if line.strip()]
        if len(observed) != len(expected) or set(observed) != set(expected):
            raise ValueError('Final disposable namespace contains missing or unexpected files')
        return result
    step('final exact ZTQUAL inventory', lambda: inventory('ZTQUAL', (TARGET, *OUTPUTS)))
    step('final exact backup inventory', lambda: inventory('ZTQBACK', (BACKUP,)))
    step('empty FILEDEF after', empty_filedefs)
    journal.data.update(passed=True, source_recovery_qualified=True,
        final_source_sha256=sha(candidate), final_module='ZTQUAL MODULE A1',
        retained_backup=BACKUP, fixture_only=True, writer_exclusion_verified=False)
    journal.persist()


def local_review(self, original, candidate):
    """Retain the standard review-only operation and compare native snapshots."""
    edit = require(self.s.edits.prepare(Path(original['snapshot_directory']).name))
    text = '\n'.join(candidate[i:i+80].decode('cp037').rstrip() for i in range(0, len(candidate), 80)) + '\n'
    Path(edit['editable_file']).write_bytes(text.encode('utf-8'))
    plan = require(self.s.edits.plan(edit['edit_id']))
    if plan['candidate_sha256'] != sha(candidate):
        raise ValueError('Edit candidate differs from contract')
    recipe = {'input_hashes': PINS, 'steps': [
        {'name': 'build', 'command': ['CMSCLNK', 'ZTQUAL', 'PLAIN'],
         'inputs': [TARGET, *PINS], 'outputs': [{'file': f, 'policy': 'create_only'} for f in OUTPUTS],
         'expected_rc': 0, 'expect': ['CMSCLNK: built ZTQUAL MODULE mode PLAIN']},
        {'name': 'test', 'command': ['ZTQUAL'], 'inputs': ['ZTQUAL MODULE A1'], 'outputs': [],
         'expected_rc': 0, 'expect': ['ZTQUAL CANDIDATE PASS 43']}],
        'rollback': {'snapshot': Path(original['snapshot_directory']).name, 'sha256': original['sha256'],
                     'target': TARGET, 'procedure': 'Explicit fixed fixture restore from freshly verified ZTQBACK C A1 only'}}
    # No invented writer exclusion statement: the standard review remains
    # incomplete and blocked. This separate disposable executor does not use
    # review_complete as execution authority or relax the production planner.
    operation = require(self.s.operations.plan(edit['edit_id'], plan['plan_id'], plan['plan_sha256'], recipe))
    self.review_data = {'edit': edit, 'plan': plan, 'operation': operation,
                        'original_cms': original['cms'], 'replaced_once': False}
    self.revalidate_review()
    return {'edit': edit, 'plan': plan, 'operation': operation}


LiveAdapter.review = local_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--qualify-recovery', action='store_true')
    parser.add_argument('--reuse-fixture-helper', action='store_true',
                        help='Reverify retained fixed helper ZM000175 instead of creating a new one')
    parser.add_argument('--contract-sha256')
    parser.add_argument('--credential-file', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    declared = contract()
    digest = sha(canonical(declared))
    if not args.live:
        print(json.dumps({'contract_sha256': digest, 'contract': declared, 'host_operations_performed': False}, indent=2))
        return 0
    if args.contract_sha256 != digest or not args.qualify_recovery or not args.output or not args.credential_file:
        parser.error('Live fixture requires exact contract hash, --qualify-recovery, --credential-file and new --output')
    from zvm_credentials import FileCredentialProvider
    from zvm_mcp import Session
    journal = Journal(args.output, declared, digest)
    session = Session(allow_login=True, allow_startup=True, allow_commands=True,
        runner_name='ZM537EF1', allow_downloads=True, download_root=ROOT / 'cms-sources',
        download_runner_name='ZM02EA0B', allow_local_edits=True,
        credential_provider=FileCredentialProvider(args.credential_file))
    adapter = LiveAdapter(session, journal, args.reuse_fixture_helper)
    try:
        connected = journal.step('connect', lambda: require(session.connect()))
        screen = connected['screen']
        if screen['state'] == 'login' or screen.get('screen_kind') == 'hercules_banner':
            journal.step('login', lambda: require(session.login()))
        journal.step('startup', lambda: require(session.startup(timeout=45, verify_cms=True)))
        journal.step('verify existing read-only helper', lambda: require(session.runner.prepare(create=False)))
        journal.step('verify fixed fixture helper' if args.reuse_fixture_helper else 'create and verify fixed fixture helper',
                     lambda: require(adapter.builder.prepare(create=not args.reuse_fixture_helper)))
        execute(adapter, journal, declared, digest, args.qualify_recovery)
    except BaseException as exc:
        journal.data.update(passed=False, error_type=type(exc).__name__,
                            failure_screen=session.last_screen, host_state_requires_review=True)
        journal.persist()
    finally:
        journal.data['disconnect'] = session.disconnect()
        journal.persist()
        journal.file.close()
    print(json.dumps({'passed': journal.data['passed'], 'evidence': str(args.output),
                      'error_type': journal.data.get('error_type')}), flush=True)
    return 0 if journal.data['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
