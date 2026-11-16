"""Read-only planner for a proposed MAINT CMS minidisk."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys


SCHEMA = "cms-minidisk-inventory-v2"
MAX_INVENTORY_AGE = timedelta(minutes=15)
MAX_SOURCE_SKEW = timedelta(minutes=5)
BLOCK_BYTES = 4096

#: Owners whose `MDISK ... 000 END volser` is an overlay marker for a volume
#: that other users also allocate from.  The marker itself reserves nothing;
#: the explicit MDISK lines are the real occupancy.  A full-pack owner outside
#: this set is treated as an exclusive reservation.
OVERLAY_FULLPACK_OWNERS = frozenset({
    "DEFAULT", "CMS1", "SYSDUMP1", "MAINT", "PMAINT", "MAINT630",
    "$PAGE$", "$SPOOL$",
})


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


def _timestamp(value, name, now):
    if not isinstance(value, str):
        raise ValueError(f"{name} capture time is missing")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} capture time must be ISO-8601") from exc
    if timestamp.tzinfo is None:
        raise ValueError(f"{name} capture time must include a timezone")
    timestamp = timestamp.astimezone(timezone.utc)
    age = now - timestamp
    if age < -timedelta(minutes=1) or age > MAX_INVENTORY_AGE:
        raise ValueError(f"{name} evidence is future-dated or older than 15 minutes")
    return timestamp


def _sha256(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def validate_inventory(inventory, now=None):
    """Validate complete, recent evidence before deriving any free extent."""
    if not isinstance(inventory, dict) or inventory.get("schema") != SCHEMA:
        raise ValueError("Unsupported minidisk inventory schema")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Planner clock must include a timezone")
    now = now.astimezone(timezone.utc)

    sources = inventory.get("sources")
    required = ("active_cp_directory", "cp_allocations", "volume_geometry")
    if not isinstance(sources, dict):
        raise ValueError("Per-source CP directory, allocation and geometry evidence is required")
    source_data = {}
    source_times = {}
    for name in required:
        source = sources.get(name)
        if not isinstance(source, dict) or source.get("status") != "complete":
            raise ValueError("Per-source CP directory, allocation and geometry evidence is required")
        if name == "active_cp_directory" and not (
                isinstance(source.get("identity"), str) and source["identity"].strip()):
            raise ValueError("Active CP directory identity is required")
        source_times[name] = _timestamp(source.get("captured_at"), name, now)
        source_data[name] = _sha256(source.get("sha256"), f"{name} SHA-256")
    if max(source_times.values()) - min(source_times.values()) > MAX_SOURCE_SKEW:
        raise ValueError("Inventory source captures are more than 5 minutes apart")

    reconciliation = inventory.get("reconciliation")
    if (not isinstance(reconciliation, dict)
            or reconciliation.get("status") != "verified"):
        raise ValueError("Verified source reconciliation is required")
    reconciled = reconciliation.get("source_sha256")
    if not isinstance(reconciled, dict) or any(
            reconciled.get(name) != source_data[name] for name in required):
        raise ValueError("Reconciliation does not match the captured source hashes")
    if reconciliation.get("active_directory_sha256") != source_data["active_cp_directory"]:
        raise ValueError("Reconciliation does not identify the captured active directory")
    cp_directory_sha = sources["cp_allocations"].get("active_directory_sha256")
    if cp_directory_sha != source_data["active_cp_directory"]:
        raise ValueError("CP allocation evidence does not identify the captured active directory")

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
        fullpack_owners = volume.get("fullpack_owners")
        eligible = volume.get("eligible_for_user_mdisk", False)
        if type(fullpack) is not bool or type(eligible) is not bool:
            raise ValueError(f"{volser} eligibility flags must be boolean")
        if fullpack:
            if (not isinstance(fullpack_owners, list) or not fullpack_owners
                    or any(not isinstance(owner, str)
                           or owner not in OVERLAY_FULLPACK_OWNERS
                           for owner in fullpack_owners)
                    or len(set(fullpack_owners)) != len(fullpack_owners)):
                raise ValueError(
                    f"{volser} full-pack owner is not an approved overlay owner")
        elif fullpack_owners != []:
            raise ValueError(f"{volser} names full-pack owners without a full pack")
        if eligible:
            review = volume.get("eligibility_review")
            if not isinstance(review, dict):
                raise ValueError(f"{volser} needs a reviewed allocation eligibility decision")
            reviewer = review.get("reviewed_by")
            if not isinstance(reviewer, str) or not reviewer.strip():
                raise ValueError(f"{volser} eligibility reviewer is required")
            reviewed_at = _timestamp(
                review.get("reviewed_at"), f"{volser} eligibility review", now)
            if reviewed_at < source_times["active_cp_directory"]:
                raise ValueError(f"{volser} eligibility review predates the active directory capture")
            if review.get("active_directory_sha256") != source_data["active_cp_directory"]:
                raise ValueError(f"{volser} eligibility review is for a different directory")
            if fullpack and review.get("fullpack_overlay_approved") is not True:
                raise ValueError(f"{volser} full-pack overlay needs separate approval")

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
            if fullpack and start == 0 and end == cylinders:
                raise ValueError(
                    f"{volser} full-pack overlay must not be listed as an allocation")
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
            "fullpack_owners": fullpack_owners,
            "eligible": eligible,
            "occupied": occupied,
            "eligibility_review": volume.get("eligibility_review"),
        })
    geometry_volsers = sources["volume_geometry"].get("volsers")
    if (not isinstance(geometry_volsers, list)
            or any(not isinstance(volser, str) for volser in geometry_volsers)
            or len(set(geometry_volsers)) != len(geometry_volsers)
            or set(geometry_volsers) != seen):
        raise ValueError("Volume geometry evidence does not match the inventoried volumes")
    return {"allowed_vdevs": allowed, "used_vdevs": set(used),
            "accessed_filemodes": set(modes),
            "reserved_filemodes": set(reserved_modes),
            "volumes": normalized}


def plan_minidisk(filemode, size_mb, inventory, now=None):
    """Return a proposal only; never update CP, directory, or CMS disks."""
    if (not isinstance(filemode, str) or not re.fullmatch(r"[A-Z]", filemode)
            or filemode == "S"):
        raise ValueError("CMS filemode must be one uppercase letter other than S")
    size_mb = _integer(size_mb, "Size in MiB", 1)
    checked = validate_inventory(inventory, now)
    if filemode in checked["accessed_filemodes"] | checked["reserved_filemodes"]:
        raise ValueError(f"CMS filemode {filemode} is already used or reserved")

    free = []
    for volume in checked["volumes"]:
        if not volume["eligible"]:
            continue
        # Cylinder zero contains volume metadata and is not allocated to a
        # regular user minidisk.
        cursor = 1
        for start, end in volume["occupied"]:
            if start > cursor:
                free.append((start - cursor, volume, cursor))
            cursor = max(cursor, end)
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
    resulting_bytes = required * bytes_per_cylinder
    actual_mib = resulting_bytes / (1024 * 1024)
    statement = (f"MDISK {vdev} 3390 {start} {required} "
                 f"{volume['volser']} W")
    cms_label = f"M{vdev}{filemode}"
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
            "resulting_bytes": resulting_bytes,
            "resulting_mib": actual_mib,
            "cms_label": cms_label,
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
        size_mb = input("Requested minidisk size in MiB: ").strip()
        if not re.fullmatch(r"[0-9]+", size_mb):
            raise ValueError("Size in MiB must be a positive integer")
        filemode = input("Requested CMS filemode letter: ").strip().upper()
        plan = plan_minidisk(filemode, int(size_mb), inventory)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "message": str(exc),
                          "cms_operations_performed": False}))
        return 1
    print(json.dumps({"ok": True, **plan}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
