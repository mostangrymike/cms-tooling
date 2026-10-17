"""Strict, nonce-correlated native-record capture. No terminal/network side effects."""
from __future__ import annotations
import re
import zlib


class CaptureError(RuntimeError):
    pass


def readonly_command(command):
    if not isinstance(command, str) or any(ord(c) < 32 or ord(c) > 126 for c in command):
        raise ValueError("Command must be one printable ASCII line")
    cmd = " ".join(command.upper().split())
    if cmd in {"QUERY CMSLEVEL", "QUERY DISK"}:
        return cmd
    match = re.fullmatch(r"(STATE|LISTFILE) ([A-Z0-9@$*%]{1,8}) ([A-Z0-9@$*%]{1,8}) ([A-Z][0-9]?)", cmd)
    if not match or (match[1] == "STATE" and any(c in cmd for c in "*%")):
        raise ValueError("Only QUERY CMSLEVEL, QUERY DISK, STATE fn ft fm, and LISTFILE fn ft fm without options are enabled")
    return cmd


FRAME = re.compile(r"^ZM1 ([0-9A-F]{16}) ([BRDZF]) ([0-9]{1,6})(?: (.*))?$")


def frames(rows, token):
    result = {}
    for row in rows:
        match = FRAME.fullmatch(row.strip())
        if match and match[1] == token:
            seq = int(match[3])
            if seq in result and result[seq] != match[0]:
                raise CaptureError("Conflicting frames at the same sequence")
            result[seq] = match[0]
    return result


def mask_frames(rows):
    # Encoded payload can contain credentials even though its hex spelling does
    # not match the literal secret. Never expose raw D payloads in diagnostics.
    return [re.sub(r"^(\s*ZM1 [0-9A-F]{16} D [0-9]+ ).*", r"\1<REDACTED NATIVE DATA>", row).ljust(80)[:80]
            if re.match(r"^\s*ZM1 [0-9A-F]{16} D ", row) else row for row in rows]


class Capture:
    def __init__(self, token):
        if not re.fullmatch(r"[0-9A-F]{16}", token):
            raise ValueError("Invalid request token")
        self.token = token
        self.next_seq = 0
        self.header = None
        self.records = []
        self.current = None
        self.length = None
        self.complete = False
        self.seen = {}

    def _finish_record(self):
        if self.current is not None:
            if len(self.current) != self.length:
                raise CaptureError("Truncated record")
            self.records.append(bytes(self.current))
            self.current = None

    def accept(self, line):
        match = FRAME.fullmatch(line)
        if not match or match[1] != self.token:
            raise CaptureError("Uncorrelated or malformed frame")
        kind, seq, body = match[2], int(match[3]), match[4] or ""
        if seq in self.seen:
            if self.seen[seq] != line:
                raise CaptureError("Conflicting duplicate frame")
            return False
        if seq != self.next_seq or self.complete:
            raise CaptureError("Missing or out-of-order frame")
        if kind == "F":
            raise CaptureError("Host runner rejected capture: " + (body if body in {"LIMIT", "ACK"} else "protocol error"))
        if kind == "B":
            if seq != 0 or not re.fullmatch(r"-?[0-9]{1,11} [0-9]+ [0-9]+ [0-9]+", body):
                raise CaptureError("Malformed capture manifest")
            rc, count, size, checksum = map(int, body.split())
            if not 0 <= count <= 4096 or not 0 <= size <= 1048576 or not 0 <= checksum <= 0xffffffff:
                raise CaptureError("Capture exceeds limits")
            self.header = (rc, count, size, checksum)
        elif self.header is None:
            raise CaptureError("Missing manifest")
        elif kind == "R":
            self._finish_record()
            if not re.fullmatch(r"[0-9]+ [0-9]+", body):
                raise CaptureError("Invalid record header")
            index, length = map(int, body.split())
            if index != len(self.records) + 1 or index > self.header[1] or not 0 <= length <= 4096:
                raise CaptureError("Invalid record index or length")
            self.current, self.length = bytearray(), length
        elif kind == "D":
            if self.current is None or not re.fullmatch(r"(?:[0-9A-F]{2}){1,24}", body):
                raise CaptureError("Invalid native data frame")
            self.current.extend(bytes.fromhex(body))
            if len(self.current) > self.length:
                raise CaptureError("Record overflow")
        elif kind == "Z":
            self._finish_record()
            rc, count, size, checksum = self.header
            raw = b"".join(self.records)
            if body != "DONE" or len(self.records) != count or len(raw) != size or zlib.adler32(raw) != checksum:
                raise CaptureError("Record count, byte count or checksum mismatch")
            self.complete = True
        self.seen[seq] = line
        self.next_seq += 1
        return True

    def result(self, redact, encoding="cp037"):
        if not self.complete:
            raise CaptureError("Capture is incomplete; no command result available")
        rc, count, size, checksum = self.header
        original = [record.decode(encoding) for record in self.records]
        redacted = [redact(record) for record in original]
        return {"cms_rc": rc, "record_count": count, "byte_count": size,
                "adler32": f"{checksum:08x}", "encoding": encoding,
                "records": redacted, "redaction_applied": original != redacted,
                "output_complete": True, "integrity_verified": True,
                "rc_source": "CMS Pipelines CMS stage, captured immediately in REXX"}
