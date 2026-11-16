"""Parse and reconcile CP QUERY ALLOC MAP output."""
from __future__ import annotations

import hashlib
import re


CP_MAP_SCHEMA = "cms-minidisk-cp-alloc-map-v1"
GEOMETRY_SCHEMA = "cms-minidisk-cp-dasd-geometry-v1"
RECONCILED_SCHEMA = "cms-minidisk-reconciled-directory-v1"
ALLOCATION_TYPES = {"DRCT", "PAGE", "SPOOL", "TDISK"}
BLOCKS_PER_3390_CYLINDER = 180


def parse_cp_dasd_details(source):
    """Extract 3390 geometry from CP QUERY DASD DETAILS responses."""
    if isinstance(source, bytes):
        try:
            text = source.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("CP DASD details must be ASCII text") from exc
    elif isinstance(source, str):
        text = source
    else:
        raise ValueError("CP DASD details must be text or bytes")

    volumes = {}
    rdevs = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        match = re.search(
            r"^\s*([0-9A-F]{4})\s+.*?DEVTYPE\s*=\s*(\d{4}-[0-9A-Z]+),"
            r"\s*VOLSER\s*=\s*([A-Z0-9$#@]{1,6}),\s*CYLS\s*=\s*(\d+)\s*$",
            line, re.IGNORECASE)
        if not match:
            continue
        rdev, model, volser, cylinder_text = match.groups()
        if not model.upper().startswith("3390-"):
            continue
        rdev, model, volser = rdev.upper(), model.upper(), volser.upper()
        cylinders = int(cylinder_text)
        if cylinders < 1:
            raise ValueError(f"Invalid DASD geometry at record {line_number}")
        if volser in volumes or rdev in rdevs:
            raise ValueError(f"Duplicate DASD geometry at record {line_number}")
        volumes[volser] = {
            "rdev": rdev,
            "device_type": "3390",
            "model": model,
            "cylinders": cylinders,
            "blocks_per_cylinder": BLOCKS_PER_3390_CYLINDER,
        }
        rdevs.add(rdev)
    if not volumes:
        raise ValueError("No 3390 geometry found in CP DASD details")
    return {
        "schema": GEOMETRY_SCHEMA,
        "source_sha256": hashlib.sha256(text.encode("ascii")).hexdigest(),
        "volumes": volumes,
    }


def parse_cp_alloc_map(source):
    """Parse CKD extent rows from CP QUERY ALLOC MAP without retaining raw text."""
    if isinstance(source, bytes):
        try:
            text = source.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("CP allocation map must be ASCII text") from exc
    elif isinstance(source, str):
        text = source
    else:
        raise ValueError("CP allocation map must be text or bytes")

    extents = []
    current_volser = None
    current_rdev = None
    for line_number, line in enumerate(text.splitlines(), 1):
        fields = line.split()
        if len(fields) >= 9 and re.fullmatch(r"[0-9A-Fa-f]{4}", fields[1]):
            volser, rdev = fields[0].upper(), fields[1].upper()
            start_token, end_token = fields[2:4]
            type_index = 8
        elif current_volser and len(fields) >= 7 and fields[0].isdecimal():
            volser, rdev = current_volser, current_rdev
            start_token, end_token = fields[0:2]
            type_index = 6
        else:
            continue

        if (not re.fullmatch(r"[A-Z0-9$#@]{1,6}", volser)
                or not start_token.isdecimal() or not end_token.isdecimal()
                or len(fields) <= type_index
                or fields[type_index].upper() not in ALLOCATION_TYPES):
            continue
        start, end = int(start_token), int(end_token)
        if end < start:
            raise ValueError(f"Invalid CP allocation extent at record {line_number}")
        current_volser, current_rdev = volser, rdev
        flags = [field.upper() for field in fields[type_index + 1:]]
        extents.append({
            "volser": volser,
            "rdev": rdev,
            "start": start,
            "end": end,
            "cylinders": end - start + 1,
            "allocation_type": fields[type_index].upper(),
            "active": "ACTIVE" in flags,
            "draining": "DR" in flags or "ACT" in flags,
            "dump_only": "DUMP" in flags,
        })
    if not extents:
        raise ValueError("No CP allocation extents found")
    by_volume = {}
    for extent in extents:
        by_volume.setdefault(extent["volser"], []).append(extent)
    for volser, volume_extents in by_volume.items():
        volume_extents.sort(key=lambda item: (item["start"], item["end"]))
        for previous, current in zip(volume_extents, volume_extents[1:]):
            if current["start"] <= previous["end"]:
                raise ValueError(f"Overlapping CP allocation extents on {volser}")
    return {
        "schema": CP_MAP_SCHEMA,
        "source_sha256": hashlib.sha256(text.encode("ascii")).hexdigest(),
        "extents": extents,
    }


def reconcile_directory(directory_snapshot, cp_alloc_map):
    """Union CP-reserved extents with parsed directory allocations.

    Exact duplicate intervals represent the same reservation in both sources
    and are counted once. Partial overlaps fail closed. CP extents outside the
    directory snapshot's explicit target-volume scope are retained only in the
    CP source list and never become planner candidates.
    """
    if (not isinstance(directory_snapshot, dict)
            or directory_snapshot.get("schema") != "cms-minidisk-directory-snapshot-v1"):
        raise ValueError("Unsupported directory snapshot")
    if (not isinstance(cp_alloc_map, dict)
            or cp_alloc_map.get("schema") != CP_MAP_SCHEMA
            or not isinstance(cp_alloc_map.get("extents"), list)):
        raise ValueError("Unsupported CP allocation map")
    targets = directory_snapshot.get("target_volsers")
    if (not isinstance(targets, list) or not targets
            or len(set(targets)) != len(targets)):
        raise ValueError("Directory snapshot target-volume scope is invalid")

    result = {
        **directory_snapshot,
        "schema": RECONCILED_SCHEMA,
        "cp_allocations": {
            "source_sha256": cp_alloc_map.get("source_sha256"),
            "extents": [dict(extent) for extent in cp_alloc_map["extents"]],
            "excluded_volsers": [],
        },
        "volumes": [],
    }
    volumes = {}
    for volume in directory_snapshot.get("volumes", []):
        if not isinstance(volume, dict) or not isinstance(volume.get("volser"), str):
            raise ValueError("Invalid directory volume snapshot")
        copied = {**volume, "allocations": [
            dict(allocation) for allocation in volume.get("allocations", [])
        ]}
        volumes[copied["volser"]] = copied
        result["volumes"].append(copied)
    if set(volumes) != set(targets):
        raise ValueError("Directory geometry does not match target-volume scope")

    for extent in cp_alloc_map["extents"]:
        if not isinstance(extent, dict):
            raise ValueError("Invalid CP allocation extent")
        volser = extent.get("volser")
        if volser not in targets:
            result["cp_allocations"]["excluded_volsers"].append(volser)
            continue
        volume = volumes.get(volser)
        if volume is None:
            raise ValueError("Target CP allocation volume is missing from directory geometry")
        start = extent.get("start")
        length = extent.get("cylinders")
        if (type(start) is not int or type(length) is not int
                or start < 0 or length < 1
                or start + length > volume["cylinders"]):
            raise ValueError("CP allocation extent exceeds verified volume geometry")
        end = start + length
        duplicate = False
        for allocation in volume["allocations"]:
            existing_start = allocation["start"]
            existing_end = existing_start + allocation["cylinders"]
            if start == existing_start and end == existing_end:
                duplicate = True
                allocation["evidence"] = sorted(set(
                    allocation.get("evidence", ["active_cp_directory"])
                    + ["cp_allocations"]))
                break
            if start < existing_end and existing_start < end:
                raise ValueError(f"CP allocation overlaps a directory extent on {volser}")
        if not duplicate:
            volume["allocations"].append({
                "start": start,
                "cylinders": length,
                "kind": "cp_reserved",
                "allocation_type": extent.get("allocation_type"),
                "evidence": ["cp_allocations"],
            })
    for volume in result["volumes"]:
        volume["allocations"].sort(
            key=lambda item: (item["start"], item["cylinders"]))
    result["cp_allocations"]["excluded_volsers"] = sorted(
        set(result["cp_allocations"]["excluded_volsers"]))
    return result
