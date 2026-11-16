#!/usr/bin/env python3
"""Upload files from CMS to the local FTP server via CMS FTP client."""
from __future__ import annotations

import re
import os
import sys
from cms_telnet_driver import CmsSession
from cms_profiles import get_profile

FTP_PROMPT = re.compile(r"(?m)^\s*Command:\s*$")
CMS_PROMPT = re.compile(r"(?m)^\s*\.\s*$")
CMS_FILEID = re.compile(r"[A-Za-z0-9@$#+_-]{1,8}\Z")
CMS_FILEMODE = re.compile(r"[A-Za-z][0-6]?\Z")
FTP_PATH = re.compile(r"[A-Za-z0-9._/-]+\Z")
DEFAULT_FTP_HOST = "192.168.200.1"
DEFAULT_FTP_PORT = 2121


class CmsFtpError(RuntimeError):
    """The CMS FTP client did not complete a file transfer."""


def _cms_fileid(value: str, default_mode: str = "A") -> str:
    """Return a CMS file ID in the dotted syntax used by the CMS FTP client."""
    if not isinstance(value, str):
        raise ValueError("CMS file ID must be text")
    fields = value.replace(".", " ").split()
    if len(fields) not in (2, 3) or any(not CMS_FILEID.fullmatch(field) for field in fields[:2]):
        raise ValueError("CMS file ID must be filename filetype [filemode]")
    mode = fields[2] if len(fields) == 3 else default_mode
    if not CMS_FILEMODE.fullmatch(mode):
        raise ValueError("CMS filemode must be a letter optionally followed by 0-6")
    return f"{fields[0]}.{fields[1]}.{mode}"


def _remote_name(value: str) -> str:
    """Normalize a two-part CMS file ID, or validate a relative FTP path."""
    if not isinstance(value, str) or not value:
        raise ValueError("FTP filename is required")
    if "/" not in value and " " in value:
        fields = value.split()
        if len(fields) == 2 and all(CMS_FILEID.fullmatch(field) for field in fields):
            return f"{fields[0]}.{fields[1]}"
    if (not FTP_PATH.fullmatch(value) or value.startswith("/")
            or any(part in {".", ".."} for part in value.split("/"))):
        raise ValueError("FTP filename must be a safe relative path")
    return value


def _read_ftp_prompt(session, timeout: int = 30, *, stream: bool = False) -> str:
    return session._read_until(FTP_PROMPT, timeout=timeout, stream=stream)


def _open_ftp(session, *, remote_directory: str | None = None,
              stream: bool = False) -> None:
    # Resolve FTP destination from profile if configured
    host, port = DEFAULT_FTP_HOST, DEFAULT_FTP_PORT
    profile_name = os.environ.get("CMS_PROFILE")
    if profile_name:
        prof = get_profile(profile_name)
        if prof:
            host = prof.get("ftp_host") or prof.get("host") or host
            port = int(prof.get("ftp_port") or prof.get("port") or port)
    session._send(f"FTP {host} {port}")
    text = session._read_until(
        re.compile(r"Enter user id|USER |Password|PASS |Command:|220 |331 "),
        timeout=45, stream=stream)
    if "Command:" not in text:
        session._send("anonymous")
        text = session._read_until(
            re.compile(r"Password|PASS |Command:|230 |331 "),
            timeout=30, stream=stream)
    if "Command:" not in text:
        session._send("cms@example.com")
        text = _read_ftp_prompt(session, stream=stream)
    if "Command:" not in text:
        raise CmsFtpError("CMS FTP login did not reach the command prompt")
    session._send("ASCII")
    _read_ftp_prompt(session, stream=stream)
    if remote_directory is not None:
        session._send(f"CWD {_remote_name(remote_directory)}")
        response = _read_ftp_prompt(session, stream=stream)
        if "250 " not in response:
            raise CmsFtpError("CMS FTP could not enter the staging directory")


def _transfer(session, command: str, *, stream: bool = False) -> str:
    session._send(command)
    response = _read_ftp_prompt(session, timeout=180, stream=stream)
    if "226 Transfer complete" not in response:
        raise CmsFtpError(f"FTP transfer failed for {command.split()[0]}")
    return response


def put_files_on_session(session, files, *, remote_directory=None, verbose=False):
    """PUT from CMS using an already connected CMS Telnet session."""
    _open_ftp(session, remote_directory=remote_directory, stream=verbose)
    try:
        for local, remote in files:
            _transfer(session, f"PUT {_cms_fileid(local)} {_remote_name(remote)}",
                      stream=verbose)
    finally:
        session._send("QUIT")
        session._read_until(CMS_PROMPT, timeout=30, stream=verbose)


def get_files_on_session(session, files, *, remote_directory=None, verbose=False):
    """GET to CMS using an already connected CMS Telnet session."""
    _open_ftp(session, remote_directory=remote_directory, stream=verbose)
    try:
        session._send("LOCSITE FIXRECFM 80")
        _read_ftp_prompt(session, stream=verbose)
        for remote, local in files:
            _transfer(session, f"GET {_remote_name(remote)} {_cms_fileid(local)}",
                      stream=verbose)
    finally:
        session._send("QUIT")
        session._read_until(CMS_PROMPT, timeout=30, stream=verbose)


def put_files(files: list[tuple[str, str]], verbose: bool = True) -> None:
    """PUT CMS files to the local FTP server.
    
    files: list of (local_cms_fileid, remote_ftp_name). CMS file IDs may be
    supplied as "GITPMK EXEC [A]" and are converted to FTP's dotted form.
    """
    with CmsSession(log_path="/tmp/cms_driver.log",
                    on_line=print if verbose else None) as session:
        session.connect()
        put_files_on_session(session, files, verbose=verbose)


def get_files(files: list[tuple[str, str]], verbose: bool = True) -> None:
    """GET FTP files into CMS as fixed 80-byte source records.

    `files` is a list of (remote_ftp_name, local_cms_fileid) pairs. The local
    ID can include an explicit mode; new files default to mode A otherwise.
    """
    with CmsSession(log_path="/tmp/cms_driver.log",
                    on_line=print if verbose else None) as session:
        session.connect()
        get_files_on_session(session, files, verbose=verbose)


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
