"""Extract sanitized MDISK allocation evidence from a CP source directory."""
from __future__ import annotations

import hashlib
import re


SNAPSHOT_SCHEMA = "cms-minidisk-directory-snapshot-v1"


def _positive_integer(value, label):
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _source_text(source):
    if isinstance(source, bytes):
        try:
            return source.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("Directory source must be ASCII text") from exc
    if isinstance(source, str):
        return source
    raise ValueError("Directory source must be text or bytes")


def parse_directory(source, volume_geometry, identity, target_volsers=None):
    """Return only allocation data; never return directory records or passwords.

    `volume_geometry` maps volser to device type, cylinder count, and 4-KiB
    blocks per cylinder, for example:
    {"VOL001": {"device_type": "3390", "cylinders": 10017,
                "blocks_per_cylinder": 180}}

    All active MDISK virtual addresses are recorded. When `target_volsers` is
    supplied, only those volumes need geometry and their extents are retained;
    allocations on other volumes cannot be selected by the resulting planner
    inventory. Commented statements are ignored.
    """
    text = _source_text(source)
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("Directory source identity is required")
    if not isinstance(volume_geometry, dict) or not volume_geometry:
        raise ValueError("Complete volume geometry is required")

    geometry = {}
    for volser, item in volume_geometry.items():
        if (not isinstance(volser, str)
                or not re.fullmatch(r"[A-Z0-9$#@]{1,6}", volser)
                or not isinstance(item, dict)):
            raise ValueError("Invalid volume geometry entry")
        device_type = item.get("device_type")
        if device_type not in {"3390", "3380"}:
            raise ValueError(f"Unsupported geometry for {volser}")
        cylinders = _positive_integer(item.get("cylinders"), f"{volser} cylinders")
        if device_type == "3390":
            blocks_per_cylinder = _positive_integer(
                item.get("blocks_per_cylinder"), f"{volser} blocks per cylinder")
        else:
            blocks_per_cylinder = None
        geometry[volser] = {
            "device_type": device_type,
            "cylinders": cylinders,
            "blocks_per_cylinder": blocks_per_cylinder,
        }

    if target_volsers is None:
        targets = {
            volser for volser, item in geometry.items()
            if item["device_type"] == "3390"
        }
    else:
        if (not isinstance(target_volsers, (list, tuple, set, frozenset))
                or not target_volsers):
            raise ValueError("At least one target volume is required")
        targets = set(target_volsers)
        if (any(not isinstance(volser, str) for volser in targets)
                or not targets <= set(geometry)
                or any(geometry[volser]["device_type"] != "3390"
                       for volser in targets)):
            raise ValueError("Target volumes need verified 3390 geometry")

    volumes = {
        volser: {
            **item,
            "fullpack_owners": [],
            "allocations": [],
        }
        for volser, item in geometry.items()
        if volser in targets
    }
    used_vdevs = set()
    owner = None
    subconfig = None
    active_records = 0

    for line_number, line in enumerate(text.splitlines(), 1):
        statement = line.strip()
        if not statement or statement.startswith("*"):
            continue
        fields = statement.split()
        keyword = fields[0].upper()
        if keyword in {"USER", "IDENTITY"}:
            if len(fields) < 2:
                raise ValueError(f"Invalid directory entry at record {line_number}")
            owner = fields[1].upper()
            subconfig = None
            continue
        if keyword == "SUBCONFIG":
            if len(fields) < 2:
                raise ValueError(f"Invalid subconfiguration at record {line_number}")
            subconfig = fields[1].upper()
            continue
        if keyword != "MDISK":
            continue
        active_records += 1
        if len(fields) < 3:
            raise ValueError(f"Invalid MDISK statement at record {line_number}")
        raw_vdev = fields[1].upper()
        if not re.fullmatch(r"[0-9A-F]{1,4}", raw_vdev):
            raise ValueError(f"Invalid MDISK address at record {line_number}")
        used_vdevs.add(raw_vdev.zfill(4))

        device_type = fields[2].upper()
        if device_type not in {"3390", "3380"}:
            if len(fields) >= 6 and fields[5].upper() in targets:
                raise ValueError(
                    f"Unsupported MDISK device type on a 3390 volume at record {line_number}")
            continue
        if owner is None or len(fields) < 6:
            raise ValueError(f"Incomplete physical MDISK at record {line_number}")
        start_token, length_token, volser = (
            fields[3].upper(), fields[4].upper(), fields[5].upper())
        if volser not in targets:
            continue
        if not start_token.isdecimal():
            raise ValueError(f"Invalid MDISK start at record {line_number}")
        start = int(start_token)
        volume = geometry.get(volser)
        if volume is None:
            raise ValueError(f"MDISK volume lacks verified geometry at record {line_number}")

        # A directory may describe 3390 volumes in 3380 compatibility mode.
        if volume["device_type"] == "3380":
            if device_type != "3380":
                raise ValueError(f"MDISK device type disagrees with volume geometry at record {line_number}")
            continue
        cylinders = volume["cylinders"]
        if start >= cylinders:
            raise ValueError(f"MDISK starts outside volume geometry at record {line_number}")
        if length_token == "END" and start == 0:
            owners = volumes[volser]["fullpack_owners"]
            if owner not in owners:
                owners.append(owner)
            continue
        if length_token == "END":
            length = cylinders - start
        elif length_token.isdecimal():
            length = int(length_token)
        else:
            raise ValueError(f"Invalid MDISK length at record {line_number}")
        if length < 1 or start + length > cylinders:
            raise ValueError(f"MDISK extent exceeds volume geometry at record {line_number}")
        volumes[volser]["allocations"].append({
            "start": start,
            "cylinders": length,
            "kind": "mdisk",
            "owner": owner,
            "vdev": raw_vdev.zfill(4),
            "subconfig": subconfig,
        })

    if not active_records:
        raise ValueError("No active MDISK statements found")

    for volser, volume in volumes.items():
        allocations = volume["allocations"]
        allocations.sort(key=lambda item: (item["start"], item["cylinders"]))
        for previous, current in zip(allocations, allocations[1:]):
            previous_end = previous["start"] + previous["cylinders"]
            if current["start"] < previous_end:
                raise ValueError(f"Overlapping MDISK extents on {volser}")

    result_volumes = []
    for volser, volume in sorted(volumes.items()):
        result_volumes.append({
            "volser": volser,
            "device_type": "3390",
            "cylinders": volume["cylinders"],
            "blocks_per_cylinder": volume["blocks_per_cylinder"],
            "fullpack": bool(volume["fullpack_owners"]),
            "fullpack_owners": sorted(volume["fullpack_owners"]),
            "allocations": volume["allocations"],
        })

    return {
        "schema": SNAPSHOT_SCHEMA,
        "target_volsers": sorted(targets),
        "source": {
            "identity": identity.strip(),
            "sha256": hashlib.sha256(text.encode("ascii")).hexdigest(),
        },
        "used_vdevs": sorted(used_vdevs),
        "volumes": result_volumes,
    }


def insert_mdisk_line(
    source,
    volume_geometry,
    identity,
    target_volsers,
    *,
    owner,
    subconfig,
    after_vdev,
    statement,
):
    """Create a separate candidate by inserting one password-free MDISK record.

    Source must be an exact ASCII F80 record stream (normally obtained over
    FTP). The function returns candidate bytes and never writes or prints them.
    """
    text = _source_text(source)
    if not text:
        raise ValueError("Directory source is empty")
    if "\r\n" in text:
        line_ending = "\r\n"
        if "\n" in text.replace("\r\n", ""):
            raise ValueError("Directory source has mixed line endings")
    else:
        line_ending = "\n"
    final_newline = text.endswith(("\n", "\r"))
    records = text.splitlines()
    if any(len(record.encode("ascii")) != 80 for record in records):
        raise ValueError("Candidate editing requires exact 80-character directory records")

    if (not isinstance(owner, str) or not re.fullmatch(r"[A-Z0-9@#$]{1,8}", owner)
            or not isinstance(subconfig, str)
            or not re.fullmatch(r"[A-Z0-9@#$-]{1,8}", subconfig)):
        raise ValueError("Directory owner and subconfiguration identifiers are invalid")
    if not isinstance(after_vdev, str) or not re.fullmatch(r"[0-9A-F]{4}", after_vdev):
        raise ValueError("Insertion anchor must be a four-digit virtual device")
    fields = statement.upper().split()
    if (len(fields) != 7 or fields[0] != "MDISK"
            or not re.fullmatch(r"[0-9A-F]{4}", fields[1])
            or fields[1] in {"0000", "0192"}
            or fields[2] != "3390"
            or not fields[3].isdecimal() or not fields[4].isdecimal()
            or fields[5] not in target_volsers or fields[6] not in {"W", "WR", "MW"}):
        raise ValueError("Candidate must be one password-free MAINT 3390 MDISK statement")
    new_vdev = fields[1]
    start, cylinders = int(fields[3]), int(fields[4])
    if start < 1 or cylinders < 1:
        raise ValueError("Candidate extent must start after cylinder zero")

    existing = parse_directory(source, volume_geometry, identity, target_volsers)
    if new_vdev in existing["used_vdevs"]:
        raise ValueError("Candidate virtual device is already used in the directory")
    volume = next(
        item for item in existing["volumes"] if item["volser"] == fields[5])
    if start + cylinders > volume["cylinders"]:
        raise ValueError("Candidate extent exceeds verified volume geometry")
    for allocation in volume["allocations"]:
        left, right = allocation["start"], allocation["start"] + allocation["cylinders"]
        if start < right and left < start + cylinders:
            raise ValueError("Candidate extent overlaps an existing MDISK")

    current_owner = None
    current_subconfig = None
    anchors = []
    for index, record in enumerate(records):
        row = record.strip()
        if not row or row.startswith("*"):
            continue
        tokens = row.split()
        keyword = tokens[0].upper()
        if keyword in {"USER", "IDENTITY"} and len(tokens) > 1:
            current_owner = tokens[1].upper()
            current_subconfig = None
        elif keyword == "SUBCONFIG" and len(tokens) > 1:
            current_subconfig = tokens[1].upper()
        elif (keyword == "MDISK" and len(tokens) > 2
                and current_owner == owner.upper()
                and current_subconfig == subconfig.upper()
                and tokens[1].upper().zfill(4) == after_vdev):
            anchors.append(index)
    if len(anchors) != 1:
        raise ValueError("Insertion anchor is missing or ambiguous")

    inserted = (" " + " ".join(fields)).ljust(80)
    records.insert(anchors[0] + 1, inserted)
    candidate_text = line_ending.join(records)
    if final_newline:
        candidate_text += line_ending
    candidate = candidate_text.encode("ascii")
    parsed_candidate = parse_directory(
        candidate, volume_geometry, identity, target_volsers)
    if new_vdev not in parsed_candidate["used_vdevs"]:
        raise ValueError("Candidate MDISK was not preserved by directory parsing")
    return candidate
