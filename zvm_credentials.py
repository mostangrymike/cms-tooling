"""Local-only credentials. No values are accepted as MCP tool arguments."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import stat


class CredentialError(RuntimeError):
    pass


@dataclass(repr=False)
class Credentials:
    userid: str = field(repr=False)
    password: str = field(repr=False)


def validate(userid, password):
    if not isinstance(userid, str) or not re.fullmatch(r"[A-Za-z0-9@#$]{1,8}", userid):
        raise CredentialError("Local userid must be 1..8 CMS identifier characters")
    if (not isinstance(password, str) or not 1 <= len(password) <= 8
            or any(ord(c) < 33 or ord(c) > 126 for c in password)
            or any(c in password for c in '\\"')):
        raise CredentialError("Local password must be 1..8 printable ASCII characters without quotes or backslashes")
    return Credentials(userid.upper(), password)


class FileCredentialProvider:
    def __init__(self, path):
        self.path = Path(path).expanduser()

    def load(self):
        # O_NOFOLLOW plus fstat avoids checking one file and reading another.
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            raise CredentialError("Local credential file is unavailable; configure it outside MCP") from None
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096):
                raise CredentialError("Credential file must be an owner-owned regular file with mode 0600, at most 4096 bytes")
            with os.fdopen(fd, "r", encoding="utf-8") as handle:
                fd = None
                try:
                    data = json.loads(handle.read(4097))
                except (ValueError, UnicodeError):
                    raise CredentialError("Local credential file is not valid credential JSON") from None
            if not isinstance(data, dict) or set(data) != {"userid", "password"}:
                raise CredentialError("Credential JSON must contain only userid and password")
            return validate(data["userid"], data["password"])
        finally:
            if fd is not None:
                os.close(fd)


def import_legacy(path):
    """Extract constants only; never import or execute a legacy automation file."""
    try:
        module = ast.parse(Path(path).read_text())
    except (OSError, SyntaxError, UnicodeError):
        raise CredentialError("Cannot read legacy credential constants") from None
    values = {}
    for node in module.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in {"USER", "PASSWORD"} and isinstance(node.value, ast.Constant):
                values[name] = node.value.value
    return validate(values.get("USER"), values.get("PASSWORD"))


def store_new(path, credentials):
    path = Path(path).expanduser()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = path.parent.stat()
    if path.parent.is_symlink() or directory.st_uid != os.getuid() or stat.S_IMODE(directory.st_mode) & 0o077:
        raise CredentialError("Credential directory must be owner-only and not a symlink")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise CredentialError("Credential destination exists or cannot be created; no overwrite performed") from None
    with os.fdopen(fd, "w") as handle:
        json.dump({"userid": credentials.userid, "password": credentials.password}, handle)
        handle.write("\n")


def main():
    import argparse
    import getpass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--import-legacy", help="Extract USER/PASSWORD constants without executing the file")
    args = parser.parse_args()
    try:
        if args.import_legacy:
            credentials = import_legacy(args.import_legacy)
        else:
            credentials = validate(input("z/VM userid: "), getpass.getpass("z/VM password: "))
        store_new(args.output, credentials)
    except CredentialError as exc:
        parser.exit(1, str(exc) + "\n")
    print("Created local credential file with mode 0600. Values were not printed.")


if __name__ == "__main__":
    main()
