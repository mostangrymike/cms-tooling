"""Explicit live validation: provision a new runner and run only read-only probes."""
import argparse
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import secrets
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from validate_zvm_mcp import content, EXPECTED
from zvm_mcp import device_selector


async def validate(args):
    server = Path(__file__).with_name("zvm_mcp.py").resolve()
    launch = [str(server), "--allow-login", "--allow-startup", "--allow-commands",
              "--credential-file", str(args.credential_file), "--device", args.device]
    if args.runner_name:
        launch.extend(["--runner-name", args.runner_name])
    evidence = {"purpose": __doc__, "commands": []}
    def persist():
        args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    params = StdioServerParameters(command=sys.executable,args=launch,cwd=str(server.parent))
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=360)) as client:
            await client.initialize()
            tools = await client.list_tools()
            if not ({t.name for t in tools.tools} == EXPECTED):
                raise RuntimeError('Unexpected MCP tool inventory')
            try:
                for key,tool,params in [
                    ("connect","zvm_connect",{}),
                    # Hercules may expose its transient banner immediately after
                    # connect.  Observe host output before inspecting the login
                    # form; this sends no terminal input.
                    ("initial_screen","zvm_screen",{"wait_output":True,"timeout":10}),
                    ("login","zvm_login",{}),
                    ("startup","zvm_startup",{"verify_cms":True}),
                    ("runner","zvm_prepare_runner",{"create":args.create_runner}),
                ]:
                    evidence[key] = content(await client.call_tool(tool,params))
                    print(json.dumps({"stage":key,"ok":evidence[key]["ok"],
                                      "outcome":evidence[key].get("outcome"),
                                      "runner":evidence[key].get("runner")}),flush=True)
                    persist()
                    if not evidence[key]["ok"]:
                        return evidence
                missing = "ZN"+secrets.token_hex(3).upper()
                commands = [("QUERY CMSLEVEL",0),(f"STATE {missing} ZMCPMISS A",28),
                            ("QUERY DISK",0),("LISTFILE * * A",0)]
                for command,expected in commands:
                    result=content(await client.call_tool("zvm_command",{"command":command,"timeout":180}))
                    evidence["commands"].append({"expected_rc":expected,**result})
                    print(json.dumps({"command":command,"ok":result["ok"],"cms_rc":result.get("cms_rc"),
                        "record_count":result.get("record_count"),"output_complete":result.get("output_complete")}),flush=True)
                    persist()
                    if not result["ok"] or result.get("cms_rc")!=expected:
                        break
            finally:
                evidence["disconnect"]=content(await client.call_tool("zvm_disconnect",{}))
                persist()
    return evidence


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live",required=True,action="store_true")
    p.add_argument("--create-runner",action="store_true")
    p.add_argument("--runner-name")
    p.add_argument("--device", type=device_selector, default="0200@")
    p.add_argument("--credential-file",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    e=asyncio.run(validate(args))
    passed=len(e["commands"])==4 and all(r["ok"] and r.get("cms_rc")==r["expected_rc"]
        and r.get("output_complete") and r.get("integrity_verified") for r in e["commands"])
    print(json.dumps({"passed":passed,"disconnect":e.get("disconnect")}),flush=True)
    raise SystemExit(0 if passed else 1)
