# CMSAWK handoff

## Published version

- GitHub repo: `mostangrymike/cms-utils`, branch `cms-awk`.
- Current commit: `b3aec58d49d66604ff8c5101a3ad86be2951ce75` (v0.7), parent
  `a6a91404ec3dccfe6dfdafc1b7a697c1be928a6f` (v0.6).
- GitHub `main` is unchanged; `cms-awk` contains only `cmsawk.c`.
- Canonical CMS source: `CMSAWK C A1` (v0.7). `CMSAWK MODULE` rebuilt.
- Source blob: `17477BD69DAEE5271CADBA9842243EDDECCF6CA3`, 111742 bytes.
  GitHub API blob bytes were verified identical to `cmsawk-v07-draft.c`.
- v0.6 source blob: `2841899931F818093DEF6BBDECC80DC158DE15A4`.
- CMS G `main` worktree is clean; `cms-awk` ref tracks v0.7.

## v0.7 changes

- `^` exponentiation; right-associative, and exponentiation binds tighter than
  unary signs (`-2 ^ 2` is `-4`). Uses the existing approximate exp/log
  routines; negative bases with integral exponents are supported.
- Regex literals can appear as primaries, including in function arguments:
  `match(s, /re/)`, `gsub(/re/, ...)`, or a boolean expression such as
  `($0 ~ /re/)`.
- Numeric `printf`/`sprintf` zero padding is restored when PDPCLIB's formatter
  ignores the `0` flag.
- Pipes are not yet implemented in CMSAWK. CMS Pipelines is present: `PIPE
  MODULE` is on read-only minidisk 0490, and the CMS Samples disk 0193 contains
  the `PIPES` segment. The public POPEN VMARC package provides `FPLPOP TEXT`
  and `FPLPOP H`; these were installed on A1 and `TXTLIB MAP FPLPOP` confirms
  the FPLP entry points. Its packaged `CPOPEN MODULE` reads multiple records
  successfully.
- The GCCCMS/PDPCLIB build uses the 24-bit S/370 calling environment, while the
  POPEN interface returns pipeline record buffers above the 24-bit line.
  `CPOPEN MODULE` from the package can read multiple records, but the GCCCMS
  adapter faults on its EOF read even after switching/copying the first
  records. No CMSAWK source or module was changed for pipes. A validated
  31-bit bridge or a compatible 31-bit C runtime is still required.

## Validation

- Host: `gcc -std=c89 -Wall -Wextra -Werror` clean.
- CMS: `CMSCLNK CMSAWK PLAIN` completed; T1–T6 outputs match the host run.
- Regression tests live in `cmsawk-tests/`; all source lines are at most 80
  columns (`FIXRECFM 80` otherwise truncates during FTP transfer).
- Publishing used `WRITE-WORKFILE`, `WRITE-TREE`, `COMMIT-TREE`,
  `UPDATE-REF SET-REF`, then `GIT PUSH`; `GIT SWITCH cms-awk` remains blocked
  by the unrelated worktree preflight error
  `GITWT: path component is absent at level 1`.

## Resume

1. Continue from `cmsawk-v07-draft.c` and `cmsawk-tests/`.
2. Finish a 31-bit/24-bit bridge for FPLPOP (or provide a compatible 31-bit C
   runtime); use read-only PIPE module source on 0490 and the installed
   `FPLPOP TXTLIB A1`.
3. Build and run the CMS differential suite before publishing subsequent work.
