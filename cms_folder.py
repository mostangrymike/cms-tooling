#!/usr/bin/env python3
"""Plan a CMS folder request as a minidisk and inspect receipt-bound deletes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import string
import sys

from cms_mdisk_lifecycle import plan_minidisk_deletion
from cms_mdisk_plan import plan_minidisk
from cms_mdisk_receipts import OwnershipReceiptStore


def choose_filemode(inventory):
    """Choose the first CMS filemode not currently accessed or reserved."""
    used = set(inventory.get("accessed_filemodes", []))
    reserved = set(inventory.get("reserved_filemodes", []))
    for mode in string.ascii_uppercase:
        if mode not in {"D", "S"} and mode not in used | reserved:
            return mode
    raise ValueError("No unused CMS filemode is available")


def plan_folder(size_mib, inventory, now=None):
    """Size-first folder request; return a minidisk proposal only."""
    filemode = choose_filemode(inventory)
    return plan_minidisk(filemode, size_mib, inventory, now=now)


def _read_json(path, description):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {description} JSON") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    plan_parser = commands.add_parser("plan", help="plan a CMS folder request")
    plan_parser.add_argument("--inventory", type=Path, required=True)
    plan_parser.add_argument("--size-mib", type=int)

    delete_parser = commands.add_parser(
        "delete-plan", help="plan removal of a minidisk created by this provisioner")
    delete_parser.add_argument("--inventory", type=Path, required=True)
    delete_parser.add_argument("--usage-evidence", type=Path, required=True)
    delete_parser.add_argument("--receipt-id", required=True)

    args = parser.parse_args(argv)
    try:
        inventory = _read_json(args.inventory, "inventory")
        if args.command == "plan":
            size_mib = args.size_mib
            if size_mib is None:
                text = input("Requested minidisk size in MiB: ").strip()
                if not text.isdecimal():
                    raise ValueError("Size in MiB must be a positive integer")
                size_mib = int(text)
            plan = plan_folder(size_mib, inventory)
            output = {
                "ok": True,
                "operation": "plan-only",
                **plan,
            }
        else:
            store = OwnershipReceiptStore()
            receipt = store.load_receipt(args.receipt_id)
            active_identity = inventory.get("sources", {}).get(
                "active_cp_directory", {}).get("identity")
            if not isinstance(active_identity, str) or not active_identity:
                raise ValueError("Active directory identity is missing")
            typed_identity = input(
                f"Confirm active directory source by typing {active_identity}: ").strip()
            usage = _read_json(args.usage_evidence, "CP usage evidence")
            receipt_id = receipt["receipt_id"]
            confirmation = input(
                f"Confirm deletion by typing DELETE MAINT "
                f"{receipt['minidisk']['virtual_device']} {receipt_id}: ").strip()
            result = plan_minidisk_deletion(
                receipt,
                store.load_key(),
                inventory,
                usage,
                active_directory_identity_confirmed=(
                    typed_identity == active_identity),
                consumed_receipt_ids=store.consumed_receipt_ids(),
                confirmation=confirmation,
            )
            output = {"ok": True, "operation": "delete-plan-only", **result}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "message": str(exc),
                          "cms_operations_performed": False}))
        return 1
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
