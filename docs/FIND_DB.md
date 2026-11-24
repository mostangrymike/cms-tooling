# FIND: filename database across minidisks

`FIND` searches every file name on every attachable minidisk defined in the CP
directory, without knowing which minidisk holds it.

Two pieces live on `MAINT`'s A disk (`191`):

| File | Purpose |
|---|---|
| `FINDBASE DATA A` | One record per file: `userid vdev filename filetype filemode records date` |
| `FIND EXEC A` | REXX search over that database (`*` and `?` wildcards) |

## Using it

```
FIND PROFILE            search filename PROFILE, any filetype
FIND *.EXEC             all EXEC files anywhere
FIND DVH*.EXEC          wildcards on both fields
FIND M?N*.*
```

Output is `userid vdev filename filetype filemode records`; the last line
reports how many records were searched. A full-database pass over ~117,000
records takes about 40 seconds on this guest. `EXECIO ... (STEM` returns
rc 2008 on this CMS level, so `FIND` reads the file in 2,000-record chunks off
the program stack instead.

## Rebuilding the database

1. Copy the active CP directory source off `MAINT 02CC` (it is `CANDFIN DIRECT`
   in this system) to the host with the CMS FTP client.
2. Scan:

```
python3 cms_find_index.py --directory candfin.direct --state findscan.json \
    --database findbase.data
```

3. Install onto the A disk:

```
python3 cms_find_index.py --install --database findbase.data --find-exec FIND.EXEC
```

`cms_find_index.py` reads `USER` and `IDENTITY` statements: identities are real
user IDs, so `MAINT` is an identity of `USER MAINT630` and owns its own MDISKs.
Disks defined in an `IDENTITY` other than the one the directory actually built
are probed too; the link fails and is recorded as `link-failed`.

## Scan results (2026-11-22)

| Result | Count |
|---|---|
| MDISK definitions in the directory source | 341 |
| Minidisks attached and listed | 267 |
| `link-failed` (`not in CP directory`, template entries) | 3 |
| `access-failed` (`DMSACP112S device error`, CP-owned/dummy disks) | 71 |
| Files recorded | 117,397 |

Per-disk results and errors are kept in the resumable state file
(`findscan.json`); a rerun skips disks already recorded.

## Notes and limits

- Only owned `MDISK` definitions are scanned. `LINK` statements (for example
  `LINK MAINT 190 190 RR`) point at another user's minidisk, which is covered
  by that owner's entry.
- Disks that another virtual machine holds read/write cannot be linked
  read-only; they appear as `link-failed` and need a rerun while the owner is
  logged off.
- `CMSAWK` and `CMSED` are present on the A disk and can filter the database
  (`CMSAWK SCR AWK A FINDBASE DATA A`), but the installed `CMSAWK` module ends
  a run with `DMSABE141T Exponent overflow exception`, so `FIND` uses REXX.
