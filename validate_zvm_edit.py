"""Exercise actual MCP local editing against a recorded snapshot. Never connect to a host."""
import argparse
import asyncio
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from validate_zvm_mcp import content, EXPECTED


async def validate(args):
    script=Path(__file__).with_name('zvm_mcp.py').resolve()
    baseline=Path(args.root)/args.snapshot/'records.ebcdic'
    original=baseline.read_bytes()
    manifest_file=baseline.with_name('manifest.json')
    original_manifest=manifest_file.read_bytes()
    launch=[str(script),'--allow-local-edits','--download-root',str(args.root)]
    if args.credential_file:launch.extend(['--credential-file',str(args.credential_file)])
    result={'purpose':__doc__}
    def persist():args.output.write_text(json.dumps(result,indent=2)+'\n')
    async with stdio_client(StdioServerParameters(command=sys.executable,args=launch,cwd=str(script.parent))) as (reader,writer):
        async with ClientSession(reader,writer,read_timeout_seconds=timedelta(seconds=45)) as client:
            await client.initialize()
            if not ({t.name for t in (await client.list_tools()).tools}==EXPECTED):
                raise RuntimeError('Unexpected MCP tool inventory')
            result['before']=content(await client.call_tool('zvm_status',{}))
            if not (result['before']['state']=='disconnected'):
                raise RuntimeError('Local review must start disconnected')
            result['prepare']=content(await client.call_tool('zvm_edit_prepare',{'snapshot':args.snapshot}));persist()
            if not (result['prepare']['ok']):
                raise RuntimeError('Local edit preparation failed')
            edit_id=result['prepare']['edit_id']
            result['no_op']=content(await client.call_tool('zvm_edit_plan',{'edit_id':edit_id}));persist()
            if not (result['no_op']['ok'] and not result['no_op']['changed']):
                raise RuntimeError('Unedited workspace did not produce an unchanged plan')
            if not (Path(result['no_op']['candidate_file']).read_bytes()==original):
                raise RuntimeError('Unedited candidate differs from original native bytes')
            working=Path(result['prepare']['editable_file'])
            text=working.read_text(encoding='utf-8')
            old='No output files or cleanup.'
            new='Local review demo; no host edits.'
            if not (text.count(old)==1):
                raise RuntimeError('Recorded helper fixture does not match the local review demonstration')
            working.write_text(text.replace(old,new,1),encoding='utf-8',newline='\n')
            result['edited']=content(await client.call_tool('zvm_edit_plan',{'edit_id':edit_id}));persist()
            planned=result['edited']
            if not (planned['ok'] and planned['changed'] and not planned['upload_authorized'] and not planned['upload_implemented']):
                raise RuntimeError('Changed edit plan did not retain disabled upload gates')
            plan=json.loads(Path(planned['plan_file']).read_text())
            if not (plan['expected_original']['sha256']==hashlib.sha256(original).hexdigest()):
                raise RuntimeError('Plan baseline hash differs from the original snapshot')
            if not (plan['proposed']['recfm']=='F' and plan['proposed']['lrecl']==80):
                raise RuntimeError('Plan candidate is not fixed-80')
            if not (plan['proposed']['record_lengths']==[80]*63):
                raise RuntimeError('Plan candidate record boundaries differ from the fixture')
            candidate=Path(planned['candidate_file']).read_bytes()
            if not (len(candidate)==len(original) and candidate[:80]!=original[:80] and candidate[80:]==original[80:]):
                raise RuntimeError('Candidate must change only the first record')
            if not (Path(planned['diff_file']).stat().st_size>0 and baseline.read_bytes()==original):
                raise RuntimeError('Diff is empty or the source snapshot changed')
            result['verification']={
                'snapshot_native_unchanged':baseline.read_bytes()==original,
                'snapshot_manifest_unchanged':manifest_file.read_bytes()==original_manifest,
                'baseline_sha256_matches':planned['base_sha256']==hashlib.sha256(original).hexdigest(),
                'candidate_sha256_matches':planned['candidate_sha256']==hashlib.sha256(candidate).hexdigest(),
                'plan_sha256_matches':planned['plan_sha256']==hashlib.sha256(Path(planned['plan_file']).read_bytes()).hexdigest(),
                'only_first_record_changed':candidate[:80]!=original[:80] and candidate[80:]==original[80:],
                'upload_not_authorized':not planned['upload_authorized'],
                'no_host_operations':not planned['host_operations_performed'],
            }
            if not (all(result['verification'].values())):
                raise RuntimeError('Local review evidence verification failed')
            result['after']=content(await client.call_tool('zvm_status',{}))
            if not (result['after']['state']=='disconnected'):
                raise RuntimeError('Local review unexpectedly connected to a host')
            result['disconnect']=content(await client.call_tool('zvm_disconnect',{}))
            if not (not result['disconnect']['terminated']):
                raise RuntimeError('Local review unexpectedly terminated an emulator')
            result['passed']=True;persist()
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--snapshot',required=True)
    p.add_argument('--credential-file',type=Path)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    r=asyncio.run(validate(args))
    print(json.dumps({'passed':r['passed'],'edit_id':r['prepare']['edit_id'],
        'plan_file':r['edited']['plan_file'],'diff_file':r['edited']['diff_file'],
        'original_unchanged':True,'connected':r['after']['connected']}))
