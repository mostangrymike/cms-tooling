import hashlib
import json
import unittest
from datetime import datetime, timezone

from cms_mdisk_inventory import build_inventory
from cms_mdisk_lifecycle import (
    create_ownership_receipt,
    plan_minidisk_deletion,
)
from cms_mdisk_plan import plan_minidisk


NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
SIGNING_KEY = b"local-provisioning-test-key-32-bytes!!"
CP_MAP = """\
VOL001 0123 1 20 20 1 1 5% DRCT ACTIVE
"""
GEOMETRY = """\
0123 CUTYPE = 2107-E8, DEVTYPE = 3390-0C, VOLSER = VOL001, CYLS = 100
"""
CAPTURED_AT = {
    "active_cp_directory": "2026-11-14T11:55:00Z",
    "cp_allocations": "2026-11-14T11:56:00Z",
    "volume_geometry": "2026-11-14T11:57:00Z",
}
REVIEW = {
    "VOL001": {
        "reviewed_by": "operator",
        "reviewed_at": "2026-11-14T11:58:00Z",
        "fullpack_overlay_approved": True,
    }
}
DIRECTORY_BEFORE = """\
USER MAINT PRIVATE1 32M 64M ABCDEFG
 MDISK A01 3390 001 020 VOL001 MR READ WRITE MULTIPLE
USER SYSDUMP1 PRIVATE2 32M 64M G
 MDISK 123 3390 000 END VOL001 MR READ WRITE MULTIPLE
"""
DIRECTORY_AFTER = """\
USER MAINT PRIVATE1 32M 64M ABCDEFG
 MDISK A01 3390 001 020 VOL001 MR READ WRITE MULTIPLE
 MDISK 600 3390 021 002 VOL001 W PRIVATE3 PRIVATE4 PRIVATE5
USER SYSDUMP1 PRIVATE2 32M 64M G
 MDISK 123 3390 000 END VOL001 MR READ WRITE MULTIPLE
"""


def inventory(directory_source):
    return build_inventory(
        directory_source,
        CP_MAP,
        GEOMETRY,
        directory_identity="M173NEW DIRECT C",
        target_volsers=["VOL001"],
        captured_at=CAPTURED_AT,
        active_directory_identity_confirmed=True,
        allowed_vdevs=["0600", "0601"],
        accessed_filemodes=["A", "C"],
        reserved_filemodes=["D"],
        volume_reviews=REVIEW,
        now=NOW,
    )


def usage_evidence(current_inventory, *, attached_users=None, linked_users=None):
    evidence = {
        "schema": "cms-mdisk-usage-v1",
        "captured_at": "2026-11-14T11:59:00Z",
        "virtual_device": "0600",
        "mdisk_location": {
            "owner": "MAINT",
            "virtual_device": "0600",
            "volser": "VOL001",
            "start_cylinder": 21,
            "cylinders": 2,
        },
        "active_directory_sha256":
            current_inventory["sources"]["active_cp_directory"]["sha256"],
        "attached_users": attached_users or [],
        "linked_users": linked_users or [],
        "sources": {
            "query_mdisk": {"status": "complete", "sha256": "a" * 64},
            "query_virtual": {"status": "complete", "sha256": "b" * 64},
            "query_links": {"status": "complete", "sha256": "c" * 64},
        },
    }
    evidence["evidence_sha256"] = hashlib.sha256(json.dumps(
        evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return evidence


class MinidiskLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.initial_inventory = inventory(DIRECTORY_BEFORE)
        self.plan = plan_minidisk("E", 1, self.initial_inventory, now=NOW)
        self.receipt = create_ownership_receipt(
            self.plan,
            {
                "active_directory_identity_confirmed": True,
                "cp_mapping_verified": True,
                "format_verified": True,
                "access_verified": True,
                "directory_identity": "M173NEW DIRECT C",
                "directory_sha256":
                    self.initial_inventory["sources"]["active_cp_directory"]["sha256"],
                "verified_at": "2026-11-14T11:58:00Z",
            },
            SIGNING_KEY,
        )
        self.current_inventory = inventory(DIRECTORY_AFTER)

    def delete_plan(self, **kwargs):
        arguments = {
            "receipt": self.receipt,
            "signing_key": SIGNING_KEY,
            "inventory": self.current_inventory,
            "usage_evidence": usage_evidence(self.current_inventory),
            "active_directory_identity_confirmed": True,
            "consumed_receipt_ids": [],
            "confirmation": (
                f"DELETE MAINT 0600 {self.receipt['receipt_id']}"),
            "now": NOW,
        }
        arguments.update(kwargs)
        return plan_minidisk_deletion(**arguments)

    def test_receipt_requires_verified_creation(self):
        with self.assertRaisesRegex(ValueError, "not fully verified"):
            create_ownership_receipt(
                self.plan, {"format_verified": True}, SIGNING_KEY)

    def test_delete_plan_requires_matching_signed_receipt_and_extent(self):
        result = self.delete_plan()
        self.assertEqual(result["action"], "remove_one_mdisk_from_candidate")
        self.assertEqual(result["target"]["virtual_device"], "0600")
        self.assertFalse(result["execution_implemented"])
        self.assertFalse(result["cms_operations_performed"])
        self.assertFalse(result["directory_activation_authorized"])
        self.assertIn("allows the physical extent to be reused",
                      result["data_warning"])

    def test_tampered_or_unowned_receipt_refuses(self):
        altered = dict(self.receipt)
        altered["minidisk"] = dict(altered["minidisk"], volser="OTHER1")
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            self.delete_plan(receipt=altered)
        with self.assertRaisesRegex(ValueError, "signature verification failed"):
            self.delete_plan(signing_key=b"another-key-which-is-long-enough-123")

    def test_current_extent_must_match_receipt_exactly(self):
        wrong_extent = DIRECTORY_AFTER.replace(
            "MDISK 600 3390 021 002", "MDISK 600 3390 022 002")
        wrong_inventory = inventory(wrong_extent)
        with self.assertRaisesRegex(ValueError, "does not exactly match"):
            self.delete_plan(
                inventory=wrong_inventory,
                usage_evidence=usage_evidence(wrong_inventory))

    def test_minidisk_must_be_detached_and_unlinked(self):
        with self.assertRaisesRegex(ValueError, "still has attached users"):
            self.delete_plan(
                usage_evidence=usage_evidence(
                    self.current_inventory, attached_users=["MAINT"]))
        with self.assertRaisesRegex(ValueError, "still has linked users"):
            self.delete_plan(
                usage_evidence=usage_evidence(
                    self.current_inventory, linked_users=["OTHER"]))

    def test_cp_location_must_match_receipt(self):
        evidence = usage_evidence(self.current_inventory)
        evidence["mdisk_location"]["start_cylinder"] = 22
        evidence.pop("evidence_sha256")
        evidence["evidence_sha256"] = hashlib.sha256(json.dumps(
            evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.delete_plan(usage_evidence=evidence)

    def test_delete_requires_exact_confirmation_and_active_source(self):
        with self.assertRaisesRegex(ValueError, "requires exact confirmation"):
            self.delete_plan(confirmation="DELETE 0600")
        with self.assertRaisesRegex(ValueError, "independently confirmed"):
            self.delete_plan(active_directory_identity_confirmed=False)

    def test_consumed_receipt_cannot_be_reused(self):
        with self.assertRaisesRegex(ValueError, "already been consumed"):
            self.delete_plan(consumed_receipt_ids=[self.receipt["receipt_id"]])


if __name__ == "__main__":
    unittest.main()
