# Removing DirMaint from the CP directory

Verified 2026-11-23 on `MAINT AT TACOTICO` (z/VM 6.3.0, service level 1302).
This page records the phases, the exact commands, and what is still held for
operator approval.

Current state: **phases 1–4 done.** The candidate was activated on
2026-11-23 with explicit operator approval.

## Why

The system runs DirMaint as the directory owner, but no DirMaint server is
logged on and `Call Dirm` in `AUTOLOG1`'s profile cannot get one started on
this system (no SSI cluster, no SMAPI setup willing to do it). Directory
maintenance goes back to the plain CP source directory on `MAINT 02CC`.

## Phases

| Phase | Action | State |
|---|---|---|
| 1 | Audit what actually references DirMaint | done |
| 2 | Stop the `AUTOLOG1` profile from autologging DirMaint/DIRMSAT | **done 2026-11-23** |
| 3 | Build and syntax-check a candidate directory without the DirMaint user IDs | **done 2026-11-23** |
| 4 | Activate the candidate with `DIRECTXA` (no `EDIT`) | **done 2026-11-23** |

## Phase 2: `AUTOLOG1 191 PROFILE EXEC`

`Call Dirm` / `rrc = result` are commented out and `rrc = 0` is set, so a
failed-for-good Dirm does not fail the profile.

```
LINK AUTOLOG1 191 291 WR
ACCESS 291 B
COPYFILE PROFILE EXECNEW B PROFILE EXEC B (REPLACE
COMPARE PROFILE EXEC B PROFILE EXECNEW B      /* silent = identical */
ERASE PROFILE EXECNEW B
CP DETACH 291
```

- Live file: `PROFILE EXEC` 220 records, 11/23/26 19:43.
- Rollback: `COPYFILE PROFILE EXECP2 B PROFILE EXEC B (REPLACE OLDDATE`
  (`PROFILE EXECP2`, 218 records, 9/14/26 14:09:42, is byte-identical to the
  pre-change file).
- `PROFILE EXECSAV` (217 records) untouched.
- Downloaded after the swap and compared byte-for-byte with the staged
  payload: identical.
- Effect lands at the next IPL; nothing changes at run time today.

## Phase 3: candidate directory

Source: `MAINT 02CC` `CANDFIN DIRECT` (4284 records, 11/20/26 16:03:45).
Candidate: `CANDNODM DIRECT` on the same disk, 4023 records.

Removed USER entries, with their `LINK`, `MDISK` and commented stubs:

- `DIRMAINT` (server)
- `DIRMSAT` (satellite)
- `DATAMOVE` (DirMaint's file transfer machine)
- `6VMDIR30` (DirMaint service machine for VMSES/E)

No other entry links any of those user IDs, so the removal is self-contained;
`DIRECTXA` would have reported a missing target otherwise. A header comment on
`CANDNODM DIRECT` states the derivation, the removals, and that the active
directory is untouched.

Validation:

```
ACCESS 2CC C          /* source and candidate */
ACCESS 551 D          /* PMAINT 551 holds DIRECTXA MODULE */
DIRECTXA CANDNODM DIRECT C (EDIT
```

Result: `z/VM USER DIRECTORY CREATION PROGRAM - VERSION 6 RELEASE 3.0`,
`EOJ DIRECTORY NOT UPDATED`, no diagnostics, 0.64 s.

`DIRECTXA` is **not** a CP command on this system: `CP DIRECTXA` and a bare
`DIRECTXA` both answer `Unknown CP/CMS command`. The module lives on
`PMAINT 551` (and `PMAINT 550`), so the disk has to be accessed first.

## Phase 4: activation

Run on 2026-11-23 after explicit operator approval:

```
ACCESS 2CC C
ACCESS 551 D
DIRECTXA CANDNODM DIRECT C
```

Observed: `z/VM USER DIRECTORY CREATION PROGRAM - VERSION 6 RELEASE 3.0`,
`EOJ DIRECTORY UPDATED AND ON LINE`, `HCPDIR494I User directory occupies 55
disk pages`, RC 0.

Post-checks: `CP LINK DIRMAINT 191 299 RR` and `CP LINK DATAMOVE 191 299 RR`
both returned `HCPLNM053E ... not in CP directory`. `QUERY USER` for the four
removed IDs returns `HCPCQU045E ... not logged on` (not logged on, and no
longer defined).

Rollback: activate `CANDFIN DIRECT` again with `DIRECTXA` (same disks
accessed). `CANDFIN DIRECT` is still on `MAINT 02CC`, unchanged.

## Do not

- Do not reuse or release DirMaint-owned extents as part of this change.
- Do not edit `CANDFIN DIRECT` in place; always derive a new candidate.
- Do not reuse or release DirMaint extents as part of this change.

## 2026-11-26 — restore the GIT600 minidisk definition

### Root cause

The active directory matched `CANDGD DIRECT C`: `WEBCONS` existed with privilege
classes `DEG`, while `CP QUERY MDISK USERID MAINT 0600 DIRECTORY` returned
`HCPQMD040E`. Diffing every `* DIRECT` file on `MAINT 02CC` showed that
`CANDWEB`, `CANDGE`, and `CANDGD` each removed exactly two MAINT records while
adding `WEBCONS`:

```text
MDISK 600 3390 6000 1600 VMCOM1 W
MDISK 0601 3390 3331 72 M01W01 W
```

`USER DIRECT` and `M173BAK DIRECT` also lacked both. `CANDFIN`, `CANDNODM`, and
`M173NEW` retained the GIT600 record. The loss therefore came from the
web-console candidate change, not the DirMaint removal.

### Recovery performed

1. Copied active `CANDGD DIRECT C` to new backup `CANDGD DRBK26 C`; `COMPARE`
   was silent/identical.
2. Derived `CANDG600 DIRECT A` and used native `PATCH` to insert only the GIT600
   line after the unique `MDISK 29D` anchor. `(CHECK` predicted 4296 → 4297.
3. Normalized to fixed 80-byte records as `CANDGF80 DIRECT A`; `LISTFILE` showed
   `F 80 4297`.
4. Ran `DIRECTXA CANDGF80 DIRECT A (EDIT`: `EOJ DIRECTORY NOT UPDATED`, no
   diagnostics.
5. After explicit approval, ran `DIRECTXA CANDGF80 DIRECT A`:
   `EOJ DIRECTORY UPDATED AND ON LINE`, `HCPDIR494I User directory occupies 58
   disk pages`.
6. Verified `CP QUERY MDISK USERID MAINT 0600 DIRECTORY` returns
   `MAINT 0600 MAINT 0600`, `WEBCONS` remains `DEG`, and a fresh read-only
   link/access exposes `GIT600` with `GITMETA REPO G` and `GIT EXEC G`.

### Rollback and retained artifacts

```text
ACCESS 02CC C
CP LINK PMAINT 551 298 RR
ACCESS 298 D
DIRECTXA CANDGD DIRECT C
CP DETACH 298
```

`CANDGD DRBK26 C` is the byte-identical pre-change source. `CANDGF80 DIRECT A`
is the validated/activated candidate. `CANDFIN`, `CANDNODM`, and `M173NEW`
remain independent older references. `MDISK 0601` was deliberately not restored.
No FORMAT, GIT600 data rewrite, or object deletion occurred.
