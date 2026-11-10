"""Minimal persistent s3270 script-mode session helper (local use only)."""
from __future__ import annotations

import pexpect


class S3270Session:
    def __init__(self, host="0202@127.0.0.1:3270", timeout=15):
        self.child = pexpect.spawn("s3270", ["-script", host], encoding="utf-8", timeout=timeout)
        self.timeout = timeout
        # consume initial status line
        try:
            self.child.expect(r"\r?\n")
        except Exception:
            pass

    def cmd(self, command):
        self.child.sendline(command)
        status = None
        data = []
        while True:
            line = self.child.readline()
            if not line:
                break
            line = line.rstrip("\r\n")
            if line in ("ok", "error"):
                return status, data, line
            if line.startswith("data: "):
                data.append(line[6:])
            elif status is None and line.strip():
                status = line

    def wait(self, seconds=1):
        return self.cmd(f"Wait({seconds})")

    def ascii(self):
        return self.cmd("Ascii()")

    def text(self):
        _, data, _ = self.ascii()
        return "\n".join(data)

    def send_text(self, text):
        return self.cmd(f'String("{text}")')

    def enter(self):
        return self.cmd("Enter()")

    def pf(self, n):
        return self.cmd(f"PF({n})")

    def pa(self, n):
        return self.cmd(f"PA({n})")

    def clear(self):
        return self.cmd("Clear()")

    def close(self):
        try:
            self.cmd("Disconnect")
        except Exception:
            pass
        try:
            self.cmd("Quit")
        except Exception:
            pass
        try:
            self.child.close(force=True)
        except Exception:
            pass
