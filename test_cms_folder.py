import unittest

from cms_folder import choose_filemode, plan_folder
from test_cms_mdisk_plan import NOW, inventory


class CmsFolderTests(unittest.TestCase):
    def test_folder_plan_selects_first_unused_valid_mode_after_size_request(self):
        self.assertEqual(choose_filemode(inventory()), "B")
        plan = plan_folder(20, inventory(), now=NOW)
        self.assertEqual(plan["request"]["size_mib"], 20)
        self.assertEqual(plan["request"]["filemode"], "B")
        self.assertFalse(plan["execution_implemented"])
        self.assertFalse(plan["cms_operations_performed"])

    def test_no_available_filemode_fails_closed(self):
        data = inventory()
        data["accessed_filemodes"] = list("ABCDEFGHIJKLMNOPQRTUVWXYZ")
        data["reserved_filemodes"] = ["D"]
        with self.assertRaisesRegex(ValueError, "No unused CMS filemode"):
            choose_filemode(data)


if __name__ == "__main__":
    unittest.main()
