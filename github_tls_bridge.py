#!/usr/bin/env python3
"""Small temporary plain-HTTP to GitHub-TLS bridge for z/VM CMS."""
import socket
import ssl
import threading

LISTEN = ("0.0.0.0", 8443)


def pipe(source, target):
    try:
        while data := source.recv(65536):
            target.sendall(data)
    except OSError:
        pass
    finally:
        for sock in (source, target):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass


def serve(client):
    try:
        upstream = ssl.create_default_context().wrap_socket(
            socket.create_connection(("github.com", 443), 10),
            server_hostname="github.com",
        )
        threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
        threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()
    except OSError:
        client.close()


with socket.socket() as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(LISTEN)
    server.listen(16)
    while True:
        client, _ = server.accept()
        threading.Thread(target=serve, args=(client,), daemon=True).start()
