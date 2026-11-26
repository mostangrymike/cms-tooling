# Changelog

Newest first. What landed, not proof claims. Detailed work log is `NOTES.md`.

## Unreleased

- Record the operator-requested CMS A sed/awk test-fixture cleanup. Only
  `S2TSCR`, `S2TDATA`, `T1`–`T6`, and `D1`/`D2` were erased, after packing all ten
  into `CMSUTTST VMARC A`; final `STATE`/`VMARC LIST` checks confirmed absence and
  recoverability. Sources, modules, and host tests were retained.
- Restore the host GitHub TLS bridge in documented `http` mode on
  `192.168.200.1:8443`, with closed repo/push allowlists and guest credential
  pass-through. Local `/healthz` and smart-HTTP discovery passed; 44 bridge
  tests and the full 125-test offline build passed. CMS-side bridge use remains
  unproven.
- Add `docs/CAPABILITIES.md`: source-grounded inventory of Telnet/FTP,
  profiles/credentials, minidisk planning, FIND, CMS/BFS bridges, MKMODULE,
  PATCH/GREP, TLS bridge, offline build, target limits, and `cms-git` integration.
- Restore `MAINT 0600` (GIT600) to the CP directory after tracing its loss to
  the `CANDWEB`/`CANDGE`/`CANDGD` web-console candidates. New fixed-80 candidate
  `CANDGF80 DIRECT A` passed `DIRECTXA (EDIT` and was activated with approval;
  58 disk pages. Rollback is `CANDGD DIRECT C`, with `CANDGD DRBK26 C` as the
  byte-identical backup. `MDISK 0601` remains absent; no FORMAT occurred.
- DirMaint removal phase 2: `AUTOLOG1 191 PROFILE EXEC` now comments out
  `Call Dirm` and sets `rrc = 0` (220 records). `PROFILE EXECP2` keeps the
  pre-change content; the live file was downloaded and compared byte-for-byte
  with the staged payload.
- DirMaint removal phase 3–4: built `CANDNODM DIRECT` on `MAINT 02CC` from
  `CANDFIN DIRECT`, removing the `DIRMAINT`, `DIRMSAT`, `DATAMOVE` and
  `6VMDIR30` entries. `DIRECTXA CANDNODM DIRECT C (EDIT` compiles with no
  diagnostics. Phase 4 activated on explicit approval: `EOJ DIRECTORY UPDATED AND ON LINE`, `HCPDIR494I User directory occupies 55 disk pages`; removed IDs now answer `HCPLNM053E ... not in CP directory`.
- Add `docs/DIRMAINT_REMOVAL.md`: phases, exact commands, rollback, and the
  fact that `DIRECTXA` is a module on `PMAINT 551`, not a CP command here.

- Add `cms-execs/PATCH.EXEC`: hunk-based in-place edit for CMS files
  (`-old`/`+new` blocks, exact match after trailing-blank strip, backup to
  `fn BAK fm`, temp `fn PTCHTMP fm` then `COPYFILE (REPLACE)`). Refuses an
  ambiguous match (RC 8) and writes nothing on any mismatch (RC 12).
  `(CHECK` dry-runs; `(FIRST`/`(ALL` opt into multiple matches.
- Add `cms-execs/GREP.EXEC`: search file contents on any accessed minidisk,
  `(I`, `(LIMIT n`, `(FILES`; RC 1 when nothing matches.
- Add `docs/TOOLS.md`: which layer (CMS native, OpenExtensions, host FTP) to
  use for which job, the shared exit-code contract, and the CMS behaviours
  that break Unix-shaped tools (`EXECIO DISKW` always appends, `stem.(expr)`
  is a routine call, `fn ft BAK` is not a filemode, writes invisible until
  `FINIS`).
- Add `test_cms_execs.py`: offline guards on the shipped REXX sources (80
  columns, no tabs, no indexed-stem expressions, writers close their files).
  `cms-execs/*.EXEC` now ship in the build bundle.

- Add `cms-execs/MKMODULE.EXEC`: stage a BFS C source onto `A`, run the site
  `CMSCLNK`, report the RC, leave `name C A1` and `name LISTING A1`.
  `PLAIN` default; verified build and run of a 2648-record source.
- Record the build limits: 186-column comment and 163-column string literal
  build, a 190-character identifier fails at assembly (`IFO026`); empty BFS
  source fails with RC 40; `'CMSCLNK'` needs the `EXEC` prefix inside REXX.
- Add `cms-execs/CMS2BFS.EXEC` and `cms-execs/BFS2CMS.EXEC`: ASCII text
  transfer between CMS files and BFS using `OPENVM PUTBFS`/`GETBFS` with
  explicit `1047`↔`819` translation. Byte-exact round trips at 80 and 300
  columns; RC 28 on a missing file in either direction.
- Record in `docs/OE_BFS.md`: numeric code pages only (`1208` fails),
  `TRANSLATE` is not implied, full file mode required, MODULE does not round
  trip, and `/bin/c89` has no compiler backend.
- Add `docs/OE_BFS.md`: OpenExtensions/BFS verification, `/bin` inventory,
  NLS gaps (`iconv`, `tar`), and the `EXEC OPENVM` profile gotcha.
- Add `docs/TLS_ASSESSMENT.md`: captured ClientHello, TLS 1.2 ceiling, no SNI
  or ECDHE, and no outbound route from the guest.
- Mount the OE root from `PROFILE EXEC` on MAINT so every logon has BFS;
  original kept as `PROFILE EXECSAV`.
- Fix `cms_telnet_driver.py` missing `import os`, which broke every live
  connection at credential loading; add a tilde-expansion regression test.
- Add canonical state stack: `STATUS.md`, `ROADMAP.md`, `docs/INDEX.md`,
  `CHANGELOG.md`, and a state-precedence block in `AGENTS.md`.

## 2026-11-16 — CI fix

- Register `test_cms_profiles.py`,
  `test_cms_profiles_offline_end2end.py`, and `test_cms_telnet_profile.py` as
  build entry points; offline build and profile test jobs are green.

## 2026-11-16 — Profile tests and runbook

- Add `test_cms_profiles.py`, `test_cms_profiles_offline_end2end.py`,
  `test_cms_telnet_profile.py`, `Profiles_Runbook.md`, and an offline CI
  workflow.

## Profile-driven destinations

- Add `cms_profiles.py`; resolve Telnet/FTP destinations from
  `~/.config/cms-tooling/cms_profiles.json` via `--profile` / `profile_name`.
- Remove destination environment-variable selection.

## Folder integration

- Integrate folder planning into `cms-tooling`; add `cms_folder.py` and FTP
  transfer tests; wire into build and tests.

## Minidisk provisioning split

- Move minidisk provisioning to its own repository; keep the read-only planner
  and receipts here.
