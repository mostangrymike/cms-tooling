# Work notes

## Goal and scope

The requested end goal is a fully functional Git client for IBM CMS. This
checkout is `cms-tooling`; its README identifies the native client as a separate
project in `ibm-sandbox`. Assumption: because the active repository is
`cms-tooling` and the task forbids touching files outside this repo, initially scoped the work to tooling; the operator has since authorized
working in any repository, so after this verified tooling step the work will
continue in the native client repository.

## Plan

1. Read repository instructions and establish the offline build/test baseline.
2. Inspect the current tooling checkpoint for a concrete, in-scope correctness
   or documentation gap that blocks reliable CMS Git work.
3. Implement one small fix, add or update regression coverage, run the full
   offline build/tests, and commit the verified step.
4. Report what this repository establishes and identify any end-goal work that
   remains outside this checkout.

## Progress

- Read `AGENTS.md`, `README.md`, `README-cms-mcp.md`, and
  `PIPELINE-READINESS.md`.
- Working tree was clean at start; branch `codex/cms-reconnect-startup` is one
  commit ahead of `origin` before this task.
- Offline baseline completed from an isolated extracted distribution: 274 tests
  passed, 0 failures/errors/skips; protocol defaults, upload gate, local review,
  operation review and failure rehearsal passed.
- Found the operator guide out of sync with the actual 18-tool MCP catalog: it
  said 16 and omitted `cms_abort_read`. Updating the guide and adding a regression
  check that binds the listed tools/count to the protocol validator.
- The isolated build after the change passed: 275 tests, 0 failures/errors/skips;
  archive reproduction, protocol defaults, upload gate, local edit/operation
  review and failure rehearsal all passed. Report: `builds/build-20261018T170829Z-37df90b2/build-report.json`.
- Next: commit this tooling documentation/regression step, then continue in the
  native client repository with its current project checkpoint.

## 2026-11-23 DirMaint removal, phases 1-3 (phase 4 held)

- Inspected live guest state as MAINT. `QUERY NAMES` shows no `DIRMAINT`,
  `DIRMSAT`, or `DATAMOVE`. `AUTOLOG1 191 B` had `PROFILE EXEC` = `PROFILE
  EXECP2` and the staged `PROFILE EXECNEW` present; diff matched the Phase 2
  intent: comment out `Call Dirm` / `rrc = result`, insert the disabled banner
  and `rrc = 0`. `Dirm:` / `ssidirm:` procedures left in place.
- Phase 2 applied on the operator's explicit "14 and 15 / proceed": linked
  `AUTOLOG1 191 291 WR`, `COPYFILE PROFILE EXECNEW B PROFILE EXEC B (REPLACE`,
  compared `PROFILE EXEC` vs `PROFILE EXECNEW` (silent), erased `EXECNEW`.
  Downloaded `PROFILE.EXEC.B` as `aut1/profile.live`; byte-identical to the
  staged `profile.new`. Rollback source remains `PROFILE EXECP2` (OLDDATE).
- Phase 3 built `CANDNODM DIRECT` on MAINT 02CC from `CANDFIN DIRECT`
  (4284 recs, 11/20/26 16:03:45). Removed USER entries `6VMDIR30`,
  `DATAMOVE`, `DIRMAINT`, `DIRMSAT` as whole blocks including banners and the
  `END USER` marker where present. Candidate 4023 records, max 80 columns.
  Directory-wide scan found no remaining non-header reference to those user IDs.
- `DIRECTXA` is not a CP command on this z/VM 6.3 system; the module is on
  `PMAINT 551` (and 550). `ACCESS 551 D` then `DIRECTXA CANDNODM DIRECT C
  (EDIT` gave `z/VM USER DIRECTORY CREATION PROGRAM - VERSION 6 RELEASE 3.0`,
  `EOJ DIRECTORY NOT UPDATED`, no diagnostics. `ACCESS 551 D` was R/O.
- Phase 4 NOT run. Activation command is `DIRECTXA CANDNODM DIRECT C` with
  the same disks accessed, but without `(EDIT`; this replaces the active
  directory and removes those four user IDs. The candidate and `CANDFIN
  DIRECT` remain on 02CC for rollback. Any operator who wants to go ahead must
  say so explicitly.

- Phase 4 activated 2026-11-23 after explicit operator approval ("approved
  for phase 4"). Commands: `ACCESS 2CC C`, `ACCESS 551 D`, `DIRECTXA CANDNODM
  DIRECT C` (no EDIT). Output: `z/VM USER DIRECTORY CREATION PROGRAM -
  VERSION 6 RELEASE 3.0`, `EOJ DIRECTORY UPDATED AND ON LINE`, `HCPDIR494I
  User directory occupies 55 disk pages`, Ready T=0.64/0.69. Post-checks:
  `CP LINK DIRMAINT 191 299 RR` and `CP LINK DATAMOVE 191 299 RR` ->
  `HCPLNM053E ... not in CP directory`. `QUERY USER` for DIRMAINT, DIRMSAT,
  DATAMOVE, 6VMDIR30 -> `HCPCQU045E ... not logged on`. `CANDFIN DIRECT`
  remains on 02CC for rollback via DIRECTXA.

## 2026-11-26 — TLS bridge, capability inventory, and GIT600 recovery

### Host TLS bridge

The old listener (PID 53158) was idle in `accept`, not deadlocked. Host curls to
`192.168.200.1` timed out because macOS routed that address through the LAN
gateway instead of loopback; direct GitHub HTTPS returned 200. The bridge was
stopped and restarted as PID 47711 in documented `http` mode on
`192.168.200.1:8443`, closed policy, allowlisted `mostangrymike/cms-git` and
`mostangrymike/cms-git-push-test`, push restricted to the test repository, and
`--auth-mode pass` because no host token file exists. Log:
`.local/github_tls_bridge.log` (0600). A temporary loopback instance returned
200 for `/healthz` and smart-HTTP discovery; 44 bridge tests and the full
125-test offline build passed. The host loopback route remains an operator
option; it is not required for the CMS VMnet path. CMS-side bridge use remains
unproven.

### Capability inventory and safety defect

Added `docs/CAPABILITIES.md` and indexed it in `docs/INDEX.md`. The inventory
was checked against source/tests; 52 targeted unit tests and two strict C89
syntax checks passed. It records that minidisk creation/activation/deletion
execution is not implemented in this repository, and it separates live-proven,
offline-tested, plan-only, and unverified capabilities.

The review found a credential-logging defect: `CmsSession.connect()` sends the
password through `_send()`, which can write verbose/session logs. One probe log
created during this session was deleted immediately. Avoid `-v` and `--log`
until redaction is fixed. Also recorded: `connect()` hardcodes `LOGON MAINT`,
`--interrupt-after` is unused, and `rc=None` is not proof of success.

### GIT600 CP-directory recovery

Live `WEBCONS` classes `DEG` matched `CANDGD`. Diffs showed `CANDWEB`, `CANDGE`,
and `CANDGD` each removed `MDISK 600` (GIT600) and `MDISK 0601` while adding
`WEBCONS`; `USER`/`M173BAK` also lacked both, while `CANDFIN`, `CANDNODM`, and
`M173NEW` retained GIT600. The earlier DirMaint removal was not the cause.

Created `CANDGD DRBK26 C` as a byte-identical backup. Derived `CANDG600 DIRECT
A`, inserted only `MDISK 600 3390 6000 1600 VMCOM1 W` with native `PATCH`, and
normalized to fixed-80 `CANDGF80 DIRECT A` (4297 records). `DIRECTXA ... (EDIT`
passed. After explicit approval, activation returned `EOJ DIRECTORY UPDATED AND
ON LINE`, 58 disk pages. CP query and fresh read-only link/access confirmed
GIT600. Rollback: `DIRECTXA CANDGD DIRECT C`. `MDISK 0601` remains absent. No
FORMAT or GIT600 data rewrite occurred.

### cms-git M301 support

The restored GIT600 target allowed a real synthetic `GIT MERGE` validation in
`cms-git`. The test deployed five runtime EXECs with `M301BK` backups, created
two disjoint branches, produced two-parent commit
`868157275B4ADFFBDA05C1E22CEDBF8544A49F34`, applied both changes, and verified
clean status. Every runtime/ref/worktree backup was restored and compared
identical afterward. Test objects and staging artifacts remain; no deletion was
performed. Details are in `cms-git/NOTES.md`.
