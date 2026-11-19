# Changelog

Newest first. What landed, not proof claims. Detailed work log is `NOTES.md`.

## Unreleased

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
