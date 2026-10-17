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
import time

from cms_edit import read_file, sha
from cms_capture import CaptureError
from cms_download import file_id, git_root_for


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
                    or plan.get("schema") != "cms-upload-review-v1" or plan.get("edit_id") != edit_id
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
            with tempfile.TemporaryDirectory(prefix="cms_mcp_upload_") as folder:
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


class FileUploader:
    """Transfer a caller-selected local file to an exact CMS file ID.

    Local sources stay inside a configured Git worktree. Existing CMS targets
    require overwrite_existing=true; target presence is checked immediately
    before DFT but the check is not atomic against another CMS session.
    """

    MAX_BYTES = 1048576

    def __init__(self, session, upload_root=None):
        self.session = session
        self.upload_root = upload_root

    @staticmethod
    def _check_text(data, recfm, lrecl):
        try:
            text = data.decode("ascii")
        except UnicodeDecodeError:
            raise ValueError("ASCII mode accepts ASCII text; use binary mode for native/non-ASCII bytes") from None
        if "\r" in text or not text.endswith("\n"):
            raise ValueError("ASCII upload requires LF-delimited records with a final LF")
        lines = text[:-1].split("\n")
        if recfm not in {"fixed", "variable"} or type(lrecl) is not int or not 1 <= lrecl <= 4096:
            raise ValueError("ASCII upload requires fixed/variable RECFM and LRECL 1..4096")
        if any(len(line.encode("ascii")) > lrecl for line in lines):
            raise ValueError("An ASCII record exceeds the requested LRECL")
        if recfm == "fixed":
            text = "\n".join(line.ljust(lrecl) for line in lines) + "\n"
        return text.encode("ascii"), len(lines)

    def upload(self, source_path, filename, filetype, filemode, *, mode="ascii",
               recfm="fixed", lrecl=80, overwrite_existing=False, timeout=120):
        s = self.session
        if not s.allow_uploads:
            return {"ok": False, "message": "File uploads require --allow-uploads"}
        if not s.allow_commands or not s.runner.verified:
            return {"ok": False, "message": "Verify the configured command runner before upload"}
        if type(overwrite_existing) is not bool:
            return {"ok": False, "message": "overwrite_existing must be boolean"}
        if type(timeout) is not int or not 1 <= timeout <= 300:
            return {"ok": False, "message": "Upload timeout must be 1..300 seconds"}
        if mode not in {"ascii", "binary"} or recfm not in {"fixed", "variable", "undefined"}:
            return {"ok": False, "message": "Use mode ascii/binary and RECFM fixed/variable/undefined"}
        if recfm in {"fixed", "variable"} and (type(lrecl) is not int or not 1 <= lrecl <= 4096):
            return {"ok": False, "message": "Fixed/variable uploads require LRECL 1..4096"}
        if recfm == "undefined" and lrecl is not None:
            return {"ok": False, "message": "Undefined RECFM does not accept LRECL"}
        try:
            identity = file_id(filename, filetype, filemode)
            if not self.upload_root:
                raise ValueError("Uploads require a configured local upload root")
            if not isinstance(source_path, str) or not source_path or any(ord(c) < 32 for c in source_path):
                raise ValueError("Provide a relative path to a local file")
            relative = Path(source_path)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Upload source must stay beneath the configured upload root")
            root, worktree = git_root_for(self.upload_root)
            source = root / relative
            if source.is_symlink():
                raise ValueError("Upload source must not be a symlink")
            for parent in (source.parent, *source.parent.parents):
                if parent == root.parent:
                    break
                if parent.is_symlink():
                    raise ValueError("Upload source path must not traverse symlinks")
            if not source.is_file() or not source.resolve().is_relative_to(root.resolve()):
                raise ValueError("Upload source must be a regular file beneath the configured upload root")
            git_root_for(source.parent)
            data = source.read_bytes()
            if not data or len(data) > self.MAX_BYTES:
                raise ValueError("Upload source must contain 1..1048576 bytes")
            # Do not allow a locally loaded login secret to be transferred by
            # accident, whether it appears in workstation or guest encoding.
            for secret in s.secrets:
                if secret and any(secret.encode(enc) in data for enc in ("utf-8", "cp037")):
                    raise ValueError("Upload source contains a locally loaded credential")
            if mode == "ascii":
                transfer_data, record_count = self._check_text(data, recfm, lrecl)
            else:
                transfer_data, record_count = data, None
        except (OSError, UnicodeError, ValueError) as exc:
            return {"ok": False, "message": s.redact(str(exc))}

        target = " ".join(identity)
        attempted = False

        def work():
            nonlocal attempted
            root_now, worktree_now = git_root_for(self.upload_root)
            if (root_now != root or worktree_now != worktree or source.is_symlink()
                    or not source.is_file() or source.read_bytes() != data):
                raise CaptureError("Upload source or configured root changed before transfer")
            state = s.runner._simple("STATE " + target, time.monotonic() + 20)
            expected_rc = 0 if overwrite_existing else 28
            if state["rc"] != expected_rc:
                expectation = "an existing target" if overwrite_existing else "an absent target"
                raise CaptureError("CMS target does not match the requested overwrite policy; expected " + expectation)
            with tempfile.TemporaryDirectory(prefix="cms_mcp_upload_") as folder:
                local = Path(folder) / "payload.bin"
                local.write_bytes(transfer_data)
                lrecl_opt = f",Lrecl={lrecl}" if lrecl is not None else ""
                exist = "replace" if overwrite_existing else "keep"
                action = (f'Transfer(Direction=send,"HostFile={target}","LocalFile={local}",'
                          f'Host=vm,Mode={mode},Exist={exist},Recfm={recfm}{lrecl_opt},BufferSize=2048)')
                attempted = True
                s.runner._transfer(action)
            after = s.runner._simple("STATE " + target, time.monotonic() + 20)
            if after["rc"] != 0:
                raise CaptureError("Transfer completed but the CMS target is not present on the verified filemode")
            return {"target": target, "source_path": str(source),
                    "source_sha256": hashlib.sha256(data).hexdigest(),
                    "transferred_sha256": hashlib.sha256(transfer_data).hexdigest(),
                    "input_bytes": len(data), "transferred_bytes": len(transfer_data),
                    "record_count": record_count, "mode": mode, "recfm": recfm,
                    "lrecl": lrecl, "overwrite_existing": overwrite_existing,
                    "target_present_after_transfer": True,
                    "transfer_complete": True, "content_readback_verified": False,
                    "git_worktree": str(worktree), "host_existence_check_is_atomic": False}

        result = s._run("file_upload", work, timeout=timeout)
        if not result["ok"]:
            result.update({"target": target, "transfer_attempted": attempted,
                           "host_file_may_be_partial": attempted,
                           "automatic_retry_performed": False, "cleanup_performed": False})
        return result
