# zvm-tooling

Guarded local automation for IBM z/VM CMS through a stdio MCP server and one
persistent s3270 terminal. Starts disconnected; terminal input and host writes
are disabled by default.

See [setup and tool documentation](README-zvm-mcp.md),
[qualification boundaries](PIPELINE-READINESS.md), and
[migration provenance](MIGRATION.md).

The [version 1 progress checkpoint](V1-PROGRESS.md) records the disposable
end-to-end development finish line, completed work and exact restart steps.
That fixed C cycle passed: backup/replacement/recovery, build/test, native
outputs and final inventory/FILEDEF checks are verified. Production execution
and replacement qualification remain separate.

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

## Fixed disposable C qualification

`validate_zvm_fixture.py` prints an offline contract by default. The separate
live path requires `--live --qualify-recovery`, the exact printed
`--contract-sha256`, a local `--credential-file` and a new `--output` evidence
file. It is limited to newly created ZTQUAL C A1, ZTQBACK C A1 and declared
ZTQUAL compiler outputs. A new source-verified random ZM helper provides only
fixed build/test/FILEDEF actions. Existing helpers and scratches are preserved.
Every step is checkpointed; a failure stops without retry, restore or cleanup.
Success qualifies that fixture only; production writer exclusion and deployment
remain unresolved. See V1-PROGRESS.md for actual validation state.

`validate_zvm_fixture_audit.py` provides a separate read-only continuation for
the retained run that stopped during LISTING capture after successful build/test.
It pins the old journal hash and a new source contract, verifies all output/source/
backup snapshots, transient absence, exact inventories and FILEDEF state, and
never repeats creation, replacement, compilation or execution. Its optional
`--recover-failed-reader` requires separate operator approval for one Clear and
one fixed QUERY CMSLEVEL probe at the exact failed-reader/Ready(00012) boundary.
For the observed three-record V52312 MODULE, `--create-output-reader` explicitly
provisions one new source-verified output-only helper. It transports bounded
chunks plus the original native record lengths; standard download/edit limits
stay unchanged. `--completed-output-evidence` and its exact SHA-256 may retain
already verified ASSEMBLE/TEXT/LISTING snapshots after revalidating their local
bytes/manifests; these are identified as retained evidence, not fresh host reads.
Neither provisioning nor an audit authorizes fixture source changes or builds.
The qualified helper is retained as `ZME09C7C EXEC A`; future explicit re-audits
must use `--output-reader ZME09C7C` and reverify its source.
No recovery or audit success is claimed merely because the implementation exists.
