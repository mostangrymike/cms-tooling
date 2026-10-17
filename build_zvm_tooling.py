"""Build and validate an isolated offline source distribution. Never connect to CMS."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
from importlib.metadata import version
import json
from pathlib import Path
import secrets
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile


SOURCE_FILES = (
    "AGENTS.md", ".gitignore", "README.md", "MIGRATION.md", "README-zvm-mcp.md", "VALIDATION-zvm-mcp.md", "PIPELINE-READINESS.md",
    "V1-PROGRESS.md", "CMS-C-RECIPE.md",
    "requirements-zvm-mcp.txt", "ZMCPRUN.EXEC", "ZMCPGET.EXEC", "ZMCPQUAL.EXEC",
    "zvm_mcp.py", "zvm_capture.py", "zvm_commands.py", "zvm_credentials.py",
    "zvm_download.py", "zvm_edit.py", "zvm_upload.py", "zvm_link_query.py", "zvm_operations.py", "zvm_rehearsal.py", "zvm_native_review.py",
    "diagnose_zvm_cms.py", "verify_codex_zvm.py", "build_zvm_tooling.py", "validate_zvm_compiler.py", "validate_zvm_fixture.py",
    "fixtures/README.md", "fixtures/terminal-screens.json",
    "fixtures/qualification/baseline/ZTQUAL.C", "fixtures/qualification/candidate/ZTQUAL.C",
    "ci/zvm-tooling.yml",
) + tuple(f"validate_zvm_{name}.py" for name in ("mcp", "login", "commands", "download", "edit", "upload", "operations", "rehearsal", "gdisk")) + tuple(
    f"test_zvm_{name}.py" for name in
    ("mcp", "login", "startup", "capture", "commands", "download", "edit", "upload", "link_query", "fixtures", "operations", "rehearsal", "native_review", "compiler", "fixture")
)

UNIT_CHECK = """
import json, unittest
suite = unittest.defaultTestLoader.discover('.', pattern='test_zvm_*.py')
result = unittest.TextTestRunner(verbosity=1).run(suite)
print(json.dumps({'passed': result.wasSuccessful() and not result.skipped,
    'tests_run': result.testsRun, 'failures': len(result.failures),
    'errors': len(result.errors), 'skipped': len(result.skipped)}))
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
"""

PREPARE_REVIEW = """
import json, subprocess
from pathlib import Path
from zvm_download import metadata, save_snapshot
repo = Path('review-fixture').resolve()
repo.mkdir()
subprocess.run(['git', 'init', '-q', str(repo)], check=True)
records = [line.ljust(80).encode('cp037') for line in Path('ZMCPRUN.EXEC').read_text(encoding='ascii').splitlines()]
meta = metadata([f'ZM537EF1 EXEC A1 F 80 {len(records)} 2 01/01/00 00:00:00 FIXTURE'], ('ZM537EF1', 'EXEC', 'A1'))
root = repo / 'sources'
result = save_snapshot(root, repo, meta, records, [])
print(json.dumps({'root': str(root), 'snapshot': Path(result['snapshot_directory']).name}))
"""


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def source_payloads(root, credential_file=None):
    payloads = {}
    for name in SOURCE_FILES:
        path = root / name
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise ValueError(f"Distribution source must be a regular non-symlink file: {name}")
        if path.stat().st_size > 2 * 1048576:
            raise ValueError(f"Distribution source is unexpectedly large: {name}")
        payloads[name] = path.read_bytes()
    if credential_file:
        from zvm_credentials import FileCredentialProvider
        credentials = FileCredentialProvider(credential_file).load()
        # Print only the offending filename; never disclose the matched value.
        for name, payload in payloads.items():
            if credentials.password.encode('ascii').lower() in payload.lower():
                raise ValueError(f"Known local credential found in distribution input: {name}")
    return payloads


def write_bundle(path, payloads):
    manifest = {"schema": "zvm-tooling-source-v1", "files": {
        name: {"bytes": len(payload), "sha256": digest(payload)}
        for name, payload in sorted(payloads.items())}}
    contents = {**payloads, "SOURCE-MANIFEST.json": (json.dumps(manifest, indent=2) + '\n').encode()}
    # Stable metadata and gzip timestamp make equal inputs produce equal bytes.
    with path.open('xb') as output:
        with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for name, payload in sorted(contents.items()):
                    member = tarfile.TarInfo('zvm-tooling/' + name)
                    member.mode, member.mtime, member.size = 0o644, 0, len(payload)
                    archive.addfile(member, io.BytesIO(payload))
    return manifest


def run_json(cwd, arguments):
    result = subprocess.run([sys.executable, '-B', *arguments], cwd=cwd,
                            capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError(f"Offline check failed ({arguments[0]}): " + (result.stderr or result.stdout)[-8000:])
    return json.loads(result.stdout)


def build(output_root, credential_file=None):
    root = Path(__file__).resolve().parent
    payloads = source_payloads(root, credential_file)
    for program in ('git', 's3270', 'rexx'):
        if not shutil.which(program):
            raise RuntimeError(f"Full offline validation requires {program} on PATH")
    output_root = output_root.absolute()
    if any(path.is_symlink() for path in (output_root, *output_root.parents)):
        raise ValueError('Build output must not traverse symlinks')
    output_root.mkdir(parents=True, exist_ok=True)
    directory = output_root / ('build-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + secrets.token_hex(4))
    directory.mkdir(mode=0o700)
    bundle = directory / 'zvm-tooling.tar.gz'
    manifest = write_bundle(bundle, payloads)
    report = {'schema': 'zvm-tooling-offline-build-v1', 'passed': False,
              'bundle': str(bundle), 'bundle_sha256': digest(bundle.read_bytes()),
              'source_file_count': len(payloads), 'source_manifest': manifest,
              'known_credential_scan': 'passed' if credential_file else 'not_requested',
              'runtime': {'python': sys.version, 'platform': platform.platform(),
                          'mcp': version('mcp'), 'py3270': version('py3270'),
                          'tools': {name: shutil.which(name) for name in ('git', 's3270', 'rexx')}},
              'live_connection_performed': False, 'checks': {}}
    try:
        with tempfile.TemporaryDirectory(prefix='zvm_tooling_build_') as temp:
            reproduced = Path(temp) / 'reproduced.tar.gz'
            write_bundle(reproduced, payloads)
            if reproduced.read_bytes() != bundle.read_bytes():
                raise ValueError('Equal source inputs did not reproduce the source archive')
            report['bundle_reproduced'] = True
            with tarfile.open(bundle, 'r:gz') as archive:
                archive.extractall(temp, filter='data')
            isolated = Path(temp) / 'zvm-tooling'
            for name, details in manifest['files'].items():
                if digest((isolated / name).read_bytes()) != details['sha256']:
                    raise ValueError(f'Extracted source hash differs: {name}')
            checks = report['checks']
            checks['unit_tests'] = run_json(isolated, ['-c', UNIT_CHECK])
            checks['protocol_default'] = run_json(isolated, ['validate_zvm_mcp.py'])
            checks['protocol_auto'] = run_json(isolated, ['validate_zvm_mcp.py', '--device', 'auto'])
            checks['upload_disabled'] = run_json(isolated, ['validate_zvm_upload.py'])
            snapshot = run_json(isolated, ['-c', PREPARE_REVIEW])
            review_path = directory / 'local-review-evidence.json'
            checks['local_review'] = run_json(isolated, ['validate_zvm_edit.py',
                '--root', snapshot['root'], '--snapshot', snapshot['snapshot'], '--output', str(review_path)])
            review = json.loads(review_path.read_text())
            if not review.get('passed') or not all(review.get('verification', {}).values()):
                raise ValueError('Isolated local review verification did not pass')
            report['review_verification'] = review['verification']
            operation_path = directory / 'operation-review-evidence.json'
            edited = review['edited']
            checks['operation_review'] = run_json(isolated, ['validate_zvm_operations.py',
                '--root', snapshot['root'], '--edit-id', edited['edit_id'],
                '--plan-id', edited['plan_id'], '--plan-sha256', edited['plan_sha256'],
                '--output', str(operation_path)])
            operation = json.loads(operation_path.read_text())
            if not operation.get('passed') or not all(operation.get('verification', {}).values()):
                raise ValueError('Isolated operation review verification did not pass')
            report['operation_verification'] = operation['verification']
            rehearsal = run_json(isolated, ['validate_zvm_rehearsal.py'])
            if not rehearsal.get('passed') or not all(rehearsal.get('verification', {}).values()):
                raise ValueError('Isolated transaction failure rehearsal did not pass')
            with (directory / 'rehearsal-evidence.json').open('x') as output:
                json.dump(rehearsal, output, indent=2)
                output.write('\n')
            checks['failure_rehearsal'] = {key: value for key, value in rehearsal.items() if key != 'suite'}
            # Temporary working files are intentionally discarded after the test;
            # the report retains verification results, not durable review links.
            report['temporary_review_workspace_retained'] = False
            if not checks['unit_tests']['passed'] or not checks['upload_disabled']['write_disabled_by_default']:
                raise ValueError('Offline build gates failed')
            report['passed'] = True
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        with (directory / 'build-report.json').open('x') as output:
            json.dump(report, output, indent=2)
            output.write('\n')
    return directory, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, default=Path(__file__).resolve().parent / 'builds')
    parser.add_argument('--credential-file', help='Optional owner-only credential file for a local password scan')
    args = parser.parse_args()
    try:
        directory, report = build(args.output_root, args.credential_file)
    except Exception as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps({'passed': report['passed'], 'build_directory': str(directory),
                      'bundle_sha256': report['bundle_sha256'], 'source_file_count': report['source_file_count'],
                      'tests': report['checks'].get('unit_tests'), 'error': report.get('error')}))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
