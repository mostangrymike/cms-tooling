"""Fixed read-only compiler/DFT availability observations; never run a compiler."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from zvm_credentials import FileCredentialProvider
from zvm_mcp import Session


# Explicit literal queries only. No caller-supplied command, disk access,
# helper provisioning, transfer or compile is accepted. The optional startup
# hold release below requires separate, explicit recovery authorization.
QUERIES = {'disks': 'QUERY DISK', **{
    'transfer_' + mode: 'STATE IND$FILE MODULE ' + mode
    for mode in ('A', 'B', 'D', 'E', 'F', 'S', 'T', 'Y')},
    'wrapper_A': 'STATE CMSCLNK EXEC A', 'wrapper_F': 'STATE CMSCLNK EXEC F',
    'compiler_A': 'STATE GCCE EXEC A', 'compiler_F': 'STATE GCCE EXEC F'}


def release_startup_hold(session, startup, timeout=20, authorized=False):
    """One separately authorized Clear for the exact captured reconnect hold.

    Standalone diagnostic only; never used by MCP startup or ordinary transfers.
    The caller must have explicitly selected --advance-startup-more. No second
    Clear, Enter, BEGIN, transfer, restore or other recovery action follows.
    """
    from zvm_commands import RunnerBridge
    from zvm_mcp import host_display
    if (authorized is not True or startup.get('outcome') != 'startup_page_hold_observed'
            or startup.get('actions') != ['BEGIN', 'Enter']
            or type(timeout) is not int or not 1 <= timeout <= 30):
        return {'ok': False, 'message': 'Exact captured reconnect hold is required', 'clear_sent': False}
    expected = startup['screen']
    clear_attempted = False

    def work():
        nonlocal clear_attempted
        deadline = time.monotonic() + timeout
        before = session.snapshot()
        rows = '\n'.join(before['rows']).upper()
        if (before['state'] not in {'more', 'holding'}
                or not RunnerBridge.input_field(before)
                or host_display(before) != host_display(expected)
                or before['rows'][6].strip() != 'BEGIN'
                or any(row.strip() for row in before['rows'][7:22])
                or 'RECONNECTED AT' not in rows
                or 'Z/VM VERSION 6 RELEASE 3.0' not in rows):
            raise ValueError('Reconnect hold changed; no paging input sent')
        session.command('MoveCursor(22,0)')
        check = session.snapshot()
        if (host_display(check) != host_display(before) or not RunnerBridge.input_field(check)
                or check['cursor'] != {'row': 23, 'column': 1, 'protected': False}):
            raise ValueError('Reconnect hold field changed; no paging input sent')
        pages = [before, check]
        session.command('Ascii')
        clear_attempted = True
        session.command('Clear')
        while time.monotonic() < deadline:
            current = session.snapshot()
            pages.append(current)
            if (host_display(current) != host_display(before) and current['state'] == 'cms_ready'
                    and RunnerBridge.input_field(current)):
                return {'clear_sent': True, 'clear_count': 1, 'screen': current,
                        'snapshots': pages, 'outcome': 'fresh_ready_after_single_clear',
                        'cms_command_complete': None, 'compiler_executed': False}
            # At most one Clear even if another held page arrives or the old
            # hold persists. Preserve it for operator review and stop.
            if (current['state'] in {'more', 'holding'}
                    and host_display(current) != host_display(before)):
                return {'ok': False, 'clear_sent': True, 'clear_count': 1,
                        'screen': current, 'snapshots': pages,
                        'message': 'Held output remains after the single authorized Clear'}
            session._wait_output(1)
        return {'ok': False, 'clear_sent': True, 'clear_count': 1,
                'screen': pages[-1], 'snapshots': pages,
                'outcome': 'ready_not_observed_after_single_clear',
                'message': 'No fresh Ready after the single authorized Clear'}

    result = session._run('compiler_startup_hold_release', work, timeout + 2)
    result['clear_attempted'] = clear_attempted
    if not result['ok'] and 'clear_sent' not in result:
        result['clear_sent'] = None if clear_attempted else False
    return result


def observe(session, query, timeout=20):
    if (not session.allow_commands or not isinstance(query, str) or query not in QUERIES
            or type(timeout) is not int or not 1 <= timeout <= 30):
        return {'ok': False, 'message': 'Enable read-only commands and select a fixed compiler observation',
                'host_file_operations_performed': False, 'replacement_safe': False}
    command = QUERIES[query]

    def work():
        # Existing bootstrap path: capture screen geometry and require the exact
        # command echo followed by Ready/RC; observed MORE/HOLDING can advance.
        # No unverified EXEC is run to obtain these availability observations.
        result = session.runner._simple(command, time.monotonic() + timeout)
        return {'command': command, 'terminal_ready_rc': result['rc'],
                'snapshots': result['snapshots'], 'screen_observation_complete': True,
                'native_output_integrity_verified': False, 'helper_executed': False,
                'compiler_executed': False, 'host_file_operations_performed': False,
                'replacement_safe': False, 'source_verified': False}

    return session._run('compiler_observation', work, timeout + 2)


def validate(args, session=None):
    if args.live is not True:
        raise ValueError('An explicit live diagnostic request is required')
    # Reserve an owner-only new evidence file BEFORE connecting. Do not overwrite
    # an earlier run, follow symlinks or create evidence outside the chosen path.
    from zvm_download import git_root_for
    output = Path(args.output).expanduser().absolute()
    git_root_for(output.parent)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as handle:
        evidence = {'schema': 'zvm-compiler-observation-v1', 'observations': {},
            'observation_complete': False, 'compiler_executed': False,
            'transfers_attempted': False, 'helper_provisioning_attempted': False,
            'automatic_retry_performed': False, 'replacement_safe': False}
        evidence['startup_hold_release_authorized'] = bool(getattr(args, 'advance_startup_more', False))

        def persist():
            handle.seek(0)
            json.dump(evidence, handle, indent=2)
            handle.write('\n')
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())

        persist()
        session = session or Session(allow_login=True, allow_startup=True,
            allow_commands=True, credential_provider=FileCredentialProvider(args.credential_file))
        try:
            stages = [('connect', lambda: session.connect('0200@', timeout=15)),
                ('screen', lambda: session.screen(wait_output=True, timeout=10)),
                ('login', lambda: session.login(timeout=30)),
                ('startup', lambda: session.startup(verify_cms=True, timeout=45))]
            for name, action in stages:
                evidence[name] = action()
                persist()
                if not evidence[name]['ok']:
                    if name == 'startup' and evidence['startup_hold_release_authorized']:
                        evidence['startup_hold_release'] = release_startup_hold(session, evidence[name], authorized=True)
                        persist()
                        if evidence['startup_hold_release']['ok']:
                            continue
                    return evidence
            for name in QUERIES:
                result = observe(session, name)
                evidence['observations'][name] = result
                persist()
                if not result['ok']:
                    return evidence
            evidence['observation_complete'] = True
            persist()
        finally:
            evidence['disconnect'] = session.disconnect()
            persist()
        return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', required=True, action='store_true')
    parser.add_argument('--credential-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--advance-startup-more', action='store_true',
        help='Separately authorize one Clear on the exact captured reconnect MORE/HOLDING page')
    args = parser.parse_args()
    try:
        evidence = validate(args)
    except Exception as exc:
        print(json.dumps({'observation_complete': False, 'error_type': type(exc).__name__}))
        return 1
    print(json.dumps({'observation_complete': evidence['observation_complete'],
        'results': {key: {field: value.get(field) for field in
            ('ok', 'terminal_ready_rc')} for key, value in evidence['observations'].items()},
        'compiler_executed': False, 'transfers_attempted': False,
        'startup_hold_release': {field: evidence.get('startup_hold_release', {}).get(field)
            for field in ('ok', 'clear_sent', 'clear_count', 'outcome', 'message')},
        'disconnect': evidence.get('disconnect')}))
    return 0 if evidence['observation_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
