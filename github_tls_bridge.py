#!/usr/bin/env python3
"""Plain-HTTP to HTTPS bridge for z/VM CMS GitHub access.

Listens for plain HTTP from CMS (typically over the Hercules VMnet link)
and forwards to an HTTPS upstream with SNI/verification. Uses half-close
(SHUT_WR) piping so large uploads (e.g. git-receive-pack) are not
truncated, and disables read timeouts for long transfers.
"""
import argparse
import os
import signal
import socket
import ssl
import sys
import threading
import time


def log(msg):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    sys.stderr.write(f"[{ts}] {msg}\n")
    sys.stderr.flush()


def relay(src, dst, label):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError as e:
        log(f"{label} relay error: {e}")
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def serve(client, addr, upstream_host, upstream_port, ctx):
    peer = f"{addr[0]}:{addr[1]}"
    upstream = None
    try:
        raw = socket.create_connection((upstream_host, upstream_port), 20)
        raw.settimeout(None)
        raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        upstream = ctx.wrap_socket(raw, server_hostname=upstream_host)
        upstream.settimeout(None)
        log(f"connect {peer} -> {upstream_host}:{upstream_port}")
        client.settimeout(None)
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        t1 = threading.Thread(target=relay, args=(client, upstream, f"{peer}>up"),
                              daemon=True)
        t2 = threading.Thread(target=relay, args=(upstream, client, f"{peer}<up"),
                              daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except OSError as e:
        log(f"{peer} upstream connect failed: {e}")
    finally:
        for sock in (client, upstream):
            if sock is None:
                continue
            try:
                sock.close()
            except OSError:
                pass
        log(f"closed {peer}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", default=os.environ.get("BRIDGE_BIND", "192.168.200.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("BRIDGE_PORT", "8443")))
    ap.add_argument("--upstream-host", default=os.environ.get("BRIDGE_UPSTREAM_HOST", "github.com"))
    ap.add_argument("--upstream-port", type=int, default=int(os.environ.get("BRIDGE_UPSTREAM_PORT", "443")))
    args = ap.parse_args()

    ctx = ssl.create_default_context()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.bind, args.port))
    server.listen(32)
    log(f"listening on {args.bind}:{args.port} -> {args.upstream_host}:{args.upstream_port}")

    def _stop(*_):
        log("stopping")
        try:
            server.close()
        except OSError:
            pass
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while True:
        try:
            client, addr = server.accept()
        except OSError:
            break
        threading.Thread(target=serve,
                         args=(client, addr, args.upstream_host, args.upstream_port, ctx),
                         daemon=True).start()


if __name__ == "__main__":
    main()
