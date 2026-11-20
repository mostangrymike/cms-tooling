# OpenExtensions and BFS on the z/VM 6.3 guest

Verified 2026-11-19 on `MAINT AT TACOTICO`
(`z/VM TACOTICO CMS_27_1302_88 CP_6.3.0_1302_84 3931`).

## Verdict

**Installed and working. Nothing to install.** The install is minimal, and two
utilities are unusable because of missing NLS tables.

## How it is reached

| Item | Value |
|---|---|
| Command | `OPENVM EXEC` and `OPENVM SEXEC` on `S2` |
| File pool | BFS `VMSYS`, mounted at `/`, read/write |
| Mount | `OPENVM MOUNT /../VMBFS:VMSYS:ROOT/ /` |
| Shell | `OPENVM RUN /bin/sh -c '...'` (single quotes survive) |
| CMS from shell | `cms <command>` works, e.g. `cms QUERY USERID` |

```
OPENVM QUERY MOUNT
Mount point = '/'
Type  Stat  Mounted
BFS   R/W  '/../VMBFS:VMSYS:ROOT/'

OPENVM RUN /bin/uname -a
z/VM TACOTICO CMS_27_1302_88 CP_6.3.0_1302_84 3931

OPENVM RUN /bin/ls /
bin  dev  etc  home  lib  opt  tmp  u  usr  var
```

`/usr/bin` is empty, `/usr/lpp` is empty, `/etc` holds six files. Everything
ships under `/bin`.

## Utility inventory (`/bin`)

```
command   fg          lp          pwd         time
alias     compress    fgrep       ls          read        touch
ar        cp          find        mailx       red         tr
awk       cpio        fold        make        rm          true
basename  cut         getconf     mkdir       rmdir       tty
bc        cxx         getopts     mkfifo      rsh         umask
bdiff     date        grep        mknod       sed         unalias
bg        dd          head        mv          sh          uname
c89       diff        iconv       newgrp      shbltin     uncompress
cat       diffh       id          nm          sleep       uniq
cd        dirname     jobs        nohup       sort        wait
chgrp     echo        join        od          strip       wc
chmod     ed          kill        paste       stty        xargs
chown     egrep       lex         pathchk     su          yacc
cksum     env         ln          pax         tail        zcat
cmp       expr        locale      pr          tar
cmsfile   false       logger      printf      tee
comm      fc          logname     ps          test
```

Verified working: `sed s/b/X/` on `abc` gives `aXc`; `grep -c` counts 19 in
`/etc/profile.sample`; `diff` reports differences with `RC=1`; `find /bin
-name sed` finds `/bin/sed`; BFS write, read-back, and delete succeed.

## Gaps

| Finding | Detail |
|---|---|
| `iconv` unusable | only the `IBM-1047` charmap; every UTF-8 or ISO8859 conversion fails with error 83. |
| `tar` broken | `filename translation initialization: error 83`; writes a 0-byte archive. |
| Missing tools | `curl wget openssl git jq python perl base64 sha256sum patch timeout ssh` |
| `c89` has no compiler | `DMSWCC616W The C compiler (CBXFINIT) does not exist`; compile on CMS. |
| `cmsfile` | not a converter; it needs an existing external link (`GSU9971`). |
| `OPENVM RUN` parser | `(` starts an option list, so inline C source needs a file. |
| Session scope | each Telnet connection is a fresh CMS IPL; mounts do not survive a disconnect. |

`iconv` and `tar` are not needed for the CMS-to-BFS bridge: `OPENVM PUTBFS`
and `OPENVM GETBFS` translate code pages themselves.

## CMS to BFS and back

`openvm putbfs` and `OPENVM GETBFS` are the converter. Both take a numeric
source and target code page and call no external translator, so the missing
charmaps do not matter.

Two execs are shipped in [`../cms-execs/`](../cms-execs/):

```
CMS2BFS fn ft fm [path]     path defaults to /tmp/<fn>.<ft> in lower case
BFS2CMS path fn ft [fm]     fm defaults to A1
```

They expand to:

```
OPENVM PUTBFS fn ft fm path (REPLACE TRANSLATE 1047 TO 819
OPENVM GETBFS path fn ft fm (REPLACE TRANSLATE 819 TO 1047
```

Verified 2026-11-19 on `MAINT`:

| Case | Result |
|---|---|
| `PROFILE EXEC` (F 80, 24 records) | 1944 bytes; round trip `cmp` clean |
| one 300-column line | CMS record becomes V 300; round trip `cmp` clean |
| missing CMS file | `DMSOVH1184E`, RC 28 |
| missing BFS file | `DMSOVH2113E Object does not exist`, RC 28 |

### Rules that bite

- Code pages must be numeric. `1047` and `819` work; `1208` (UTF-8) fails with
  `DMSOVH639E Error in PIPE routine; return code was 660`, and names such as
  `IBM-1047` are rejected with `DMSPCL395E Invalid number`. Non-ASCII text
  therefore needs our own table, not this option.
- `TRANSLATE` is not implied. A variable-format CMS file is copied byte for
  byte, so without it the BFS file holds EBCDIC.
- Pass a full file mode (`A1`). `GETBFS ... LNG TXT A` produced `LNG TXT A0`.
- Fixed-format padding survives: an 80-column record becomes 81 bytes, 80
  characters plus newline. Strip it on the BFS side if a tool cares.
- Text only. A CMS MODULE does not round trip: record boundaries are lost, and
  a `NOTRANSLATE` copy did not compare equal. Move binaries with FTP.
- `od -c` and console `cat` misreport some characters here (same NLS gap).
  Trust `od -An -tx1` and `cmp`, not the pretty printer.
- Command help: `HELP OPENVM PUTbfs` / `HELP OPENVM GETbfs`.

## Building a MODULE from BFS source

A source file that lives in BFS (where `sed`, `grep`, `make`, `diff` can work
on it) is built with one command. `cms-execs/MKMODULE.EXEC` stages the file
onto CMS and runs the site build exec `CMSCLNK` on `F`:

```
MKModule name path [NAPI|PLAIN]
```

`name` is the CMS file name, at most 8 characters. The staged source becomes
`name C A1`, the listing `name LISTING A1`, and the output `name MODULE A1`.
`PLAIN` is the default and links only PDPCLIB. `NAPI` also assembles
`GITCAPI` and `GITINFA`, which are not part of the base install: without them
`CMSCLNK` stops at `DMSASM002E File GITINFA ASSEMBLE not found`.

`CMSCLNK` on `F1` is the existing driver: `GCCE` (compile to ASSEMBLE),
`ASSEMBLE`, `LOAD`, `GENMOD`. It builds from the `A` disk, which is why the
source is staged there rather than compiled in place.

Verified 2026-11-20:

| Case | Result |
|---|---|
| `S2SED C` (2648 records) staged, then built | `built S2DEF MODULE mode PLAIN`; module runs |
| 186-column comment line | compiles and links |
| 163-column string literal | compiles and links |
| 190-character identifier | `IFO026 CHARACTERS APPEAR BETWEEN THE BEGIN AND CONTINUE COLUMNS ON CONTINUATION CARD`; assembly fails, RC 16 |
| missing BFS source | `DMSOVH2113E`, RC 28 |
| empty BFS source | `DMSOVH173E Empty output file ... not created`, RC 40 |
| C syntax error | `CMSCLNK: C compile failed`, RC 12 |

So record width is not the limit: a long line survives staging and compiles.
The limit is the assembler card, so keep *identifiers* short; long comments and
string literals are fine.

A built MODULE stays on CMS. It cannot be copied to BFS: `GETBFS` drops record
boundaries and the result does not compare equal.

### Gotcha

`'CMSCLNK' name` inside a REXX exec fails with `RC(-3)` even though the same
name runs from the CMS prompt. Use `'EXEC CMSCLNK' name`, the same fix as
`EXEC OPENVM`.

## Logon integration

`PROFILE EXEC A` on MAINT mounts OE at every logon. Original preserved as
`PROFILE EXECSAV A`; restore with `COPYFILE PROFILE EXECSAV A PROFILE EXEC A`.

```rexx
/* Mount the OpenExtensions BFS root (VMSYS) at / for this session. */
'SET CMSTYPE HT'
'EXEC OPENVM MOUNT /../VMBFS:VMSYS:ROOT/ /'
omrc = rc
'SET CMSTYPE RT'
if omrc = 0 then do
  'EXEC OPENVM SET DIRECTORY /'
  if rc = 0 then say 'PROFILE: OE mounted at /'
  else say 'PROFILE: OE mounted, SET DIRECTORY RC' rc
end
else say 'PROFILE: cannot mount OE root RC' omrc
```

Observed at logon:

```
RESTORE: LINK 0592 OK
RESTORE: T = TCPMAINT 0592
RESTORE: G = 600 (GIT600)
PROFILE: F = GCCLIB 29D
PROFILE: OE mounted at /
```

### Why `EXEC OPENVM` and not bare `OPENVM`

Bare `'OPENVM MOUNT ...'` inside a REXX exec fails with `RC(-3)`, command not
found, even though `STATE OPENVM EXEC S2` returns 0 and the same command works
at the CMS prompt. `EXEC OPENVM` resolves in both places. Use the `EXEC` form
in profiles and other execs.

## Re-verify in one session

```
OPENVM QUERY MOUNT
OPENVM QUERY DIRECTORY
OPENVM RUN /bin/sh -c 'echo OK; uname -a'
```

All three must answer without a manual mount once `PROFILE EXEC` carries the
block above.

## Upload note

Replacing a CMS file needs `GET ... (REPLACE`. The helper's
`ERASE PROFILE.EXEC.A1` fails with `DMSJED1223E There is no default file pool
currently defined` because CMS routes dotted names into BFS.
