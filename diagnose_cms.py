"""Fixed read-only QUERY CMSLEVEL probe after the verified startup sequence."""
import argparse
import json
from pathlib import Path
import re
import time

from cms_credentials import FileCredentialProvider


def _blank_vm_read_startup(screen):
    rows = screen.get("rows", [])
    fields = [f for f in screen.get("fields", []) if not f["protected"]]
    return (screen.get("state") == "vm_read"
        and screen.get("screen_kind") in {"hercules_banner", "zvm_guest_banner"}
        and screen.get("connected") and screen.get("keyboard") == "U"
        and screen.get("field_layout_error") is None and len(rows) == 24 and len(fields) == 1
        and (fields[0]["row"], fields[0]["column"], fields[0]["length"],
             fields[0]["nondisplay"], fields[0]["empty"]) == (23, 1, 139, False, True)
        and "VM READ" in rows[-1].upper() and "CP READ" not in rows[-1].upper())


def probe_boundary(result):
    screen = result.get("screen", {})
    fields = [f for f in screen.get("fields", []) if not f["protected"]]
    rows = screen.get("rows", [])
    # A recovered CMS reconnect can print its bare CMS prompt immediately
    # after BEGIN, with no additional blank startup Enter. Accept that exact
    # observed banner/prompt shape only; arbitrary RUNNING screens stay refused.
    bare_reconnect = (result.get('actions') == ['BEGIN', 'Enter'] and len(rows) == 24
        and rows[6].strip() == 'BEGIN' and rows[8].strip() == 'CMS'
        and all(not row.strip() for i, row in enumerate(rows[7:22], 7) if i != 8)
        and 'Z/VM VERSION 6 RELEASE 3.0' in '\n'.join(rows).upper())
    snapshots = result.get('snapshots', [])
    initial_vm_read = snapshots[0] if snapshots else {}
    vm_read_transition = (result.get('actions') in (['Enter'], ['b', 'Enter'])
        and _blank_vm_read_startup(initial_vm_read)
        and len(rows) == 24 and screen.get('connected') and screen.get('keyboard') == 'U'
        and screen.get('field_layout_error') is None and len(fields) == 1
        and fields[0].get('empty') and not fields[0].get('nondisplay')
        and (fields[0]['row'], fields[0]['column'], fields[0]['length']) == (23, 1, 139)
        and 'Z/VM VERSION 6 RELEASE 3.0' in '\n'.join(rows).upper()
        and any(row.strip() == 'CMS' for row in rows[:22]) and 'RUNNING' in rows[-1])
    outcome = result.get("outcome")
    transition_allowed = (outcome == "startup_transition_timeout"
        or (outcome == "startup_transition_observed" and (bare_reconnect or vm_read_transition)))
    return bool((bare_reconnect or vm_read_transition
                 or result.get("actions") in (["BEGIN", "Enter", "Enter"], ["BEGIN", "Enter", "Enter", "Enter"]))
                and transition_allowed
                and screen.get("connected") and screen.get("keyboard") == "U"
                and screen.get("field_layout_error") is None
                and len(fields) == 1 and fields[0].get("empty")
                and (fields[0]["row"], fields[0]["column"], fields[0]["length"]) == (23, 1, 139)
                and not fields[0]["nondisplay"] and len(rows) == 24
                and ("RECONNECTED AT" in "\n".join(rows) or vm_read_transition)
                and any(row.strip() == "CMS" for row in rows[:22])
                and "RUNNING" in rows[-1])


def probe(session, startup_result, display_signature):
    if not probe_boundary(startup_result):
        return {"ok": False, "outcome": "probe_boundary_not_verified"}
    def work():
        before = session.snapshot()
        check = {**startup_result, "screen": before}
        if not probe_boundary(check):
            raise RuntimeError("Read-only probe input boundary changed")
        session.command("MoveCursor(22,0)")
        check_screen = session.snapshot()
        if (check_screen["cursor"] != {"row": 23, "column": 1, "protected": False}
                or not probe_boundary({**startup_result, "screen": check_screen})):
            raise RuntimeError("Read-only probe cursor/field verification failed")
        session.command('String("QUERY CMSLEVEL")')
        session.command("Ascii")
        session.command("Enter")
        snapshots = [before]
        deadline = time.monotonic() + 15
        previous = before
        while time.monotonic() < deadline:
            fresh = session._wait_output(2)
            after = session.snapshot()
            snapshots.append(after)
            fresh = fresh or display_signature(after) != display_signature(previous)
            previous = after
            text = "\n".join(after["rows"])
            level = re.search(r"(?:z/)?CMS Level\s+\d+,?\s+Service Level\s+\d+", text, re.I)
            if fresh and level and after["state"] == "cms_ready":
                return {"outcome": "cms_level_and_ready_observed", "screen": after,
                        "response": level[0], "snapshots": snapshots,
                        "cms_command_complete": None, "query": "QUERY CMSLEVEL"}
            session.command("Ascii")
        return {"ok": False, "outcome": "query_evidence_incomplete", "screen": after,
                "snapshots": snapshots, "query": "QUERY CMSLEVEL"}
    return session._run("readonly_cmslevel_probe", work, timeout=18)


def main():
    from cms_mcp import Session, host_display
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-query", required=True, action="store_true")
    parser.add_argument("--credential-file", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    session = Session(allow_login=True, allow_startup=True,
                      credential_provider=FileCredentialProvider(args.credential_file))
    evidence = {"purpose": __doc__}
    try:
        evidence["connect"] = session.connect("0200@")
        if evidence["connect"]["ok"]:
            evidence["login"] = session.login()
            if evidence["login"]["ok"]:
                evidence["startup"] = session.startup()
                if evidence["startup"]["ok"]:
                    evidence["outcome"] = "cms_ready_observed_without_probe"
                else:
                    evidence["probe"] = probe(session, evidence["startup"], host_display)
    finally:
        evidence["disconnect"] = session.disconnect()
        args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    final = evidence.get("probe", evidence.get("startup", evidence.get("login", evidence["connect"])))
    print(json.dumps({"ok": final.get("ok"), "outcome": final.get("outcome"),
                      "screen": final.get("screen"), "disconnect": evidence["disconnect"]}, indent=2))
    return 0 if final.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
