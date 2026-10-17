# zvm-tooling

Guarded local automation for IBM z/VM CMS through a stdio MCP server and one
persistent s3270 terminal. Starts disconnected; terminal input and host writes
are disabled by default.

See [setup and tool documentation](README-zvm-mcp.md),
[qualification boundaries](PIPELINE-READINESS.md), and
[migration provenance](MIGRATION.md).

Requires Python 3.12+, Git, s3270 and Regina REXX (`rexx`). From this directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-zvm-mcp.txt
.venv/bin/python -B build_zvm_tooling.py
```

The build runs entirely offline, including protocol checks and local review
rehearsals. It does not connect to CMS. GitHub Actions repeats the isolated build
on Python 3.12 and 3.14.

This project originated in
[mostangrymike/ibm-sandbox](https://github.com/mostangrymike/ibm-sandbox).
The production native CMS Git client remains there. No production source,
credentials, local snapshots or live capture artifacts are included here.
