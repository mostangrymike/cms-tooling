"""Offline gate check or one exact create-only upload with optional native verification."""
import argparse
import asyncio
import hashlib
import json
from datetime import timedelta
from pathlib import Path
import re
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from validate_zvm_mcp import content, EXPECTED
from zvm_mcp import device_selector


def validation_passed(evidence):
    if not evidence.get('live_create'):
        return evidence.get('write_disabled_by_default') is True
    upload = evidence.get('upload', {})
    passed = (all(evidence.get(stage, {}).get('ok') is True
                  for stage in ('connect', 'login', 'startup', 'runner', 'upload', 'disconnect'))
              and upload.get('create_only') is True and upload.get('readback_verified') is True
              and upload.get('existing_file_replaced') is False
              and isinstance(upload.get('candidate_sha256'), str)
              and re.fullmatch(r'[0-9a-f]{64}', upload['candidate_sha256']) is not None
              and upload.get('candidate_sha256') == upload.get('readback_sha256'))
    if evidence.get('native_verification_requested'):
        native = evidence.get('native_readback', {})
        passed = (passed and native.get('ok') is True
                  and native.get('download_complete') is True and native.get('candidate_equal') is True)
    return passed


async def run(args):
    script = Path(__file__).with_name('zvm_mcp.py').resolve()
    server_args = [str(script), '--device', args.device]
    live = bool(args.live_create)
    if live:
        server_args += ['--allow-login', '--allow-startup', '--allow-commands',
                        '--runner-name', 'ZM537EF1', '--allow-local-edits',
                        '--allow-create-only-upload', '--download-root', str(Path(args.download_root).resolve()),
                        '--credential-file', args.credential_file]
        if args.verify_native:
            server_args += ['--allow-downloads', '--download-runner-name', args.reader_name]
    params = StdioServerParameters(command=sys.executable, args=server_args, cwd=str(script.parent))
    evidence = {'live_create': live, 'endpoint': '127.0.0.1:3271', 'device': args.device,
                'native_verification_requested': bool(args.verify_native), 'passed': False}

    def persist():
        args.output.write_text(json.dumps(evidence, indent=2) + '\n')

    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=360)) as client:
            await client.initialize()
            evidence['tools'] = sorted(t.name for t in (await client.list_tools()).tools)
            if set(evidence['tools']) != EXPECTED:
                raise RuntimeError('Unexpected MCP tool catalog')
            evidence['status_before'] = content(await client.call_tool('zvm_status', {}))
            if not live:
                status = evidence['status_before']
                evidence['write_disabled_by_default'] = (status.get('state') == 'disconnected'
                    and status.get('create_only_upload_enabled') is False)
                evidence['passed'] = validation_passed(evidence)
                persist()
                return evidence

            async def stage(name, tool, arguments):
                result = content(await client.call_tool(tool, arguments))
                evidence[name] = result
                persist()
                print(json.dumps({'stage': name, **{key: result.get(key) for key in
                    ('ok', 'outcome', 'readback_verified', 'record_count', 'download_complete')}}), flush=True)
                return result.get('ok') is True

            try:
                for name, tool, arguments in [
                    ('connect', 'zvm_connect', {'timeout': 15}),
                    ('login', 'zvm_login', {'timeout': 30}),
                    ('startup', 'zvm_startup', {'timeout': 45, 'verify_cms': True}),
                    ('runner', 'zvm_prepare_runner', {'create': False}),
                    ('upload', 'zvm_upload_create_only', {
                        'edit_id': args.edit_id, 'plan_id': args.plan_id,
                        'plan_sha256': args.plan_sha256, 'target': args.target,
                        'candidate_sha256': args.candidate_sha256, 'timeout': 180}),
                ]:
                    if not await stage(name, tool, arguments):
                        return evidence
                if args.verify_native:
                    filename, filetype, filemode = args.target.split()
                    if not await stage('native_readback', 'zvm_download', {
                            'filename': filename, 'filetype': filetype, 'filemode': filemode,
                            'create_runner': False, 'timeout': 300}):
                        return evidence
                    native = evidence['native_readback']
                    raw = Path(native['native_file']).read_bytes()
                    native['sha256'] = hashlib.sha256(raw).hexdigest()
                    native['candidate_equal'] = native['sha256'] == args.candidate_sha256
                    persist()
            except Exception as exc:
                # Preserve progress and exact target even on SDK/transport failure.
                evidence['validator_error_type'] = type(exc).__name__
                evidence['target'] = args.target
                persist()
            finally:
                evidence['disconnect'] = content(await client.call_tool('zvm_disconnect', {}))
                evidence['passed'] = validation_passed(evidence) and 'validator_error_type' not in evidence
                persist()
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-create', action='store_true', help='Create exactly the supplied absent scratch target')
    parser.add_argument('--edit-id')
    parser.add_argument('--plan-id')
    parser.add_argument('--plan-sha256')
    parser.add_argument('--candidate-sha256')
    parser.add_argument('--target', help='Exact disposable target, e.g. ZV123456 EXEC A1')
    parser.add_argument('--credential-file')
    parser.add_argument('--download-root')
    parser.add_argument('--device', type=device_selector, default='0200@')
    parser.add_argument('--verify-native', action='store_true', help='Also perform two native reads with verified reader')
    parser.add_argument('--reader-name', default='ZM02EA0B')
    parser.add_argument('--output', type=Path, default=Path('zvm-upload-validation-evidence.json'))
    args = parser.parse_args()
    if args.verify_native and not args.live_create:
        parser.error('--verify-native requires --live-create')
    if args.live_create:
        if not all((args.edit_id, args.plan_id, args.plan_sha256, args.candidate_sha256,
                    args.target, args.credential_file, args.download_root)):
            parser.error('Live creation requires exact edit/plan/hash/target and configured local paths')
        if not re.fullmatch(r'ZV[0-9A-F]{6} EXEC A1', args.target):
            parser.error('Target must be an exact ZVxxxxxx EXEC A1 scratch file ID')
    result = asyncio.run(run(args))
    if args.live_create:
        print(json.dumps({'passed': result['passed'], 'target': args.target,
                          'native_candidate_equal': result.get('native_readback', {}).get('candidate_equal'),
                          'disconnect': result.get('disconnect')}), flush=True)
    else:
        print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
