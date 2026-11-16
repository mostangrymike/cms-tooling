import json
import os
import tempfile
import types
import sys
import unittest

import cms_profiles


class CmsProfilesTests(unittest.TestCase):
    def test_load_and_list_profiles_tmp(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            cfg = {
                "default": "default",
                "profiles": [
                    {"name": "default", "host": "host1", "port": 23, "ftp_host": "ftp1", "ftp_port": 2121},
                    {"name": "lab", "host": "host2", "port": 22, "ftp_host": "ftp2", "ftp_port": 2122},
                ],
            }
            json.dump(cfg, f)
            f.flush()
            path = f.name
        try:
            data = cms_profiles.load_profiles(path)
            self.assertIn("profiles", data)
            self.assertEqual(len(data["profiles"]), 2)
            self.assertEqual(data["profiles"][0]["name"], "default")
        finally:
            os.unlink(path)

    def test_get_profile_and_read_destination(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            cfg = {
                "default": "lab",
                "profiles": [
                    {"name": "default", "host": "host1", "port": 23, "ftp_host": "ftp1", "ftp_port": 2121},
                    {"name": "lab", "host": "host2", "port": 22, "ftp_host": "ftp2", "ftp_port": 2122},
                ],
            }
            json.dump(cfg, f)
            f.flush()
            path = f.name
        try:
            prof = cms_profiles.get_profile("lab", path)
            self.assertIsNotNone(prof)
            self.assertEqual(prof["host"], "host2")
            dest = cms_profiles.read_profile_ftp_destination("lab", path)
            self.assertEqual(dest, ("ftp2", 2122))
            # non-existent profile
            self.assertIsNone(cms_profiles.get_profile("doesnotexist", path))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
