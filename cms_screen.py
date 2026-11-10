"""Pure 3270 screen classification and boundary predicates.

This module owns no terminal, session, or network state.  It turns observed
rows, terminal status, and field geometry into sanitized observations and the
exact screen-shape predicates a session may act on.  Keeping it separate from
``cms_mcp.Session`` makes the geometry rules testable without an emulator and
gives the transport layer one narrow dependency.
"""
from __future__ import annotations

import re

ROWS, COLS = 24, 80


def classify(rows: list[str]) -> dict:
    """Heuristics report observations, never command completion."""
    text = "\n".join(rows).upper()
    patterns = [
        ("login", r"USERID\s*===>[\s\S]*PASSWORD\s*===>"),
        ("password", r"(?:ENTER|TYPE|YOUR|LOGON).*PASSWORD|PASSWORD\s*[:=]|^\s*PASSWORD\s*$"),
        ("xedit", r"\bXEDIT\b|\*\*\* TOP OF FILE \*\*\*|\*\*\* END OF FILE \*\*\*"),
        # The host may append its z/VM system name after MORE; that suffix is
        # informational and can vary. Classify the MORE marker itself only.
        ("holding", r"\bHOLDING\b"), ("more", r"\bMORE\.\.\.|\bMORE\s*$"),
        ("cp_read", r"\bCP READ\b"),
        ("cms_ready", r"^\s*READY(?:\(-?[0-9]+\))?;"),
        ("vm_read", r"\bVM READ\b"),
        # Retain a preliminary RUNNING classification until the session can
        # combine it with guest-banner and input-field evidence.
        ("vm_running", r"\bRUNNING\s+[A-Z0-9*#@._-]+\s*$"),
        ("login", r"LOGON USERID|HCPLON\d+[A-Z]|ENTER.*LOGON"),
        ("logo", r"Z/VM ONLINE|HERCULES VERSION(?:\s*:|\s+\d)"),
    ]
    matches = [name for name, pattern in patterns if re.search(pattern, text, re.M)]
    if "HERCULES VERSION" in text:
        screen_kind = "hercules_banner"
    elif (re.search(r"Z/VM VERSION 6 RELEASE 3\.0", text)
          and re.search(r"\b(?:LOGON AT|RECONNECTED AT)\b", text)):
        screen_kind = "zvm_guest_banner"
    else:
        screen_kind = "guest_or_unknown"
    return {"state": matches[0] if matches else "unknown", "indicators": matches,
            "screen_kind": screen_kind,
            "cms_command_complete": None, "classification": "heuristic"}


def field_layout(lines: list[str]) -> list[dict]:
    """Parse SF attributes without ever returning field contents or raw hex."""
    starts = []
    pos = 0
    for token in " ".join(lines).split():
        if token.startswith("SA("):
            continue
        if token.startswith("SF("):
            m = re.search(r"c0=([0-9a-fA-F]{2})", token)
            if not m:
                raise ValueError("Field attribute missing c0")
            attr = int(m[1], 16)
            starts.append((pos, attr))
        elif not re.fullmatch(r"[0-9a-fA-F]{2,8}|-|GE\([0-9a-fA-F]{2}\)", token):
            raise ValueError("Unrecognized buffer token; contents withheld")
        pos += 1
    if pos != ROWS * COLS:
        raise ValueError(f"Expected 1920 screen positions, got {pos}")
    fields = []
    for i, (start, attr) in enumerate(starts):
        end = starts[(i + 1) % len(starts)][0]
        fields.append({"attribute_offset": start, "start_offset": (start + 1) % pos,
                       "length": (end - start - 1) % pos,
                       "row": (start + 1) % pos // COLS + 1,
                       "column": (start + 1) % COLS + 1,
                       "protected": bool(attr & 0x20), "numeric": bool(attr & 0x10),
                       "nondisplay": attr & 0x0C == 0x0C, "modified": bool(attr & 1)})
    return fields


def sanitize_rows(rows: list[str], fields: list[dict], secrets: set[str],
                  password: bool = False, layout_ok: bool = True) -> list[str]:
    flat = list("".join(rows))
    if not layout_ok or (secrets and not fields):
        return ["*" * COLS for _ in range(ROWS)]
    for field in fields:
        if field["nondisplay"] or ((password or secrets) and not field["protected"]):
            for n in range(field["length"]):
                flat[(field["start_offset"] + n) % len(flat)] = "*"
    text = "".join(flat)
    # Every input string is treated as potentially secret, including across rows.
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            text = re.sub(re.escape(secret), lambda m: "*" * len(m[0]), text, flags=re.I)
    # Protect credentials already present when attaching to a screen.
    rows = [text[i:i + COLS] for i in range(0, ROWS * COLS, COLS)]
    # Match inline passwords within one physical row, never the next row's
    # version banner or the ordinary 'LOGON AT <time>' diagnostic.
    safe_rows = []
    for row in rows:
        row = re.sub(r"(?i)(\bLOGON[ \t]+(?!AT(?:[ \t]|$))\S+[ \t]+)(\S+)",
                     lambda m: m[1] + "*" * len(m[2]), row)
        # CP READ may display an account/session identifier after the state.
        row = re.sub(r"(?i)(\b(?:CP READ|VM READ|RUNNING)[ \t]+)([A-Z0-9$#@._-]+)",
                     lambda m: m[1] + "*" * len(m[2]), row)
        safe_rows.append(row)
    return safe_rows


def host_display(screen):
    """Compare host-controlled display only, excluding local input and keyboard."""
    flat = list("".join(screen["rows"]))
    for field in screen["fields"]:
        if not field["protected"]:
            for n in range(field["length"]):
                flat[(field["start_offset"] + n) % (ROWS * COLS)] = " "
    return "".join(flat)


def login_layout(screen):
    """Verify the combined guest login form before any credential is sent."""
    expected = [(20, 17, 8, False), (21, 17, 8, True), (23, 17, 123, False)]
    fields = [f for f in screen["fields"] if not f["protected"]]
    actual = [(f["row"], f["column"], f["length"], f["nondisplay"]) for f in fields]
    rows = screen["rows"]
    if (screen["state"] != "login" or screen["field_layout_error"] is not None
            or not screen["connected"] or screen["emulator_mode"] != "I"
            or actual != expected or any(f["modified"] for f in fields)
            or "USERID" not in rows[19][:16] or "PASSWORD" not in rows[20][:16]
            or "COMMAND" not in rows[22][:16]):
        raise RuntimeError("Login form or field attributes differ from verified layout; no credentials submitted")
    return fields


def tnz_login_layout(screen):
    """TNZ may receive field attributes before protected label text."""
    fields = [f for f in screen["fields"] if not f["protected"]]
    actual = [(f["row"], f["column"], f["length"], f["nondisplay"]) for f in fields]
    expected = [(20, 17, 8, False), (21, 17, 8, True), (23, 17, 123, False)]
    if (screen["field_layout_error"] is not None or screen["keyboard"] != "U"
            or actual != expected or any(not f["empty"] for f in fields)):
        raise RuntimeError("TNZ login field geometry differs from verified layout")
    screen["state"] = "login"
    screen["indicators"] = ["login"]
    return fields


def blank_vm_read_input(screen):
    """True for the exact empty startup prompt, including the TNZ pending case."""
    rows = screen.get("rows", [])
    fields = [f for f in screen.get("fields", []) if not f["protected"]]
    labelled_vm_read = "VM READ" in rows[-1].upper() and "CP READ" not in rows[-1].upper()
    geometry = (len(rows) == ROWS and len(fields) == 1
        and (fields[0]["row"], fields[0]["column"], fields[0]["length"],
             fields[0]["nondisplay"], fields[0]["empty"])
            == (23, 1, 139, False, True))
    tnz_pending_vm_read = (screen.get("state") == "vm_running"
        and screen.get("screen_kind") == "zvm_guest_banner")
    return ((screen.get("state") == "vm_read" or tnz_pending_vm_read)
            and screen.get("connected") and screen.get("keyboard") == "U"
            and screen.get("field_layout_error") is None and geometry
            and (labelled_vm_read or tnz_pending_vm_read))


def runner_protocol_visible(screen):
    """A startup continuation must not consume a visible capture exchange."""
    return any(re.match(r"^\s*(?:ZM1|ZA1)\s+[0-9A-F]{16}\b", row)
               for row in screen.get("rows", []))


def cp_input_field(screen, nondisplay=False, require_cursor=True):
    fields = [f for f in screen.get("fields", []) if not f["protected"]]
    return (screen.get("connected") and screen.get("keyboard") == "U"
            and screen.get("field_layout_error") is None
            and (not require_cursor or screen.get("cursor") == {
                "row": 23, "column": 1, "protected": False})
            and len(fields) == 1 and fields[0]["row"] == 23
            and fields[0]["column"] == 1 and fields[0]["length"] == 139
            and fields[0]["nondisplay"] is nondisplay and fields[0]["empty"])


def cp_logon_boundary(screen, require_cursor=False):
    rows = screen.get("rows", [])
    text = "\n".join(rows).upper()
    menu = (rows[1].strip() == "Enter one of the following commands:"
            and re.match(r"\s*LOGON userid\b.*\bLOGON VMUSER1\)", rows[3], re.I)
            and rows[5].strip() == "LOGOFF")
    hercules_cp = (screen.get("screen_kind") == "hercules_banner"
                   and "DEVICE NUMBER" in text and "SUBCHANNEL" in text)
    return (screen.get("state") == "cp_read" and len(rows) == ROWS
            and cp_input_field(screen, nondisplay=False,
                               require_cursor=require_cursor)
            and "CP READ" in rows[23].upper() and (menu or hercules_cp)
            and not re.search(r"\b(?:RECONNECTED AT|LOGON AT)\b", text, re.I))


def cp_password_prompt(screen):
    rows = screen.get("rows", [])
    return (screen.get("state") == "password" and len(rows) == ROWS
            and cp_input_field(screen, nondisplay=True)
            and re.search(r"\bPASSWORD\b", "\n".join(rows), re.I)
            and "CP READ" in rows[23].upper())


def cp_pending_password_boundary(screen, require_cursor=False):
    """Recognize an empty CP password field after an explicit HERE reconnect."""
    rows = screen.get("rows", [])
    return (screen.get("state") == "cp_read" and len(rows) == ROWS
            and screen.get("screen_kind") in {"hercules_banner", "guest_or_unknown"}
            and cp_input_field(screen, nondisplay=True,
                               require_cursor=require_cursor)
            and "CP READ" in rows[23].upper())


def hx_read_boundary(screen, staged_hx=False):
    rows = screen.get("rows", [])
    fields = [field for field in screen.get("fields", []) if not field["protected"]]
    return (screen.get("connected") and screen.get("keyboard") == "U"
            and screen.get("state") == "vm_read"
            and screen.get("screen_kind") == "zvm_guest_banner"
            and screen.get("field_layout_error") is None
            and len(rows) == ROWS and "VM READ" in rows[-1].upper()
            and "CP READ" not in rows[-1].upper()
            and re.search(r"\bRECONNECTED AT\b", "\n".join(rows), re.I)
            and len(fields) == 1
            and (fields[0]["row"], fields[0]["column"], fields[0]["length"],
                 fields[0]["nondisplay"], fields[0]["empty"])
                == (23, 1, 139, False, not staged_hx)
            and screen.get("cursor") == {"row": 23, "column": 3 if staged_hx else 1,
                                           "protected": False})


def password_is_vm_read_startup(observed, rows, fields, status_parts, layout_error):
    """Refine an empty startup field that still shows the password instruction.

    After a CP LOGON password is accepted, Hercules can retain the password
    instruction in the banner while the guest has already reached its VM READ
    startup prompt.  Only this exact empty, visible, row-23 shape is refined;
    all other password screens remain password screens.
    """
    editable = [field for field in fields if not field["protected"]]
    return (observed["state"] == "password"
        and observed["screen_kind"] == "hercules_banner"
        and "VM READ" in rows[23].upper() and "CP READ" not in rows[23].upper()
        and re.search(r"\b(?:LOGON AT|RECONNECTED AT)\b", "\n".join(rows), re.I)
        and status_parts[0] == "U" and layout_error is None and len(editable) == 1
        and (editable[0]["row"], editable[0]["column"], editable[0]["length"],
             editable[0]["nondisplay"], editable[0]["empty"]) == (23, 1, 139, False, True))


def expected_input_matches(fields, rows, expected):
    """Compare the one unprotected field to a value without returning it."""
    editable = [field for field in fields if not field["protected"]]
    if len(editable) != 1 or len(expected) > editable[0]["length"]:
        return False
    field = editable[0]
    flat = "".join(rows)
    actual = "".join(flat[(field["start_offset"] + n) % (ROWS * COLS)]
                   for n in range(field["length"]))
    return actual == expected + " " * (field["length"] - len(expected))
