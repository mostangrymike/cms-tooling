import unittest

from cms_mdisk_cp import (
    parse_cp_alloc_map,
    parse_cp_dasd_details,
    reconcile_directory,
)


CP_MAP = """\
                EXTENT     EXTENT                         % ALLOCATION
VOLID  RDEV      START        END  TOTAL IN USE   HIGH USED TYPE
-----  ---- ---------- ---------- ------ ------ ------ ---- -------------
M01RES 0123          1         20     20      1      1   5% DRCT ACTIVE
                     40         49     10      0      0   0% DRCT
M01P01 0125          1        100    100      1      1   1% PAGE ACT
Ready; T=0.01/0.01
.
"""


def directory_snapshot():
    return {
        "schema": "cms-minidisk-directory-snapshot-v1",
        "target_volsers": ["M01RES", "M01P01"],
        "source": {"identity": "USER DIRECT C", "sha256": "a" * 64},
        "used_vdevs": ["0123"],
        "volumes": [
            {
                "volser": "M01RES",
                "device_type": "3390",
                "cylinders": 100,
                "blocks_per_cylinder": 180,
                "fullpack": True,
                "fullpack_owners": ["MAINT"],
                "allocations": [
                    {"start": 1, "cylinders": 20, "kind": "mdisk",
                     "owner": "$DIRECT$", "vdev": "0A01", "subconfig": None}
                ],
            },
            {
                "volser": "M01P01",
                "device_type": "3390",
                "cylinders": 200,
                "blocks_per_cylinder": 180,
                "fullpack": True,
                "fullpack_owners": ["$PAGE$"],
                "allocations": [],
            },
        ],
    }


class CpAllocationTests(unittest.TestCase):
    def test_parses_cp_dasd_geometry_and_3390_block_geometry(self):
        result = parse_cp_dasd_details("""\
0123 CUTYPE = 2107-E8, DEVTYPE = 3390-0C, VOLSER = M01RES, CYLS = 11000
0124 CUTYPE = 2107-E8, DEVTYPE = 3390-0C, VOLSER = M01S01, CYLS = 11000
Ready;
.
""")
        self.assertEqual(result["volumes"]["M01RES"]["cylinders"], 11000)
        self.assertEqual(result["volumes"]["M01RES"]["blocks_per_cylinder"], 180)
        self.assertEqual(result["volumes"]["M01S01"]["rdev"], "0124")

    def test_cp_dasd_geometry_rejects_duplicates_and_empty_output(self):
        duplicate = """\
0123 CUTYPE = 2107-E8, DEVTYPE = 3390-0C, VOLSER = M01RES, CYLS = 11000
0124 CUTYPE = 2107-E8, DEVTYPE = 3390-0C, VOLSER = M01RES, CYLS = 11000
"""
        with self.assertRaisesRegex(ValueError, "Duplicate DASD geometry"):
            parse_cp_dasd_details(duplicate)
        with self.assertRaisesRegex(ValueError, "No 3390 geometry"):
            parse_cp_dasd_details("No DASD details\n")

    def test_parses_extent_rows_and_continuations(self):
        result = parse_cp_alloc_map(CP_MAP)
        self.assertEqual(result["schema"], "cms-minidisk-cp-alloc-map-v1")
        self.assertEqual(len(result["extents"]), 3)
        self.assertEqual(result["extents"][0]["cylinders"], 20)
        self.assertTrue(result["extents"][0]["active"])
        self.assertEqual(result["extents"][1]["volser"], "M01RES")
        self.assertFalse(result["extents"][1]["active"])
        self.assertEqual(result["extents"][2]["allocation_type"], "PAGE")

    def test_reconciliation_deduplicates_exact_reservation_and_adds_cp_only(self):
        cp = parse_cp_alloc_map(CP_MAP)
        result = reconcile_directory(directory_snapshot(), cp)
        m01res, m01p01 = result["volumes"]
        self.assertEqual(len(m01res["allocations"]), 2)
        self.assertEqual(
            m01res["allocations"][0]["evidence"],
            ["active_cp_directory", "cp_allocations"],
        )
        self.assertEqual(m01res["allocations"][1]["kind"], "cp_reserved")
        self.assertEqual(m01p01["allocations"][0]["start"], 1)
        self.assertEqual(m01p01["allocations"][0]["cylinders"], 100)
        self.assertEqual(m01p01["allocations"][0]["kind"], "cp_reserved")

    def test_partial_overlap_and_out_of_geometry_fail_closed(self):
        cp = parse_cp_alloc_map(CP_MAP)
        cp["extents"] = [dict(cp["extents"][0], start=15, end=25, cylinders=11)]
        with self.assertRaisesRegex(ValueError, "overlaps a directory extent"):
            reconcile_directory(directory_snapshot(), cp)
        cp["extents"] = [dict(cp["extents"][0], start=95, end=105, cylinders=11)]
        with self.assertRaisesRegex(ValueError, "exceeds verified volume geometry"):
            reconcile_directory(directory_snapshot(), cp)

    def test_no_extent_rows_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "No CP allocation extents"):
            parse_cp_alloc_map("QUERY ALLOC MAP returned no extents\n")

    def test_cp_extents_outside_target_scope_are_not_candidates(self):
        cp = parse_cp_alloc_map("""\
M01RES 0123 1 20 20 1 1 5% DRCT ACTIVE
OTHER1 0124 1 30 30 1 1 3% SPOOL
""")
        directory = directory_snapshot()
        directory["target_volsers"] = ["M01RES"]
        directory["volumes"] = [directory["volumes"][0]]
        result = reconcile_directory(directory, cp)
        self.assertEqual(result["cp_allocations"]["excluded_volsers"], ["OTHER1"])


if __name__ == "__main__":
    unittest.main()
