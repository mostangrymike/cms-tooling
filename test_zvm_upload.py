"""Offline safeguards for exact-plan, create-only upload validation."""
import re
import shutil
from contextlib import asynccontextmanager, redirect_stdout
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, AsyncMock, patch
from types import SimpleNamespace

from zvm_download import metadata, save_snapshot
from zvm_mcp import Session
from validate_zvm_upload import validation_passed, run as validate_upload
from validate_zvm_mcp import EXPECTED


class CreateOnlyUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.root = self.repo / "sources"
        self.session = Session(allow_local_edits=True, download_root=self.root,
                               factory=Mock(side_effect=AssertionError("No terminal allowed")))
        old = ("/* ORIGINAL SOURCE " + " " * 63)[:80].encode("cp037")
        meta = metadata(["TEST EXEC A1 F 80 1 1 10/16/26 15:00:00 USER01"], ("TEST", "EXEC", "A1"))
        snapshot = save_snapshot(self.root, self.repo, meta, [old], [])
        edit = self.session.edits.prepare(Path(snapshot["snapshot_directory"]).name)
        Path(edit["editable_file"]).write_bytes(b"/* CHANGED SOURCE" + b" " * 63 + b"\n")
        plan = self.session.edits.plan(edit["edit_id"])
        self.assertTrue(plan["ok"], plan)
        self.edit_id, self.plan_id = edit["edit_id"], plan["plan_id"]
        self.candidate_sha = plan["candidate_sha256"]
        self.plan_sha = plan["plan_sha256"]
        self.target = "ZV1234AB EXEC A1"

    def tearDown(self):
        self.temp.cleanup()

    def test_disabled_and_invalid_requests_cannot_connect(self):
        result = self.session.uploader.upload(self.edit_id, self.plan_id, self.plan_sha, self.target, self.candidate_sha)
        self.assertFalse(result["ok"])
        self.assertIn("--allow-create-only-upload", result["message"])
        self.session.allow_create_only_upload = True
        self.assertFalse(self.session.uploader.upload(self.edit_id, self.plan_id, self.plan_sha,
                         "TEST EXEC A", self.candidate_sha)["ok"])
        self.assertFalse(self.session.uploader.upload(self.edit_id, self.plan_id, self.plan_sha,
                         self.target, "0" * 64)["ok"])
        self.assertIsNone(self.session.em)
        self.session.factory.assert_not_called()

    def test_exact_changed_plan_is_created_and_native_readback_verified(self):
        self.session.allow_create_only_upload = True
        self.session.allow_commands = True
        self.session.runner.verified = True
        self.session.runner._simple = Mock(return_value={"rc": 28})
        saved = {}

        def transfer(action):
            path = Path(re.search(r"LocalFile=([^,]+)", action)[1])
            if "Direction=send" in action:
                saved["bytes"] = path.read_bytes()
            else:
                # Model IND$FILE ASCII receive omitting fixed-record right pad.
                lines = saved["bytes"].decode("ascii").splitlines()
                path.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="ascii")
            return []

        self.session.runner._transfer = Mock(side_effect=transfer)
        result = self.session.uploader.upload(self.edit_id, self.plan_id, self.plan_sha,
                                              self.target, self.candidate_sha)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["readback_verified"])
        self.assertTrue(result["create_only"])
        self.assertFalse(result["existing_file_replaced"])
        self.assertEqual(result["candidate_sha256"], result["readback_sha256"])
        self.assertEqual(self.session.runner._simple.call_count, 1)
        self.assertEqual(self.session.runner._transfer.call_count, 2)
        self.assertIsNone(self.session.em)

    def test_present_target_is_refused_before_any_transfer(self):
        self.session.allow_create_only_upload = True
        self.session.allow_commands = True
        self.session.runner.verified = True
        self.session.runner._simple = Mock(return_value={"rc": 0})
        self.session.runner._transfer = Mock()
        result = self.session.uploader.upload(self.edit_id, self.plan_id, self.plan_sha,
                                              self.target, self.candidate_sha)
        self.assertFalse(result["ok"])
        self.assertIn("not absent", result["message"])
        self.assertFalse(result["transfer_attempted"])
        self.assertIsNone(result["host_file_may_exist"])
        self.session.runner._transfer.assert_not_called()

    def test_symlinked_artifact_ancestors_are_refused_before_host_operations(self):
        self.session.allow_create_only_upload = True
        self.session.allow_commands = True
        self.session.runner.verified = True
        self.session.runner._simple = Mock()
        self.session.runner._transfer = Mock()
        edit = self.root / 'edits' / self.edit_id
        for path in (edit / self.plan_id, edit, self.root / 'edits'):
            with self.subTest(component=path.name):
                outside = self.repo / 'relocated'
                shutil.move(str(path), outside)
                path.symlink_to(outside, target_is_directory=True)
                try:
                    result = self.session.uploader.upload(self.edit_id, self.plan_id,
                        self.plan_sha, self.target, self.candidate_sha)
                    self.assertFalse(result['ok'], result)
                    self.assertIn('symlink', result['message'])
                    self.session.runner._simple.assert_not_called()
                    self.session.runner._transfer.assert_not_called()
                finally:
                    path.unlink()
                    shutil.move(str(outside), path)

    def test_candidate_hash_mismatch_is_refused_before_state_or_transfer(self):
        self.session.allow_create_only_upload = True
        self.session.allow_commands = True
        self.session.runner.verified = True
        self.session.runner._simple = Mock()
        self.session.runner._transfer = Mock()
        result = self.session.uploader.upload(self.edit_id, self.plan_id, self.plan_sha,
                                              self.target, "f" * 64)
        self.assertFalse(result["ok"])
        self.assertIn("hash", result["message"])
        self.session.runner._simple.assert_not_called()
        self.session.runner._transfer.assert_not_called()

    def test_tampered_plan_hash_is_refused_before_state_or_transfer(self):
        self.session.allow_create_only_upload = True
        self.session.allow_commands = True
        self.session.runner.verified = True
        self.session.runner._simple = Mock()
        self.session.runner._transfer = Mock()
        result = self.session.uploader.upload(self.edit_id, self.plan_id, "f" * 64,
                                              self.target, self.candidate_sha)
        self.assertFalse(result["ok"])
        self.session.runner._simple.assert_not_called()
        self.session.runner._transfer.assert_not_called()

    def test_failed_send_preserves_exact_target_and_partial_file_warning(self):
        self.session.allow_create_only_upload = True
        self.session.allow_commands = True
        self.session.runner.verified = True
        self.session.runner._simple = Mock(return_value={"rc": 28})
        self.session.runner._transfer = Mock(side_effect=TimeoutError("synthetic partial send"))
        result = self.session.uploader.upload(self.edit_id, self.plan_id, self.plan_sha,
                                              self.target, self.candidate_sha)
        self.assertFalse(result["ok"])
        self.assertEqual(result["target"], self.target)
        self.assertTrue(result["transfer_attempted"])
        self.assertTrue(result["host_file_may_exist"])
        self.assertFalse(result["readback_verified"])
        self.assertFalse(result["automatic_retry_performed"])
        self.assertFalse(result["cleanup_performed"])
        self.session.runner._transfer.assert_called_once()

    def test_readback_mismatch_preserves_target_without_retry(self):
        self.session.allow_create_only_upload = True
        self.session.allow_commands = True
        self.session.runner.verified = True
        self.session.runner._simple = Mock(return_value={"rc": 28})

        def transfer(action):
            if "Direction=receive" in action:
                Path(re.search(r"LocalFile=([^,]+)", action)[1]).write_bytes(b"CHANGED ON HOST\n")

        self.session.runner._transfer = Mock(side_effect=transfer)
        result = self.session.uploader.upload(self.edit_id, self.plan_id, self.plan_sha,
                                              self.target, self.candidate_sha)
        self.assertFalse(result["ok"])
        self.assertIn("differs", result["message"])
        self.assertTrue(result["host_file_may_exist"])
        self.assertFalse(result["readback_verified"])
        self.assertFalse(result["cleanup_performed"])
        self.assertEqual(self.session.runner._transfer.call_count, 2)


class UploadValidatorTests(unittest.TestCase):
    def evidence(self):
        result = {"live_create": True, "native_verification_requested": True}
        result.update({name: {"ok": True} for name in
                       ("connect", "login", "startup", "runner", "upload", "disconnect")})
        result["upload"].update({"create_only": True, "readback_verified": True,
                                 "existing_file_replaced": False,
                                 "candidate_sha256": "a" * 64, "readback_sha256": "a" * 64})
        result["native_readback"] = {"ok": True, "download_complete": True, "candidate_equal": True}
        return result

    def test_complete_live_validation_requires_native_match(self):
        evidence = self.evidence()
        self.assertTrue(validation_passed(evidence))
        evidence["native_readback"]["candidate_equal"] = False
        self.assertFalse(validation_passed(evidence))
        del evidence["native_readback"]
        self.assertFalse(validation_passed(evidence))

    def test_any_failed_stage_prevents_live_pass(self):
        for name in ("connect", "login", "startup", "runner", "upload", "disconnect"):
            with self.subTest(stage=name):
                evidence = self.evidence()
                evidence[name]["ok"] = False
                self.assertFalse(validation_passed(evidence))

    def test_missing_or_mismatched_readback_hashes_prevent_pass(self):
        evidence = self.evidence()
        evidence["upload"]["readback_sha256"] = "b" * 64
        self.assertFalse(validation_passed(evidence))
        evidence["upload"].pop("candidate_sha256")
        evidence["upload"].pop("readback_sha256")
        self.assertFalse(validation_passed(evidence))

    def test_offline_validation_requires_explicit_disabled_gate(self):
        self.assertFalse(validation_passed({"live_create": False}))
        self.assertTrue(validation_passed({"live_create": False, "write_disabled_by_default": True}))


class UploadValidatorFlowTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, failures):
        calls = []

        @asynccontextmanager
        async def stdio(_):
            yield None, None

        async def call(name, arguments):
            calls.append(name)
            result = failures.get(name, {"ok": True})
            if name == "zvm_upload_create_only":
                result = {"ok": True, "create_only": True, "readback_verified": True,
                          "existing_file_replaced": False, "candidate_sha256": "a" * 64,
                          "readback_sha256": "a" * 64}
            return SimpleNamespace(isError=False, structuredContent=result)

        client = AsyncMock()
        client.__aenter__.return_value = client
        client.list_tools.return_value = SimpleNamespace(tools=[SimpleNamespace(name=n) for n in EXPECTED])
        client.call_tool.side_effect = call
        with tempfile.TemporaryDirectory() as folder:
            args = SimpleNamespace(device="0200@", live_create=True, verify_native=True,
                download_root=folder, credential_file="/unused-local-credentials", reader_name="ZM02EA0B",
                output=Path(folder) / "evidence.json", edit_id="edit-" + "0" * 24,
                plan_id="plan-" + "0" * 24, plan_sha256="b" * 64,
                candidate_sha256="a" * 64, target="ZV1234AB EXEC A1")
            with patch("validate_zvm_upload.stdio_client", stdio), \
                 patch("validate_zvm_upload.ClientSession", return_value=client), \
                 redirect_stdout(io.StringIO()):
                result = await validate_upload(args)
            self.assertTrue(args.output.is_file())
        return calls, result

    async def test_failed_startup_stops_before_runner_or_upload(self):
        calls, result = await self.exercise({"zvm_startup": {"ok": False, "outcome": "timeout"}})
        self.assertFalse(result["passed"])
        self.assertNotIn("zvm_prepare_runner", calls)
        self.assertNotIn("zvm_upload_create_only", calls)
        self.assertEqual(calls[-1], "zvm_disconnect")

    async def test_failed_native_readback_never_repeats_successful_upload(self):
        calls, result = await self.exercise({"zvm_download": {"ok": False, "download_complete": False}})
        self.assertFalse(result["passed"])
        self.assertTrue(result["upload"]["readback_verified"])
        self.assertEqual(calls.count("zvm_upload_create_only"), 1)
        self.assertEqual(calls[-1], "zvm_disconnect")


if __name__ == "__main__":
    unittest.main()
