# Capabilities inventory

**Reference:** what this repository can do, how to invoke it, and what is
actually proven. `STATUS.md` remains the only current-state authority;
`ROADMAP.md` remains the only gap list.

## Architecture

- Host automation is Python 3.12+ and standard-library-only for the Telnet,
  FTP, profile, and planner paths.
- Live access uses z/VM **line-mode Telnet** at `192.168.200.2:23` through
  `cms_telnet_driver.py`. There is no 3270 or screen-scraping path.
- File transfer uses CMS FTP driven from the same Telnet session through
  `cms_ftpput.py`.
- Credentials come from `~/.config/ibm-zvm-cms/credentials.json`; profiles come
  from `~/.config/cms-tooling/cms_profiles.json`. Neither belongs in source,
  arguments, logs, or profiles.
- The host TLS bridge is the only path from CMS plain HTTP to GitHub HTTPS.
  It stays on the workstation and must not be uploaded to CMS.

## Capability map

| Capability | Entry point | What exists | Evidence / limits |
|---|---|---|---|
| Telnet command execution | `cms_telnet_driver.py` | Persistent session, logon, dot-prompt completion, RC capture, streaming, paging, timeout/interrupt recovery; `probe`, `run`, `batch`, `shell` | Live exercised; fake-server tests. No 3270/MCP. See [TELNET-DRIVER.md](../TELNET-DRIVER.md). |
| FTP transfer | `cms_ftpput.py` | Drives CMS FTP from the Telnet session. CLI is PUT-only; GET is available through the Python API. | Live and offline tested. Replacement semantics must be reviewed before overwriting protected files. |
| Profiles | `cms_profiles.py` | Profile-selected Telnet/FTP destinations; no destination environment variables. | Offline tested. Local profile file is optional; defaults target MAINT. |
| Credential loading | `cms_credentials.py` | Loads owner-only credentials outside the repository. | Values must never be printed or passed as arguments. See the logging defect below. |
| Minidisk inventory/plan | `cms_mdisk_inventory.py`, `cms_mdisk_plan.py` | Sanitized inventory, CP/directory reconciliation, best-fit 3390 planning. | Offline tested, read-only/plan-only. |
| Directory candidate | `cms_mdisk_directory.py` | Candidate CP-directory generation with collision and overlap checks. | Offline tested. Activation is a separate, guarded operation. |
| Lifecycle/receipts | `cms_mdisk_lifecycle.py`, `cms_mdisk_receipts.py` | HMAC-signed ownership receipts and receipt-gated deletion proposals. | Offline tested, plan-only. Creation, FORMAT, activation, and deletion execution are not implemented here. |
| Filename index | `cms_find_index.py`, `cms-execs/FIND.EXEC` | Builds `FINDBASE DATA A` and searches `filename[.filetype]` with `*`/`?`. | Documented live: 117,397 files from 267 of 341 MDISK definitions. See [FIND_DB.md](FIND_DB.md). |
| CMS/BFS text bridge | `cms-execs/CMS2BFS.EXEC`, `BFS2CMS.EXEC` | `OPENVM PUTBFS`/`GETBFS` with explicit numeric `1047`↔`819` translation. | Documented byte-exact round trip. ASCII text only; UTF-8/binary/MODULE transfer unproven. See [OE_BFS.md](OE_BFS.md). |
| One-command module build | `cms-execs/MKMODULE.EXEC` | Stages BFS C source, runs `CMSCLNK`, then `GENMOD`; propagates staging/compile/assembly failures. | PLAIN build documented live. NAPI and compiler-backend limitations remain. |
| Native patch | `cms-execs/PATCH.EXEC` | Exact-context hunks, backup, dry-run, ambiguity refusal, temp-then-replace writes. | Documented live 2026-11-23. See [TOOLS.md](TOOLS.md). |
| Native search | `cms-execs/GREP.EXEC` | Case-folding search over accessed CMS files with limits and file-only output. | Documented live 2026-11-23. See [TOOLS.md](TOOLS.md). |
| TLS bridge | `github_tls_bridge.py` | Raw `relay`; policy-enforcing smart-HTTP `http`; `/healthz`; repo/push allowlists; pass-through or host-held auth; framing/limits; redacted request logs. | Offline tested; host health/discovery verified 2026-11-26. Live CMS clone/pull/push remains unproven in this checkout. See [BRIDGE.md](../BRIDGE.md). |
| Offline build | `build_cms_tooling.py` | Import-closure manifest, isolated extracted tests, reproducible archive bytes, hash verification, optional credential scan. | Offline proven; never contacts CMS. |
| C utilities | `cms-utils/` | CMSED/CMSAWK C89 sources and fixtures. | Outside the Python bundle. Current snapshot has not been requalified live. |

## Target facts and hard limits

Verified target (2026-11-19):

- z/VM 6.3.0, CMS 27 SL 1302, `MAINT AT TACOTICO`.
- OpenExtensions installed; BFS `VMSYS` mounts at `/` from `PROFILE EXEC`.
- `OPENVM RUN /bin/sh` works; `cms` works from the shell.
- `iconv` supports only `IBM-1047`; no UTF-8 or ISO8859 conversion.
- `tar` is unusable (filename translation error 83).
- `c89` exists but has no compiler backend (`CBXFINIT`).
- Outbound TLS is limited to TLS 1.2; no SNI, ECDHE, AEAD, or ALPN.
- `192.168.200.0/24` is not NATed, so CMS cannot reach GitHub directly.

See [TLS_ASSESSMENT.md](TLS_ASSESSMENT.md) and [OE_BFS.md](OE_BFS.md).

## Runnable examples

Run from `/Users/mikewommack/cms-tooling`.

```sh
# Offline qualification; build writes builds/ and never contacts CMS.
.venv/bin/python -B build_cms_tooling.py
.venv/bin/python -B -m unittest discover -v

# One command, with RC and duration captured by the driver.
.venv/bin/python cms_telnet_driver.py run --timeout 600 "CP QUERY DISK"

# Multiple commands in one logged-on session; stops on nonzero RC.
.venv/bin/python cms_telnet_driver.py batch commands.txt --timeout 120

# PUT only: local CMS file ID -> FTP name.
.venv/bin/python cms_ftpput.py "PATCH EXEC A1" "PATCH.EXEC"

# Plan-only folder/minidisk operations.
.venv/bin/python cms_folder.py plan --inventory inventory.json --size-mib 50
.venv/bin/python cms_folder.py delete-plan \
  --inventory inventory.json --usage-evidence usage.json \
  --receipt-id RECEIPT_UUID

# Build a filename database from a CP directory source.
.venv/bin/python cms_find_index.py \
  --directory candfin.direct --state findscan.json --database findbase.data
# Install through the live session; this writes MAINT A.
.venv/bin/python cms_find_index.py --install --state findscan.json
```

CMS-side examples:

```sh
FIND *.EXEC
CMS2BFS PROFILE EXEC A /tmp/profile.exec
BFS2CMS /tmp/profile.exec PROFILE EXEC A1
MKMODULE S2SED /tmp/s2sed.c PLAIN
PATCH PTEST EXEC A HUNK TEXT A (CHECK
GREP MAXCONN * EXEC A (I (LIMIT 20
```

Host bridge (normal documented HTTP mode):

```sh
.venv/bin/python github_tls_bridge.py \
  --mode http \
  --bind 192.168.200.1 --port 8443 \
  --upstream-host github.com --upstream-port 443 \
  --policy closed \
  --allow-repo mostangrymike/cms-git \
  --allow-repo mostangrymike/cms-git-push-test \
  --allow-push-repo mostangrymike/cms-git-push-test \
  --auth-mode pass

curl -fsS http://192.168.200.1:8443/healthz
```

Use `--auth-mode host --token-file ...` only when a valid owner-only token file
exists. Never echo or log the token.

## Deploying and validating `cms-git`

The supported integration is one `CmsSession` for transfer, command execution,
and evidence capture:

```python
from cms_telnet_driver import CmsSession
from cms_ftpput import get_files_on_session

pairs = [(".cms-execs/FIND.EXEC", "FIND EXEC A1")]

with CmsSession() as session:
    session.connect()
    get_files_on_session(session, pairs)
    state = session.command("STATE FIND EXEC A1", timeout=30)
    if state.rc != 0:
        raise RuntimeError(f"deployment failed: {state.output}")
    result = session.command("EXEC GIT LEVEL", timeout=60)
    print(result.rc, result.duration, result.output)
```

Rules for evidence:

1. Capture `CommandResult.output`, `rc`, and `duration`; retain the exact command.
2. Treat `rc=None` as **no RC captured**, not success. CMS built-ins often do
   not provide a numeric RC.
3. Validate postconditions separately with `STATE`, `COMPARE`, or BFS `cmp`.
4. Concatenate CMS-wrapped output before parsing long OIDs.
5. Do not claim host-test success as CMS proof.
6. Do not overwrite protected files or replace production EXECs without the
   exact target and operation being part of the task.

## 2026-11-26 operational proof

- The host TLS bridge was restored in `http` mode on `192.168.200.1:8443` with
  closed repo/push allowlists. Local health/discovery, 44 bridge tests, and the
  full 125-test offline build passed; CMS-side bridge use remains unproven.
- Native `PATCH`, `GREP`, `COMPARE`, `TYPE`, `COPYFILE`, `LISTFILE`, FTP, and
  `DIRECTXA` were used to restore the missing `MAINT 0600` GIT600 definition.
  The active `CANDGD` web-console candidate had dropped both `MDISK 600` and
  `MDISK 0601`; only GIT600 was restored through fixed-80 candidate
  `CANDGF80 DIRECT A`. See [`DIRMAINT_REMOVAL.md`](DIRMAINT_REMOVAL.md).
- Restored GIT600 supported a real synthetic `cms-git` M301 `GIT MERGE` test.
  All temporary runtime/ref/worktree replacements were restored from `M301BK`
  backups and verified identical. This is target evidence for that test only,
  not a production rollout.

## Known defects and documentation gaps

- **Credential logging defect:** `CmsSession.connect()` sends the password
  through `_send()`, which can write verbose/session logs. Avoid `-v` and
  `--log` until redaction is fixed. FTP convenience functions also default to
  `/tmp/cms_driver.log`.
- `CmsSession.connect()` currently hardcodes `LOGON MAINT`, despite loading a
  userid.
- `--interrupt-after` is parsed but unused.
- `CommandResult.ok` treats `rc=None` as success; callers must not.
- `BRIDGE.md` and `AGENTS.md` say the bridge is not shipped, but the current
  build manifest includes `github_tls_bridge.py` and its test.
- `STATUS.md` names commit `c4f40b0`; current `main` at inventory time was
  `f8e3404`, which added `cms-utils`. Those utilities are not yet covered by
  the Python build or canonical status.
- The initial inventory was source/test-based. Live CMS/FTP operations used
  for the 2026-11-26 recovery are recorded in the operational-proof section;
  no live GitHub operation was run. CMS-side TLS-bridge use remains unproven.

## Validation performed for this inventory

```sh
.venv/bin/python -B -m unittest -v \
  test_cms_execs test_cms_mdisk_plan test_cms_mdisk_inventory \
  test_cms_mdisk_directory test_cms_mdisk_cp test_cms_folder \
  test_cms_mdisk_lifecycle
```

Result: **52 tests passed**.

```sh
gcc -std=c89 -Wall -Wextra -Werror -fsyntax-only \
  -DCMSED_HOST cms-utils/cms-sed/cmsed.c
gcc -std=c89 -Wall -Wextra -Werror -fsyntax-only \
  cms-utils/cms-awk/cmsawk.c
```

Result: both exited 0 with no diagnostics.

Separate bridge qualification on 2026-11-26:

```sh
.venv/bin/python -m unittest -q test_github_tls_bridge
.venv/bin/python -B build_cms_tooling.py
```

Result: **44 bridge tests passed**; full offline build **125 tests passed**.
A temporary loopback instance returned `200` for `/healthz` and smart-HTTP
discovery. The production listener was left in `http` mode on
`192.168.200.1:8443`; CMS-side use remains unproven.
