"""Exact-plan create-only CMS source upload validation.

This deliberately starts with fixed 80-byte printable source files. It creates
only a fresh ZVxxxxxx EXEC A1 target, then reads it back and compares native
bytes. It never replaces or erases a CMS file.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile

from zvm_edit import read_file, sha
from zvm_capture import CaptureError
from zvm_download import git_root_for


class CreateOnlyUploader:
    def __init__(self, session):
        self.session = session

    def upload(self, edit_id, plan_id, plan_sha256, target, candidate_sha256, timeout=120):
        s = self.session
        if not s.allow_create_only_upload:
            return {"ok": False, "message": "Create-only upload requires --allow-create-only-upload"}
        if not s.allow_commands or not s.runner.verified:
            return {"ok": False, "message": "Verify the configured read-only runner before upload"}
        if not isinstance(edit_id, str) or not re.fullmatch(r"edit-[0-9a-f]{24}", edit_id):
            return {"ok": False, "message": "Invalid generated edit identifier"}
        if not isinstance(plan_id, str) or not re.fullmatch(r"plan-[0-9a-f]{24}", plan_id):
            return {"ok": False, "message": "Invalid generated plan identifier"}
        if not isinstance(plan_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", plan_sha256):
            return {"ok": False, "message": "Provide the exact review plan SHA-256"}
        if not isinstance(target, str) or not re.fullmatch(r"ZV[0-9A-F]{6} EXEC A1", target):
            return {"ok": False, "message": "Target must be an exact generated ZVxxxxxx EXEC A1 scratch file ID"}
        if not isinstance(candidate_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", candidate_sha256):
            return {"ok": False, "message": "Provide the exact candidate SHA-256 from the review plan"}
        if type(timeout) is not int or not 1 <= timeout <= 300:
            return {"ok": False, "message": "Upload timeout must be 1..300 seconds"}

        transfer_attempted = False

        def work():
            nonlocal transfer_attempted
            root, _ = s.edits.context()
            edit = root / "edits" / edit_id
            plan_dir = edit / plan_id
            git_root_for(plan_dir)
            plan_bytes = read_file(plan_dir / "plan.json", 2 * 1048576)
            plan = json.loads(plan_bytes)
            candidate = read_file(plan_dir / "candidate.ebcdic", 1048576)
            if (sha(plan_bytes) != plan_sha256
                    or plan.get("schema") != "zvm-cms-upload-review-v1" or plan.get("edit_id") != edit_id
                    or plan.get("upload_implemented") is not False or plan.get("upload_authorized") is not False
                    or plan.get("changed") is not True or sha(candidate) != candidate_sha256
                    or plan.get("proposed", {}).get("sha256") != candidate_sha256):
                raise CaptureError("Review plan or candidate hash does not match the explicit upload request")
            cms = plan["proposed"]
            if cms.get("recfm") != "F" or cms.get("lrecl") != 80:
                raise CaptureError("First upload validator supports only fixed 80-byte source records")
            lengths = cms.get("record_lengths")
            if not isinstance(lengths, list) or any(n != 80 for n in lengths) or sum(lengths) != len(candidate):
                raise CaptureError("Candidate does not contain complete fixed 80-byte records")
            records = [candidate[i:i + 80] for i in range(0, len(candidate), 80)]
            if not records:
                raise CaptureError("Empty files are not accepted by the scratch upload validator")
            if any(sha(r) != h for r, h in zip(records, cms.get("records_sha256", []))) or len(records) != len(cms.get("records_sha256", [])):
                raise CaptureError("Candidate record hashes do not match the review plan")
            try:
                ascii_records = [r.decode("cp037") for r in records]
            except UnicodeDecodeError:
                raise CaptureError("Candidate is not valid cp037 source") from None
            if any(len(line) != 80 or not line.isprintable() for line in ascii_records):
                raise CaptureError("Candidate contains nonprintable or unsupported source bytes")

            # The explicit target name is restricted to a disposable namespace.
            # STATE is read-only; absence is rechecked immediately before DFT.
            state = s.runner._simple("STATE " + target, __import__("time").monotonic() + 20)
            if state["rc"] != 28:
                raise CaptureError("Exact scratch target is not absent; no transfer attempted")
            with tempfile.TemporaryDirectory(prefix="zvm_mcp_upload_") as folder:
                local = Path(folder) / "candidate.exec"
                received = Path(folder) / "readback.exec"
                local.write_bytes(("\n".join(ascii_records) + "\n").encode("ascii"))
                # A failed send can still leave a partial host file. Record the
                # target before starting DFT so failure evidence preserves it.
                transfer_attempted = True
                s.runner._transfer(f'Transfer(Direction=send,"HostFile={target}",LocalFile={local},Host=vm,Mode=ascii,Exist=keep,Recfm=fixed,Lrecl=80,BufferSize=2048)')
                s.runner._transfer(f'Transfer(Direction=receive,"HostFile={target}",LocalFile={received},Host=vm,Mode=ascii,Cr=add,Exist=keep,BufferSize=2048)')
                if not received.is_file():
                    raise CaptureError("Create-only upload completed without a readable local readback")
                readback = received.read_text(encoding="ascii").splitlines()
                expected = [line.rstrip() for line in ascii_records]
                actual = [line.rstrip() for line in readback]
                if actual != expected:
                    raise CaptureError("Readback source differs from the approved native candidate")
                if len(readback) != len(records) or any(len(line) > 80 for line in readback):
                    raise CaptureError("Readback record count or width differs from the fixed-80 candidate")
                # IND$FILE ASCII receive omits insignificant fixed-record right
                # padding. Restore the declared F80 width before native compare.
                readback_native = b"".join(line.ljust(80).encode("cp037") for line in readback)
                if readback_native != candidate:
                    raise CaptureError("Native readback bytes differ from the approved candidate")
            return {"target": target, "plan_sha256": plan_sha256, "candidate_sha256": candidate_sha256,
                    "readback_sha256": hashlib.sha256(readback_native).hexdigest(),
                    "record_count": len(records), "native_bytes": len(candidate),
                    "create_only": True, "existing_file_replaced": False,
                    "readback_verified": True, "cms_build_or_test_performed": False}

        result = s._run("create_only_upload", work, timeout=timeout)
        if not result["ok"]:
            result.update({"target": target, "create_only": True,
                           "transfer_attempted": transfer_attempted,
                           # Without a send, this operation has not established
                           # whether a host file exists (including refused targets).
                           "host_file_may_exist": True if transfer_attempted else None,
                           "readback_verified": False,
                           "automatic_retry_performed": False,
                           "cleanup_performed": False})
        return result
