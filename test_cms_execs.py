"""Static guards for the shipped CMS exec sources.

These are not REXX interpreters.  Each check corresponds to a failure that was
actually observed on the z/VM 6.3 guest, so a regression fails here instead of
at the CMS prompt with a message like ``DMSOPN062E Invalid character . in
fileid RXA. MODULE``.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

EXECS = Path(__file__).resolve().parent / "cms-execs"

#: CMS reads these as fixed 80-column records; a longer line is truncated or
#: rejected by the upload path.
MAX_COLUMNS = 80

#: ``stem.(expression)`` is parsed as a routine call by this CMS REXX level and
#: fails at run time with Error 40.
INDEXED_STEM = re.compile(r"[A-Za-z0-9_]\.\(")

#: ``stem.a.stem.b`` silently becomes ``stem.A.STEM.B``: a stem cannot index by
#: its own stem name.  Computed counts must go through a plain variable.
STEM_OF_STEM = re.compile(r"\b([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\.\1\.")


def exec_files():
    return sorted(p for p in EXECS.glob("*.EXEC"))


class CmsExecSources(unittest.TestCase):
    def test_execs_exist(self):
        self.assertTrue(exec_files(), "no cms-execs/*.EXEC sources found")

    def test_records_fit_eighty_columns(self):
        for path in exec_files():
            with self.subTest(path=path.name):
                for number, line in enumerate(path.read_text().splitlines(), 1):
                    self.assertLessEqual(
                        len(line), MAX_COLUMNS,
                        f"{path.name}:{number} is {len(line)} columns")

    def test_no_tabs(self):
        for path in exec_files():
            with self.subTest(path=path.name):
                self.assertNotIn("\t", path.read_text(), f"{path.name} has a tab")

    def test_no_indexed_stem_expressions(self):
        for path in exec_files():
            with self.subTest(path=path.name):
                for number, line in enumerate(path.read_text().splitlines(), 1):
                    self.assertIsNone(
                        INDEXED_STEM.search(line),
                        f"{path.name}:{number} uses stem.(expr), which this CMS "
                        "REXX parses as a routine call")

    def test_no_stem_indexed_by_its_own_stem(self):
        for path in exec_files():
            with self.subTest(path=path.name):
                for number, line in enumerate(path.read_text().splitlines(), 1):
                    self.assertIsNone(
                        STEM_OF_STEM.search(line),
                        f"{path.name}:{number} indexes a stem by itself; the "
                        "middle name is read as an index, not as its value")

    def test_header_comment(self):
        for path in exec_files():
            with self.subTest(path=path.name):
                first = path.read_text().splitlines()[0]
                self.assertTrue(first.startswith("/*"), f"{path.name} needs a header comment")

    def test_writers_close_their_files(self):
        """EXECIO writes stay invisible to other commands until FINIS."""
        for path in exec_files():
            text = path.read_text()
            if "DISKW" not in text:
                continue
            with self.subTest(path=path.name):
                self.assertIn(
                    "(FINIS", text,
                    f"{path.name} writes with EXECIO but never closes the file; "
                    "the next command will not see it")

    def test_patch_keeps_its_safety_nets(self):
        text = (EXECS / "PATCH.EXEC").read_text()
        self.assertIn("BAK", text, "PATCH must leave a backup")
        self.assertIn("(CHECK", text, "PATCH must keep the dry-run option")

    def test_patch_and_grep_declare_exit_codes(self):
        for name in ("PATCH.EXEC", "GREP.EXEC"):
            with self.subTest(path=name):
                text = (EXECS / name).read_text()
                self.assertIn("Exit", text, f"{name} should document its exit codes")
                self.assertIn("usage", text.lower(), f"{name} should have a usage path")


if __name__ == "__main__":
    unittest.main()
