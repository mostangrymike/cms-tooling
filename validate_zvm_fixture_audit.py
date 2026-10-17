"""Read-only post-build audit of the retained, interrupted ZTQUAL qualification.

Never create, replace, build, test, restore or erase a fixture file. An explicit
create-output-reader option may provision one absent source-verified helper.
The separately
approved recovery option permits one Clear and one fixed QUERY CMSLEVEL probe
only after the exact abandoned reader's terminal ACK failure and Ready(00012).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time

import validate_zvm_fixture as fixture
from zvm_edit import canonical, read_file, sha


def prior_run(path, expected):
    raw = read_file(path, 64 * 1048576)
    if sha(raw) != expected:
        raise ValueError('Prior journal hash differs')
    data = json.loads(raw)
    declared = data['contract']
    if (sha(canonical(declared)) != data['contract_sha256']
            or declared['target'] != fixture.TARGET or declared['backup'] != fixture.BACKUP
            or declared['baseline_sha256'] != fixture.contract()['baseline_sha256']
            or declared['candidate_sha256'] != fixture.contract()['candidate_sha256']):
        raise ValueError('Prior fixture contract differs')
    steps = data['steps']
    required = ('explicit source recovery and verify', 'candidate reapply and native readback',
                'build candidate', 'test candidate', 'native output ZTQUAL ASSEMBLE A1',
                'native output ZTQUAL TEXT A1')
    for name in required:
        matches = [step for step in steps if step['step'] == name]
        if len(matches) != 1 or matches[0]['state'] != 'complete':
            raise ValueError('Prior recovery/build/test/output prerequisite missing')
        if name in ('explicit source recovery and verify', 'candidate reapply and native readback'):
            role = 'baseline' if name == 'explicit source recovery and verify' else 'candidate'
            result = matches[0]['result']
            if (result.get('ok') is not True or result.get('download_complete') is not True
                    or result.get('integrity_verified') is not True
                    or result.get('sha256') != declared[role + '_sha256']):
                raise ValueError('Prior native recovery/reapply verification missing')
        if name in ('build candidate', 'test candidate'):
            fixture.command_ok(matches[0]['result'], marker=(
                'CMSCLNK: built ZTQUAL MODULE mode PLAIN' if name == 'build candidate'
                else 'ZTQUAL CANDIDATE PASS 43'))
    if steps[-1]['step'] != 'native output ZTQUAL LISTING A1' or steps[-1]['state'] != 'failed':
        raise ValueError('Only the exact interrupted post-build LISTING run is supported')
    failed = data['last_download']['evidence'][-1]
    if (failed.get('stage') != 'FILEREAD' or failed.get('error_type') != 'CaptureError'
            or failed.get('message') != 'Capture deadline exceeded; partial output is not a complete command result'
            or failed.get('output_complete') is not False):
        raise ValueError('Expected interrupted native-read failure missing')
    token, sequence = failed['request_id'], failed['frames_verified']
    if not re.fullmatch('[0-9A-F]{16}', token) or type(sequence) is not int or sequence < 1:
        raise ValueError('Invalid failed-reader identity')
    return data, token, sequence


def failed_boundary(screen, token, sequence):
    from zvm_commands import RunnerBridge, ready_rc
    rows = screen.get('rows', [])
    frames = [i for i, row in enumerate(rows) if row.strip() == f'ZM1 {token} F {sequence} ACK']
    other = [row for row in rows if re.search(r'ZM1 [0-9A-F]{16} ', row)
             and row.strip() != f'ZM1 {token} F {sequence} ACK']
    ready = [i for i, row in enumerate(rows) if ready_rc(row) == 12]
    return bool(screen.get('state') == 'cms_ready' and screen.get('connected')
                and screen.get('field_layout_error') is None
                and RunnerBridge.input_field(screen) and len(rows) == 24
                and len(frames) == 1 and not other and ready and min(ready) > frames[0])


def recover_failed_reader(session, token, sequence):
    """Explicit recovery, never an automatic exception handler or capture success."""
    from zvm_commands import RunnerBridge, ready_rc
    def work():
        before = session.snapshot()
        if not failed_boundary(before, token, sequence):
            raise ValueError('Exact failed-reader and fresh Ready(00012) boundary required')
        session.command('MoveCursor(22,0)')
        checked = session.snapshot()
        if (not failed_boundary(checked, token, sequence)
                or checked['cursor'] != {'row': 23, 'column': 1, 'protected': False}):
            raise ValueError('Recovery cursor/field changed')
        session.command('Clear')
        deadline = time.monotonic() + 15
        screens = [before]
        while time.monotonic() < deadline:
            after = session.snapshot()
            screens.append(after)
            if (after.get('connected') and after.get('field_layout_error') is None
                    and RunnerBridge.input_field(after)
                    and all(not row.strip() for row in after['rows'][:22])):
                break
            if after.get('state') in ('more', 'holding', 'cp_read', 'login'):
                raise ValueError('Unexpected recovery state; no further input')
            session._wait_output(1)
        else:
            raise ValueError('Clear did not establish empty command area')
        session.runner._input('QUERY CMSLEVEL')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            session._wait_output(1)
            after = session.snapshot()
            screens.append(after)
            rows = after['rows']
            echoes = [i for i, row in enumerate(rows) if row.strip() == 'QUERY CMSLEVEL']
            levels = [i for i, row in enumerate(rows) if row.strip() == 'CMS Level 27, Service Level 1302']
            ready = [i for i, row in enumerate(rows) if ready_rc(row) == 0]
            if (after['state'] == 'cms_ready' and RunnerBridge.input_field(after)
                    and len(echoes) == 1 and len(levels) == 1 and ready
                    and echoes[0] < levels[0] < max(ready)):
                return {'retired_failed_reader': token, 'failed_sequence': sequence,
                        'prior_capture_complete': False, 'query': 'QUERY CMSLEVEL',
                        'fresh_ready_observed': True, 'snapshots': screens}
            if after['state'] in ('more', 'holding', 'cp_read', 'login'):
                raise ValueError('Unexpected probe state; no retry or paging')
        raise ValueError('Fresh CMSLEVEL/Ready boundary unverified')
    return fixture.require(session._run('explicit_failed_reader_recovery', work, timeout=35))


def audit(adapter, journal, previous, completed_outputs=None):
    """Only read-only actions; a failure stops the sequence without retry."""
    step = journal.step
    disks = step('audit disk identity', lambda: adapter.command('QUERY DISK'))
    if not any(row.split()[:4] == ['MNT191', '191', 'A', 'R/W'] for row in disks['records']):
        raise ValueError('Fixture disk identity changed')
    for target in fixture.OUTPUTS:
        if target in (completed_outputs or {}):
            step('retain previously verified native output ' + target,
                 lambda target=target: completed_outputs[target])
            continue
        old = next((x['result'] for x in previous['steps']
                    if x['step'] == 'native output ' + target and x['state'] == 'complete'), None)
        expected = old['sha256'] if old else None
        step('audit native output ' + target, lambda target=target, expected=expected:
             adapter.download(target, expected))
    for target, role in ((fixture.TARGET, 'candidate'), (fixture.BACKUP, 'baseline')):
        step('audit native ' + target, lambda target=target, role=role:
             adapter.download(target, previous['contract'][role + '_sha256']))
    for target in fixture.TRANSIENT:
        step('audit transient absent ' + target, lambda target=target: adapter.command('STATE ' + target, rc=28))
    for namespace, expected in (('ZTQUAL', (fixture.TARGET, *fixture.OUTPUTS)), ('ZTQBACK', (fixture.BACKUP,))):
        def inventory(namespace=namespace, expected=expected):
            result = adapter.command(f'LISTFILE {namespace} * A')
            observed = [' '.join(row.split()) for row in result['records'] if row.strip()]
            if len(observed) != len(expected) or set(observed) != set(expected):
                raise ValueError('Final namespace differs from exact inventory')
            return result
        step('audit exact inventory ' + namespace, inventory)
    def filedefs():
        result = adapter.action('FILEDEFS')
        records = [row.strip().upper() for row in result['records'] if row.strip()]
        if records not in ([], ['NO FILE DEFINITIONS IN EFFECT'],
                           ['DMSFLD324I NO USER DEFINED FILEDEFS IN EFFECT']):
            raise ValueError('Final FILEDEF state is not empty')
        return result
    step('audit empty FILEDEF', filedefs)
    journal.data.update(passed=True, postbuild_audit_passed=True, fixture_only=True,
                        source_recovery_qualified=True, writer_exclusion_verified=False,
                        build_or_test_repeated=False, fixture_file_writes=False,
                        host_file_writes=journal.data.get('output_helper_creation_requested', False))
    journal.persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--recover-failed-reader', action='store_true',
                        help='Requires separate operator approval for one guarded Clear and CMSLEVEL probe')
    parser.add_argument('--prior-evidence', type=Path)
    parser.add_argument('--prior-evidence-sha256')
    parser.add_argument('--contract-sha256')
    parser.add_argument('--credential-file', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--completed-output-evidence', type=Path)
    parser.add_argument('--completed-output-sha256')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--create-output-reader', action='store_true',
                       help='Explicitly provision one absent random retained output-only helper; needs live approval')
    group.add_argument('--output-reader', help='Reverify an exact retained output-only helper; never replace it')
    args = parser.parse_args()
    declared = fixture.contract()
    digest = sha(canonical(declared))
    if not args.live:
        print(json.dumps({'contract_sha256': digest, 'host_operations_performed': False,
                          'read_only_postbuild_audit': True,
                          'recovery_requires_separate_approval': True}, indent=2))
        return 0
    if args.contract_sha256 != digest or not all((args.prior_evidence, args.prior_evidence_sha256,
                                                args.credential_file, args.output)):
        parser.error('Require exact contract, prior evidence/hash, credential file and new output')
    previous, token, sequence = prior_run(args.prior_evidence, args.prior_evidence_sha256)
    if bool(args.completed_output_evidence) != bool(args.completed_output_sha256):
        parser.error('Completed-output evidence requires its exact hash')
    from zvm_fixture_output import retained_outputs, ModuleReader
    retained = (retained_outputs(args.completed_output_evidence, args.completed_output_sha256,
                                args.prior_evidence_sha256)
                if args.completed_output_evidence else None)
    from zvm_credentials import FileCredentialProvider
    from zvm_mcp import Session
    journal = fixture.Journal(args.output, declared, digest)
    journal.data.update(prior_evidence_sha256=args.prior_evidence_sha256,
                        prior_contract_sha256=previous['contract_sha256'],
                        explicit_reader_recovery_authorized=args.recover_failed_reader,
                        completed_output_evidence_sha256=args.completed_output_sha256,
                        output_helper_creation_requested=args.create_output_reader)
    journal.persist()
    session = Session(allow_login=True, allow_startup=True, allow_commands=True,
        runner_name='ZM537EF1', allow_downloads=True, download_root=fixture.ROOT / 'cms-sources',
        download_runner_name='ZM02EA0B', credential_provider=FileCredentialProvider(args.credential_file))
    adapter = fixture.LiveAdapter(session, journal, reuse_helper=True)
    module = ModuleReader(session, fixture.ROOT / 'cms-sources', args.output_reader) if (
        args.create_output_reader or args.output_reader) else None
    try:
        connected = journal.step('connect audit', lambda: fixture.require(session.connect()))
        if connected['screen']['state'] == 'login' or connected['screen'].get('screen_kind') == 'hercules_banner':
            journal.step('login audit', lambda: fixture.require(session.login()))
        journal.step('startup audit', lambda: fixture.require(session.startup(timeout=45, verify_cms=True)))
        if args.recover_failed_reader:
            journal.step('explicit failed-reader recovery', lambda: recover_failed_reader(session, token, sequence))
        journal.step('verify read-only helper', lambda: fixture.require(session.runner.prepare(create=False)))
        journal.step('verify fixed FILEDEF helper', lambda: fixture.require(adapter.builder.prepare(create=False)))
        if module:
            journal.step('create and verify output-only reader' if args.create_output_reader else 'verify output-only reader',
                         lambda: fixture.require(module.reader.prepare(create=args.create_output_reader)))
            ordinary_download = adapter.download
            def download(target, expected=None):
                if target != 'ZTQUAL MODULE A1':
                    return ordinary_download(target, expected)
                result = module.download()
                journal.data['last_download'] = result
                journal.persist()
                fixture.require(result)
                if expected is not None and result['sha256'] != expected:
                    raise ValueError('Native MODULE differs from prior output hash')
                return result
            adapter.download = download
        # Keep the standard default and per-capture limit; allow up to 900s for
        # metadata plus two complete native reads and matching final metadata.
        adapter.download_timeout = 900
        session.downloader.max_timeout = 900
        audit(adapter, journal, previous, retained)
    except BaseException as exc:
        journal.data.update(passed=False, error_type=type(exc).__name__,
                            failure_screen=session.last_screen, host_state_requires_review=True)
        journal.persist()
    finally:
        journal.data['disconnect'] = session.disconnect()
        journal.persist()
        journal.file.close()
    print(json.dumps({'passed': journal.data['passed'], 'evidence': str(args.output)}))
    return 0 if journal.data['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
