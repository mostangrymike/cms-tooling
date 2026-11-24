#!/usr/bin/env python3
"""Index every minidisk in the CP directory and build a CMS filename database.

The CP directory source lists one ``MDISK`` statement per minidisk, grouped by
``USER``/``IDENTITY`` entry (identities are real user IDs in the active
directory).  For each definition this tool links the minidisk read-only on a
scratch address, accesses it, runs ``LISTFILE``, and records every file.

The records are written as ``FINDBASE DATA A`` on MAINT's A disk, which the
CMS-side ``FIND EXEC`` searches.

Usage::

    python3 cms_find_index.py --directory candfin.direct --state scan.json \\
        --database findbase.data
    python3 cms_find_index.py --install --state scan.json

``--install`` uploads the database and ``FIND EXEC`` to MAINT with the same
Telnet session.  A wedged line (a previous session closed without LOGOFF) is
cleared with LOGOFF before logging on.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

from cms_telnet_driver import CmsSession, CmsTimeout, DEFAULT_CREDS, visible
from cms_ftpput import _open_ftp

SCRATCH = '0299'
MODE = 'Z'
SCREEN = re.compile(r"(?m)Enter password:|Enter one of the following|^\s*\.\s*$")
PROMPT = re.compile(r"(?m)^\s*\.\s*$")


def _password(path=DEFAULT_CREDS):
    with open(os.path.expanduser(path), encoding='utf-8') as fh:
        data = json.load(fh)
    return data.get('password') or data.get('pass') or data.get('PASSWORD')


def parse_directory(path):
    """Return one dict per owned MDISK, attributed to its USER/IDENTITY."""
    owner = None
    out = []
    for line in open(path):
        s = line.strip()
        m = re.match(r'(USER|IDENTITY)\s+(\S+)', s)
        if m:
            owner = m.group(2)
            continue
        if s.startswith('PROFILE '):
            owner = None
            continue
        if s.startswith('MDISK ') and owner:
            p = s.split()
            out.append({
                'user': owner, 'vdev': p[1], 'type': p[2], 'start': p[3],
                'size': int(p[4]) if p[4].isdigit() else 0, 'vol': p[5],
            })
    return out


def load_state(path):
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return {'done': {}, 'files': []}


def save_state(state, path):
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(state, fh)
    os.replace(tmp, path)


def parse_listfile(text):
    rows = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('FILENAME') or s.startswith('DMSLST'):
            continue
        p = s.split()
        if len(p) < 6 or not re.fullmatch(r'[A-Z][0-6]?', p[2]):
            continue
        rows.append({'fn': p[0], 'ft': p[1], 'fm': p[2], 'recs': p[5],
                     'date': p[7] if len(p) > 7 else ''})
    return rows


def open_session(userid='MAINT', log_path=None, tries=4):
    """Log on to CMS, clearing a stale line that still owns the user ID."""
    password = _password()
    for _ in range(tries):
        s = CmsSession(log_path=log_path)
        s._open()
        s._drain(0.4)
        s._send_raw(bytes([0xFF, 0xF3]))
        try:
            banner = s._read_until(SCREEN, timeout=10)
        except CmsTimeout:
            banner = visible(s._pending.decode('latin-1', 'replace'))
            s._pending = b''
        if PROMPT.search(banner) and 'PRESS BREAK' not in banner:
            r = s.command('CP QUERY USERID', timeout=40)
            if userid in r.output:
                return s
        if 'Already logged on' in banner:
            s._send('LOGOFF')
            time.sleep(6)
            s._drain(3)
            s.close()
            time.sleep(3)
            continue
        s._send(f'LOGON {userid}')
        try:
            s._read_until(re.compile('Enter password:'), timeout=25)
        except CmsTimeout:
            s.close()
            time.sleep(3)
            continue
        s._log('send', '<password redacted>')
        s._send_raw(password.encode('utf-8') + b'\r\n')
        try:
            s._read_until(PROMPT, timeout=60)
        except CmsTimeout:
            pass
        s._send('IPL CMS')
        try:
            s._read_until(PROMPT, timeout=120)
        except CmsTimeout:
            pass
        s._logged_in = True
        r = s.command('CP QUERY USERID', timeout=40)
        if userid in r.output:
            return s
        s.close()
    raise SystemExit(f'could not log on as {userid}')


def close_session(s):
    try:
        s._send('LOGOFF')
        time.sleep(5)
        s._drain(3)
    except Exception:  # noqa: BLE001
        pass
    finally:
        s.close()


def scan(disks, state, state_path, log=print, session=None):
    s = session or open_session()
    try:
        for d in disks:
            key = f"{d['user']}/{d['vdev']}"
            if key in state['done']:
                continue
            entry = {'user': d['user'], 'vdev': d['vdev'], 'vol': d['vol'],
                     'size': d['size'], 'files': 0, 'status': 'ok'}
            try:
                r = s.command(f"CP LINK {d['user']} {d['vdev']} {SCRATCH} RR", timeout=60)
                if r.rc not in (None, 0):
                    r = s.command(f"CP LINK {d['user']} {d['vdev']} {SCRATCH} SR", timeout=60)
                if r.rc not in (None, 0):
                    entry['status'] = 'link-failed'
                    entry['error'] = r.output.strip().splitlines()[0][:100] if r.output.strip() else ''
                    continue
                r = s.command(f'ACCESS {SCRATCH} {MODE}', timeout=60)
                if r.rc not in (None, 0):
                    entry['status'] = 'access-failed'
                    entry['error'] = r.output.strip().splitlines()[0][:100] if r.output.strip() else ''
                    continue
                r = s.command(f'LISTFILE * * {MODE} (DATE L)', timeout=300)
                rows = parse_listfile(r.output)
                for row in rows:
                    row.update({'user': d['user'], 'vdev': d['vdev'], 'vol': d['vol']})
                state['files'].extend(rows)
                entry['files'] = len(rows)
            except Exception as exc:  # noqa: BLE001
                entry['status'] = 'error'
                entry['error'] = str(exc)[:200]
            finally:
                try:
                    s.command(f'RELEASE {MODE} (DET', timeout=60)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    if s.command(f'CP QUERY VIRTUAL {SCRATCH}', timeout=60).rc in (None, 0):
                        s.command(f'CP DETACH {SCRATCH}', timeout=60)
                except Exception:  # noqa: BLE001
                    pass
            state['done'][key] = entry
            save_state(state, state_path)
            if len(state['done']) % 10 == 0:
                log(f"{len(state['done'])} disks, {len(state['files'])} files")
    finally:
        if session is None:
            close_session(s)
    return state


def write_database(state, path):
    rows = []
    for f in state['files']:
        rows.append((f"{f['user']:<8} {f['vdev']:<5} {f['fn']:<8} {f['ft']:<8} "
                     f"{f['fm']:<2} {f['recs']:>6} {f['date']}").rstrip())
    rows.sort()
    with open(path, 'w', newline='\r\n') as fh:
        for r in rows:
            fh.write(r + '\n')
    return len(rows)


def install(database, find_exec, log=print):
    s = open_session()
    try:
        _open_ftp(s)
        for remote, local in ((database, 'FINDBASE.DATA.A'), ):
            s._send(f'GET {remote} {local} (REPLACE')
            s._read_until(re.compile(r"(?m)^\s*Command:\s*$"), timeout=900)
        s._send(f'GET {find_exec} FIND.EXEC.A (REPLACE')
        s._read_until(re.compile(r"(?m)^\s*Command:\s*$"), timeout=300)
        s._send('QUIT')
        try:
            s._read_until(PROMPT, timeout=60)
        except CmsTimeout:
            pass
        for c in ('LISTFILE FINDBASE DATA A (DATE L)', 'LISTFILE FIND EXEC A (DATE L)'):
            log(s.command(c, timeout=120).output)
    finally:
        close_session(s)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--directory', help='CP directory source file')
    ap.add_argument('--state', default='findscan.json')
    ap.add_argument('--database', default='findbase.data')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--install', action='store_true')
    ap.add_argument('--find-exec', default='FIND.EXEC')
    args = ap.parse_args(argv)

    if args.install:
        install(args.database, args.find_exec)
        return 0
    if not args.directory:
        ap.error('--directory is required unless --install is used')
    disks = parse_directory(args.directory)
    if args.limit:
        disks = disks[:args.limit]
    state = load_state(args.state)
    scan(disks, state, args.state)
    count = write_database(state, args.database)
    print(f'{len(state["done"])} disks scanned, {count} records written')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
