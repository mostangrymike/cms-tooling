"""Read-only planner for a proposed MAINT CMS minidisk."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys


SCHEMA = "cms-minidisk-inventory-v1"
MAX_INVENTORY_AGE = timedelta(minutes=15)
BLOCK_BYTES = 4096


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _vdev(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9A-F]{4}", value):
        raise ValueError("Virtual device addresses must be four uppercase hex digits")
    return value


def _allowed_vdev(value):
    value = _vdev(value)
    if value in {"0000", "0192"}:
        raise ValueError(f"Virtual device {value} is reserved by CMS")
    return value


def validate_inventory(inventory, now=None):
    """Validate complete, recent evidence before deriving any free extent."""
    if not isinstance(inventory, dict) or inventory.get("schema") != SCHEMA:
        raise ValueError("Unsupported minidisk inventory schema")
    sources = inventory.get("sources")
    required = ("active_cp_directory", "cp_allocations", "volume_geometry")
    if (not isinstance(sources, dict)
            or any(sources.get(name) != "complete" for name in required)):
        raise ValueError("Complete CP directory, CP allocation and geometry evidence is required")

    timestamp = inventory.get("captured_at")
    if not isinstance(timestamp, str):
        raise ValueError("Inventory capture time is missing")
    try:
        captured = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Inventory capture time must be ISO-8601") from exc
    if captured.tzinfo is None:
        raise ValueError("Inventory capture time must include a timezone")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Planner clock must include a timezone")
    age = now - captured.astimezone(timezone.utc)
    if age < -timedelta(minutes=1) or age > MAX_INVENTORY_AGE:
        raise ValueError("Inventory is future-dated or older than 15 minutes")

    allowed = inventory.get("allowed_vdevs")
    used = inventory.get("used_vdevs")
    modes = inventory.get("accessed_filemodes")
    reserved_modes = inventory.get("reserved_filemodes")
    if not isinstance(allowed, list) or not allowed:
        raise ValueError("No reviewed MAINT virtual-device range is configured")
    if (not isinstance(used, list) or not isinstance(modes, list)
            or not isinstance(reserved_modes, list)):
        raise ValueError("Used virtual devices and CMS filemodes are required")
    allowed = [_allowed_vdev(value) for value in allowed]
    used = [_vdev(value) for value in used]
    if len(set(allowed)) != len(allowed):
        raise ValueError("Allowed virtual-device list contains duplicates")
    if len(set(used)) != len(used):
        raise ValueError("Used virtual-device list contains duplicates")
    if any(not isinstance(mode, str) or not re.fullmatch(r"[A-Z]", mode)
           for mode in (*modes, *reserved_modes)):
        raise ValueError("Accessed CMS filemodes must be single uppercase letters")

    volumes = inventory.get("volumes")
    if not isinstance(volumes, list) or not volumes:
        raise ValueError("Complete volume geometry is required")
    seen = set()
    normalized = []
    for volume in volumes:
        if not isinstance(volume, dict):
            raise ValueError("Volume inventory entry must be an object")
        volser = volume.get("volser")
        if (not isinstance(volser, str)
                or not re.fullmatch(r"[A-Z0-9$#@]{1,6}", volser)):
            raise ValueError("Volume serial must be 1-6 uppercase CMS characters")
        if volser in seen:
            raise ValueError("Duplicate volume serial in inventory")
        seen.add(volser)
        if volume.get("device_type") != "3390":
            raise ValueError(f"Unsupported device type on {volser}")
        cylinders = _integer(volume.get("cylinders"), f"{volser} cylinders", 1)
        blocks_per_cylinder = _integer(
            volume.get("blocks_per_cylinder"),
            f"{volser} blocks per cylinder", 1)
        allocations = volume.get("allocations")
        if not isinstance(allocations, list):
            raise ValueError(f"{volser} allocation list is missing")
        fullpack = volume.get("fullpack")
        eligible = volume.get("eligible_for_user_mdisk", False)
        if type(fullpack) is not bool or type(eligible) is not bool:
            raise ValueError(f"{volser} eligibility flags must be boolean")

        occupied = []
        for allocation in allocations:
            if not isinstance(allocation, dict):
                raise ValueError(f"{volser} allocation entry must be an object")
            start = _integer(allocation.get("start"), f"{volser} allocation start")
            length = _integer(allocation.get("cylinders"),
                               f"{volser} allocation cylinders", 1)
            end = start + length
            if end > cylinders:
                raise ValueError(f"{volser} allocation exceeds verified geometry")
            occupied.append((start, end))
        occupied.sort()
        for previous, current in zip(occupied, occupied[1:]):
            if current[0] < previous[1]:
                raise ValueError(f"{volser} inventory has overlapping allocations")
        normalized.append({
            "volser": volser,
            "cylinders": cylinders,
            "blocks_per_cylinder": blocks_per_cylinder,
            "fullpack": fullpack,
            "eligible": eligible,
            "occupied": occupied,
        })
    return {"allowed_vdevs": allowed, "used_vdevs": set(used),
            "accessed_filemodes": set(modes),
            "reserved_filemodes": set(reserved_modes),
            "volumes": normalized}


def plan_minidisk(filemode, size_mb, inventory, now=None):
    """Return a proposal only; never update CP, directory, or CMS disks."""
    if not isinstance(filemode, str) or not re.fullmatch(r"[A-Z]", filemode):
        raise ValueError("CMS filemode must be one uppercase letter")
    size_mb = _integer(size_mb, "Size in MiB", 1)
    checked = validate_inventory(inventory, now)
    if filemode in checked["accessed_filemodes"] | checked["reserved_filemodes"]:
        raise ValueError(f"CMS filemode {filemode} is already used or reserved")

    free = []
    for volume in checked["volumes"]:
        if volume["fullpack"] or not volume["eligible"]:
            continue
        cursor = 0
        for start, end in volume["occupied"]:
            if start > cursor:
                free.append((start - cursor, volume, cursor))
            cursor = end
        if cursor < volume["cylinders"]:
            free.append((volume["cylinders"] - cursor, volume, cursor))

    choices = []
    for free_cylinders, volume, start in free:
        bytes_per_cylinder = (
            volume["blocks_per_cylinder"] * BLOCK_BYTES)
        required = (size_mb * 1024 * 1024 + bytes_per_cylinder - 1) // bytes_per_cylinder
        if free_cylinders >= required:
            choices.append((free_cylinders, volume["volser"], start,
                            required, volume, bytes_per_cylinder))
    if not choices:
        raise ValueError("No verified contiguous extent fits the requested size")

    # Best fit preserves the largest remaining free ranges.
    _, _, start, required, volume, bytes_per_cylinder = min(
        choices, key=lambda choice: (choice[0], choice[1], choice[2]))
    vdev = next((candidate for candidate in checked["allowed_vdevs"]
                 if candidate not in checked["used_vdevs"]), None)
    if vdev is None:
        raise ValueError("No unused virtual device in the reviewed MAINT range")
    actual_mib = required * bytes_per_cylinder // (1024 * 1024)
    statement = (f"MDISK {vdev} 3390 {start} {required} "
                 f"{volume['volser']} W")
    result = {
        "schema": "cms-minidisk-plan-v1",
        "inventory_sha256": hashlib.sha256(json.dumps(
            inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "request": {"filemode": filemode, "size_mib": size_mb},
        "proposal": {
            "owner": "MAINT", "virtual_device": vdev,
            "volser": volume["volser"], "start_cylinder": start,
            "cylinders": required, "block_size": BLOCK_BYTES,
            "blocks_per_cylinder": volume["blocks_per_cylinder"],
            "resulting_mib": actual_mib,
            "directory_mdisk_statement": statement,
            "cms_format": f"FORMAT {vdev.lstrip('0')} {filemode} {required} (BLKSIZE 4096",
            "access": f"ACCESS {vdev.lstrip('0')} {filemode}",
        },
        "execution_authorized": False,
        "execution_implemented": False,
        "cms_operations_performed": False,
        "format_authorized": False,
        "replacement_safe": False,
    }
    result["plan_sha256"] = hashlib.sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True,
                        help="Recent complete normalized CP/volume inventory JSON")
    args = parser.parse_args(argv)
    try:
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
        filemode = input("Requested CMS filemode letter: ").strip().upper()
        size_mb = input("Requested minidisk size in MiB: ").strip()
        if not re.fullmatch(r"[0-9]+", size_mb):
            raise ValueError("Size in MiB must be a positive integer")
        plan = plan_minidisk(filemode, int(size_mb), inventory)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "message": str(exc),
                          "cms_operations_performed": False}))
        return 1
    print(json.dumps({"ok": True, **plan}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
