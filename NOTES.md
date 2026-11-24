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
