# Native CMS tooling for agent work

Verified 2026-11-23 on `MAINT AT TACOTICO` (z/VM 6.3.0, CMS 27 SL 1302).
This page records which layer to use for which job, and the CMS behaviours that
silently break tools written as if this were Unix.

## Three layers, one rule

| Layer | Reach | Use when |
|---|---|---|
| **CMS native** (`REXX`, `EXECIO`, CMS Pipelines, `XEDIT`, `COPYFILE`) | any accessed minidisk, any filemode, no mount, no code page | the file is a CMS file and you want to edit it in place |
| **OpenExtensions** (`OPENVM RUN /bin/sh -c '…'`) | BFS files only, under a mounted `/` | you need a real shell tool (`grep -n`, `diff`, `sort`, `make`) and the file is already in BFS |
| **Host FTP** (`cms_ftpput.py`) | CMS ⇄ host, one whole file at a time | bootstrap: moving a file that does not exist on the guest yet |

OE cannot edit a CMS file. It sees only the BFS, so a CMS file must be copied
into BFS (code-page translation, 80-column padding) and copied back. For an
in-place edit that is four steps and two chances to corrupt the file; the native
path is one command.

## Inventory

| Job | Use | Notes |
|---|---|---|
| find a file by name | `FIND fn[.ft]` | `FINDBASE DATA A`, 117,397 files from every attachable minidisk |
| find text inside files | `GREP pattern [fn [ft [fm]]]` | native, in place, no BFS copy |
| apply an edit | `PATCH fn ft fm hunkfn hunkft hunkfm` | native, backup, refuses ambiguity |
| diff two CMS files | `COMPARE f1 f2` / OE `diff` | `COMPARE` is native and byte-exact |
| read a file | `TYPE fn ft fm`, OE `cat` | |
| shell pipeline | CMS Pipelines: `PIPE < fn ft fm \| locate /PAT/ \| console` | stages: `locate`, `xlate`, `spec`, `sort`, `count`, `take`, `stem`, `var` |
| list files | `PIPE CMS LISTFILE fn ft fm \| stem F.` | gives `F.0` and one `fn ft fm` per record |
| build C | `MKMODULE.EXEC`, `CMSCLNK`, `GCC370` | toolchain on `MAINT 29D`; `c89` in OE has no compiler |
| batch job | `CMSBATCH` (class G, defined, not logged on) | submit work without holding the one Telnet line |
| transfer | `cms_ftpput.py` | anonymous FTP, host staging directory |

OE gaps worth remembering (`docs/OE_BFS.md`): no `patch`, `git`, `jq`,
`base64`, `sha256sum`, `curl`; `tar` is broken; `c89` has no compiler.

## Exit-code contract

Every tool here exits with a code that means the same thing, so an agent can
branch without parsing prose.

| Code | Meaning |
|---|---|
| 0 | did the work; something matched or was applied |
| 1 | `GREP` only: ran fine, nothing matched |
| 4 | usage error |
| 8 | `PATCH` only: ambiguous match, **nothing written** |
| 12 | `PATCH` only: hunk not found, **nothing written** |
| 20 | bad input, no files matched, or read error |
| 28 | file not found |
| 40 | write failed; original left alone where possible |

From inside a REXX exec, invoke another exec as `'EXEC name'`; a bare
`'name'` returns `RC(-3)` even when `STATE name EXEC` finds it.

## CMS behaviours that break Unix-shaped tools

Each of these was hit and confirmed on this guest; all of them fail *quietly*
or with a misleading message.

| Behaviour | Symptom | Rule |
|---|---|---|
| No compound variable with an expression | `DMSOPN062E Invalid character . in fileid RXA. MODULE`, then `Error 40 Incorrect call to routine` | `t.(p+j)` is parsed as a function call. Compute the index into a variable and use `t.q` |
| A stem cannot index by its own stem | `ho.h.ho.h` becomes `ho.1.HO.1` and reads as the literal name | compute the count first: `c = ho.h + 1` then `ho.h.c = …` |
| `EXECIO n DISKW` always appends | rewriting a 6-record file with 2 records leaves 8 | never rewrite in place; write a temp file |
| `EXECIO 0 DISKW … (FINIS` does not truncate | file keeps its old records | `STATE`/`ERASE` the temp first |
| Writes stay invisible until closed | `COPYFILE` says `INPUT file … not found` right after a successful `DISKW` | finish with `'EXECIO 0 DISKW fn ft fm (FINIS'` before using the file |
| Leftover stack records are executed | `Unknown CP/CMS command` after the exec ends | drain with `do while queued() > 0; parse pull; end` |
| `EXECIO … (STEM` fails here | `RC 2008` | read chunks with `EXECIO 2000 DISKR` + `queued()`, as `FIND` does |
| `=NAME` is not a valid filetype | `DMSPCL389E Invalid filetype: =PTCH` | use a real 1-8 character filetype (`PTCHTMP`) |
| `COPYFILE` takes `fn ft fm fn2 ft2 fm2` | `DMSCPY048E Invalid filemode BAK` when a filetype was meant | the backup is `fn BAK fm`, not `fn ft BAK` |
| `RENAME` will not overwrite | `DMSRNM024E File … already exists` | `ERASE` then `RENAME`, or `COPYFILE (REPLACE` |
| EXECIO writes variable-format records | an `F 80` file becomes `V` after a rewrite | expected; `V` also preserves lines over 80 columns |
| CMS command chatter | `DMSSTT002E File … not found` from a probe | wrap the probe: `SET CMSTYPE HT` … `SET CMSTYPE RT` |

## `PATCH`

```
PATCH fn ft fm hunkfn hunkft hunkfm [(CHECK] [(FIRST] [(ALL]
```

A hunk file holds `-old` lines followed by `+new` lines; `*` lines and blank
lines separate hunks. Matching is exact after trailing blanks are stripped, so
express an insertion by repeating its anchor:

```
-    rrc = result
+    /* DISABLED: DirMaint phase 2 */
+    rrc = 0
```

Guarantees:

- one hunk matching twice is an error (RC 8), not a guess; `(FIRST`/`(ALL)`
  opt in;
- nothing is written unless every hunk matched;
- `fn BAK fm` holds the previous content (`OLDDATE`, original timestamp);
- the new text goes to `fn PTCHTMP fm`, is closed, then `COPYFILE (REPLACE)`s
  the target, so a failed write leaves the target intact.

Verified 2026-11-23: `(CHECK` predicted `6 → 7` records without touching the
file; apply produced the expected text and a `PTEST BAK A` copy; the duplicate
line produced RC 8 with the file unchanged; the missing anchor produced RC 12; a
two-hunk delete+insert produced RC 0 and `7 → 8` records; re-running the same
patch produced RC 12; `(ALL` changed both occurrences and kept the record count.

## `GREP`

```
GREP pattern [fn [ft [fm]]] [(I] [(LIMIT n] [(FILES]
```

Defaults are `* * *`; `fm=*` searches every accessed minidisk. Output is one
line per hit, `fn ft fm line: text`. `(I` folds case, `(LIMIT n` defaults to
100, `(FILES` prints only file IDs.

Verified 2026-11-23: case-sensitive hit and miss, `(I`, `(FILES`, `(LIMIT`;
a 117,397-record `FINDBASE DATA A` scan returned three hits in 0.47 s.

## Deliberately not built

`bash`/coreutils, `perl`, `python`, a second editor, a VFS, a package manager,
or a re-implementation of OE. `XEDIT` macros are already REXX: that is the
editor API and it does not need replacing.
