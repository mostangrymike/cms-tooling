"""Explicitly authorized one-shot live login through MCP; credentials stay local."""
import argparse
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from validate_cms_mcp import content, EXPECTED
from cms_mcp import device_selector


async def run(credential_file, startup=False, device="0200@"):
    script = Path(__file__).with_name("cms_mcp.py").resolve()
    launch = [str(script), "--allow-login", "--credential-file", str(credential_file), "--device", device]
    if startup:
        launch.append("--allow-startup")
    params = StdioServerParameters(command=sys.executable, args=launch, cwd=str(script.parent))
    evidence = {"purpose": "authorized login/startup; no CMS commands or transfers", "startup_requested": startup}
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=55)) as client:
            await client.initialize()
            tools = await client.list_tools()
            if not ({t.name for t in tools.tools} == EXPECTED):
                raise RuntimeError('Unexpected MCP tool inventory')
            evidence["tools"] = sorted(EXPECTED)
            try:
                evidence["connect"] = content(await client.call_tool("cms_connect", {}))
                if evidence["connect"]["ok"]:
                    evidence["login"] = content(await client.call_tool("cms_login", {"timeout": 30}))
                    if startup and evidence["login"]["ok"]:
                        evidence["startup"] = content(await client.call_tool("cms_startup", {"timeout": 30}))
                    evidence["status"] = content(await client.call_tool("cms_status", {}))
            finally:
                evidence["disconnect"] = content(await client.call_tool("cms_disconnect", {}))
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-file", required=True, type=Path)
    parser.add_argument("--live-login", required=True, action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", type=device_selector, default="0200@")
    parser.add_argument("--startup", action="store_true", help="Also perform explicitly authorized startup continuation")
    args = parser.parse_args()
    result = asyncio.run(run(args.credential_file, args.startup, args.device))
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    login = result.get("login", {})
    final = result.get("startup", login)
    print(json.dumps({"connect_ok": result.get("connect", {}).get("ok"),
                      "login_ok": login.get("ok"), "outcome": login.get("outcome"),
                      "submitted": login.get("submitted"), "startup_ok": result.get("startup", {}).get("ok"),
                      "final_outcome": final.get("outcome"), "screen": final.get("screen"),
                      "disconnect": result.get("disconnect")}, indent=2))
    if not login.get("ok") or not final.get("ok"):
        sys.exit(1)
