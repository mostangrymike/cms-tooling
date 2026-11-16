import unittest
from datetime import datetime, timezone

from cms_mdisk_plan import plan_minidisk


NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
DIRECTORY_SHA = "a" * 64
ALLOCATIONS_SHA = "b" * 64
GEOMETRY_SHA = "c" * 64


def inventory():
    return {
        "schema": "cms-minidisk-inventory-v2",
        "sources": {
            "active_cp_directory": {
                "status": "complete", "identity": "USER DIRECT C",
                "captured_at": "2026-11-14T11:55:00Z", "sha256": DIRECTORY_SHA,
            },
            "cp_allocations": {
                "status": "complete", "captured_at": "2026-11-14T11:56:00Z",
                "sha256": ALLOCATIONS_SHA,
                "active_directory_sha256": DIRECTORY_SHA,
            },
            "volume_geometry": {
                "status": "complete", "captured_at": "2026-11-14T11:57:00Z",
                "sha256": GEOMETRY_SHA, "volsers": ["FULL01", "DATA01"],
            },
        },
        "reconciliation": {
            "status": "verified",
            "active_directory_sha256": DIRECTORY_SHA,
            "source_sha256": {
                "active_cp_directory": DIRECTORY_SHA,
                "cp_allocations": ALLOCATIONS_SHA,
                "volume_geometry": GEOMETRY_SHA,
            },
        },
        "allowed_vdevs": ["0600", "0601"],
        "used_vdevs": ["0192"],
        "accessed_filemodes": ["A", "C", "G"],
        "reserved_filemodes": ["D"],
        "volumes": [
            {
                "volser": "FULL01",
                "device_type": "3390",
                "cylinders": 11000,
                "blocks_per_cylinder": 180,
                "eligible_for_user_mdisk": True,
                "eligibility_review": {
                    "reviewed_by": "operator",
                    "reviewed_at": "2026-11-14T11:58:00Z",
                    "active_directory_sha256": DIRECTORY_SHA,
                    "fullpack_overlay_approved": True,
                },
                "fullpack": True,
                "fullpack_owners": ["PMAINT"],
                "allocations": [],
            },
            {
                "volser": "DATA01",
                "device_type": "3390",
                "cylinders": 100,
                "blocks_per_cylinder": 180,
                "eligible_for_user_mdisk": True,
                "eligibility_review": {
                    "reviewed_by": "operator",
                    "reviewed_at": "2026-11-14T11:58:00Z",
                    "active_directory_sha256": DIRECTORY_SHA,
                    "fullpack_overlay_approved": False,
                },
                "fullpack": False,
                "fullpack_owners": [],
                "allocations": [
                    {"start": 0, "cylinders": 10, "kind": "mdisk"},
                    {"start": 30, "cylinders": 20, "kind": "cp_reserved"},
                    {"start": 80, "cylinders": 20, "kind": "mdisk"},
                ],
            },
        ],
    }


class MinidiskPlanTests(unittest.TestCase):
    def test_best_fit_plan_is_read_only_and_uses_verified_extent(self):
        result = plan_minidisk("E", 20, inventory(), now=NOW)
        proposal = result["proposal"]
        # 20 MiB needs ceil(20 * 256 / 180) = 29 cylinders.
        self.assertEqual(proposal["virtual_device"], "0600")
        self.assertEqual(proposal["volser"], "DATA01")
        self.assertEqual(proposal["start_cylinder"], 50)
        self.assertEqual(proposal["cylinders"], 29)
        self.assertEqual(proposal["resulting_bytes"], 21_381_120)
        self.assertEqual(proposal["resulting_mib"], 20.390625)
        self.assertEqual(proposal["directory_mdisk_statement"],
                         "MDISK 0600 3390 50 29 DATA01 W")
        self.assertEqual(proposal["cms_label"], "M0600E")
        self.assertFalse(result["execution_implemented"])
        self.assertFalse(result["cms_operations_performed"])
        self.assertFalse(result["format_authorized"])

    def test_unknown_filemode_and_accessed_filemode_refuse(self):
        with self.assertRaisesRegex(ValueError, "one uppercase letter"):
            plan_minidisk("DD", 1, inventory(), now=NOW)
        with self.assertRaisesRegex(ValueError, "other than S"):
            plan_minidisk("S", 1, inventory(), now=NOW)
        with self.assertRaisesRegex(ValueError, "already used or reserved"):
            plan_minidisk("G", 1, inventory(), now=NOW)
        with self.assertRaisesRegex(ValueError, "used or reserved"):
            plan_minidisk("D", 1, inventory(), now=NOW)

    def test_stale_or_incomplete_inventory_refuses(self):
        data = inventory()
        data["sources"]["active_cp_directory"]["captured_at"] = "2026-11-14T11:00:00Z"
        with self.assertRaisesRegex(ValueError, "older than 15 minutes"):
            plan_minidisk("E", 1, data, now=NOW)
        data = inventory()
        data["sources"]["cp_allocations"]["status"] = "partial"
        with self.assertRaisesRegex(ValueError, "Per-source"):
            plan_minidisk("E", 1, data, now=NOW)

    def test_source_hashes_and_capture_skew_must_reconcile(self):
        data = inventory()
        data["reconciliation"]["source_sha256"]["cp_allocations"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "does not match"):
            plan_minidisk("E", 1, data, now=NOW)
        data = inventory()
        data["sources"]["volume_geometry"]["captured_at"] = "2026-11-14T11:50:00Z"
        with self.assertRaisesRegex(ValueError, "more than 5 minutes apart"):
            plan_minidisk("E", 1, data, now=NOW)
        data = inventory()
        data["sources"]["cp_allocations"]["active_directory_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "does not identify"):
            plan_minidisk("E", 1, data, now=NOW)
        data = inventory()
        data["sources"]["volume_geometry"]["volsers"] = ["FULL01"]
        with self.assertRaisesRegex(ValueError, "does not match"):
            plan_minidisk("E", 1, data, now=NOW)

    def test_approved_fullpack_overlay_uses_only_explicit_allocations(self):
        data = inventory()
        data["volumes"][0]["eligible_for_user_mdisk"] = True
        data["volumes"][1]["eligible_for_user_mdisk"] = False
        data["volumes"][0]["allocations"] = [
            {"start": 0, "cylinders": 100, "kind": "mdisk"},
            {"start": 200, "cylinders": 100, "kind": "mdisk"},
        ]
        result = plan_minidisk("E", 20, data, now=NOW)
        proposal = result["proposal"]
        # Full-pack is an overlay marker; explicit MDISK extents stay occupied.
        self.assertEqual(proposal["volser"], "FULL01")
        self.assertEqual(proposal["start_cylinder"], 100)
        self.assertEqual(proposal["cylinders"], 29)

    def test_eligible_volume_needs_current_directory_review(self):
        data = inventory()
        data["volumes"][1]["eligibility_review"]["active_directory_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "different directory"):
            plan_minidisk("E", 1, data, now=NOW)
        data = inventory()
        data["volumes"][0]["eligibility_review"]["fullpack_overlay_approved"] = False
        with self.assertRaisesRegex(ValueError, "separate approval"):
            plan_minidisk("E", 1, data, now=NOW)
        data = inventory()
        data["volumes"][1]["eligibility_review"]["reviewed_at"] = "2026-11-14T11:54:00Z"
        with self.assertRaisesRegex(ValueError, "predates"):
            plan_minidisk("E", 1, data, now=NOW)

    def test_unknown_fullpack_owner_refuses(self):
        data = inventory()
        data["volumes"][0]["fullpack_owners"] = ["UNREVIEWED"]
        with self.assertRaisesRegex(ValueError, "not an approved overlay owner"):
            plan_minidisk("E", 1, data, now=NOW)

    def test_fullpack_marker_cannot_be_listed_as_an_extent(self):
        data = inventory()
        data["volumes"][0]["allocations"] = [
            {"start": 0, "cylinders": 11000, "kind": "fullpack"}
        ]
        with self.assertRaisesRegex(ValueError, "must not be listed as an allocation"):
            plan_minidisk("E", 1, data, now=NOW)

    def test_overlap_or_out_of_range_inventory_refuses(self):
        data = inventory()
        data["volumes"][1]["allocations"].append(
            {"start": 25, "cylinders": 10, "kind": "mdisk"})
        with self.assertRaisesRegex(ValueError, "overlapping allocations"):
            plan_minidisk("E", 1, data, now=NOW)
        data = inventory()
        data["volumes"][1]["allocations"][0]["start"] = 99
        with self.assertRaisesRegex(ValueError, "exceeds verified geometry"):
            plan_minidisk("E", 1, data, now=NOW)

    def test_special_vdev_and_exhausted_vdevs_refuse(self):
        data = inventory()
        data["allowed_vdevs"] = ["0192"]
        with self.assertRaisesRegex(ValueError, "reserved by CMS"):
            plan_minidisk("E", 1, data, now=NOW)
        data = inventory()
        data["used_vdevs"] = ["0600", "0601"]
        with self.assertRaisesRegex(ValueError, "No unused virtual device"):
            plan_minidisk("E", 1, data, now=NOW)

    def test_no_fit_and_invalid_size_refuse(self):
        data = inventory()
        data["volumes"][0]["eligible_for_user_mdisk"] = False
        with self.assertRaisesRegex(ValueError, "No verified contiguous extent"):
            plan_minidisk("E", 500, data, now=NOW)
        with self.assertRaisesRegex(ValueError, "Size in MiB"):
            plan_minidisk("E", 0, data, now=NOW)

    def test_regular_minidisk_never_uses_cylinder_zero(self):
        data = inventory()
        data["volumes"][0]["eligible_for_user_mdisk"] = False
        data["volumes"][1]["cylinders"] = 1
        data["volumes"][1]["allocations"] = []
        with self.assertRaisesRegex(ValueError, "No verified contiguous extent"):
            plan_minidisk("E", 1, data, now=NOW)

    def test_fifty_mib_reports_actual_cylinder_capacity(self):
        data = inventory()
        data["volumes"][0]["eligible_for_user_mdisk"] = False
        data["volumes"][1]["cylinders"] = 11000
        data["volumes"][1]["allocations"] = [
            {"start": 0, "cylinders": 10, "kind": "mdisk"},
            {"start": 30, "cylinders": 20, "kind": "cp_reserved"},
            {"start": 80, "cylinders": 10000, "kind": "mdisk"},
        ]
        proposal = plan_minidisk("E", 50, data, now=NOW)["proposal"]
        self.assertEqual(proposal["cylinders"], 72)
        self.assertEqual(proposal["resulting_bytes"], 53_084_160)
        self.assertEqual(proposal["resulting_mib"], 50.625)
        self.assertEqual(proposal["cms_label"], "M0600E")


if __name__ == "__main__":
    unittest.main()
