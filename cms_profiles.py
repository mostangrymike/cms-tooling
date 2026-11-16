#!/usr/bin/env python3
"""
Profile management for CMS tooling destinations (telnet/ftp).

- Profiles are stored in JSON under ~/.config/cms-tooling/cms_profiles.json
- Each profile can contain fields like:
  - name: string
  - host: string (telnet destination or CMS host)
  - port: int
  - ftp_host: string (optional override for FTP destination)
  - ftp_port: int (optional FTP port)
  - description: string (optional)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator, Optional, Tuple

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "cms-tooling"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "cms_profiles.json"

def load_profiles(path: Optional[str | Path] = None) -> dict:
    p = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not p.exists():
        return {"profiles": [], "default": None}
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("cms_profiles.json must contain a JSON object")
    return data

def get_profile(name: Optional[str] = None, path: Optional[str | Path] = None) -> Optional[dict]:
    data = load_profiles(path)
    if name is None:
        name = data.get("default")
    for prof in data.get("profiles", []):
        if prof.get("name") == name:
            return prof
    return None

def list_profiles(path: Optional[str | Path] = None) -> list:
    data = load_profiles(path)
    return data.get("profiles", [])

def read_profile_ftp_destination(name: Optional[str] = None, path: Optional[str | Path] = None) -> Optional[Tuple[str, int]]:
    prof = get_profile(name, path)
    if not prof:
        return None
    host = prof.get("ftp_host") or prof.get("host")
    port = int(prof.get("ftp_port") or prof.get("port") or 2121)
    if not host:
        return None
    return host, port
