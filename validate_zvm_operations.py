"""Validate an actual MCP operation review while disconnected. Never connect to CMS."""
import argparse
import asyncio
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from validate_zvm_mcp import EXPECTED, content
from zvm_edit import read_file


async def validate(args):
    script = Path(__file__).with_name('zvm_mcp.py').resolve()
    launch = [str(script), '--allow-local-edits', '--download-root', str(args.root)]
    if args.credential_file:
        launch += ['--credential-file', str(args.credential_file)]
    recipe = json.loads(read_file(args.recipe_file, 65536)) if args.recipe_file else {}
    evidence = {'purpose': __doc__, 'passed': False}

    def persist():
        args.output.write_text(json.dumps(evidence, indent=2) + '\n')

    async with stdio_client(StdioServerParameters(command=sys.executable, args=launch, cwd=str(script.parent))) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=45)) as client:
            await client.initialize()
            if {tool.name for tool in (await client.list_tools()).tools} != EXPECTED:
                raise RuntimeError('Unexpected MCP tool catalog')
            try:
                evidence['before'] = content(await client.call_tool('zvm_status', {}))
                if evidence['before'].get('state') != 'disconnected':
                    raise RuntimeError('Local operation validation must start disconnected')
                result = content(await client.call_tool('zvm_operation_plan', {
                    'edit_id': args.edit_id, 'plan_id': args.plan_id,
                    'plan_sha256': args.plan_sha256, 'recipe': recipe}))
                evidence['operation'] = result
                persist()
                if not result.get('ok'):
                    return evidence
                raw = read_file(Path(result['operation_file']), 2 * 1048576)
                receipt = json.loads(raw)
                evidence['after'] = content(await client.call_tool('zvm_status', {}))
                evidence['verification'] = {
                    'operation_hash_matches': hashlib.sha256(raw).hexdigest() == result['operation_sha256'],
                    'source_plan_pinned': receipt['source_plan_sha256'] == args.plan_sha256,
                    'execution_not_authorized': receipt['execution_authorized'] is False,
                    'execution_not_implemented': receipt['execution_implemented'] is False,
                    'replacement_not_safe': receipt['replacement_safe'] is False,
                    'writer_exclusion_not_claimed': receipt['writer_exclusion_verified'] is False,
                    'host_operations_not_performed': receipt['host_operations_performed'] is False,
                    'still_disconnected': evidence['after'].get('state') == 'disconnected',
                }
            except Exception as exc:
                evidence['error_type'] = type(exc).__name__
            finally:
                evidence['disconnect'] = content(await client.call_tool('zvm_disconnect', {}))
                checks = evidence.get('verification', {})
                evidence['passed'] = (len(checks) == 8 and all(checks.values())
                    and evidence['disconnect'].get('ok') is True
                    and evidence['disconnect'].get('terminated') is False)
                persist()
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--edit-id', required=True)
    parser.add_argument('--plan-id', required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--recipe-file', type=Path, help='Optional bounded local JSON recipe; absent fields are reported')
    parser.add_argument('--credential-file', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(validate(args))
    print(json.dumps({'passed': result['passed'], 'operation': result.get('operation'),
                      'verification': result.get('verification'), 'error_type': result.get('error_type')}))
    raise SystemExit(0 if result['passed'] else 1)
