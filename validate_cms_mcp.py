"""Validate actual stdio MCP; --live permits ONLY connect/screen/status/disconnect."""
import argparse
import asyncio
import json
import pathlib
import sys
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from cms_mcp import device_selector

EXPECTED = {"cms_connect", "cms_screen", "cms_status", "cms_send", "cms_disconnect", "cms_login", "cms_startup", "cms_abort_read", "cms_prepare_runner", "cms_command", "cms_resolve_failed_capture", "cms_query_links", "cms_download", "cms_edit_prepare", "cms_edit_plan", "cms_operation_plan", "cms_upload_create_only", "cms_upload_file"}


def content(result):
    if result.isError:
        raise RuntimeError("MCP tool returned protocol error: " + str(result))
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


async def validate(live=False, device="0200@"):
    script = pathlib.Path(__file__).with_name("cms_mcp.py").resolve()
    params = StdioServerParameters(command=sys.executable, args=[str(script), "--device", device], cwd=str(script.parent))
    evidence = {"live": live, "interpreter": sys.executable}
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=45)) as session:
            initialized = await session.initialize()
            evidence["protocol_version"] = initialized.protocolVersion
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            if not (names == EXPECTED):
                raise RuntimeError('Unexpected MCP tool inventory')
            evidence["tools"] = sorted(names)
            evidence["startup_status"] = content(await session.call_tool("cms_status", {}))
            if not (evidence["startup_status"]["state"] == "disconnected"):
                raise RuntimeError('MCP must start disconnected')
            if not (not evidence["startup_status"]["input_enabled"]):
                raise RuntimeError('General terminal input must be disabled')
            if live:
                try:
                    evidence["connect"] = content(await session.call_tool("cms_connect", {}))
                    if evidence["connect"]["ok"]:
                        evidence["screen"] = content(await session.call_tool("cms_screen", {
                            "wait_output": True, "timeout": 10}))
                        evidence["status"] = content(await session.call_tool("cms_status", {}))
                finally:
                    evidence["disconnect"] = content(await session.call_tool("cms_disconnect", {}))
                evidence["passed"] = all(evidence.get(stage, {}).get("ok") is True
                                         for stage in ("connect", "screen", "status", "disconnect"))
            else:
                result = content(await session.call_tool("cms_screen", {}))
                if not (result["ok"] is False):
                    raise RuntimeError('Offline screen request was not rejected')
                evidence["offline_screen_rejected"] = True
                result = content(await session.call_tool("cms_send", {"action": "Enter"}))
                if not (result["ok"] is False):
                    raise RuntimeError('Offline terminal input was not rejected')
                evidence["offline_input_rejected"] = True
                result = content(await session.call_tool("cms_login", {}))
                if not (result["ok"] is False):
                    raise RuntimeError('Offline login was not rejected')
                evidence["offline_login_rejected"] = True
                result = content(await session.call_tool("cms_startup", {}))
                if not (result["ok"] is False):
                    raise RuntimeError('Offline startup was not rejected')
                evidence["offline_startup_rejected"] = True
                if not (content(await session.call_tool("cms_abort_read", {}))["ok"] is False):
                    raise RuntimeError('Offline HX recovery was not rejected')
                evidence["offline_abort_read_rejected"] = True
                if not (content(await session.call_tool("cms_command", {"command": "QUERY DISK"}))["ok"] is False):
                    raise RuntimeError('Offline command execution was not rejected')
                if not (content(await session.call_tool("cms_prepare_runner", {}))["ok"] is False):
                    raise RuntimeError('Offline runner provisioning was not rejected')
                if not (content(await session.call_tool("cms_resolve_failed_capture", {
                        "token": "0" * 16}))['ok'] is False):
                    raise RuntimeError('Offline failed-capture recovery was not rejected')
                evidence["offline_commands_rejected"] = True
                link_result = content(await session.call_tool("cms_query_links", {"vaddr": "191"}))
                if not (link_result["ok"] is False and link_result["replacement_safe"] is False):
                    raise RuntimeError('Offline link query was not safely rejected')
                evidence["offline_link_query_rejected"] = True
                if not (content(await session.call_tool("cms_download", {"filename": "TEST", "filetype": "EXEC", "filemode": "A"}))["ok"] is False):
                    raise RuntimeError('Offline download was not rejected')
                evidence["offline_download_rejected"] = True
                if not (content(await session.call_tool("cms_edit_prepare", {"snapshot": "snapshot-" + "0" * 24}))["ok"] is False):
                    raise RuntimeError('Offline edit preparation was not rejected')
                if not (content(await session.call_tool("cms_edit_plan", {"edit_id": "edit-" + "0" * 24}))["ok"] is False):
                    raise RuntimeError('Offline edit planning was not rejected')
                if not (content(await session.call_tool("cms_operation_plan", {
                    "edit_id": "edit-" + "0" * 24, "plan_id": "plan-" + "0" * 24,
                    "plan_sha256": "0" * 64, "recipe": {}}))["ok"] is False):
                    raise RuntimeError('Offline operation planning was not rejected')
                evidence["offline_operation_plans_rejected"] = True
                if not (content(await session.call_tool("cms_upload_create_only", {
                    "edit_id": "edit-" + "0" * 24, "plan_id": "plan-" + "0" * 24,
                    "plan_sha256": "0" * 64, "target": "ZV123456 EXEC A1",
                    "candidate_sha256": "0" * 64}))['ok'] is False):
                    raise RuntimeError('Offline upload was not rejected')
                if not (content(await session.call_tool("cms_upload_file", {
                    "source_path": "missing.txt", "filename": "TEST", "filetype": "EXEC",
                    "filemode": "A"}))['ok'] is False):
                    raise RuntimeError('Offline general upload was not rejected')
                evidence["offline_local_edits_rejected"] = True
                evidence["disconnect"] = content(await session.call_tool("cms_disconnect", {}))
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--device", type=device_selector, default="0200@")
    args = parser.parse_args()
    result = asyncio.run(validate(args.live, args.device))
    data = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(data + "\n")
    print(data)
    if args.live and not result.get("passed"):
        sys.exit(1)
