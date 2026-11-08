#!/usr/bin/env python3
"""Upload files from CMS to the local FTP server via CMS FTP client."""
from __future__ import annotations

import re
import sys
from cms_telnet_driver import CmsSession

FTP_PROMPT = re.compile(r"(?m)^\s*Command:\s*$")
CMS_PROMPT = re.compile(r"(?m)^\s*\.\s*$")


def put_files(files: list[tuple[str, str]], verbose: bool = True) -> None:
    """PUT files from CMS to FTP server.
    
    files: list of (local_cms_fileid, remote_ftp_name)
    local_cms_fileid is like "GITPMK EXEC" (filename filetype, mode defaults to A)
    """
    with CmsSession(log_path="/tmp/cms_driver.log", on_line=print) as session:
        session.connect()
        print("== FTP 192.168.200.1 2121 ==", flush=True)
        session._send("FTP 192.168.200.1 2121")
        text = session._read_until(
            re.compile(r"Enter user id|USER |Password|PASS |Command:|220 |331 "),
            timeout=45, stream=True)
        if "Command:" not in text:
            print("== sending user anonymous ==", flush=True)
            session._send("anonymous")
            text = session._read_until(
                re.compile(r"Password|PASS |Command:|230 |331 "),
                timeout=30, stream=True)
        if "Command:" not in text:
            print("== sending password ==", flush=True)
            session._send("cms@example.com")
            session._read_until(FTP_PROMPT, timeout=30, stream=True)
        print("== ASCII / PUT / QUIT ==", flush=True)
        session._send("ASCII")
        session._read_until(FTP_PROMPT, timeout=30, stream=True)
        for local, remote in files:
            print(f"== PUT {local} {remote} ==", flush=True)
            session._send(f"PUT {local} {remote}")
            text = session._read_until(FTP_PROMPT, timeout=120, stream=True)
            print(text[-300:] if len(text) > 300 else text)
        session._send("QUIT")
        session._read_until(CMS_PROMPT, timeout=30, stream=True)
        print("== FTP session closed ==", flush=True)


if __name__ == "__main__":
    pairs = []
    args = sys.argv[1:]
    if not args or len(args) % 2:
        print("usage: cms_ftpput.py local_cms_fileid remote_ftp_name [local_cms_fileid remote_ftp_name ...]")
        print("  local_cms_fileid: CMS filename+filetype (e.g., GITPMK EXEC)")
        print("  remote_ftp_name: name on FTP server (e.g., GITPMK EXEC)")
        raise SystemExit(2)
    for i in range(0, len(args), 2):
        pairs.append((args[i], args[i + 1]))
    put_files(pairs)
