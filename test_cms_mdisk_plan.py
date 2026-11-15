import unittest
from datetime import datetime, timezone

from cms_mdisk_plan import plan_minidisk


NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def inventory():
    return {
        "schema": "cms-minidisk-inventory-v1",
        "captured_at": "2026-11-14T11:55:00Z",
        "sources": {
            "active_cp_directory": "complete",
            "cp_allocations": "complete",
            "volume_geometry": "complete",
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
                "fullpack": True,
                "allocations": [],
            },
            {
                "volser": "DATA01",
                "device_type": "3390",
                "cylinders": 100,
                "blocks_per_cylinder": 180,
                "eligible_for_user_mdisk": True,
                "fullpack": False,
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
        self.assertEqual(proposal["directory_mdisk_statement"],
                         "MDISK 0600 3390 50 29 DATA01 W")
        self.assertFalse(result["execution_implemented"])
        self.assertFalse(result["cms_operations_performed"])
        self.assertFalse(result["format_authorized"])

    def test_unknown_filemode_and_accessed_filemode_refuse(self):
        with self.assertRaisesRegex(ValueError, "one uppercase letter"):
            plan_minidisk("DD", 1, inventory(), now=NOW)
        with self.assertRaisesRegex(ValueError, "already used or reserved"):
            plan_minidisk("G", 1, inventory(), now=NOW)
        with self.assertRaisesRegex(ValueError, "used or reserved"):
            plan_minidisk("D", 1, inventory(), now=NOW)

    def test_stale_or_incomplete_inventory_refuses(self):
        data = inventory()
        data["captured_at"] = "2026-11-14T11:00:00Z"
        with self.assertRaisesRegex(ValueError, "older than 15 minutes"):
            plan_minidisk("E", 1, data, now=NOW)
        data = inventory()
        data["sources"]["cp_allocations"] = "partial"
        with self.assertRaisesRegex(ValueError, "Complete CP directory"):
            plan_minidisk("E", 1, data, now=NOW)

    def test_fullpack_volume_is_never_allocated(self):
        data = inventory()
        data["volumes"] = data["volumes"][:1]
        with self.assertRaisesRegex(ValueError, "No verified contiguous extent"):
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
        with self.assertRaisesRegex(ValueError, "No verified contiguous extent"):
            plan_minidisk("E", 500, inventory(), now=NOW)
        with self.assertRaisesRegex(ValueError, "Size in MiB"):
            plan_minidisk("E", 0, inventory(), now=NOW)


if __name__ == "__main__":
    unittest.main()
