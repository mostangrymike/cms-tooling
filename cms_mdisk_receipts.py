"""Owner-only storage for signed minidisk ownership receipts."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import secrets
import stat
import uuid

from cms_mdisk_lifecycle import (
    _verify_receipt,
    create_ownership_receipt,
    plan_minidisk_deletion,
)


DEFAULT_STATE_DIR = Path.home() / ".config" / "cms-minidisk-provisioning"
KEY_FILENAME = "ownership.key"
RECEIPTS_DIRNAME = "receipts"
CONSUMED_FILENAME = "consumed-receipts.json"
LOCK_FILENAME = ".receipt-ledger.lock"
KEY_BYTES = 32


class OwnershipReceiptStore:
    """Persist receipts and their one-time state outside the repository."""

    def __init__(self, state_dir=None):
        self.state_dir = Path(state_dir or DEFAULT_STATE_DIR).expanduser()
        self.key_path = self.state_dir / KEY_FILENAME
        self.receipts_dir = self.state_dir / RECEIPTS_DIRNAME
        self.consumed_path = self.state_dir / CONSUMED_FILENAME
        self.lock_path = self.state_dir / LOCK_FILENAME

    @staticmethod
    def _check_owner_mode(info, label, directory=False):
        if directory:
            valid_type = stat.S_ISDIR(info.st_mode)
        else:
            valid_type = stat.S_ISREG(info.st_mode)
        if not valid_type or info.st_uid != os.getuid():
            raise ValueError(f"{label} must be a regular user-owned {'directory' if directory else 'file'}")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError(f"{label} must not be accessible by group or others")

    @classmethod
    def _ensure_private_dir(cls, path, label):
        try:
            info = path.lstat()
        except FileNotFoundError:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"{label} must not be a symlink")
        cls._check_owner_mode(info, label, directory=True)

    @classmethod
    def _open_private(cls, path, flags, label):
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags | nofollow)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise ValueError(f"Cannot safely open {label}") from exc
        try:
            cls._check_owner_mode(os.fstat(fd), label)
        except Exception:
            os.close(fd)
            raise
        return fd

    def _read_private(self, path, label):
        fd = self._open_private(path, os.O_RDONLY, label)
        with os.fdopen(fd, "rb") as source:
            return source.read()

    def load_or_create_key(self):
        self._ensure_private_dir(self.state_dir, "Ownership state directory")
        try:
            key = self.load_key()
        except FileNotFoundError:
            key = secrets.token_bytes(KEY_BYTES)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(self.key_path, flags, 0o600)
            except FileExistsError:
                key = self.load_key()
            else:
                with os.fdopen(fd, "wb") as target:
                    target.write(key)
                    target.flush()
                    os.fsync(target.fileno())
        if len(key) < KEY_BYTES:
            raise ValueError("Ownership key is invalid")
        return key

    def load_key(self):
        """Load an existing key; never silently replace a missing key."""
        self._ensure_private_dir(self.state_dir, "Ownership state directory")
        key = self._read_private(self.key_path, "Ownership key")
        if len(key) < KEY_BYTES:
            raise ValueError("Ownership key is invalid")
        return key

    def _ensure_receipts_dir(self):
        self._ensure_private_dir(self.state_dir, "Ownership state directory")
        self._ensure_private_dir(self.receipts_dir, "Ownership receipts directory")

    def save_receipt(self, receipt):
        key = self.load_or_create_key()
        verified = _verify_receipt(receipt, key)
        receipt_id = str(uuid.UUID(verified["receipt_id"]))
        self._ensure_receipts_dir()
        path = self.receipts_dir / f"{receipt_id}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags, 0o600)
        except OSError as exc:
            raise ValueError("Cannot safely create ownership receipt") from exc
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump(receipt, target, sort_keys=True, separators=(",", ":"))
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path

    def issue_receipt(self, plan, verification):
        """Sign and persist a receipt after a caller verifies completed creation."""
        receipt = create_ownership_receipt(
            plan, verification, self.load_or_create_key())
        self.save_receipt(receipt)
        return receipt

    def load_receipt(self, receipt_id):
        try:
            receipt_id = str(uuid.UUID(receipt_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Receipt ID is invalid") from exc
        self._ensure_receipts_dir()
        path = self.receipts_dir / f"{receipt_id}.json"
        raw = self._read_private(path, "Ownership receipt")
        try:
            receipt = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Stored ownership receipt is invalid") from exc
        _verify_receipt(receipt, self.load_key())
        return receipt

    def consumed_receipt_ids(self):
        self._ensure_private_dir(self.state_dir, "Ownership state directory")
        try:
            raw = self._read_private(self.consumed_path, "Consumed-receipt ledger")
        except FileNotFoundError:
            return []
        try:
            entries = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Consumed-receipt ledger is invalid") from exc
        if (not isinstance(entries, list)
                or any(not isinstance(item, str) for item in entries)
                or len(set(entries)) != len(entries)):
            raise ValueError("Consumed-receipt ledger is invalid")
        try:
            return [str(uuid.UUID(item)) for item in entries]
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Consumed-receipt ledger contains an invalid ID") from exc

    def consume_receipt(self, receipt_id):
        """Mark a receipt consumed after deletion is independently verified."""
        receipt = self.load_receipt(receipt_id)
        receipt_id = str(uuid.UUID(receipt["receipt_id"]))
        self._ensure_private_dir(self.state_dir, "Ownership state directory")
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            lock_fd = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise ValueError("Cannot safely open receipt-ledger lock") from exc
        try:
            self._check_owner_mode(os.fstat(lock_fd), "Receipt-ledger lock")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            consumed = self.consumed_receipt_ids()
            if receipt_id in consumed:
                raise ValueError("Ownership receipt has already been consumed")
            self._write_consumed_ledger(consumed + [receipt_id])
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def plan_deletion(
        self,
        receipt_id,
        inventory,
        usage_evidence,
        *,
        active_directory_identity_confirmed,
        confirmation,
        now=None,
    ):
        """Plan deletion using only locally stored ownership and replay state."""
        return plan_minidisk_deletion(
            self.load_receipt(receipt_id),
            self.load_key(),
            inventory,
            usage_evidence,
            active_directory_identity_confirmed=active_directory_identity_confirmed,
            consumed_receipt_ids=self.consumed_receipt_ids(),
            confirmation=confirmation,
            now=now,
        )

    def _write_consumed_ledger(self, entries):
        temporary = self.state_dir / f".consumed-{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump(entries, target, separators=(",", ":"))
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.consumed_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
