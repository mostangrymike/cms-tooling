import sys
import types
import unittest

import cms_telnet_driver as telnet_driver  # top-level module


class TelnetProfileOverrideTests(unittest.TestCase):
    def test_profile_override_applied_without_network(self):
        # Inject a fake cms_profiles module to simulate profile loading
        fake = types.SimpleNamespace(get_profile=lambda name: {"host": "10.0.0.1", "port": 2323})
        old = sys.modules.get("cms_profiles")
        sys.modules["cms_profiles"] = fake
        try:
            # Construct with explicit credentials to avoid loading from credentials.json
            s = telnet_driver.CmsSession(host="127.0.0.1", port=23,
                                         userid="USER", password="PASS",
                                         profile_name="default")
            self.assertEqual(s.host, "10.0.0.1")
            self.assertEqual(s.port, 2323)
        finally:
            if old is None:
                del sys.modules["cms_profiles"]
            else:
                sys.modules["cms_profiles"] = old


if __name__ == "__main__":
    unittest.main()
