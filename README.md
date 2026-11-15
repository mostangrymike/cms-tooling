# cms-tooling

Guarded local automation for IBM z/VM CMS. Connections use the z/VM TCPIP
line-mode Telnet service only; file transfer uses FTP. There is no 3270
terminal, no screen scraping, and no MCP server in this tree.

## Components

| Path | Purpose |
| --- | --- |
| `cms_telnet_driver.py` | Persistent line-mode Telnet session: logon, CMS ready checks, one-command-at-a-time capture with RC, interrupt/recovery, CLI (`probe`, `run`, `batch`, `shell`). |
| `cms_ftpput.py` | FTP transfer helper that drives the CMS FTP client from the same Telnet session. |
| `cms_mdisk_plan.py` | Read-only minidisk planner for a MAINT 3390 extent. |
| `cms_credentials.py` | Owner-only local credential store. Values are never printed or passed as arguments. |
| `github_tls_bridge.py` | Host-side plain-HTTP-to-HTTPS bridge for the CMS Git client. See [BRIDGE.md](BRIDGE.md). |

Requires Python 3.12+ and Git. The runtime uses only the standard library, so
no pip install is needed for the Telnet, FTP, or planner paths.

```sh
.venv/bin/python cms_telnet_driver.py probe
.venv/bin/python cms_telnet_driver.py run "CP QUERY ALLOC"
.venv/bin/python -B build_cms_tooling.py
```

The build runs entirely offline: unit tests in an isolated extracted copy,
reproducible archive bytes, and an optional credential scan. It never connects
to CMS. GitHub Actions repeats it on Python 3.12 and 3.14.

## Safety

Read [AGENTS.md](AGENTS.md) before touching a live system. Credentials live
outside the repository in an owner-only file (see `cms_credentials.py`).
Protected CMS files, disks, directory entries, and other users' sessions are
never modified without explicit authorization for that exact target. Host-level
success does not prove CMS behaviour; report target validation separately.

Minidisk scope, inventory contract, and the executor gates are in
[MINIDISK-PROVISIONING.md](MINIDISK-PROVISIONING.md). Telnet driver behaviour
and limits are in [TELNET-DRIVER.md](TELNET-DRIVER.md).

This project originated in
[mostangrymike/ibm-sandbox](https://github.com/mostangrymike/ibm-sandbox).
