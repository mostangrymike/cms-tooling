# CMSAWK v0.7 test suite

Differential tests for `cmsawk-v06-draft.c`: the same sources run natively on
the host and on CMS, and the output must be identical.

Files here use `_` for the CMS blank in the file name (`T1_AWK` is CMS
`T1 AWK`).

## Host run

```sh
gcc -std=c89 -Wall -Wextra -Werror -o /tmp/cmsawk cmsawk-v06-draft.c
cd cmsawk-tests
for f in D1_DATA D2_DATA; do cp "$f" "${f/_/ } A"; done
for t in T1 T2 T3 T4 T5 T6; do
  cp "${t}_AWK" "${t} AWK A"
  /tmp/cmsawk "$t" AWK A D1 DATA A D2 DATA A
done
```

`make_file_id()` builds `fn ft fm` and hands that literal string to `fopen`,
so the host copies need the trailing mode letter in the file name.

## CMS run

Upload each file with the CMS FTP client (`LOCSITE FIXRECFM 80`), then:

```
CMSCLNK CMSA07 PLAIN
CMSA07 T1 AWK A D1 DATA A D2 DATA A
```

## Rules

- Every source line must be 80 characters or fewer. `FIXRECFM 80` truncates
  silently, which produces tests that fail for the wrong reason.
- `\.` is not a valid escape inside a CMSAWK string literal; use `[.]`.
- printf zero padding (`%05.2f`) is not implemented by PDPCLIB; CMS prints
  space padding where glibc prints zeros.

## Coverage

| Test | Covers |
| --- | --- |
| T1 | `ARGC`/`ARGV`, `FILENAME`, `FNR`, `NR`, `NF`, `$0`, `$NF`, multiple input files |
| T2 | ERE alternation, leftmost-longest, POSIX classes, intervals, backreferences, nested groups, `RSTART`/`RLENGTH`, `sub`/`gsub` |
| T3 | arrays, recursion, user functions, `split`, `substr`, `index`, `sprintf`, case conversion, numeric comparison |
| T4 | mutable `ARGV` in `BEGIN` |
| T5 | multi-line `if`/`else`, `while`, `do`/`while`, `continue`, `next`, comments |
| T6 | right-associative `^`, unary precedence, regex literals in expressions and calls, numeric zero padding |
