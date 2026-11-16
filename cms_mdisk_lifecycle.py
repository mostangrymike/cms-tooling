"""Signed ownership receipts and read-only minidisk deletion plans."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import uuid

from cms_mdisk_plan import _sha256, validate_inventory


RECEIPT_SCHEMA = "cms-minidisk-ownership-receipt-v1"
DELETE_PLAN_SCHEMA = "cms-minidisk-delete-plan-v1"
PROVISIONER_ID = "cms-minidisk-provisioning"
MAX_USAGE_EVIDENCE_AGE = timedelta(minutes=2)


def _canonical_sha256(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _sign(payload, signing_key):
    if not isinstance(signing_key, bytes) or len(signing_key) < 32:
        raise ValueError("Ownership signing key must contain at least 32 bytes")
    return hmac.new(signing_key, json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        hashlib.sha256).hexdigest()


def _parse_timestamp(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} timestamp is required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} timestamp must be ISO-8601") from exc
    if result.tzinfo is None:
        raise ValueError(f"{label} timestamp must include a timezone")
    return result.astimezone(timezone.utc)


def _verify_receipt(receipt, signing_key):
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError("A provisioner ownership receipt is required")
    if receipt.get("provisioner") != PROVISIONER_ID:
        raise ValueError("Receipt was not issued by this provisioner")
    signature = receipt.get("signature")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise ValueError("Receipt signature is invalid")
    unsigned = {key: value for key, value in receipt.items() if key != "signature"}
    expected = _sign(unsigned, signing_key)
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Receipt signature verification failed")
    try:
        uuid.UUID(unsigned.get("receipt_id"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Receipt ID is invalid") from exc
    _sha256(unsigned.get("plan_sha256"), "Receipt plan SHA-256")
    _sha256(unsigned.get("directory_sha256"), "Receipt directory SHA-256")
    _parse_timestamp(unsigned.get("created_at"), "Receipt creation")
    mdisk = unsigned.get("minidisk")
    if (not isinstance(mdisk, dict) or mdisk.get("owner") != "MAINT"
            or not isinstance(mdisk.get("virtual_device"), str)
            or not re.fullmatch(r"[0-9A-F]{4}", mdisk["virtual_device"])
            or not isinstance(mdisk.get("volser"), str)
            or not re.fullmatch(r"[A-Z0-9$#@]{1,6}", mdisk["volser"])
            or type(mdisk.get("start_cylinder")) is not int
            or mdisk["start_cylinder"] < 1
            or type(mdisk.get("cylinders")) is not int
            or mdisk["cylinders"] < 1):
        raise ValueError("Receipt MDISK identity or extent is invalid")
    return unsigned


def create_ownership_receipt(plan, verification, signing_key):
    """Issue a signed receipt only after a future executor verifies creation."""
    if not isinstance(plan, dict) or plan.get("schema") != "cms-minidisk-plan-v1":
        raise ValueError("A valid minidisk plan is required")
    plan_sha = plan.get("plan_sha256")
    _sha256(plan_sha, "Plan SHA-256")
    unsigned_plan = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if _canonical_sha256(unsigned_plan) != plan_sha:
        raise ValueError("Plan hash verification failed")
    proposal = plan.get("proposal")
    if not isinstance(proposal, dict) or proposal.get("owner") != "MAINT":
        raise ValueError("Receipt can only cover a MAINT minidisk plan")
    if not isinstance(verification, dict):
        raise ValueError("Verified creation evidence is required")
    required_true = (
        "active_directory_identity_confirmed",
        "cp_mapping_verified",
        "format_verified",
        "access_verified",
    )
    if any(verification.get(name) is not True for name in required_true):
        raise ValueError("Creation is not fully verified; no ownership receipt issued")
    directory_identity = verification.get("directory_identity")
    if not isinstance(directory_identity, str) or not directory_identity.strip():
        raise ValueError("Verified directory identity is required")
    directory_sha = _sha256(
        verification.get("directory_sha256"), "Directory SHA-256")
    created_at = verification.get("verified_at")
    _parse_timestamp(created_at, "Creation verification")

    unsigned = {
        "schema": RECEIPT_SCHEMA,
        "provisioner": PROVISIONER_ID,
        "receipt_id": str(uuid.uuid4()),
        "plan_sha256": plan_sha,
        "created_at": created_at,
        "directory_identity": directory_identity.strip(),
        "directory_sha256": directory_sha,
        "verification": {name: True for name in required_true},
        "request": dict(plan.get("request", {})),
        "minidisk": {
            "owner": "MAINT",
            "virtual_device": proposal.get("virtual_device"),
            "volser": proposal.get("volser"),
            "start_cylinder": proposal.get("start_cylinder"),
            "cylinders": proposal.get("cylinders"),
        },
    }
    mdisk = unsigned["minidisk"]
    if (not isinstance(mdisk["virtual_device"], str)
            or not re.fullmatch(r"[0-9A-F]{4}", mdisk["virtual_device"])
            or not isinstance(mdisk["volser"], str)
            or type(mdisk["start_cylinder"]) is not int
            or type(mdisk["cylinders"]) is not int
            or mdisk["start_cylinder"] < 1 or mdisk["cylinders"] < 1):
        raise ValueError("Plan has invalid MDISK identity or extent")
    receipt = dict(unsigned)
    receipt["signature"] = _sign(unsigned, signing_key)
    return receipt


def _verify_usage_evidence(evidence, receipt, inventory, now):
    if not isinstance(evidence, dict) or evidence.get("schema") != "cms-mdisk-usage-v1":
        raise ValueError("Fresh CP usage evidence is required")
    captured = _parse_timestamp(evidence.get("captured_at"), "Usage evidence")
    if now - captured < -timedelta(minutes=1) or now - captured > MAX_USAGE_EVIDENCE_AGE:
        raise ValueError("CP usage evidence is future-dated or older than 2 minutes")
    mdisk = receipt["minidisk"]
    if evidence.get("virtual_device") != mdisk["virtual_device"]:
        raise ValueError("Usage evidence refers to a different virtual device")
    current_directory = inventory["sources"]["active_cp_directory"]["sha256"]
    if evidence.get("active_directory_sha256") != current_directory:
        raise ValueError("Usage evidence is for a different active directory")
    location = evidence.get("mdisk_location")
    expected_location = {
        "owner": mdisk["owner"],
        "virtual_device": mdisk["virtual_device"],
        "volser": mdisk["volser"],
        "start_cylinder": mdisk["start_cylinder"],
        "cylinders": mdisk["cylinders"],
    }
    if location != expected_location:
        raise ValueError("CP MDISK location does not match the ownership receipt")
    for field in ("attached_users", "linked_users"):
        users = evidence.get(field)
        if not isinstance(users, list) or any(
                not isinstance(user, str) or not user.strip() for user in users):
            raise ValueError(f"Usage evidence must include a valid {field} list")
        if users:
            raise ValueError(f"Minidisk still has {field.replace('_', ' ')}")
    sources = evidence.get("sources")
    required_sources = ("query_mdisk", "query_virtual", "query_links")
    if (not isinstance(sources, dict)
            or any(not isinstance(sources.get(name), dict)
                   or sources[name].get("status") != "complete"
                   for name in required_sources)):
        raise ValueError("MDISK, VIRTUAL, and LINKS query evidence is required")
    for name in required_sources:
        _sha256(sources[name].get("sha256"), f"{name} evidence SHA-256")
    unsigned = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("evidence_sha256") != _canonical_sha256(unsigned):
        raise ValueError("Usage evidence hash verification failed")


def plan_minidisk_deletion(
    receipt,
    signing_key,
    inventory,
    usage_evidence,
    *,
    active_directory_identity_confirmed,
    consumed_receipt_ids,
    confirmation,
    now=None,
):
    """Return a deletion proposal; never edit or activate a CP directory."""
    owned = _verify_receipt(receipt, signing_key)
    if active_directory_identity_confirmed is not True:
        raise ValueError("Active directory identity must be independently confirmed")
    if not isinstance(consumed_receipt_ids, list):
        raise ValueError("Protected consumed-receipt ledger is required")
    if (any(not isinstance(item, str) for item in consumed_receipt_ids)
            or len(set(consumed_receipt_ids)) != len(consumed_receipt_ids)):
        raise ValueError("Consumed-receipt ledger is invalid")
    receipt_id = owned.get("receipt_id")
    if receipt_id in consumed_receipt_ids:
        raise ValueError("Ownership receipt has already been consumed")

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Planner clock must include a timezone")
    now = now.astimezone(timezone.utc)
    checked = validate_inventory(inventory, now=now)
    _verify_usage_evidence(usage_evidence, owned, inventory, now)

    mdisk = owned.get("minidisk")
    if not isinstance(mdisk, dict) or mdisk.get("owner") != "MAINT":
        raise ValueError("Receipt does not identify a MAINT-owned minidisk")
    vdev = mdisk.get("virtual_device")
    if not isinstance(vdev, str) or vdev not in checked["used_vdevs"]:
        raise ValueError("Receipt virtual device is not present in the active directory")

    matching_volume = next(
        (volume for volume in inventory["volumes"]
         if volume.get("volser") == mdisk.get("volser")), None)
    if matching_volume is None:
        raise ValueError("Receipt volume is missing from the current inventory")
    matches = [
        allocation for allocation in matching_volume.get("allocations", [])
        if allocation.get("kind") == "mdisk"
        and allocation.get("owner") == "MAINT"
        and allocation.get("vdev") == vdev
        and allocation.get("start") == mdisk.get("start_cylinder")
        and allocation.get("cylinders") == mdisk.get("cylinders")
    ]
    same_vdev = [
        allocation
        for volume in inventory["volumes"]
        for allocation in volume.get("allocations", [])
        if allocation.get("kind") == "mdisk"
        and allocation.get("owner") == "MAINT"
        and allocation.get("vdev") == vdev
    ]
    if len(matches) != 1 or len(same_vdev) != 1:
        raise ValueError("Current directory MDISK does not exactly match the ownership receipt")

    required_confirmation = f"DELETE MAINT {vdev} {receipt_id}"
    if confirmation != required_confirmation:
        raise ValueError(f"Deletion requires exact confirmation: {required_confirmation}")

    result = {
        "schema": DELETE_PLAN_SCHEMA,
        "action": "remove_one_mdisk_from_candidate",
        "receipt_id": receipt_id,
        "receipt_sha256": _canonical_sha256(receipt),
        "inventory_sha256": _canonical_sha256(inventory),
        "target": dict(mdisk),
        "required_confirmation": required_confirmation,
        "data_warning": (
            "No FORMAT or erase is performed. Removing the directory entry makes "
            "the data inaccessible and allows the physical extent to be reused."
        ),
        "execution_authorized": False,
        "execution_implemented": False,
        "cms_operations_performed": False,
        "directory_activation_authorized": False,
        "replacement_safe": False,
        "required_gates": [
            "Preserve the current directory and protected backup",
            "Remove only this exact MDISK from a separate candidate",
            "Run DIRECTXA candidate (EDIT",
            "Stop for separate approval before directory activation",
            "Record receipt ID in the protected consumed-receipt ledger",
        ],
    }
    result["delete_plan_sha256"] = _canonical_sha256(result)
    return result
