"""Offline guards for the derived distribution manifest.

The builder no longer keeps a hand-written file list.  These tests pin the
rules: follow real imports, keep support files explicit, and fail the build
when a tracked module is neither shipped nor excluded with a reason.
"""
import tempfile
import unittest
from pathlib import Path
import subprocess

import build_cms_tooling as build


class ManifestTests(unittest.TestCase):
    def tree(self, files, docs=("README.md",)):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name in docs:
            (root / name).write_text("doc\n", encoding="utf-8")
        for name, text in files.items():
            (root / name).write_text(text, encoding="utf-8")
        return root

    def test_follows_transitive_local_imports(self):
        root = self.tree({
            "app.py": "import helper\n",
            "helper.py": "from leaf import thing\n",
            "leaf.py": "thing = 1\n",
        })
        files = build.source_files(root, entry_points=("app.py",),
                                   support_files=("README.md",), excluded={})
        self.assertEqual(files, ("README.md", "app.py", "helper.py", "leaf.py"))

    def test_sees_imports_inside_functions_and_guarded_blocks(self):
        root = self.tree({
            "app.py": ("def run():\n    import late\n\n"
                       "try:\n    from guarded import x\nexcept ImportError:\n    x = None\n"),
            "late.py": "",
            "guarded.py": "x = 1\n",
        })
        files = build.source_files(root, entry_points=("app.py",), support_files=(), excluded={})
        self.assertEqual(files, ("app.py", "guarded.py", "late.py"))

    def test_unreachable_module_fails_the_build(self):
        root = self.tree({"app.py": "", "orphan.py": ""})
        with self.assertRaises(ValueError) as caught:
            build.source_files(root, entry_points=("app.py",), support_files=(), excluded={})
        self.assertIn("orphan.py", str(caught.exception))

    def test_explicit_exclusion_with_a_reason_is_allowed(self):
        root = self.tree({"app.py": "", "legacy.py": ""})
        files = build.source_files(root, entry_points=("app.py",), support_files=(),
                                   excluded={"legacy.py": "retired helper"})
        self.assertEqual(files, ("app.py",))

    def test_blank_exclusion_reason_is_rejected(self):
        root = self.tree({"app.py": "", "legacy.py": ""})
        with self.assertRaises(ValueError):
            build.source_files(root, entry_points=("app.py",), support_files=(),
                               excluded={"legacy.py": "   "})

    def test_excluding_an_imported_module_is_rejected(self):
        root = self.tree({"app.py": "import used\n", "used.py": ""})
        with self.assertRaises(ValueError) as caught:
            build.source_files(root, entry_points=("app.py",), support_files=(),
                               excluded={"used.py": "not really unused"})
        self.assertIn("used.py", str(caught.exception))

    def test_missing_support_file_is_rejected(self):
        root = self.tree({"app.py": ""})
        with self.assertRaises(ValueError):
            build.source_files(root, entry_points=("app.py",),
                               support_files=("MISSING.md",), excluded={})

    def git_tree(self, files):
        root = self.tree(files)
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "README.md", *files], check=True)
        return root

    def test_untracked_scratch_file_is_not_required(self):
        root = self.git_tree({"app.py": ""})
        (root / "scratch.py").write_text("", encoding="utf-8")
        files = build.source_files(root, entry_points=("app.py",), support_files=(), excluded={})
        self.assertEqual(files, ("app.py",))

    def test_exclusion_naming_an_untracked_file_is_rejected(self):
        root = self.git_tree({"app.py": ""})
        with self.assertRaises(ValueError):
            build.source_files(root, entry_points=("app.py",), support_files=(),
                               excluded={"ghost.py": "typo in the exclusion table"})

    def test_repository_manifest_is_complete(self):
        root = Path(build.__file__).resolve().parent
        files = build.source_files(root)
        self.assertEqual(len(files), len(set(files)))
        for required in ("cms_mcp.py", "cms_policy.py", "build_cms_tooling.py",
                         "test_cms_build.py", "ci/cms-tooling.yml"):
            self.assertIn(required, files)
        for excluded in build.EXCLUDED_SOURCES:
            self.assertNotIn(excluded, files)


if __name__ == "__main__":
    unittest.main()
