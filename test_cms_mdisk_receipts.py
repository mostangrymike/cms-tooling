import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from cms_mdisk_lifecycle import create_ownership_receipt
from cms_mdisk_receipts import OwnershipReceiptStore


def creation_inputs():
    plan = {
        "schema": "cms-minidisk-plan-v1",
        "request": {"filemode": "E", "size_mib": 32},
        "proposal": {
            "owner": "MAINT",
            "virtual_device": "0600",
            "volser": "VOL001",
            "start_cylinder": 21,
            "cylinders": 46,
        },
    }
    plan["plan_sha256"] = hashlib.sha256(json.dumps(
        plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    verification = {
        "active_directory_identity_confirmed": True,
        "cp_mapping_verified": True,
        "format_verified": True,
        "access_verified": True,
        "directory_identity": "M173NEW DIRECT C",
        "directory_sha256": "a" * 64,
        "verified_at": "2026-11-14T11:58:00Z",
    }
    return plan, verification


def create_receipt(key):
    plan, verification = creation_inputs()
    return create_ownership_receipt(plan, verification, key)


class ReceiptStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "private-state"
        self.store = OwnershipReceiptStore(self.root)

    def test_key_receipt_and_consumed_ledger_are_private_and_persistent(self):
        key = self.store.load_or_create_key()
        self.assertGreaterEqual(len(key), 32)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.store.key_path.stat().st_mode), 0o600)
        self.assertEqual(self.store.load_or_create_key(), key)

        plan, verification = creation_inputs()
        receipt = self.store.issue_receipt(plan, verification)
        path = self.store.receipts_dir / f"{receipt['receipt_id']}.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(self.store.load_receipt(receipt["receipt_id"]), receipt)
        self.assertEqual(self.store.consumed_receipt_ids(), [])

        self.store.consume_receipt(receipt["receipt_id"])
        self.assertEqual(self.store.consumed_receipt_ids(), [receipt["receipt_id"]])
        with self.assertRaisesRegex(ValueError, "already been consumed"):
            self.store.consume_receipt(receipt["receipt_id"])

    def test_key_symlinks_and_permissive_state_directory_refuse(self):
        self.root.mkdir(mode=0o700)
        target = self.root / "external-key"
        target.write_bytes(b"x" * 32)
        self.store.key_path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "safely open Ownership key"):
            self.store.load_or_create_key()

        self.store.key_path.unlink()
        os.chmod(self.root, 0o755)
        with self.assertRaisesRegex(ValueError, "must not be accessible"):
            self.store.load_or_create_key()

    def test_receipt_signature_is_checked_before_persistence(self):
        key = self.store.load_or_create_key()
        receipt = create_receipt(key)
        receipt["minidisk"]["cylinders"] += 1
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            self.store.save_receipt(receipt)


if __name__ == "__main__":
    unittest.main()
