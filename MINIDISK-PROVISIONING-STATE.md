# Minidisk provisioning — paused state (2026-11-15)

Resume point for the direct-directory minidisk work. Read with
`MINIDISK-PROVISIONING.md` and `AGENTS.md`.

## Decision

DirMaint is out. Allocations will be made by editing the CP source directory
(`USER DIRECT`) and activating it with `DIRECTXA`. No DirMaint, SMAPI, or
3270 path is in scope for this task. Access is by line-mode Telnet
(`192.168.200.2:23`) through `cms_telnet_driver.py`, not s3270.

## Confirmed live facts (read-only, 2026-11-15)

- Telnet driver `probe` reached CMS as MAINT. CMS Level 27.
- `CP QUERY ALLOC`:
  - `M01RES` DRCT total 20 cylinders, 1 in use, **ACTIVE**.
  - `M01S01` SPOOL 10999 cylinders.
  - `M01P01` PAGE 10999 cylinders.
  - `VMCOM1` has no DRCT/SPOOL/PAGE allocation.
- `CP QUERY DASD`: 0123 M01RES, 0124 M01S01, 0125 M01P01, 0126 M01W01,
  0127 VMCOM1, 0128 630RL1.
- Directory source found: **`USER DIRECT` is on minidisk `02CC` (volser
  MNT2CC on VMCOM1), filemode `P`**. Also present on that disk:
  `USER MDISKMAP P` (392 recs, 2026-10-08), `USER DISKMAP P` (356),
  `M173BAK DIRECT P` (4282, 2026-10-08), `M173NEW DIRECT P` (4283, 2026-10-08),
  `M173NEW MDISKMAP P` (394).
- `USER DIRECT` = 4282 F80 records, dated 2026-09-27 18:20:23.
- No `USER DIRECT` on A/F/G/S/T/Y, 0CF1 (CP IPL), 0CF3, 0CFD, 019D/0401/0402
  (only HELPCP files), 0990, 0551, 049E, 0600.
- System has 37 `USER` entries.

## Volume/alloc evidence

`USER MDISKMAP P` (DISKMAP output) reports:

| Volume | Size (cyl) | Full-pack holder | Free gaps |
|--------|-----------:|------------------|-----------|
| M01RES | 10017 | MAINT/CMS1 0123, SYSDUMP1 | 9413–9419 (7), 9440–10016 (577) |
| M01W01 | 3339 | MAINT 0124 | 3331–3338 (8) |
| VMCOM1 | 10017 | PMAINT 0141 | 5936–10016 (4081) |
| 630RL1 | 10017 | MAINT630 0131 | 5959–10016 (4058) |

Every volume also carries a full-pack definition, so the current planner
(`cms_mdisk_plan.py`) fails closed on all of them by design. The direct route
needs an explicit policy decision: treat system full-pack holders
(`DEFAULT`, `CMS1`, `PMAINT`, `MAINT630`, `$PAGE$`, `$SPOOL$`) as overlay
owners, not as exclusive reservation, and rely on DISKMAP gaps plus
`CP QUERY ALLOC` for free extents. That policy change is **not** implemented.

## Blocker

`DIRECTXA` is documented in `DIRECTXA HELPCP` on 019D/0401/0402, but both
`DIRECTXA` and `CP DIRECTXA` return `Unknown CP/CMS command` /
`Unknown CP command`. `CP HELP ...` is also unavailable. Activation method is
unresolved. Options to try next:

1. Check whether `DIRECTXA` must be invoked from a specific service machine or
   with a privileged class/command authorization (CP directory `COMMAND`
   statement or `CLASS`).
2. Search remaining MAINT minidisks (0193, 0990, 0CF3, 0401/0402 full) for a
   `DIRECTXA MODULE` or a wrapper EXEC.
3. Check the CP nucleus/SYSTEM CONFIG for directory utility support.

Do not attempt activation until this is resolved. `M173NEW DIRECT P` (4283,
one extra record vs `USER DIRECT`) shows a prior candidate was built on
2026-10-08; its exact diff and whether it was ever activated are unverified.

## Local artifacts

- `probe_direct_source.py` — removed after the survey; re-create only as a
  disposable scratch probe. It contained no credentials.
- `/tmp/cms-direct/user-direct.txt`, `user-mdiskmap.txt`, `user-diskmap.txt` —
  TYPE captures, mode 600. **`USER DIRECT` contains password material: never
  copy into the repo, never commit, never paste.** Re-download after a reboot.

## Next steps

1. Resolve `DIRECTXA` availability (blocker above).
2. Fetch `USER DIRECT` again and diff `M173BAK`/`M173NEW` to learn what the
   prior candidate changed.
3. Decide the full-pack overlay policy, then extend `cms_mdisk_plan.py` to
   build an inventory directly from the directory text + `CP QUERY ALLOC`.
4. Generate exactly one `MDISK` insertion in the MAINT entry, write a distinct
   candidate file, and run `DIRECTXA candidate (EDIT` only.
5. Stop before non-EDIT activation and before any `FORMAT`.

## Safety

Never modify protected disks, directory entries, or other users without the
exact task authorization. No cleanup or extent release after a failure.
Host success does not prove CMS behavior; report target validation separately.
