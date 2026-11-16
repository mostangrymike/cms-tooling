"""Assemble a reconciled, sanitized inventory from captured CMS evidence."""
from __future__ import annotations

from cms_mdisk_cp import (
    parse_cp_alloc_map,
    parse_cp_dasd_details,
    reconcile_directory,
)
from cms_mdisk_directory import parse_directory
from cms_mdisk_plan import SCHEMA, validate_inventory


def build_inventory(
    directory_source,
    cp_alloc_source,
    geometry_source,
    *,
    directory_identity,
    target_volsers=None,
    captured_at,
    active_directory_identity_confirmed,
    allowed_vdevs,
    accessed_filemodes,
    reserved_filemodes,
    volume_reviews=None,
    now=None,
):
    """Build a planner inventory from raw captures and explicit policy.

    `geometry_source` is CP QUERY DASD DETAILS text/bytes. `target_volsers`
    selects the candidate 3390 volumes whose extents will be inventoried.
    MDISKs on other volumes contribute their virtual addresses but cannot
    become planner candidates. `captured_at` maps the three source names to
    timezone-aware ISO-8601 times.

    Active-directory identity and per-volume eligibility are deliberate
    operator decisions. This function checks their consistency; it cannot
    independently prove which directory CP loaded or authenticate its caller.
    """
    if active_directory_identity_confirmed is not True:
        raise ValueError("Active directory identity must be independently confirmed")
    if not isinstance(captured_at, dict):
        raise ValueError("Capture times for all evidence sources are required")
    if volume_reviews is None:
        volume_reviews = {}
    if not isinstance(volume_reviews, dict):
        raise ValueError("Volume eligibility reviews must be an object")

    geometry = parse_cp_dasd_details(geometry_source)
    volume_geometry = geometry["volumes"]
    if target_volsers is None:
        target_volsers = sorted(volume_geometry)
    if (not isinstance(target_volsers, (list, tuple, set, frozenset))
            or not target_volsers
            or not set(target_volsers) <= set(volume_geometry)):
        raise ValueError("CP geometry must cover every explicit target volume")

    directory = parse_directory(
        directory_source, volume_geometry, directory_identity, target_volsers)
    cp_allocations = parse_cp_alloc_map(cp_alloc_source)
    reconciled = reconcile_directory(directory, cp_allocations)
    directory_sha = directory["source"]["sha256"]
    cp_sha = cp_allocations["source_sha256"]
    geometry_sha = geometry["source_sha256"]

    sources = {
        "active_cp_directory": {
            "status": "complete",
            "identity": directory["source"]["identity"],
            "captured_at": captured_at.get("active_cp_directory"),
            "sha256": directory_sha,
        },
        "cp_allocations": {
            "status": "complete",
            "captured_at": captured_at.get("cp_allocations"),
            "sha256": cp_sha,
            "active_directory_sha256": directory_sha,
        },
        "volume_geometry": {
            "status": "complete",
            "captured_at": captured_at.get("volume_geometry"),
            "sha256": geometry_sha,
            "volsers": sorted(
                volume["volser"] for volume in reconciled["volumes"]),
        },
    }
    inventory = {
        "schema": SCHEMA,
        "sources": sources,
        "reconciliation": {
            "status": "verified",
            "active_directory_sha256": directory_sha,
            "source_sha256": {
                "active_cp_directory": directory_sha,
                "cp_allocations": cp_sha,
                "volume_geometry": geometry_sha,
            },
        },
        "allowed_vdevs": allowed_vdevs,
        "used_vdevs": directory["used_vdevs"],
        "accessed_filemodes": accessed_filemodes,
        "reserved_filemodes": reserved_filemodes,
        "volumes": [],
    }
    volsers = {volume["volser"] for volume in reconciled["volumes"]}
    if set(volume_reviews) - volsers:
        raise ValueError("Eligibility review names an unknown volume")
    for volume in reconciled["volumes"]:
        item = {
            key: volume[key]
            for key in (
                "volser", "device_type", "cylinders", "blocks_per_cylinder",
                "fullpack", "fullpack_owners", "allocations",
            )
        }
        review = volume_reviews.get(volume["volser"])
        item["eligible_for_user_mdisk"] = review is not None
        if review is not None:
            if not isinstance(review, dict):
                raise ValueError(f"{volume['volser']} eligibility review must be an object")
            item["eligibility_review"] = {
                "reviewed_by": review.get("reviewed_by"),
                "reviewed_at": review.get("reviewed_at"),
                "active_directory_sha256": directory_sha,
                "fullpack_overlay_approved": review.get(
                    "fullpack_overlay_approved", False),
            }
        inventory["volumes"].append(item)

    validate_inventory(inventory, now=now)
    return inventory
