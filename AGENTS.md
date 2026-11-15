# Local z/VM CMS automation

- Preserve existing source and transfer scripts; do not reset unrelated changes.
- Use the repository `.venv/bin/python`.
- Command access is line-mode Telnet to `192.168.200.2:23` through
  `cms_telnet_driver.py`. There is no 3270 path in this tree; do not add one.
- File transfer is FTP only, driven from the same Telnet session
  (`cms_ftpput.py`). Do not reintroduce 3270 file transfer (DFT/IND$FILE).
- Credentials live in an owner-only file outside the repository
  (`~/.config/ibm-zvm-cms/credentials.json`), loaded locally. Never print
  values, never put them in arguments, never commit them.

## Authorization (recorded, still binding)

- On 2026-10-19 the operator authorized Codex to take any action on CMS without
  per-action confirmation and asked that this authority persist. On 2026-10-20
  the operator repeated that authorization for future CMS work.
- Continue to record each action and its observed result. Use only the actions
  needed for the active task. A general command capability is not blanket
  authority to modify protected targets.
- Never modify protected CMS files, disks, directory entries, or other
  sessions without the exact target and operation being part of the current
  task. Never erase or replace a CMS file without specific authorization.
- Destructive, broad, or irreversible steps still get a stop-and-confirm: CP
  directory activation, FORMAT, DASD initialization, RELEASE, or deleting
  another user's data.

## Command discipline

- One command in flight. Completion needs the CMS prompt (a line containing
  only `.`) plus a `Ready` RC where one is produced. Never treat a screen
  change or keyboard unlock as proof of completion.
- Do not scroll with sleeps to collect output. Stream complete lines; let the
  driver advance `MORE`/`HOLDING`.
- A timeout means unknown state. Do not retry automatically. Reconnect and
  inspect before deciding whether the command ran.
- Interrupt a runaway program with Telnet IP, then `HX`, then `IPL CMS` only as
  the driver documents. Never infer an RC that was not captured.
- Keep stdout clean when a script is consumed programmatically. Diagnostics to
  stderr.

## Minidisk work

Minidisk provisioning lives in the separate
`mostangrymike/cms-minidisk-provisioning` repository. Use its planner and its
inventory contract; do not duplicate provisioning logic here.

- The planner is read-only. It needs a recent complete inventory and fails
  closed on stale, incomplete, overlapping, full-pack, or ineligible evidence.
- Directory changes are made by editing the CP source directory and activating
  it with `DIRECTXA`. Never edit the active directory in place, never invent a
  free extent from `DIRMAP` alone, and never use virtual device `0192`.
- Keep a protected backup and a separate candidate. Run `DIRECTXA candidate
  (EDIT` first; stop for explicit approval before non-EDIT activation.
- Stop again before `FORMAT`. Verify geometry, label, and access afterwards.
- Do not clean up or release an extent automatically after a failure. Preserve
  candidate, backup, and partial target for review.

## Build and validation

- Run offline unit tests and `build_cms_tooling.py` before any live test.
- `build_cms_tooling.py` validates an isolated extracted copy, reproducible
  archive bytes, and every tracked Python module is reachable from an entry
  point or explicitly excluded with a reason.
- Build artifacts and host-side success do not establish CMS target
  qualification. Do not claim live validation unless it actually ran.
- The host TLS bridge (`github_tls_bridge.py`) is a workstation process. It is
  not shipped to the guest and must not be uploaded.

## Project

- Tooling repository: `mostangrymike/cms-tooling`. The separate production
  project is `mostangrymike/ibm-sandbox`; read its `CHAT_STATE.md` and
  `README.md` before production work.
- Preserve the production G disk stage/index, MODULEs, rollback sources, and
  exact scratch-cleanup rules.
- No production source replacement follows from local tooling work.
