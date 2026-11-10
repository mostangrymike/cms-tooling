"""Offline guards for the pure screen layer.

These tests never open a terminal.  They pin the sanitized observations and the
exact geometry predicates that ``cms_mcp.Session`` relies on, and they assert
that the screen layer does not import the server module back.
"""
import subprocess
import sys
import unittest
from pathlib import Path

import cms_screen
from cms_screen import (ROWS, COLS, blank_vm_read_input, classify, cp_input_field,
                        cp_logon_boundary, cp_password_prompt,
                        cp_pending_password_boundary, expected_input_matches,
                        field_layout, hx_read_boundary, login_layout,
                        password_is_vm_read_startup, sanitize_rows)


def rows_at(**cells):
    rows = [" " * COLS for _ in range(ROWS)]
    for index, text in cells.items():
        rows[int(index)] = text.ljust(COLS)
    return rows


def field(row=23, column=1, start_offset=1760, length=139, protected=False,
          nondisplay=False, empty=True, modified=False):
    return {"attribute_offset": start_offset - 1, "start_offset": start_offset,
            "length": length, "row": row, "column": column,
            "protected": protected, "numeric": False, "nondisplay": nondisplay,
            "modified": modified, "empty": empty}


def snapshot(rows=None, fields=None, state="vm_read", screen_kind="zvm_guest_banner",
             connected=True, keyboard="U", layout_error=None, cursor=None,
             emulator_mode="I"):
    return {"rows": rows if rows is not None else rows_at(**{"0": "Ready;"}),
            "fields": fields if fields is not None else [field()],
            "state": state, "screen_kind": screen_kind, "connected": connected,
            "keyboard": keyboard, "field_layout_error": layout_error,
            "emulator_mode": emulator_mode,
            "cursor": cursor if cursor is not None else {
                "row": 23, "column": 1, "protected": False}}


class ClassificationTests(unittest.TestCase):
    def test_reports_observations_without_completion(self):
        result = classify(rows_at(**{"0": "Ready;"}))
        self.assertEqual(result["state"], "cms_ready")
        self.assertIsNone(result["cms_command_complete"])
        self.assertEqual(result["classification"], "heuristic")

    def test_banner_kinds_are_distinct(self):
        hercules = classify(rows_at(**{"0": "HHC01027I Hercules version 4.7.0"}))
        guest = classify(rows_at(**{"0": "z/VM Version 6 Release 3.0  LOGON AT 12:00:00"}))
        self.assertEqual(hercules["screen_kind"], "hercules_banner")
        self.assertEqual(guest["screen_kind"], "zvm_guest_banner")


class GeometryTests(unittest.TestCase):
    def buffer(self, attrs):
        cells = ["20"] * (ROWS * COLS)
        for offset, attr in attrs.items():
            cells[offset] = f"SF(c0={attr})"
        return [" ".join(cells[n:n + COLS]) for n in range(0, ROWS * COLS, COLS)]

    def test_field_layout_recovers_the_139_column_input(self):
        fields = field_layout(self.buffer({0: "20", 1759: "00", 1899: "20"}))
        self.assertEqual(len(fields), 3)
        self.assertEqual((fields[1]["row"], fields[1]["column"], fields[1]["length"],
                          fields[1]["start_offset"], fields[1]["protected"],
                          fields[1]["nondisplay"]), (23, 1, 139, 1760, False, False))

    def test_sanitize_masks_nondisplay_fields_and_secrets(self):
        rows = rows_at(**{"0": "Ready;", "22": "TOPSECRET"})
        fields = [field(nondisplay=True)]
        safe = sanitize_rows(rows, fields, {"TOPSECRET"})
        self.assertNotIn("TOPSECRET", "\n".join(safe))
        self.assertEqual("\n".join(safe).replace("*", "").strip(), "Ready;")

    def test_sanitize_hides_everything_when_layout_is_unavailable(self):
        self.assertEqual(sanitize_rows(rows_at(**{"0": "Ready;"}), [], set(),
                                       layout_ok=False), ["*" * COLS] * ROWS)


class PredicateTests(unittest.TestCase):
    def login_screen(self):
        rows = rows_at(**{"19": "USERID", "20": "PASSWORD", "22": "COMMAND"})
        fields = [field(row=20, column=17, start_offset=1504, length=8),
                  field(row=21, column=17, start_offset=1584, length=8, nondisplay=True),
                  field(row=23, column=17, start_offset=1760, length=123)]
        return snapshot(rows=rows, fields=fields, state="login",
                        screen_kind="guest_or_unknown", cursor=None)

    def test_login_layout_accepts_the_verified_form(self):
        self.assertEqual(len(login_layout(self.login_screen())), 3)

    def test_login_layout_rejects_changed_geometry(self):
        screen = self.login_screen()
        screen["fields"][0]["length"] = 9
        with self.assertRaises(RuntimeError):
            login_layout(screen)

    def test_blank_vm_read_input_requires_the_exact_field(self):
        rows = rows_at(**{"23": "VM READ"})
        self.assertTrue(blank_vm_read_input(snapshot(rows=rows)))
        self.assertFalse(blank_vm_read_input(snapshot(rows=rows, fields=[field(length=138)])))

    def test_hx_boundary_requires_the_staged_cursor_when_hx_is_typed(self):
        rows = rows_at(**{"0": "z/VM 6.3.0  RECONNECTED AT 12:00:00", "23": "VM READ"})
        self.assertTrue(hx_read_boundary(snapshot(rows=rows)))
        self.assertFalse(hx_read_boundary(snapshot(rows=rows, cursor={
            "row": 23, "column": 3, "protected": False})))
        staged = snapshot(rows=rows, fields=[field(empty=False)], cursor={
            "row": 23, "column": 3, "protected": False})
        self.assertTrue(hx_read_boundary(staged, staged_hx=True))

    def test_cp_input_field_checks_cursor_and_nondisplay(self):
        screen = snapshot(state="cp_read", fields=[field(nondisplay=True)])
        self.assertTrue(cp_input_field(screen, nondisplay=True))
        self.assertFalse(cp_input_field(screen, nondisplay=False))

    def test_cp_logon_boundary_accepts_the_hercules_console(self):
        rows = rows_at(**{"0": "DEVICE NUMBER  SUBCHANNEL", "23": "CP READ"})
        self.assertTrue(cp_logon_boundary(snapshot(
            rows=rows, state="cp_read", screen_kind="hercules_banner")))

    def test_cp_password_prompt_needs_the_password_label(self):
        rows = rows_at(**{"0": "PASSWORD", "23": "CP READ"})
        self.assertTrue(cp_password_prompt(snapshot(
            rows=rows, state="password", fields=[field(nondisplay=True)])))

    def test_pending_password_boundary_accepts_an_unknown_banner(self):
        rows = rows_at(**{"23": "CP READ"})
        self.assertTrue(cp_pending_password_boundary(snapshot(
            rows=rows, state="cp_read", screen_kind="guest_or_unknown",
            fields=[field(nondisplay=True)])))

    def test_password_screen_refines_only_the_empty_startup_shape(self):
        rows = rows_at(**{"0": "PASSWORD  LOGON AT 12:00:00", "23": "VM READ"})
        observed = {"state": "password", "screen_kind": "hercules_banner"}
        parts = ["U", "F", "U", "C(127.0.0.1)", "I", "2", "24", "80", "22", "1"]
        self.assertTrue(password_is_vm_read_startup(observed, rows, [field()], parts, None))
        self.assertFalse(password_is_vm_read_startup(observed, rows, [field(empty=False)],
                                                     parts, None))
        self.assertFalse(password_is_vm_read_startup(observed, rows, [field()], parts,
                                                     "layout unavailable"))

    def test_expected_input_matches_the_padded_field(self):
        rows = rows_at(**{"22": "HELLO"})
        self.assertTrue(expected_input_matches([field()], rows, "HELLO"))
        self.assertFalse(expected_input_matches([field()], rows, "WRONG"))

    def test_screen_layer_does_not_import_the_server(self):
        root = Path(cms_screen.__file__).resolve().parent
        probe = "import sys, cms_screen; print('cms_mcp' in sys.modules)"
        result = subprocess.run([sys.executable, "-B", "-c", probe], cwd=root,
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
