#!/usr/bin/env python3
"""Plain-HTTP to HTTPS bridge for z/VM CMS GitHub access.

The bridge exists because z/VM 6.3 CMS cannot originate the TLS that GitHub
requires.  It listens on the Hercules VMnet address, verifies the upstream
certificate, and forwards only the smart-HTTP endpoints a Git client needs.

Two modes are available:

``relay``
    The original behaviour: forward bytes to the upstream and back.  It is
    retained for compatibility and for emergency rollback.

``http``
    Parse the request line and headers, enforce an optional repository and
    method allowlist, optionally strip the client's ``Authorization`` header
    and inject a host-held GitHub credential, and add a correlation ID to the
    logs.  The response is passed through unchanged so existing CMS clients
    keep working.

The bridge never logs request bodies, credentials, or ``Authorization``
values.  It binds one address (the VMnet interface by default) and connects
only to the configured upstream host.
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import secrets
import signal
import socket
import ssl
import stat
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

HEADER_END = b"\r\n\r\n"
MAX_HEADER_DEFAULT = 64 * 1024
MAX_BODY_DEFAULT = 256 * 1024 * 1024
MAX_TOKEN_BYTES = 4096
REPO_PART = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")
METHOD = re.compile(r"[A-Z]{1,16}\Z")
HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}\Z")
MAX_TARGET = 8192
MAX_HEADERS = 200
CHUNK_LINE_LIMIT = 1024
CHUNK_SIZE = re.compile(rb"[0-9A-Fa-f]{1,16}\Z")


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    sys.stderr.write(f"[{ts}] {msg}\n")
    sys.stderr.flush()


class BridgeError(Exception):
    """A request-level failure with an HTTP status and a safe message."""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass(frozen=True)
class RepoRequest:
    repo: str
    service: str
    push: bool
    discovery: bool


@dataclass(frozen=True)
class Token:
    user: str
    secret: str

    def header(self) -> str:
        raw = f"{self.user}:{self.secret}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")


@dataclass
class Policy:
    closed: bool
    allow: set[str]
    allow_push: set[str]

    def check(self, request: RepoRequest) -> None:
        if not self.closed:
            return
        repo = request.repo.lower()
        if repo not in self.allow:
            raise BridgeError(403, "repository is not allowed")
        if request.push and repo not in self.allow_push:
            raise BridgeError(403, "push is not allowed for this repository")


def normalize_repo(value: str) -> str:
    value = value.strip().strip("/")
    if value.lower().endswith(".git"):
        value = value[:-4]
    return value.lower()


def valid_repo_part(value: str) -> bool:
    return bool(REPO_PART.fullmatch(value)) and value not in (".", "..")


def parse_request_head(head: bytes) -> tuple[str, str, str, list[tuple[str, str]]]:
    try:
        text = head.decode("iso-8859-1")
    except UnicodeDecodeError as exc:
        raise BridgeError(400, "request header is not ISO-8859-1") from exc
    lines = text.split("\r\n")
    if not lines or not lines[0]:
        raise BridgeError(400, "empty request")
    parts = lines[0].split(" ")
    if len(parts) != 3:
        raise BridgeError(400, "malformed request line")
    method, target, version = parts
    if not METHOD.fullmatch(method):
        raise BridgeError(400, "invalid request method")
    if not target or len(target) > MAX_TARGET:
        raise BridgeError(400, "request target is too long")
    if any(ord(ch) < 0x21 for ch in target):
        raise BridgeError(400, "control character in request target")
    if version not in ("HTTP/1.0", "HTTP/1.1"):
        raise BridgeError(400, "unsupported HTTP version")
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line:
            continue
        if line[0] in " \t":
            raise BridgeError(400, "folded header is not supported")
        name, sep, value = line.partition(":")
        if not sep or not name:
            raise BridgeError(400, "malformed header")
        if not HEADER_NAME.fullmatch(name):
            raise BridgeError(400, "invalid header name")
        value = value.strip(" \t")
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
            raise BridgeError(400, "control character in header")
        headers.append((name, value))
    if len(headers) > MAX_HEADERS:
        raise BridgeError(431, "too many request headers")
    return method, target, version, headers


def header_values(headers: Iterable[tuple[str, str]], name: str) -> list[str]:
    wanted = name.lower()
    return [value for key, value in headers if key.lower() == wanted]


def header_get(headers: Iterable[tuple[str, str]], name: str) -> str | None:
    values = header_values(headers, name)
    return values[0] if values else None


def parse_repo_request(method: str, target: str) -> RepoRequest:
    path, _, query = target.partition("?")
    if not path.startswith("/"):
        raise BridgeError(400, "request target must be an absolute path")
    if path.endswith("/info/refs"):
        repo_path = path[: -len("/info/refs")]
        service = ""
        for item in query.split("&"):
            key, _, value = item.partition("=")
            if key == "service":
                service = value
        if service not in ("git-upload-pack", "git-receive-pack"):
            raise BridgeError(400, "invalid discovery service")
        if method != "GET":
            raise BridgeError(405, "discovery requires GET")
        push = service == "git-receive-pack"
        kind = "receive-pack" if push else "upload-pack"
        discovery = True
    elif path.endswith("/git-upload-pack"):
        repo_path = path[: -len("/git-upload-pack")]
        if method != "POST":
            raise BridgeError(405, "upload-pack requires POST")
        push = False
        kind = "upload-pack"
        discovery = False
    elif path.endswith("/git-receive-pack"):
        repo_path = path[: -len("/git-receive-pack")]
        if method != "POST":
            raise BridgeError(405, "receive-pack requires POST")
        push = True
        kind = "receive-pack"
        discovery = False
    else:
        raise BridgeError(404, "unsupported Git endpoint")

    parts = [part for part in repo_path.split("/") if part]
    if len(parts) != 2:
        raise BridgeError(400, "repository path must be owner/repository")
    owner, repo = parts
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not valid_repo_part(owner) or not valid_repo_part(repo):
        raise BridgeError(400, "invalid repository name")
    return RepoRequest(f"{owner}/{repo}", kind, push, discovery)


def read_request_head(client: socket.socket, limit: int) -> tuple[bytes, bytes]:
    data = b""
    while HEADER_END not in data:
        chunk = client.recv(4096)
        if not chunk:
            raise BridgeError(400, "client closed before request header")
        data += chunk
        if len(data) > limit:
            raise BridgeError(413, "request header too large")
    head, _, rest = data.partition(HEADER_END)
    return head, rest


def rewrite_headers(
    headers: list[tuple[str, str]],
    *,
    auth_mode: str,
    auth_header: str | None,
    request_id: str,
) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name, value in headers:
        lowered = name.lower()
        if lowered == "authorization":
            if auth_mode == "pass":
                out.append((name, value))
            continue
        if lowered == "x-cms-git-id":
            continue
        if lowered == "connection":
            continue
        out.append((name, value))
    if auth_mode == "host" and auth_header:
        out.append(("Authorization", auth_header))
    out.append(("X-CMS-Git-Id", request_id))
    out.append(("Connection", "close"))
    return out


def build_request_head(method: str, target: str, version: str,
                       headers: Iterable[tuple[str, str]]) -> bytes:
    lines = [f"{method} {target} {version}"]
    lines.extend(f"{name}: {value}" for name, value in headers)
    return ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1")


def send_error(client: socket.socket, status: int, reason: str) -> None:
    body = (reason + "\n").encode("utf-8")
    response = (
        f"HTTP/1.0 {status} {reason}\r\n"
        "Content-Type: text/plain\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + body
    try:
        client.sendall(response)
    except OSError:
        pass


def send_health(client: socket.socket) -> None:
    body = b"ok\n"
    response = (
        b"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n"
        b"Content-Length: 3\r\nConnection: close\r\n\r\n" + body
    )
    try:
        client.sendall(response)
    except OSError:
        pass


def load_token(path: str) -> Token:
    """Read a host-held GitHub credential without ever logging it.

    The file must be a regular, non-symlink file owned by the current user and
    not readable by group or others.  Its single line is either ``TOKEN`` or
    ``USER:TOKEN``.  The default user is ``git``.
    """
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("token file must be a regular file")
    if info.st_uid != os.getuid():
        raise ValueError("token file must be owned by the bridge user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("token file must not be group/other accessible")
    if info.st_size > MAX_TOKEN_BYTES:
        raise ValueError("token file is too large")
    text = Path(path).read_text(encoding="utf-8")
    value = text.strip()
    if "\n" in value or "\r" in value:
        raise ValueError("token file must contain exactly one line")
    if not value:
        raise ValueError("token file is empty")
    user, sep, secret = value.partition(":")
    if not sep:
        user, secret = "git", value
    if not user or not secret or ":" in user or len(secret) > 4096:
        raise ValueError("invalid token file content")
    return Token(user, secret)


def connect_upstream(host: str, port: int, timeout: float,
                     context: ssl.SSLContext) -> ssl.SSLSocket:
    raw = socket.create_connection((host, port), timeout)
    raw.settimeout(timeout)
    raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    upstream = context.wrap_socket(raw, server_hostname=host)
    upstream.settimeout(timeout)
    return upstream


def next_timeout(idle_timeout: float, deadline: float | None) -> float | None:
    """Return the next socket timeout, or None when both limits are disabled."""
    if deadline is None:
        return idle_timeout or None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("total timeout")
    return min(idle_timeout, remaining) if idle_timeout else remaining


def relay(src: socket.socket, dst: socket.socket, label: str,
          idle_timeout: float, deadline: float | None) -> int:
    total = 0
    try:
        while True:
            src.settimeout(next_timeout(idle_timeout, deadline))
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
            total += len(data)
    except (OSError, TimeoutError) as exc:
        log(f"{label} relay stopped: {exc}")
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass
    return total


class _Reader:
    """Buffered reader over the client socket with a pre-read prefix."""

    def __init__(self, sock: socket.socket, initial: bytes,
                 idle_timeout: float, deadline: float | None):
        self._sock = sock
        self._buf = bytearray(initial)
        self._idle = idle_timeout
        self._deadline = deadline

    def _fill(self) -> bool:
        try:
            self._sock.settimeout(next_timeout(self._idle, self._deadline))
        except TimeoutError as exc:
            raise BridgeError(408, "request body timed out") from exc
        try:
            chunk = self._sock.recv(65536)
        except (OSError, TimeoutError) as exc:
            raise BridgeError(408, "request body timed out") from exc
        if not chunk:
            return False
        self._buf += chunk
        return True

    def read_exact(self, count: int) -> bytes:
        while len(self._buf) < count:
            if not self._fill():
                raise BridgeError(400, "client body ended early")
        out = bytes(self._buf[:count])
        del self._buf[:count]
        return out

    def read_line(self, limit: int) -> bytes:
        while True:
            index = self._buf.find(b"\r\n")
            if index >= 0:
                line = bytes(self._buf[:index])
                del self._buf[:index + 2]
                return line
            if len(self._buf) > limit:
                raise BridgeError(400, "chunk header is too long")
            if not self._fill():
                raise BridgeError(400, "client body ended early")


def forward_length(reader: _Reader, upstream: socket.socket, count: int) -> int:
    total = 0
    while total < count:
        data = reader.read_exact(min(65536, count - total))
        upstream.sendall(data)
        total += len(data)
    return total


def forward_chunked(reader: _Reader, upstream: socket.socket, max_body: int) -> int:
    """Relay a chunked request body unchanged, stopping at the final trailer."""
    total = 0
    while True:
        line = reader.read_line(CHUNK_LINE_LIMIT)
        size_text = line.split(b";", 1)[0].strip()
        if not CHUNK_SIZE.fullmatch(size_text):
            raise BridgeError(400, "invalid chunk size")
        size = int(size_text, 16)
        upstream.sendall(line + b"\r\n")
        if size == 0:
            while True:
                trailer = reader.read_line(CHUNK_LINE_LIMIT)
                upstream.sendall(trailer + b"\r\n")
                if not trailer:
                    return total
        total += size
        if total > max_body:
            raise BridgeError(413, "request body too large")
        remaining = size
        while remaining:
            data = reader.read_exact(min(65536, remaining))
            upstream.sendall(data)
            remaining -= len(data)
        if reader.read_exact(2) != b"\r\n":
            raise BridgeError(400, "malformed chunk terminator")
        upstream.sendall(b"\r\n")


def upstream_host_from_header(value: str | None) -> str | None:
    if not value:
        return None
    host = value.strip()
    if host.startswith("["):
        return host.split("]", 1)[0].lstrip("[")
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def validate_headers(headers: list[tuple[str, str]], expected: str,
                     max_body: int) -> int | None:
    """Reject ambiguous framing and return the declared body length, if any.

    A duplicate ``Host``, both ``Transfer-Encoding`` and ``Content-Length``,
    or an unsupported transfer coding are request-smuggling shapes that a
    trusted Git client never sends, so they fail closed.
    """
    hosts = header_values(headers, "host")
    if len(hosts) != 1:
        raise BridgeError(400, "exactly one Host header is required")
    host = upstream_host_from_header(hosts[0])
    if host is None or host.lower() != expected.lower():
        raise BridgeError(400, "unexpected Host header")

    transfers = header_values(headers, "transfer-encoding")
    lengths = header_values(headers, "content-length")
    if transfers and lengths:
        raise BridgeError(400, "Transfer-Encoding and Content-Length conflict")
    if len(transfers) > 1:
        raise BridgeError(400, "duplicate Transfer-Encoding")
    if transfers:
        if transfers[0].strip().lower() != "chunked":
            raise BridgeError(400, "unsupported transfer coding")
        return None
    if not lengths:
        return None
    if len(set(lengths)) != 1 or not lengths[0].isdigit():
        raise BridgeError(400, "invalid Content-Length")
    length = int(lengths[0])
    if length > max_body:
        raise BridgeError(413, "request body too large")
    return length


def request_id(headers: list[tuple[str, str]]) -> str:
    supplied = header_get(headers, "x-cms-git-id")
    if supplied and REQUEST_ID.fullmatch(supplied):
        return supplied
    return secrets.token_hex(6)


def serve_http(client: socket.socket, addr: tuple, args, context: ssl.SSLContext,
               policy: Policy, token: Token | None) -> None:
    peer = f"{addr[0]}:{addr[1]}"
    client.settimeout(args.connect_timeout)
    head, rest = read_request_head(client, args.max_header)
    method, target, version, headers = parse_request_head(head)
    rid = request_id(headers)

    if method == "GET" and target.partition("?")[0] == "/healthz":
        send_health(client)
        log(f"health id={rid} peer={peer}")
        return

    request = parse_repo_request(method, target)
    length = validate_headers(headers, args.upstream_host, args.max_body)
    chunked = bool(header_values(headers, "transfer-encoding"))
    if request.discovery and (length not in (None, 0) or chunked):
        raise BridgeError(400, "discovery must not carry a body")

    policy.check(request)

    auth_header = token.header() if (args.auth_mode == "host" and token) else None
    out_headers = rewrite_headers(
        headers, auth_mode=args.auth_mode, auth_header=auth_header, request_id=rid)
    wire = build_request_head(method, target, version, out_headers)

    upstream = connect_upstream(args.upstream_host, args.upstream_port,
                                args.connect_timeout, context)
    deadline = (time.monotonic() + args.total_timeout
                if args.total_timeout else None)
    try:
        upstream.sendall(wire)
        sent = len(wire)
        log(f"request id={rid} peer={peer} {method} {request.repo} "
            f"{request.service} push={int(request.push)}")
        if not request.discovery:
            reader = _Reader(client, rest, args.idle_timeout, deadline)
            if length is not None:
                sent += forward_length(reader, upstream, length)
            else:
                sent += forward_chunked(reader, upstream, args.max_body)
        elif rest:
            log(f"discard id={rid} unexpected discovery body bytes={len(rest)}")
        received = relay(upstream, client, f"id={rid} upstream>client",
                         args.idle_timeout, deadline)
        log(f"complete id={rid} peer={peer} sent={sent} received={received}")
    finally:
        try:
            upstream.close()
        except OSError:
            pass


def serve_relay(client: socket.socket, addr: tuple, args,
                context: ssl.SSLContext) -> None:
    peer = f"{addr[0]}:{addr[1]}"
    upstream = None
    try:
        upstream = connect_upstream(args.upstream_host, args.upstream_port,
                                    args.connect_timeout, context)
        log(f"relay connect peer={peer} -> {args.upstream_host}:{args.upstream_port}")
        client.settimeout(None)
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        deadline = (time.monotonic() + args.total_timeout
                    if args.total_timeout else None)
        sent = [0]
        received = [0]

        def to_upstream() -> None:
            sent[0] = relay(client, upstream, f"peer={peer} client>upstream",
                            args.idle_timeout, deadline)

        def to_client() -> None:
            received[0] = relay(upstream, client, f"peer={peer} upstream>client",
                                args.idle_timeout, deadline)

        first = threading.Thread(target=to_upstream, daemon=True)
        second = threading.Thread(target=to_client, daemon=True)
        first.start()
        second.start()
        first.join()
        second.join()
        log(f"relay complete peer={peer} sent={sent[0]} received={received[0]}")
    finally:
        for sock in (client, upstream):
            if sock is None:
                continue
            try:
                sock.close()
            except OSError:
                pass


def handle_connection(client: socket.socket, addr: tuple, args,
                      context: ssl.SSLContext, policy: Policy,
                      token: Token | None) -> None:
    peer = f"{addr[0]}:{addr[1]}"
    try:
        if args.mode == "http":
            serve_http(client, addr, args, context, policy, token)
        else:
            serve_relay(client, addr, args, context)
    except BridgeError as exc:
        log(f"reject peer={peer} status={exc.status} reason={exc.reason}")
        send_error(client, exc.status, exc.reason)
    except (OSError, TimeoutError) as exc:
        log(f"connection peer={peer} failed: {exc}")
    except Exception as exc:  # keep the bridge alive; never print request data
        log(f"connection peer={peer} internal error: {type(exc).__name__}")
    finally:
        try:
            client.close()
        except OSError:
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bind", default=os.environ.get("BRIDGE_BIND", "192.168.200.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("BRIDGE_PORT", "8443")))
    ap.add_argument("--upstream-host",
                    default=os.environ.get("BRIDGE_UPSTREAM_HOST", "github.com"))
    ap.add_argument("--upstream-port", type=int,
                    default=int(os.environ.get("BRIDGE_UPSTREAM_PORT", "443")))
    ap.add_argument("--mode", choices=("relay", "http"),
                    default=os.environ.get("BRIDGE_MODE", "relay"))
    ap.add_argument("--policy", choices=("open", "closed"),
                    default=os.environ.get("BRIDGE_POLICY", "open"))
    ap.add_argument("--allow-repo", action="append", default=[],
                    help="owner/repository allowed in closed policy (repeatable)")
    ap.add_argument("--allow-push-repo", action="append", default=[],
                    help="owner/repository allowed for receive-pack (repeatable)")
    ap.add_argument("--auth-mode", choices=("pass", "host"),
                    default=os.environ.get("BRIDGE_AUTH_MODE", "pass"))
    ap.add_argument("--token-file",
                    default=os.environ.get("BRIDGE_GITHUB_TOKEN_FILE"))
    ap.add_argument("--ca-file", default=os.environ.get("BRIDGE_CA_FILE"),
                    help="optional CA bundle for the upstream certificate")
    ap.add_argument("--max-header", type=int, default=MAX_HEADER_DEFAULT)
    ap.add_argument("--max-body", type=int, default=MAX_BODY_DEFAULT)
    ap.add_argument("--max-connections", type=int, default=8)
    ap.add_argument("--connect-timeout", type=float, default=20.0)
    ap.add_argument("--idle-timeout", type=float, default=900.0)
    ap.add_argument("--total-timeout", type=float, default=3600.0)
    return ap.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if not 0 < args.port < 65536 or not 0 < args.upstream_port < 65536:
        raise SystemExit("port values must be between 1 and 65535")
    if args.max_header < 1024:
        raise SystemExit("--max-header must be at least 1024")
    if args.max_body < 1024:
        raise SystemExit("--max-body must be at least 1024")
    if not 1 <= args.max_connections <= 1024:
        raise SystemExit("--max-connections must be between 1 and 1024")
    if not 0 < args.connect_timeout <= 86400:
        raise SystemExit("--connect-timeout must be in (0, 86400]")
    for name in ("idle_timeout", "total_timeout"):
        if not 0 <= getattr(args, name) <= 86400:
            raise SystemExit(f"--{name.replace('_', '-')} must be in [0, 86400]; "
                             "0 disables the limit")
    if args.idle_timeout and args.connect_timeout > args.idle_timeout:
        raise SystemExit("--connect-timeout must not exceed --idle-timeout")


def build_policy(args: argparse.Namespace) -> Policy:
    policy = Policy(closed=args.policy == "closed",
                    allow={normalize_repo(value) for value in args.allow_repo},
                    allow_push={normalize_repo(value) for value in args.allow_push_repo})
    for entry in policy.allow | policy.allow_push:
        owner, _, repo = entry.partition("/")
        if not owner or not repo or not valid_repo_part(owner) or not valid_repo_part(repo):
            raise SystemExit(f"invalid --allow-repo value: {entry!r}")
    if policy.closed:
        if not policy.allow:
            raise SystemExit("--policy closed requires at least one --allow-repo")
        missing = policy.allow_push - policy.allow
        if missing:
            raise SystemExit("--allow-push-repo entries must also be allowed to read: "
                             + ", ".join(sorted(missing)))
    elif policy.allow or policy.allow_push:
        log("warning: --allow-repo is ignored unless --policy closed")
    return policy


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    validate_args(args)
    if args.mode == "relay":
        if args.auth_mode == "host" or args.policy == "closed":
            log("warning: relay mode ignores auth-mode and policy settings")
    policy = build_policy(args)
    token = None
    if args.auth_mode == "host":
        if not args.token_file:
            raise SystemExit("host auth mode requires --token-file or BRIDGE_GITHUB_TOKEN_FILE")
        try:
            token = load_token(args.token_file)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"cannot load token file: {exc}") from exc

    context = ssl.create_default_context(cafile=args.ca_file)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.bind, args.port))
    server.listen(max(32, args.max_connections))
    if args.mode == "http":
        log(f"listening {args.bind}:{args.port} http policy={args.policy} "
            f"auth={args.auth_mode} allow={len(policy.allow)} "
            f"push={len(policy.allow_push)} -> "
            f"{args.upstream_host}:{args.upstream_port}")
        if args.policy == "open":
            log("warning: policy=open forwards any github.com repository; "
                "set --policy closed and --allow-repo for enforcement")
    else:
        log(f"listening {args.bind}:{args.port} relay -> "
            f"{args.upstream_host}:{args.upstream_port}")
    if args.auth_mode == "host" and token:
        log(f"host credential loaded user={token.user} (value not logged)")

    slots = threading.BoundedSemaphore(args.max_connections)

    def _stop(*_):
        log("stopping")
        try:
            server.close()
        except OSError:
            pass
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    def worker(client: socket.socket, addr: tuple) -> None:
        try:
            handle_connection(client, addr, args, context, policy, token)
        finally:
            slots.release()

    while True:
        try:
            client, addr = server.accept()
        except OSError:
            break
        if not slots.acquire(blocking=False):
            log(f"connection limit reached; refusing {addr[0]}:{addr[1]}")
            try:
                client.close()
            except OSError:
                pass
            continue
        threading.Thread(target=worker, args=(client, addr), daemon=True).start()


if __name__ == "__main__":
    main()
