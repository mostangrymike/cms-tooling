"""Explicit live native source backup, optionally checked against exact local source."""
import argparse
import asyncio
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from validate_cms_mcp import content, EXPECTED
from cms_mcp import device_selector


async def validate(args):
    server=Path(__file__).with_name('cms_mcp.py').resolve()
    launch=[str(server),'--allow-login','--allow-startup','--allow-commands',
            '--runner-name','ZM537EF1','--allow-downloads','--download-root',str(args.download_root),
            '--credential-file',str(args.credential_file),'--device',args.device]
    if args.reader_name:launch.extend(['--download-runner-name',args.reader_name])
    evidence={'purpose':__doc__}
    def persist():args.output.write_text(json.dumps(evidence,indent=2)+'\n')
    async with stdio_client(StdioServerParameters(command=sys.executable,args=launch,cwd=str(server.parent))) as (reader,writer):
        async with ClientSession(reader,writer,read_timeout_seconds=timedelta(seconds=360)) as client:
            await client.initialize()
            if not ({t.name for t in (await client.list_tools()).tools}==EXPECTED):
                raise RuntimeError('Unexpected MCP tool inventory')
            try:
                for stage,tool,params in [('connect','cms_connect',{}),
                    ('initial_screen','cms_screen',{'wait_output':True,'timeout':10}),
                    ('login','cms_login',{}),('startup','cms_startup',{'verify_cms':True}),
                    ('download','cms_download',{'filename':args.filename,'filetype':args.filetype,'filemode':args.filemode,
                                               'create_runner':args.create_reader,'timeout':300})]:
                    result=content(await client.call_tool(tool,params));evidence[stage]=result;persist()
                    print(json.dumps({'stage':stage,**{k:result.get(k) for k in ('ok','outcome','reader','record_count','byte_count','download_complete')}}),flush=True)
                    if not result['ok']:return evidence
                result=evidence['download']
                actual=Path(result['native_file']).read_bytes()
                if args.expected_native:
                    expected=Path(args.expected_native).read_bytes()
                    evidence['expected_native_sha256']=hashlib.sha256(expected).hexdigest()
                    evidence['downloaded_native_sha256']=hashlib.sha256(actual).hexdigest()
                    evidence['candidate_readback_equal']=actual==expected
                    if actual!=expected:
                        persist()
                        return evidence
                elif args.snapshot_only:
                    expected=actual
                else:
                    source=args.expected_source or server.with_name('ZMCPRUN.EXEC')
                    lines=source.read_text(encoding='ascii').splitlines()
                    if not (lines and all(len(line)<=80 for line in lines)):
                        raise RuntimeError('Expected source must contain records no wider than 80 characters')
                    expected=b''.join(line.ljust(80).encode('cp037') for line in lines)
                    if not (actual==expected):
                        raise RuntimeError('Native downloaded source differs from the expected local source')
                manifest=json.loads(Path(result['manifest']).read_text())
                if not (manifest['cms']['recfm']=='F' and manifest['cms']['lrecl']==80):
                    raise RuntimeError('Expected fixed-80 snapshot metadata')
                if not (manifest['sha256']==hashlib.sha256(expected).hexdigest()):
                    raise RuntimeError('Snapshot hash differs from expected native bytes')
                if not (manifest['record_lengths']==[80]*(len(expected)//80)):
                    raise RuntimeError('Snapshot record boundaries differ from expected fixed-80 records')
                if not (all(step.get('cms_rc',0)==0 for step in manifest['verification'])):
                    raise RuntimeError('Snapshot evidence contains a nonzero CMS return code')
                evidence['native_snapshot_verified']=True
                evidence['known_source_verified']=not args.snapshot_only
                evidence['snapshot_only']=args.snapshot_only
                persist()
            finally:
                evidence['disconnect']=content(await client.call_tool('cms_disconnect',{}));persist()
    return evidence


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',required=True,action='store_true')
    p.add_argument('--create-reader',action='store_true')
    p.add_argument('--reader-name')
    p.add_argument('--device',type=device_selector,default='0200@')
    p.add_argument('--credential-file',type=Path,required=True)
    p.add_argument('--download-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--filename',default='ZM537EF1')
    p.add_argument('--filetype',default='EXEC')
    p.add_argument('--filemode',default='A1')
    expected=p.add_mutually_exclusive_group()
    expected.add_argument('--expected-native',type=Path)
    expected.add_argument('--expected-source',type=Path,help='Exact ASCII source for fixed-80 native comparison')
    expected.add_argument('--snapshot-only',action='store_true',help='Verify native backup integrity without claiming equality to a local candidate')
    args=p.parse_args()
    if args.create_reader and args.reader_name:p.error('Select new-reader creation OR existing-reader reuse')
    e=asyncio.run(validate(args))
    passed=e.get('native_snapshot_verified',False) and e.get('download',{}).get('download_complete',False)
    print(json.dumps({'passed':passed,'disconnect':e.get('disconnect')}),flush=True)
    raise SystemExit(0 if passed else 1)
