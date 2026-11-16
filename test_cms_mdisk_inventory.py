import unittest
from datetime import datetime, timezone

from cms_mdisk_inventory import build_inventory
from cms_mdisk_plan import plan_minidisk


NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
DIRECTORY = """\
USER MAINT DO-NOT-EMIT 32M 64M ABCDEFG
 MDISK 600 3390 021 010 VOL001 W READ WRITE MULTIPLE
USER $DIRECT$ DO-NOT-EMIT 32M 64M G
 MDISK A01 3390 001 020 VOL001 MR READ WRITE MULTIPLE
USER SYSDUMP1 DO-NOT-EMIT 32M 64M G
 MDISK 123 3390 000 END VOL001 MR READ WRITE MULTIPLE
"""
CP_MAP = """\
VOLID  RDEV      START        END  TOTAL IN USE   HIGH USED TYPE
VOL001 0123          1         20     20      1      1   5% DRCT ACTIVE
"""
GEOMETRY = """\
0123 CUTYPE = 2107-E8, DEVTYPE = 3390-0C, VOLSER = VOL001, CYLS = 100
Ready;
.
"""
CAPTURED_AT = {
    "active_cp_directory": "2026-11-14T11:55:00Z",
    "cp_allocations": "2026-11-14T11:56:00Z",
    "volume_geometry": "2026-11-14T11:57:00Z",
}
REVIEWS = {
    "VOL001": {
        "reviewed_by": "operator",
        "reviewed_at": "2026-11-14T11:58:00Z",
        "fullpack_overlay_approved": True,
    }
}


class InventoryBuilderTests(unittest.TestCase):
    def build(self, **overrides):
        arguments = {
            "directory_source": DIRECTORY,
            "cp_alloc_source": CP_MAP,
            "geometry_source": GEOMETRY,
            "directory_identity": "USER DIRECT C",
            "captured_at": CAPTURED_AT,
            "active_directory_identity_confirmed": True,
            "allowed_vdevs": ["0601"],
            "accessed_filemodes": ["A", "C", "G"],
            "reserved_filemodes": ["D"],
            "volume_reviews": REVIEWS,
            "now": NOW,
        }
        arguments.update(overrides)
        return build_inventory(**arguments)

    def test_builds_planner_inventory_without_copying_directory_passwords(self):
        inventory = self.build()
        self.assertEqual(inventory["schema"], "cms-minidisk-inventory-v2")
        self.assertEqual(inventory["volumes"][0]["fullpack_owners"],
                         ["SYSDUMP1"])
        self.assertEqual(inventory["volumes"][0]["allocations"][0]["evidence"],
                         ["active_cp_directory", "cp_allocations"])
        self.assertNotIn("DO-NOT-EMIT", repr(inventory))
        proposal = plan_minidisk("E", 1, inventory, now=NOW)["proposal"]
        self.assertEqual(proposal["start_cylinder"], 31)

    def test_requires_explicit_active_directory_confirmation(self):
        with self.assertRaisesRegex(ValueError, "independently confirmed"):
            self.build(active_directory_identity_confirmed=False)

    def test_cp_directory_partial_overlap_fails_closed(self):
        cp_map = CP_MAP.replace("1         20", "15        25")
        with self.assertRaisesRegex(ValueError, "overlaps a directory extent"):
            self.build(cp_alloc_source=cp_map)

    def test_eligibility_reviews_must_name_known_volumes(self):
        with self.assertRaisesRegex(ValueError, "unknown volume"):
            self.build(volume_reviews={"NOTVOL": REVIEWS["VOL001"]})


if __name__ == "__main__":
    unittest.main()
