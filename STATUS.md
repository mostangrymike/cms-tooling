# Status

**Canonical current-state file for `cms-tooling`.** If any other document
disagrees with this page, this page wins. Last updated 2026-11-26.

## Right now

| Field | Value |
|---|---|
| Branch | `main` |
| Latest commit | see `git log -1 --oneline`; includes capability inventory and CMS A cleanup record |
| Working tree | clean; CMS A sed/awk fixture cleanup documented below |
| Build | `python3 -B build_cms_tooling.py` (offline, no CMS) |
| Tests | 125 tests, 0 failures/errors; Python 3.12 and 3.14 |
| CI | `cms tooling offline build` and `Offline tests (profiles)` — **green** |

## What works

- Line-mode Telnet driver with one-command-at-a-time capture, RC, intervention
  and recovery (`cms_telnet_driver.py`); credentials paths expand `~`.
- FTP transfer driven from the same Telnet session (`cms_ftpput.py`).
- Profile-driven destinations: `cms_profiles.py`, `~/.config/cms-tooling/cms_profiles.json`,
  selected by `--profile` / `profile_name`. **No destination environment variables.**
- Credentials loaded from `~/.config/ibm-zvm-cms/credentials.json`; never in
  source, profiles, or arguments.
- Read-only minidisk planner, directory plan, inventory, and receipt-gated
  lifecycle (`cms_mdisk_*`).
- Host-side plain-HTTP-to-HTTPS bridge with policy/credential boundary
  (`github_tls_bridge.py`). Restored 2026-11-26 in `http` mode on
  `192.168.200.1:8443` with closed repository/push allowlists and guest
  credential pass-through; 44 bridge tests and the 125-test offline build
  passed. CMS-side bridge use remains unproven.
- CMS↔BFS ASCII text bridge (`cms-execs/CMS2BFS.EXEC`, `cms-execs/BFS2CMS.EXEC`)
  built on `OPENVM PUTBFS`/`GETBFS` with explicit `1047`↔`819` translation;
  round trips verified byte-exact.
- One-command CMS build from BFS source (`cms-execs/MKMODULE.EXEC`): stage,
  `CMSCLNK`, `GENMOD`, with RC propagation for staging, compile and assembly
  failures.
- Native in-place edit and search, verified on the guest 2026-11-23:
  `PATCH fn ft fm hunkfn hunkft hunkfm` (backup to `fn BAK fm`, refuses an
  ambiguous match, nothing written on a mismatch) and `GREP pattern
  [fn [ft [fm]]]`. Details and the exit-code contract:
  [`docs/TOOLS.md`](docs/TOOLS.md).

## Target environment (verified 2026-11-19)

| Fact | Value |
|---|---|
| Guest | `MAINT AT TACOTICO`; z/VM 6.3.0, CMS 27 SL 1302 |
| OpenExtensions | installed; BFS `VMSYS` mounts at `/` from `PROFILE EXEC` |
| Shell | `OPENVM RUN /bin/sh`; `cms` works from inside the shell |
| `iconv` | only the `IBM-1047` charmap; no UTF-8 or ISO8859 conversion |
| `tar` | unusable (filename translation error 83) |
| `c89` | present but no compiler backend (`CBXFINIT`) |
| Outbound TLS | TLS 1.2 maximum; no SNI, no ECDHE, no AEAD |
| Outbound network | none; `192.168.200.0/24` is not NATed |

Details: [`docs/OE_BFS.md`](docs/OE_BFS.md),
[`docs/TLS_ASSESSMENT.md`](docs/TLS_ASSESSMENT.md).

## Filename database (`FIND`)

`MAINT 191` (A) carries `FINDBASE DATA A` — 117,397 records covering 267 of the
341 MDISK definitions in `CANDFIN DIRECT` — and `FIND EXEC A`, which searches
`filename[.filetype]` with `*`/`?` wildcards. Rebuild with
`cms_find_index.py --directory <source> --state <json> --database <file>`, then
`--install`. Details: [`docs/FIND_DB.md`](docs/FIND_DB.md).

## DirMaint removal

Phases 1–4 are complete.

| Phase | State |
|---|---|
| 1 — audit | done |
| 2 — stop `AUTOLOG1` autologging DirMaint/DIRMSAT | **applied 2026-11-23**; live profile byte-identical to the staged payload |
| 3 — candidate directory without DirMaint | **validated 2026-11-23**: `CANDNODM DIRECT C` on `MAINT 02CC`, 4023 recs, `DIRECTXA ... (EDIT` clean |
| 4 — activate candidate | **applied 2026-11-23** — `EOJ DIRECTORY UPDATED AND ON LINE`, 55 disk pages; removed IDs now `not in CP directory` |

Candidate removes `DIRMAINT`, `DIRMSAT`, `DATAMOVE`, `6VMDIR30`; no other entry
references them. `CANDFIN DIRECT` is unchanged and is the rollback source.
`DIRECTXA` is not a CP command here — the module is on `PMAINT 551`, which must
be accessed. Details: [`docs/DIRMAINT_REMOVAL.md`](docs/DIRMAINT_REMOVAL.md).

## GIT600 directory restoration — 2026-11-26

The active directory had lost `MAINT 0600` (GIT600). The web-console candidates
`CANDWEB`, `CANDGE`, and `CANDGD` each dropped both `MDISK 600` and `MDISK 0601`
while adding `WEBCONS`; the live `WEBCONS` privilege classes `DEG` identified
`CANDGD` as the active source. `CANDFIN`, `CANDNODM`, and `M173NEW` retained the
GIT600 record.

A new fixed-80 candidate `CANDGF80 DIRECT A` restored only:

```text
MDISK 600 3390 6000 1600 VMCOM1 W
```

`DIRECTXA CANDGF80 DIRECT A (EDIT` passed, and explicit approval was followed by
`DIRECTXA CANDGF80 DIRECT A`: `EOJ DIRECTORY UPDATED AND ON LINE`, 58 disk
pages. `CP QUERY MDISK USERID MAINT 0600 DIRECTORY` and a fresh read-only
link/access now expose `GIT600`. Rollback is `DIRECTXA CANDGD DIRECT C`;
`CANDGD DRBK26 C` is the byte-identical pre-change backup. `MDISK 0601` remains
absent. No FORMAT or GIT600 data rewrite occurred.

This restoration enabled real synthetic `cms-git` M301–M303 merge validation
recorded in the `cms-git` repository. All test runtime/ref/workfile files were
restored from `M301BK` backups afterward.

## CMS A sed/awk fixture cleanup — 2026-11-26

At the operator's request, only these ten test fixtures were erased from A:
`S2TSCR SED A1`, `S2TDATA DATA A1`, `T1`–`T6 AWK A1`, and `D1`/`D2 DATA A1`.
Before deletion they were packed into `CMSUTTST VMARC A`; a final read-only
`STATE`/`VMARC LIST` pass confirmed every fixture is absent and all ten are
recoverable from that archive. CMSED/CMSAWK sources, modules, and host test files
were not removed.

## What is not done

- Telnet credential logging defect: `connect()` sends the password through
  `_send()`, which can write verbose/session logs. Avoid `-v` and `--log` until
  redaction is fixed; FTP convenience functions also default to
  `/tmp/cms_driver.log`.
- `CmsSession.connect()` currently hardcodes `LOGON MAINT`; `--interrupt-after`
  is parsed but unused; `CommandResult.ok` treats `rc=None` as success, so
  callers must distinguish missing RC capture from numeric RC 0.
- No live production rollout; planner and lifecycle are offline/read-only.
- Deletion remains plan-only behind signed receipts.
- No dedicated offline end-to-end lifecycle harness (plan → create → activate
  → delete) beyond profile resolution tests.
- No general binary/MODULE BFS bridge or NAPI build driver; `CMS2BFS` and
  `BFS2CMS` cover ASCII text only, and `c89` has no compiler backend.
- DirMaint removal is complete through phase 4; `CANDFIN DIRECT` remains on 02CC as the rollback source.

## Protected CMS files (standing rule, 2026-11-22)

Never rename, erase, replace, or move these without a new explicit instruction
from the operator naming the exact file:

| Userid / disk | File | Role |
|---|---|---|
| `MAINT 191` (A) | `PROFILE EXEC` | MAINT logon profile (absent since 2026-11-22 erase; protected if recreated) |
| `MAINT 191` (A) | `RESTORE EXEC` | restore utility |
| `AUTOLOG1 191` (A) | `PROFILE EXEC` | autolog profile (220 recs, 11/23/26; DirMaint autolog disabled) |

`AUTOLOG1 191 PROFILE EXECSAV` (217 recs, 9/14/26 14:07:53) is the rollback
copy for that profile.

## Read next

1. [`ROADMAP.md`](ROADMAP.md) — remaining work.
2. [`docs/INDEX.md`](docs/INDEX.md) — what every doc is.
3. [`CHANGELOG.md`](CHANGELOG.md) — delivered work, newest first.
4. [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`AGENTS.md`](AGENTS.md) — validation and rules.
5. [`NOTES.md`](NOTES.md) — detailed work log.
