import unittest

from cms_mdisk_directory import insert_mdisk_line, parse_directory


GEOMETRY = {
    "VOL001": {
        "device_type": "3390",
        "cylinders": 100,
        "blocks_per_cylinder": 180,
    },
    "OLD338": {
        "device_type": "3380",
        "cylinders": 885,
        "blocks_per_cylinder": None,
    },
}


def f80(*records):
    return "".join(record.ljust(80) + "\n" for record in records).encode("ascii")


F80_GEOMETRY = {
    "VOL001": {
        "device_type": "3390",
        "cylinders": 200,
        "blocks_per_cylinder": 180,
    }
}


class DirectoryParserTests(unittest.TestCase):
    def test_extracts_extents_fullpacks_and_vdevs_without_passwords(self):
        source = """\
USER MAINT SUPERSECRET 32M 64M ABCDEFG
 MDISK 600 3390 0001 0010 VOL001 W READ WRITE MULTIPLE
SUBCONFIG MAINT-1
 MDISK 601 3390 0011 0009 VOL001 MR RDPASS WRPASS MPPASS
USER PMAINT ANOTHERSECRET 32M 64M G
 MDISK 141 3390 000 END VOL001 MR READ WRITE MULTIPLE
USER SYSDUMP1 SECRET3 32M 64M G
 MDISK 123 3390 000 END VOL001 MR READ WRITE MULTIPLE
USER OLDUSER SECRET4 32M 64M G
 MDISK CF1 3380 001 020 OLD338 MR READ WRITE MULTIPLE
* MDISK 777 3390 0001 0001 VOL001 W COMMENTED OUT
"""
        result = parse_directory(source, GEOMETRY, "USER DIRECT C")
        volume = result["volumes"][0]

        self.assertEqual(result["schema"], "cms-minidisk-directory-snapshot-v1")
        self.assertEqual(result["used_vdevs"], ["0123", "0141", "0600", "0601", "0CF1"])
        self.assertTrue(volume["fullpack"])
        self.assertEqual(volume["fullpack_owners"], ["PMAINT", "SYSDUMP1"])
        self.assertEqual(
            [(item["start"], item["cylinders"]) for item in volume["allocations"]],
            [(1, 10), (11, 9)],
        )
        self.assertEqual(volume["allocations"][1]["subconfig"], "MAINT-1")
        self.assertNotIn("SUPERSECRET", repr(result))
        self.assertNotIn("RDPASS", repr(result))
        self.assertNotIn("WRPASS", repr(result))
        self.assertNotIn("MPPASS", repr(result))

    def test_end_from_nonzero_start_means_remaining_extent(self):
        source = "USER MAINT SECRET 32M 64M G\n MDISK 600 3390 090 END VOL001 W\n"
        result = parse_directory(source, GEOMETRY, "M173NEW DIRECT C")
        self.assertEqual(result["volumes"][0]["allocations"][0]["cylinders"], 10)

    def test_overlapping_extents_fail_closed(self):
        source = """\
USER ONE SECRET 32M 64M G
 MDISK 600 3390 001 020 VOL001 W
USER TWO SECRET 32M 64M G
 MDISK 601 3390 010 020 VOL001 W
"""
        with self.assertRaisesRegex(ValueError, "Overlapping MDISK extents"):
            parse_directory(source, GEOMETRY, "USER DIRECT C")

    def test_target_volume_requires_verified_geometry_without_echoing_record(self):
        source = "USER MAINT SECRET 32M 64M G\n MDISK 600 3390 001 020 MISSING W SECRET\n"
        with self.assertRaisesRegex(ValueError, "Target volumes need verified 3390 geometry") as caught:
            parse_directory(
                source, GEOMETRY, "USER DIRECT C", target_volsers=["MISSING"])
        self.assertNotIn("SECRET", str(caught.exception))

    def test_unsupported_disk_type_on_target_volume_fails_closed(self):
        source = "USER MAINT SECRET 32M 64M G\n MDISK 600 FB-512 001 020 VOL001 W\n"
        with self.assertRaisesRegex(ValueError, "Unsupported MDISK device type"):
            parse_directory(source, GEOMETRY, "USER DIRECT C")

    def test_target_scope_skips_other_volume_extents_but_reserves_their_vdevs(self):
        source = """\
USER MAINT SECRET 32M 64M G
 MDISK 600 3390 001 020 VOL001 W
 MDISK 150 3390 001 020 OFFLINE W
"""
        result = parse_directory(
            source, {"VOL001": GEOMETRY["VOL001"]}, "USER DIRECT C",
            target_volsers=["VOL001"])
        self.assertEqual(result["target_volsers"], ["VOL001"])
        self.assertEqual(result["used_vdevs"], ["0150", "0600"])
        self.assertEqual(len(result["volumes"][0]["allocations"]), 1)

    def test_candidate_writer_inserts_one_line_and_preserves_source(self):
        source = f80(
            "USER MAINT PRIVATE-PASSWORD 32M 64M ABCDEFG",
            "SUBCONFIG MAINT-1",
            " MDISK 600 3390 100 010 VOL001 W PRIVATE1 PRIVATE2 PRIVATE3",
            "* END OF MAINT-1",
        )
        candidate = insert_mdisk_line(
            source,
            F80_GEOMETRY,
            "M173NEW DIRECT C",
            ["VOL001"],
            owner="MAINT",
            subconfig="MAINT-1",
            after_vdev="0600",
            statement="MDISK 0601 3390 110 5 VOL001 W",
        )
        original_records = [line.decode("ascii") for line in source.splitlines()]
        candidate_records = [line.decode("ascii") for line in candidate.splitlines()]
        self.assertEqual(len(candidate_records), len(original_records) + 1)
        inserted_index = next(
            i for i, record in enumerate(candidate_records)
            if record.strip().startswith("MDISK 0601 "))
        self.assertEqual(candidate_records[inserted_index - 1].strip(),
                         "MDISK 600 3390 100 010 VOL001 W PRIVATE1 PRIVATE2 PRIVATE3")
        self.assertEqual(candidate_records[inserted_index].strip(),
                         "MDISK 0601 3390 110 5 VOL001 W")
        restored = candidate_records[:inserted_index] + candidate_records[inserted_index + 1:]
        self.assertEqual(restored, original_records)

    def test_candidate_writer_refuses_used_vdev_overlap_and_missing_anchor(self):
        source = f80(
            "USER MAINT SECRET 32M 64M ABCDEFG",
            "SUBCONFIG MAINT-1",
            " MDISK 600 3390 100 010 VOL001 W",
        )
        args = {
            "volume_geometry": F80_GEOMETRY,
            "identity": "M173NEW DIRECT C",
            "target_volsers": ["VOL001"],
            "owner": "MAINT",
            "subconfig": "MAINT-1",
            "after_vdev": "0600",
        }
        with self.assertRaisesRegex(ValueError, "already used"):
            insert_mdisk_line(
                source, **args, statement="MDISK 0600 3390 110 5 VOL001 W")
        with self.assertRaisesRegex(ValueError, "overlaps"):
            insert_mdisk_line(
                source, **args, statement="MDISK 0601 3390 105 5 VOL001 W")
        with self.assertRaisesRegex(ValueError, "anchor is missing"):
            insert_mdisk_line(
                source, **{**args, "after_vdev": "0602"},
                statement="MDISK 0601 3390 110 5 VOL001 W")

    def test_directory_with_no_mdisk_fails(self):
        with self.assertRaisesRegex(ValueError, "No active MDISK"):
            parse_directory("USER MAINT SECRET 32M 64M G\n", GEOMETRY,
                            "USER DIRECT C")


if __name__ == "__main__":
    unittest.main()
