"""Observe only the documented G-disk attachment, directory mapping and volume links."""
import argparse
import json
from pathlib import Path
import re

from zvm_credentials import FileCredentialProvider
from zvm_mcp import Session


def access_gate(observations, secrets):
    """Require exact documented geometry, mapping, known links, and unused G."""
    def rows(name):
        result = observations[name]
        if not result.get('ok') or not result.get('output_complete') or 'output_rows' not in result:
            raise ValueError('Complete correlated diagnostic output is required')
        return result['output_rows']
    owner = 'MAINT'
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            owner = re.sub(re.escape(secret), lambda match: '*' * len(match[0]), owner, flags=re.I)
    virtual = [row for row in rows('virtual') if row.startswith('DASD 0600 ')]
    if len(virtual) != 1 or not re.fullmatch(
            r'DASD 0600 3390 VMCOM1 R/W\s+1600 CYL ON DASD\s+0127 SUBCHANNEL = [0-9A-F]{4}', virtual[0]):
        raise ValueError('Virtual 0600 is not the exact documented existing disk')
    expected = [owner, '0600', owner, '0600', '3390', 'VMCOM1', '0127', '6000', '1600']
    for name in ('location', 'directory'):
        mappings = [row.split() for row in rows(name) if len(row.split()) == 9 and row.split()[1] == '0600']
        if mappings != [expected]:
            raise ValueError('Current and directory physical mappings must match exactly')
    volume = rows('volume')
    links = []
    for row in volume:
        if row.startswith('DASD '):
            continue
        for entry in row.split(','):
            parts = entry.split()
            if len(parts) != 3 or parts[2] not in {'R/W', 'R/O'}:
                raise ValueError('Unrecognized volume-link row')
            links.append(tuple(parts))
    expected_links = {(owner, '0600', 'R/W'), (owner, '0551', 'R/O'),
                      (owner, '02CC', 'R/W'), (owner, '049E', 'R/O')}
    expected_links.update(('VMSERVP', address, 'R/W') for address in
        ('0311', '0310', '0309', '0308', '0307', '0306', '0305', '0304', '0303', '0301', '0302', '0191'))
    if (len(links) != 16 or set(links) != expected_links
            or not any(re.fullmatch(r'DASD 0127 ATTACHED CPVOL\s+0016 VMCOM1', row) for row in volume)):
        raise ValueError('Unexpected volume links; do not access the protected disk')
    disk = [row.split() for row in rows('disk') if len(row.split()) >= 7 and row.split()[1] != 'VDEV']
    if not disk or any(parts[2].split('/')[0] == 'G' or parts[1].lstrip('0') == '600' for parts in disk):
        raise ValueError('G or virtual 600 is already accessed; no access change allowed')
    return {'exact_virtual_geometry': True, 'current_and_directory_mapping_match': True,
            'volume_links_match_documented_baseline': True, 'G_and_600_not_accessed': True,
            'writer_exclusion_established': False, 'replacement_safe': False}


def validate(args):
    provider = FileCredentialProvider(args.credential_file)
    session = Session(allow_login=True, allow_startup=True, allow_query_links=True,
                      allow_commands=args.access_existing_g, runner_name='ZM537EF1',
                      credential_provider=provider)
    evidence = {'purpose': __doc__, 'observations': {}, 'disk_changes_performed': False,
                'source_replacement_performed': False}

    def persist():
        args.output.write_text(json.dumps(evidence, indent=2) + '\n')

    try:
        stages = [('connect', lambda: session.connect('0200@', timeout=15)),
                  ('initial_screen', lambda: session.screen(wait_output=True, timeout=10)),
                  ('login', lambda: session.login(timeout=30)),
                  ('startup', lambda: session.startup(verify_cms=True, timeout=45))]
        for name, action in stages:
            result = action()
            evidence[name] = result
            persist()
            print(json.dumps({'stage': name, 'ok': result['ok'], 'outcome': result.get('outcome')}), flush=True)
            if not result['ok']:
                return evidence
        for name in ('virtual', 'location', 'directory', 'volume', 'disk'):
            result = session.link_query.inspect_g(name, timeout=45)
            evidence['observations'][name] = result
            persist()
            print(json.dumps({'stage': name, 'ok': result['ok'],
                'command': result.get('command'), 'page_count': result.get('page_count')}), flush=True)
            if not result['ok']:
                return evidence
        # Capture completion is not a claim that attachment/mapping is correct,
        # that the CP command returned zero, or that any disk is safe to write.
        evidence['observation_complete'] = True
        if args.access_existing_g:
            if provider.load().userid != 'MAINT':
                raise ValueError('The existing-disk access procedure is scoped to its documented owner')
            evidence['access_gate'] = access_gate(evidence['observations'], session.secrets)
            evidence['disk_access_change_attempted'] = True
            evidence['disk_changes_performed'] = None
            persist()
            result = session.link_query._observe('ACCESS 600 G', '600', 30)
            result['host_operations_performed'] = True
            evidence['access'] = result
            persist()
            if not result['ok']:
                return evidence
            prepared = session.runner.prepare(create=False)
            evidence['runner'] = prepared
            persist()
            if not prepared['ok']:
                return evidence
            evidence['postchecks'] = []
            for command in ('QUERY DISK', 'STATE M173NET STAGE G1', 'STATE M174NET INDEX G1'):
                checked = session.runner.run(command, timeout=60)
                evidence['postchecks'].append(checked)
                persist()
                print(json.dumps({'stage': 'postcheck', 'command': command,
                                  'ok': checked['ok'], 'cms_rc': checked.get('cms_rc')}), flush=True)
                if not checked['ok'] or checked.get('cms_rc') != 0:
                    return evidence
            matches = [row.split() for row in evidence['postchecks'][0]['records']
                       if row.startswith('GIT600 ')]
            if (len(matches) != 1 or matches[0][1:7] != ['600', 'G', 'R/W', '1600', '3390', '4096']):
                raise ValueError('G access metadata does not match the protected disk')
            evidence['disk_changes_performed'] = True
            evidence['G_access_verified'] = True
        return evidence
    except Exception as exc:
        evidence['error_type'] = type(exc).__name__
        evidence['message'] = session.redact(str(exc))
        return evidence
    finally:
        evidence['disconnect'] = session.disconnect()
        persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--credential-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--access-existing-g', action='store_true',
        help='Explicitly assign verified existing 0600 to unused G; never LINK, FORMAT, replace or erase')
    args = parser.parse_args()
    result = validate(args)
    print(json.dumps({'observation_complete': result.get('observation_complete', False),
                      'G_access_verified': result.get('G_access_verified', False),
                      'disk_changes_performed': result.get('disk_changes_performed'),
                      'source_replacement_performed': False}))
    return 0 if result.get('observation_complete') and (not args.access_existing_g or result.get('G_access_verified')) else 1


if __name__ == '__main__':
    raise SystemExit(main())
