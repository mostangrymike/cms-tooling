import json
import os
import tempfile
import unittest

import cms_profiles


class CmsProfilesOfflineEnd2EndTests(unittest.TestCase):
    def test_offline_end2end_profile_lookup(self):
        # Prepare a temporary profiles.json
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "profiles.json")
            cfg = {
                "default": "default",
                "profiles": [
                    {"name": "default", "host": "host1", "port": 23, "ftp_host": "ftp-host1", "ftp_port": 2121},
                    {"name": "lab", "host": "host2", "port": 22, "ftp_host": "ftp-host2", "ftp_port": 2122},
                ],
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
            data = cms_profiles.load_profiles(path)
            self.assertIn("profiles", data)
            self.assertEqual([p["name"] for p in data["profiles"]], ["default", "lab"])
            ftp_dest = cms_profiles.read_profile_ftp_destination("lab", path)
            self.assertEqual(ftp_dest, ("ftp-host2", 2122))


if __name__ == "__main__":
    unittest.main()
