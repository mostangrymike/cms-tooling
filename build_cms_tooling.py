"""Build and validate an isolated offline source distribution. Never connect to CMS."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import secrets
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile


#: Non-Python files the distribution promises to ship.  Everything else is
#: reached by following imports from the entry points below.
SUPPORT_FILES = (
    "AGENTS.md", ".gitignore", "README.md", "TELNET-DRIVER.md", "BRIDGE.md",
    "ci/cms-tooling.yml",
)

#: Python files the distribution deliberately exposes.  Local modules they
#: import are added transitively, so a new dependency cannot be forgotten.
ENTRY_POINTS = (
    "build_cms_tooling.py", "cms_telnet_driver.py", "cms_ftpput.py", "cms_folder.py",
    "cms_credentials.py", "github_tls_bridge.py",
    "cms_mdisk_plan.py", "cms_mdisk_directory.py", "cms_mdisk_cp.py",
    "cms_mdisk_inventory.py", "cms_mdisk_lifecycle.py", "cms_mdisk_receipts.py",
    "test_cms_build.py", "test_cms_telnet_driver.py",
    "test_cms_ftptransfer.py", "test_cms_mdisk_plan.py",
    "test_cms_mdisk_directory.py", "test_cms_mdisk_cp.py",
    "test_cms_mdisk_inventory.py", "test_cms_mdisk_lifecycle.py",
    "test_cms_mdisk_receipts.py", "test_cms_folder.py",
    "test_cms_profiles.py", "test_cms_profiles_offline_end2end.py",
    "test_cms_telnet_profile.py",
    "test_github_tls_bridge.py",
)

#: Every tracked Python module that is deliberately not shipped, with the
#: reason it stays out.  The build fails when a tracked module is missing from
#: both this table and the import closure, so drift is a build error instead of
#: a silent omission.
EXCLUDED_SOURCES: dict[str, str] = {}


def tracked_python(root):
    """Return tracked top-level module names, or None outside a Git work tree.

    Git is authoritative when present: it also lets the caller notice an
    exclusion that names a file nobody tracks.  Outside a work tree the caller
    falls back to the files that actually exist.
    """
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--', '*.py'],
                            capture_output=True)
    if result.returncode:
        return None
    return sorted(name for name in result.stdout.decode().split('\0') if name)


def local_sources(root):
    """Return (importable, required, authoritative) top-level Python sources.

    `importable` also includes an untracked file at the top level, so a module
    that exists on disk is never silently dropped from the bundle.  `required`
    is the authoritative set the build must account for: Git's tracked files
    when available, otherwise the files on disk.  `authoritative` says whether
    an exclusion that names an absent file is a real error or just a source
    tree without Git metadata.
    """
    root = Path(root)
    on_disk = {path.name for path in root.glob('*.py')}
    tracked = tracked_python(root)
    if tracked is None:
        return sorted(on_disk), sorted(on_disk), False
    nested = sorted(name for name in tracked if '/' in name)
    if nested:
        raise ValueError("Nested Python sources cannot enter the flat bundle: " + ", ".join(nested))
    return sorted(set(tracked) | on_disk), tracked, True


def imported_modules(path):
    """Top-level module names imported anywhere in one source file."""
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise ValueError(f"Relative import cannot survive the flat bundle: {path}")
            if node.module:
                names.add(node.module.split('.')[0])
    return names


def source_files(root, entry_points=ENTRY_POINTS, support_files=SUPPORT_FILES,
                 excluded=EXCLUDED_SOURCES):
    """Resolve the explicit distribution manifest from the import graph.

    Returns support files plus every local module reachable from the entry
    points.  Raises ValueError instead of silently shipping an incomplete
    bundle: a tracked module that is neither imported nor explicitly excluded
    fails the build, as does an exclusion that is actually imported or that
    names a file Git does not track.
    """
    root = Path(root)
    files = set(support_files)
    for name in files:
        if not (root / name).is_file():
            raise ValueError(f"Distribution support file is missing: {name}")
    if any(not reason.strip() for reason in excluded.values()):
        raise ValueError("Every excluded source needs a non-empty reason")

    importable, required, authoritative = local_sources(root)
    reached = set()
    pending = list(entry_points)
    while pending:
        name = pending.pop()
        if name in reached:
            continue
        if not (root / name).is_file():
            raise ValueError(f"Distribution entry point is missing: {name}")
        reached.add(name)
        for module in imported_modules(root / name):
            candidate = module + '.py'
            if candidate in importable and candidate not in reached:
                pending.append(candidate)

    unknown = sorted(set(required) - reached - set(excluded))
    if unknown:
        raise ValueError("Tracked Python modules are neither reachable from an entry point "
                         "nor explicitly excluded with a reason: " + ", ".join(unknown))
    imported = sorted(set(excluded) & reached)
    if imported:
        raise ValueError("Excluded source is imported by a bundled module: " + ", ".join(imported))
    untracked = sorted(set(excluded) - set(required))
    if untracked and authoritative:
        raise ValueError("Exclusion names an untracked source: " + ", ".join(untracked))
    return tuple(sorted(files | reached))

UNIT_CHECK = """
import json, unittest
suite = unittest.defaultTestLoader.discover('.', pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=1).run(suite)
print(json.dumps({'passed': result.wasSuccessful() and not result.skipped,
    'tests_run': result.testsRun, 'failures': len(result.failures),
    'errors': len(result.errors), 'skipped': len(result.skipped)}))
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
"""


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def source_payloads(root, credential_file=None):
    payloads = {}
    for name in source_files(root):
        path = root / name
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise ValueError(f"Distribution source must be a regular non-symlink file: {name}")
        if path.stat().st_size > 2 * 1048576:
            raise ValueError(f"Distribution source is unexpectedly large: {name}")
        payloads[name] = path.read_bytes()
    if credential_file:
        from cms_credentials import FileCredentialProvider
        credentials = FileCredentialProvider(credential_file).load()
        # Print only the offending filename; never disclose the matched value.
        for name, payload in payloads.items():
            if credentials.password.encode('ascii').lower() in payload.lower():
                raise ValueError(f"Known local credential found in distribution input: {name}")
    return payloads


def write_bundle(path, payloads):
    manifest = {"schema": "cms-tooling-source-v1", "files": {
        name: {"bytes": len(payload), "sha256": digest(payload)}
        for name, payload in sorted(payloads.items())}}
    contents = {**payloads, "SOURCE-MANIFEST.json": (json.dumps(manifest, indent=2) + '\n').encode()}
    # Stable metadata and gzip timestamp make equal inputs produce equal bytes.
    with path.open('xb') as output:
        with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for name, payload in sorted(contents.items()):
                    member = tarfile.TarInfo('cms-tooling/' + name)
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
    if not shutil.which('git'):
        raise RuntimeError("Full offline validation requires git on PATH")
    output_root = output_root.absolute()
    if any(path.is_symlink() for path in (output_root, *output_root.parents)):
        raise ValueError('Build output must not traverse symlinks')
    output_root.mkdir(parents=True, exist_ok=True)
    directory = output_root / ('build-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + secrets.token_hex(4))
    directory.mkdir(mode=0o700)
    bundle = directory / 'cms-tooling.tar.gz'
    manifest = write_bundle(bundle, payloads)
    report = {'schema': 'cms-tooling-offline-build-v1', 'passed': False,
              'bundle': str(bundle), 'bundle_sha256': digest(bundle.read_bytes()),
              'source_file_count': len(payloads), 'source_manifest': manifest,
              'excluded_sources': dict(EXCLUDED_SOURCES),
              'known_credential_scan': 'passed' if credential_file else 'not_requested',
              'runtime': {'python': sys.version, 'platform': platform.platform(),
                          'tools': {name: shutil.which(name) for name in ('git',)}},
              'live_connection_performed': False, 'checks': {}}
    try:
        with tempfile.TemporaryDirectory(prefix='cms_tooling_build_') as temp:
            reproduced = Path(temp) / 'reproduced.tar.gz'
            write_bundle(reproduced, payloads)
            if reproduced.read_bytes() != bundle.read_bytes():
                raise ValueError('Equal source inputs did not reproduce the source archive')
            report['bundle_reproduced'] = True
            with tarfile.open(bundle, 'r:gz') as archive:
                archive.extractall(temp, filter='data')
            isolated = Path(temp) / 'cms-tooling'
            for name, details in manifest['files'].items():
                if digest((isolated / name).read_bytes()) != details['sha256']:
                    raise ValueError(f'Extracted source hash differs: {name}')
            checks = report['checks']
            checks['unit_tests'] = run_json(isolated, ['-c', UNIT_CHECK])
            if not checks['unit_tests']['passed']:
                raise ValueError('Offline unit tests failed')
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
