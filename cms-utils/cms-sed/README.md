# CMSED 0.4

CMSED is a C89 stream editor for CMS records with a host build for ordinary
paths and standard input. It follows POSIX sed and the common GNU extensions,
with the differences listed at the end.

## Build and run on CMS

Build with GCCCMS:

```
CMSCLNK S2SED PLAIN
```

CMS invocation uses `fn ft fm` triples:

```
S2SED [-n] [-s] [-E] [-e command]
      [-f scriptFN scriptFT scriptFM]
      scriptFN scriptFT scriptFM dataFN dataFT dataFM [...]
```

If no `-e` or `-f` is given, the first triple is the script file. CMS `-i`
stages each result and keeps the original as `S2B#### SEDBAK` on the same
filemode. The `e` command and `s///e` are not available on CMS.

## Host build and run

```
gcc -std=c89 -DCMSED_HOST -o s2sed cmsed.c
s2sed -n -e 's/foo/bar/g' input.txt
s2sed -f script.sed input.txt
s2sed -i.bak -e 's/foo/bar/' file1 file2
```

Host mode reads standard input when no path is given. `-i` writes a sibling
temporary file and renames it only after success; an optional suffix keeps a
backup.

## Options

Short: `-n`, `-s`, `-z`, `-E`/`-r`, `-l N`, `-e`, `-f -`, `-i[SUFFIX]`, `-u`,
`-b`.

Long: `--quiet`, `--silent`, `--expression=`, `--file=`, `--in-place[=]`,
`--line-length=`, `--null-data`, `--separate`, `--regexp-extended`,
`--unbuffered`, `--binary`, `--posix`, `--sandbox`, `--follow-symlinks`,
`--debug`, `--help`, `--version`.

`--sandbox` disables the `e`, `r`, `R`, `w`, and `W` commands and `s///w`, and
exits 1. `--posix` disables the GNU BRE operators `\|`, `\+`, `\?`, and `\{`,
following GNU sed; it does not print GNU's portability warnings.

## Script syntax

- Commands may be separated by newlines or semicolons.
- `{` and `}` group commands, with addresses and `!` on the group.
- `#n` as the first script record enables quiet mode.
- `a`, `i`, and `c` accept one-line text or a backslash followed by one or
  more following script records. Leading blanks before that text are skipped.
- An empty regular expression reuses the last regular expression.

## Commands

- `s/regex/replacement/flags` with `g`, `p`, `w file`, `i`/`I`, `m`/`M`,
  `e`, and a numeric occurrence.
- Replacement text supports `&`, `\1`-`\9`, and the GNU case operators
  `\U`, `\L`, `\u`, `\l`, and `\E`.
- `d`, `p`, `q [code]`, `Q [code]`, `n`, `N`, `P`, `D`
- `=`, `l [width]`, `F`, `z`, `v [version]`
- `y/source/destination/`
- `h`, `H`, `g`, `G`, `x`
- `b label`, `t label`, `T label`, and `:label`
- `a`, `i`, `c`, `r`, `R`, `w`, `W`
- `e [command]` (host only). Without a command, the pattern space is replaced
  by the command output; with a command, the output is written and the pattern
  space is unchanged.

`v` compares against the GNU sed 4.10 feature level, so `v 4.2` succeeds and
`v 5.0` fails with exit code 1.

## Addresses

Line numbers, `$`, `/regex/`, `\c/regex/c`, `first~step`, `addr,+N`,
`addr,~N`, `0,/regex/`, regex `I`/`M` modifiers, `!`, and two-address ranges.
Line numbers are cumulative across input files unless `-s` is used. Very large
line numbers are accepted and simply never match.

## Regular expressions

Basic regular expressions support literals, `.`, `^`, `$`, `*`, `\+`, `\?`,
`\|`, `\{m,n\}`, bracket classes and ranges, POSIX character classes, groups,
backreferences `\1` through `\9`, `\b`, `\B`, `\<`, `\>`, `` \` ``, and `\'`
anchors, and the `\w`, `\W`, `\s`, and `\S` character classes.
Matching is leftmost-longest. `-E`/`-r` accepts extended syntax and translates
it to the same engine.

Malformed intervals, unmatched groups, and out-of-range backreferences in the
pattern or replacement are rejected at script parse time.

On the host build, `.` and bracket classes consume one UTF-8 character when the
input is valid UTF-8, and are byte-oriented otherwise (the C locale model).
Case conversion and `\w` remain byte-oriented, so non-ASCII case mapping is not
performed.

## Input and output

Multiple input files are read as one stream, and `n`/`N` cross file
boundaries. `-s` resets line numbers and ranges per file. `-z` uses NUL as the
record separator. A missing trailing separator is preserved. Carriage returns
are ordinary data on the host build; the CMS build still drops them. Existing
`w`/`W` targets are truncated at startup. Host `/dev/stdout` and `/dev/stderr`
are mapped to the standard streams. A missing `r`/`R` file is silently ignored.

`l` renders control characters as `\a`, `\b`, `\t`, `\n`, `\v`, `\f`, and
`\r`, and on the host build renders bytes above 127 as octal escapes.

## Exit status

Script, usage, and sandbox errors exit 1. An unreadable `-f` file or `w`
target exits 4. An unreadable input file exits 2.

## Limits

Records are limited to 4095 characters, scripts to 1024 characters, commands
to 128, input files to 16, groups to 9, and block nesting to 32. CMS scripts
and inputs are CMS files; host paths and standard input are host-only.

## Differences from GNU sed

- CMS `e` and `s///e` are unavailable because PDPCLIB has no `popen`.
- Diagnostic wording and expression offsets differ; exit codes match for the
  common cases listed above.
- `--debug` is accepted but produces no trace.
- `v` compares against 4.10 as a fixed feature level.
- `--posix` is enforced but does not print GNU warnings.
- Multibyte case conversion and `\w` classification are not implemented.

## Tests

`tests/test.sed`, `tests/test.in`, and `tests/test.expected` cover
substitution, addresses, delete, print, backreferences, and quit. Run on CMS:

```
S2SED S2TSCR SED A1 S2TDATA DATA A1
```

Host regression scripts T1-T3 are in `tests/`.
