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
| `cmsfile` syntax | needs the OE Command Reference; CMS-to-BFS attempts fail with `GSU9971`. |
| `OPENVM RUN` parser | `(` starts an option list, so inline C source needs a file. |
| Session scope | each Telnet connection is a fresh CMS IPL; mounts do not survive a disconnect. |

Do not plan on `iconv` or `tar` for the CMS-to-BFS bridge. Translation has to
happen in our own code.

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
