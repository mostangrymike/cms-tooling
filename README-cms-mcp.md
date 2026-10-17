# Local IBM z/VM CMS MCP server

This version provides sixteen tools, including login, startup, arbitrary
correlated CMS command capture, source downloads, general file uploads and local
edit/review plans, over
stdio, using one dedicated persistent s3270 process through py3270. It never
connects or logs in at startup. Login requires a separate enable flag and local
credential file; general terminal input remains independently disabled. Legacy
user pipelines and transfer scripts remain untouched.

## Runtime and registration

From the repository root, create a Python 3.12+ environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-cms-mcp.txt
codex mcp add ibm-cms -- /absolute/path/to/cms-tooling/.venv/bin/python /absolute/path/to/cms-tooling/cms_mcp.py
codex mcp get ibm-cms
```

The absolute interpreter/script paths avoid dependence on Codex's working
directory. `s3270` must be on the MCP process's PATH. The operator-authorized
registration uses `--allow-login --allow-startup --allow-commands
--allow-arbitrary-commands --allow-downloads --allow-local-edits
--allow-create-only-upload --allow-uploads`, plus configured download/upload
roots and the owner-only credential file. Per-tool `approval_mode = "auto"`
applies to command capture, download, upload, and runner preparation. It leaves
`--allow-input` and `--allow-query-links` disabled. A new command helper must be
created with `create=true` and source-verified because the runner source changed.
The registered `tool_timeout_sec` is 360 seconds to accommodate the server's
maximum 300-second command deadline. The configured helper is source-verified
again by `cms_prepare_runner` in every new terminal session.

The TN3270 endpoint is fixed to `127.0.0.1:3271`. The default terminal selector
remains `0200@`. Set server `--device auto` to let Hercules assign an available
terminal, or `--device CODEX@` for an existing terminal group. Groups accept
1..8 alphanumeric characters starting with a letter; specific addresses use four
hex digits followed by `@`. `cms_connect(device=...)` can override the configured
default for one connection. No c3270 script listener is used or controlled.

See [PIPELINE-READINESS.md](PIPELINE-READINESS.md) for the exact remaining
production replacement/build gates and the transaction inputs needed next.

The live command, download, login and observation validators also accept
`--device`. A bare `auto` selection can include the Hercules integrated `SYSG`
console, as observed in the live pool smoke test; use a configured terminal group
if automation must be restricted to designated devices. Pool connection and
guest login are separate checks. No terminal groups are created by this tooling.

## Tools

| Tool | Behavior |
| --- | --- |
| `cms_connect(device=None, timeout=10)` | Spawn s3270 using the configured terminal selector, wait for 3270 mode and inspect the guest without typing anything. |
| `cms_screen()` | Atomic saved screen: 24 rows of 80 characters, 1-based cursor, keyboard/format status and field metadata. |
| `cms_status()` | Disconnected status or a fresh screen with heuristic state classification. |
| `cms_send(action, …)` | One validated terminal action; disabled in the initial registration. |
| `cms_login(timeout=30)` | Submit local credentials once into the verified combined form; separate `--allow-login` flag required. |
| `cms_startup(timeout=30, verify_cms=False)` | Continue verified startup; optional fixed read-only CMS verification; requires `--allow-startup`. |
| `cms_prepare_runner(create=False)` | Verify a configured helper, or explicitly create one new unique EXEC when create=true. |
| `cms_command(command, timeout=120)` | Run one CMS command through the correlated runner and return complete native output plus the actual CMS-stage RC. Arbitrary mode has a 108-character limit and reserves `|` and `#` for framing. |
| `cms_query_links(vaddr, timeout=120)` | Submit only the fixed `CP QUERY LINKS` command for one three-digit virtual address through the observed CMS input field; captures pages until a fresh Ready prompt. |
| `cms_download(filename, filetype, filemode, create_runner=False, timeout=300)` | Capture native file records twice, verify CMS metadata, and save a new snapshot in the configured local Git worktree. |
| `cms_edit_prepare(snapshot)` | Validate a local snapshot and create a separate working copy with pinned original bytes and metadata. |
| `cms_edit_plan(edit_id)` | Validate local changes; write a full diff, native candidate bytes and an unauthorized, review-only upload plan. |
| `cms_operation_plan(edit_id, plan_id, plan_sha256, recipe)` | Pin an existing review to a local replacement/build manifest; report missing inputs, collisions, protected targets and unverified execution gates. Never execute. |
| `cms_upload_create_only(edit_id, plan_id, plan_sha256, target, candidate_sha256)` | Optional live validation: create one absent `ZVxxxxxx EXEC A1` fixed-80 scratch file and require exact native readback. Disabled unless `--allow-create-only-upload` is explicitly added. |
| `cms_upload_file(source_path, filename, filetype, filemode, mode, recfm, lrecl, overwrite_existing)` | Upload one local file beneath `--upload-root` to an exact CMS file ID. Existing files require `overwrite_existing=true`; transfer completion and target presence are checked, but this path does not read back content. |
| `cms_disconnect()` | Terminate/reap this server's process. Never send LOGOFF. Idempotent. |

Fields expose 1-based row/column, zero-based buffer offsets, length, protection,
numeric, modified, empty and nondisplay flags. Empty is determined from the raw
saved screen before masking; no field contents are disclosed. A wrapping field can cover the end and
beginning of the screen. Raw ReadBuffer hex is never returned. Nondisplay fields
are masked position-for-position. After String input, unprotected fields are also
masked to cover partial input on a failed action. If field parsing fails, the screen is fully
masked and the error is exposed, rather than risking credential disclosure.

States are `logo`, `login`, `password`, `cp_read`, `vm_read`, `cms_ready`, `more`, `holding`,
`xedit`, and `unknown`. Classification is heuristic: a Ready prompt may be stale.
Screen/status observations leave `cms_command_complete` null. A successful
`cms_command` sets it true only after verified capture and a fresh wrapper Ready.

After the operator authorizes input, a future registration can add
`--allow-input` to the server arguments. This enables `String`, `Enter`, `Clear`,
`PF(1..24)`, `PA(1..3)`, `Home`, `Tab`, `BackTab`, `EraseInput`, `Reset`, and
`MoveCursor`. There is no arbitrary action/macro/shell/transfer interface.
`String` takes printable ASCII without backslash action escapes and does not
press Enter. Use `number` for PF/PA and 1-based `row`/`column` for MoveCursor.

The `wait` option is `none` or `output`; `output` uses bounded
`Wait(timeout,Output)`, armed by an ASCII read before the action. Host output is
not proof of command completion. `aidWait=false` avoids relying on unlock for
action synchronization. Pipe reads also have deadlines. A failed/ambiguous
operation is not retried; the process is terminated and sanitized screen,
operation trace, error and stderr evidence are returned. A timeout may leave only
the last successfully captured screen available. Explicit reconnection is needed.

Avoid `Snap(Wait,...,Output)` with the installed s3270 4.5ga6: a live passive
observation triggered SIGSEGV in its `snap_save` / `set_output_needed` path on
incoming host output. Ordinary snapshots and `Wait(Output)` remain separate.

## Credentials and operating boundaries

There are no credentials in the new server. All String inputs are treated as
potential secrets for response redaction; password/nondisplay inputs receive
additional token redaction. py3270 raw debug logging is disabled. Diagnostics use
stderr; stdout is reserved for MCP JSON-RPC.

MCP clients can retain tool arguments before server-side redaction. Do not pass
passwords through Codex tool arguments. `cms_login` accepts only a timeout and
loads credentials locally after checking the guest form.

The local file must be a regular, non-symlink, owner-owned file with mode 0600,
at most 4096 bytes, containing only `userid` and `password`. Its directory is
created with mode 0700 by `cms_credentials.py`. Values never enter MCP arguments
or the server launch arguments. To provision interactively outside MCP:

```sh
.venv/bin/python cms_credentials.py --output ~/.config/ibm-cms/credentials.json
```

The utility uses getpass and refuses to overwrite an existing file. The existing
pipeline constants can be imported once with `--import-legacy cms_pipeline.py`;
the importer uses AST constants and never executes the pipeline. The original
legacy file is preserved and still contains its pre-existing credentials.

`cms_login` verifies the established editable fields and nondisplay password
attribute, refuses existing/modified input, checks the target cursor before each
String, and sends Enter only once. It never sends a LOGON command, BEGIN, Clear,
file transfers or CMS commands. It stops on rejection, CP READ, CMS Ready,
MORE/HOLDING, or a bounded timeout. CP READ does not mean CMS is ready. General
`cms_send` stays disabled unless separately authorized and enabled. VM READ is
also a stopping state; it is distinct from CMS Ready and does not trigger Enter.

Never authorize a command that erases/replaces files implicitly. In particular,
the old inventory pipeline's `LISTFILE (EXEC` replaces `CMS EXEC A`. This server
does not invoke it. Input enablement is an operator authorization boundary, not a
CMS command policy engine; enabled terminal input can affect the guest.

## Validation

### Continuous integration

The dedicated repository workflow `.github/workflows/cms-tooling.yml` runs the
offline source build on Ubuntu 24.04 with Python 3.12 and 3.14. It installs
`s3270`, Regina REXX and the pinned Python dependencies, checks parity with
`ci/cms-tooling.yml`, and retains reports and source archives for 30 days.
It uses read-only repository permissions and requires no CMS credentials or
tunnel. It does not invoke any live validator. The production project's native staging workflow remains in `mostangrymike/ibm-sandbox`.

`ci/cms-tooling.yml` is the packaged, reviewed workflow template. Install it at
the repository workflow path only when adding the dedicated CI job. Both copies
must remain byte-identical. Local actionlint validation and a local offline
build do not establish a completed GitHub Actions run; inspect the published
commit's actual CI result separately.

The build report records Python/platform, pinned package versions and runtime
tool paths. Every build independently regenerates the source archive and
requires byte equality before testing the extracted distribution.

Build and validate a portable source package without contacting CMS:

```sh
cd /absolute/path/to/cms-tooling
.venv/bin/python -B build_cms_tooling.py \
  --credential-file ~/.config/ibm-cms/credentials.json
```

The optional credential argument scans distribution inputs for the configured
local password; values are never printed or copied. Omit it on another machine.
The complete build requires installed `git`, `s3270`, `rexx` (Regina), and the
pinned Python dependencies. It fails if a test is skipped. The existing Mac
environment uses Python 3.14; use Python 3.12 or later for the archive extractor.

Each invocation creates a new `builds/build-...` directory with a reproducible
`cms-tooling.tar.gz`, a SHA-256 source manifest inside the archive, and a
`build-report.json`. The builder verifies extracted hashes, runs the full unit
suite from a temporary extracted copy, exercises real stdio MCP with default
and automatic terminal configuration while disconnected, verifies uploads are
disabled, and runs the complete local edit/review demo against a synthetic
snapshot in a temporary Git repository. No guest connection is made.

The distribution uses an explicit source list. Legacy pipelines containing
embedded credentials, local captures, downloaded snapshots, edit workspaces,
caches and prior builds are excluded. They remain on disk. Tests use portable,
sanitized screen fixtures under `fixtures/`, not personal live-evidence files.
The build's temporary review paths are diagnostic only and are discarded after
verification; the earlier live workflow review artifacts remain in `cms-sources`.

```sh
.venv/bin/python -B -m unittest -v test_cms_mcp test_cms_login test_cms_startup test_cms_capture test_cms_commands test_cms_download test_cms_edit test_cms_upload test_cms_link_query test_cms_operations
.venv/bin/python -B validate_cms_mcp.py
.venv/bin/python -B verify_codex_cms.py
```

Unit tests use synthetic/recorded screens, a fake emulator, and one disconnected
local s3270 process. Protocol validation initializes the real MCP stdio server,
checks all fifteen tools and verifies that input/login/startup/commands/link
queries/downloads, local edits and create-only upload remain disabled by default. Codex
discovery validation uses `codex app-server` catalog discovery without a model
turn or any terminal connection. It may require local sandbox approval.

For an authorized download/edit review using the existing helpers:

```sh
cd /absolute/path/to/cms-tooling
.venv/bin/python -B validate_cms_download.py \
  --live --device 0200@ --reader-name ZM02EA0B \
  --credential-file ~/.config/ibm-cms/credentials.json \
  --download-root "$PWD/cms-sources" --output cms-download-workflow-evidence.json
```

Use the returned snapshot directory name for the separate local review:

```sh
.venv/bin/python -B validate_cms_edit.py \
  --root "$PWD/cms-sources" --snapshot snapshot-REPLACE_WITH_RETURNED_ID \
  --credential-file ~/.config/ibm-cms/credentials.json \
  --output cms-edit-workflow-evidence.json
```

The review validates a native no-op round trip, changes only the helper's first
comment record in a new local working copy, and checks the original snapshot,
manifest, candidate hash and plan hash. The returned plan authorizes no upload.
The download reads twice with matching metadata before and after; this checks
consistency without claiming an atomic CMS snapshot.

For separately authorized create-only qualification, `validate_cms_upload.py`
requires `--live-create` with exact edit/plan IDs, plan and candidate hashes,
an absent scratch target, credential file and download root. Add
`--verify-native --reader-name ZM02EA0B` for independent double-read native
verification after transfer readback. It persists every completed stage, stops
on any failed prerequisite and exits unsuccessfully when qualification fails.
The scratch target remains on CMS and is not executed or erased. Do not replay
an upload against a previously created target.

The corrected upload path has passed live qualification for `ZVF69FE6 EXEC A1`,
including native equality for 63 F80 records / 5040 bytes. This does not enable
production replacement or build execution. Both that scratch file and the older
`ZV7C2E91 EXEC A1` remain retained; standard registration still disables uploads.

Local replacement/build review is available through `cms_operation_plan` under
the existing `--allow-local-edits` gate. It binds a changed plan to command-token,
input/output, return-code and marker declarations without running anything.
It revalidates the snapshot, pinned baseline, working file, candidate and diff;
checks output collisions/dependency ordering; reports missing writer/rollback
details; and preserves disabled execution flags even for a complete recipe.
The [recipe contract](PIPELINE-READINESS.md#local-recipe-contract) documents the
JSON fields and the distinction between supplied statements and host evidence.

Validate a local operation review using the same pinned edit/plan values:

```sh
.venv/bin/python -B validate_cms_operations.py \
  --root "$PWD/cms-sources" --edit-id edit-REPLACE_WITH_EDIT_ID \
  --plan-id plan-REPLACE_WITH_PLAN_ID --plan-sha256 REPLACE_WITH_PLAN_SHA256 \
  --output cms-operation-review-evidence.json
```

Omitting `--recipe-file` deliberately reports the missing production inputs.
The offline source build includes an actual MCP operation-review check. For
all tests, including newly added planner cases, use unittest discovery:

```sh
.venv/bin/python -B -m unittest discover -p 'test_cms_*.py'
```

Only with explicit live-connection authorization:

```sh
.venv/bin/python -B validate_cms_mcp.py --live --output cms-live-evidence.json
```

The live validator calls only connect/screen/status/disconnect. It never calls
send. It writes complete sanitized screen/field evidence and disconnects in a
finally block. MCP shutdown also closes the dedicated process.

## Next stage

The endpoint is an SSH tunnel from Mac localhost:3271 to EC2 localhost:3270;
Hercules is running on EC2, not locally. The first live test read its transient
banner before the guest updated the screen. A later passive `Wait(Output)`
observation established the combined z/VM login form. See
`cms-ec2-observation.json`: USERID at row 20 column 17 (8 characters), PASSWORD
at row 21 column 17 (8 characters, nondisplay), COMMAND at row 23 column 17
(123 positions, wrapping). The cursor starts in USERID. No input was sent.
The recorded combined form was originally classified as password, then corrected
to login with an offline regression test; original evidence remains unchanged.

Local credentials and explicit one-shot login are now implemented. For an
authorized live login test, use `validate_cms_login.py --live-login
--credential-file <local-path> --output <evidence-path>`. It disconnects in a
finally block and records sanitized results. Subsequent CMS command execution
needs request-correlated output and actual return codes.
Transfer/build/edit tools need explicit overwrite policy, complete output capture,
record-format handling and verification before enabling autonomous development.

The first authorized live login submitted once and the guest displayed LOGON AT
and z/VM 6.3 banners, then VM READ. The initial login flow timed out because VM
READ was not recognized yet. VM READ support was then added and tested against
that recorded screen offline; no second login or password retry was performed.
The original result is preserved in `cms-login-evidence.json`. CMS Ready has not
been established. The next stage needs an authorized continuation of the startup
prompt before implementing correlated CMS command output and return codes.

`cms_startup` is separately enabled and accepts no command text. It requires the
recorded logon/reconnect marker, exact 139-character input at row 23 column 1,
an unlocked keyboard, a visible input field, and an empty field. It verifies the
cursor and field again before input. It sends one Enter at VM READ, or BEGIN
and Enter at CP READ, at most once per state in a call. It does not clear any
input or perform paging. The recorded blank reconnect boundary after our own
BEGIN may also require an Enter even while the terminal says RUNNING; unrelated
RUNNING/application screens are refused. A Ready observation after fresh host output is distinct
from verifying a CMS command return code. Use `--startup` with the live-login
validator only when this continuation is authorized.

The successful fixed `QUERY CMSLEVEL` diagnostic returned `CMS Level 27, Service
Level 1302` followed by a new `Ready;` prompt. See
`cmslevel-probe-evidence.json`. The registered `cms_startup` tool exposes the
same guarded probe only when `verify_cms=true` is explicitly supplied. Without
that option, it can time out after a bare CMS prompt without claiming readiness.
The probe accepts no command text, verifies the empty input field again, and
executes exactly one QUERY CMSLEVEL. It requires both the level response and a
fresh Ready prompt; it does not assert a captured CMS return code. The successful
live probe used the diagnostic helper and the same Session adapter; the optional
MCP wrapper was subsequently validated offline.

## CMS command capture

Enable `--allow-commands`, establish CMS Ready, then call `cms_prepare_runner`.
With a configured `--runner-name ZMxxxxxx`, preparation downloads and verifies
the existing helper's source against local `ZMCPRUN.EXEC`. It does not upload or
execute an unverified file. Without a configured helper, explicit `create=true`
selects a random ZMxxxxxx name, checks STATE returns RC28, sends with Exist=keep,
and verifies the new source by round-trip download. Helpers are retained; the
server never replaces or erases them. Source changes require a new helper name.

Bootstrap STATE refuses input if the same command echo remains visible from a
previous request: that echo and its Ready RC cannot establish fresh completion.
The server does not clear the screen or retry automatically to bypass this guard.

The remote absence check and unique name are the host-side overwrite guard;
x3270's Exist=keep check protects local receive destinations and is not an atomic
host create operation. Do not concurrently create files in this reserved helper
namespace. Transfers temporarily enable AidWait so the emulator reports transfer
completion. They then wait for a fresh CMS Ready and an empty command field;
transfer completion alone does not establish terminal readiness. Each transfer
also positions and verifies the input cursor. Terminal actions otherwise keep
AidWait disabled.

`--allow-arbitrary-commands` removes the allowlist while preserving complete
nonce-correlated output capture and the actual CMS-stage return code. Commands
must be one printable ASCII line of at most 108 characters. `|` and `#` are
reserved by the capture runner as pipeline and CMS logical-line delimiters.
Commands that enter a full-screen interface, wait for input, or end the session
cannot return a complete capture and fail without retry. Generic terminal input
remains disabled. Calls to `cms_command` are configured for automatic execution.

The helper captures CMS Pipeline records in a REXX stem and saves RC immediately
after the CMS stage. It sends a manifest, per-record lengths, native EBCDIC data
chunks, and an end marker. Every frame has a fresh request nonce and sequence
number and waits for an exact acknowledgement. Python verifies the complete
record count, total bytes and Adler-32 checksum before returning records and RC.
It then verifies the wrapper returned to a fresh Ready after the last frame.
The wrapper's own successful return is distinct from the captured command RC.
A nonzero command RC can be a complete, valid result.

The data path preserves duplicate/empty records and trailing blanks. Native
bytes use cp037 for text decoding. Known credentials are redacted only after
integrity verification; `redaction_applied` identifies changed text, and byte
counts/checksum describe the original records. Encoded data frames are masked in
diagnostic screenshots as well. Asynchronous CP messages outside the CMS stage
are diagnostic screen evidence rather than command response records.

No host output files are created. On MORE/HOLDING the driver captures the current
frame and advances paging under protocol control; there are no timed scrolling
loops. Captures exceeding 4096 records, 4096 bytes per record or 1 MiB total fail
explicitly. Missing, conflicting, truncated, reordered or checksum-invalid frames
cannot produce `output_complete=true`. A timeout terminates the local terminal;
the helper may still be waiting for acknowledgement on the guest. Such an
interrupted helper is not treated as a shell and is not retried automatically.

The default command timeout is 120 seconds (maximum 300); the Codex tool timeout
must accommodate that bound. Live validation is explicit:

```sh
.venv/bin/python -B validate_cms_commands.py --live --create-runner --credential-file ~/.config/ibm-cms/credentials.json --output cms-command-evidence.json
```

For subsequent runs, pass `--runner-name ZMxxxxxx` instead of `--create-runner`.
The validator runs only the successful CMS-level query, a random missing-file
STATE expecting RC28, QUERY DISK and LISTFILE * * A. A real local Regina REXX test
also exercises framing, checksums and acknowledgements offline, with only the
CMS-specific capture statement replaced by synthetic records.

The interrupted initial upload was canceled by one Clear on a verified blank,
unformatted screen; CMS reported transfer cancellation and a fresh Ready.
Candidate `ZM6360C6 EXEC A` may be partial and remains untouched/unverified.
A new helper, `ZM537EF1 EXEC A`, uploaded successfully. A second observed race
required waiting for CMS to restore its command field after DFT completion;
the corrected download then verified the helper source before execution.
Live captures passed for QUERY CMSLEVEL (RC0), missing-file STATE (RC28), and
QUERY DISK (RC0), plus LISTFILE * * A (345 records, RC0). All captures verified
complete native records, checksums and fresh wrapper Ready. See
VALIDATION-cms-mcp.md for complete current results and
the recorded evidence. No IPL, LOGOFF, erase or replacement was performed.

## Verified source snapshots

`--allow-downloads --download-root <absolute-directory-in-a-Git-worktree>`
enables `cms_download` alongside `--allow-commands`. No filesystem changes or
terminal connections occur at server startup. The configured root can be a new
subdirectory of this repository's existing working tree; no Git staging,
committing or branch changes are performed.

The separate `ZMCPGET.EXEC` reader supports only internally generated FILEMETA
(read-only LISTFILE LABEL) and FILEREAD (CMS Pipelines disk input) operations.
Existing command-helper source is unchanged. Initial explicit
`create_runner=true` creates a new unique reader EXEC and verifies it by download;
later runs configure `--download-runner-name ZMxxxxxx` and verify that source
again. No existing helper or source file is replaced or erased.

Each download pins the numeric CMS filemode, captures native records twice, and
compares all bytes, record boundaries and before/after LISTFILE metadata. Each
capture also checks the existing framing, checksum and CMS RC protocol. This is
a consistency check, not an atomic snapshot against other guest writers.
Fixed and variable records are represented without text-mode transfer conversion;
empty records, duplicate records and trailing blanks are retained. Limits are
4096 records, 4096 bytes per record and 1 MiB total, with a 300-second overall
download deadline. Source with locally known credential values is not exported.

A new `snapshot-<random-id>` directory contains `records.ebcdic`, a manifest with
CMS identity/RECFM/LRECL/date/disk label, record lengths, SHA-256 hashes and capture
evidence, plus UTF-8 `FILENAME.FILETYPE` when every record is printable text.
Text preserves trailing blanks and uses one LF per record. The native file and
manifest remain authoritative for round trips. Downloads refuse symlink paths,
non-Git destinations and existing snapshot collisions. No overwrite option is
provided. Literal file IDs exclude # to prevent CMS line-separator injection.

Explicit live validation downloads only the already verified command helper and
compares all native bytes with the known local fixed-80 source:

```sh
.venv/bin/python -B validate_cms_download.py --live --create-reader --credential-file ~/.config/ibm-cms/credentials.json --download-root /absolute/path/to/cms-tooling/cms-sources --output cms-download-evidence.json
```

For reader reuse, replace `--create-reader` with `--reader-name ZMxxxxxx`.

Actual live source validation passed using reader ZM02EA0B: the downloaded
ZM537EF1 EXEC A1 contained 63 fixed-80 records (5040 native bytes), matched on
both reads and matched every byte of the known local source. The saved snapshot
is under `cms-sources/snapshot-76f5d418b1716af321b80c94`. Variable records have
offline coverage but have not been validated live. See cms-download-evidence.json.

## Local editing and review plans

Enable `--allow-local-edits --download-root <configured-snapshot-root>`. The
local tools work without connecting or logging in. A configured local credential
provider is loaded for redaction even when no guest session exists.

1. Call `cms_edit_prepare` with a generated `snapshot-<24-hex>` identifier. It
   verifies the snapshot's native bytes, metadata, lengths and hashes, then
   creates a new `edits/edit-<24-hex>` workspace. The original snapshot remains
   intact. Baseline bytes, the original manifest and their hashes are pinned.
2. Edit only the returned `working/FILENAME.FILETYPE` with normal Codex CLI
   file tools. Fixed-record text omits visual trailing padding; planning restores
   native blanks to the original LRECL. Variable records retain trailing blanks.
   Every record must end with LF. Empty text means zero records; one LF means
   one blank record. Tabs are preserved as native bytes, never expanded.
3. Call `cms_edit_plan(edit_id)`. It rechecks the source snapshot and baseline,
   validates strict cp037 encoding and original width limits, and writes a new
   plan directory containing `candidate.ebcdic`, complete `source.diff` and
   `plan.json`. The plan binds original metadata and record lengths, original
   and proposed hashes, edited-text hash, record changes and required future
   upload checks. Earlier plans are retained.

The tools reject changed baselines, symlink artifacts/parents, path arguments,
credentials, binary/control-containing text, ambiguous line endings, record
overflow and unencodable characters. They never truncate or silently substitute
characters. V-record maximum length can shrink after editing; it cannot exceed
the original LRECL. Original local manifests are integrity-checked, not signed
proof of remote provenance. Later host writes need fresh native revalidation.

Plans always declare `upload_implemented=false` and `upload_authorized=false`.
The separate create-only validator accepts only a changed fixed-80 plan and
requires the exact plan hash, candidate hash and disposable `ZVxxxxxx EXEC A1`
target in one explicit tool call. It checks `STATE` for absence immediately
before sending, then uses IND$FILE `Exist=keep` and reads back the file for native
byte equality. The tool does not remove the scratch file. Its serialized
check/write sequence cannot stop another CMS session from racing to create the
same target; `Exist=keep` makes that transfer fail if the target exists when the
host handles it. It does not support V records or build/test execution. General
`cms_upload_file` supports ASCII and binary IND$FILE sends from a worktree-bounded
local path to an exact CMS file ID. It checks CMS `STATE` immediately before
transfer; an existing target requires the explicit `overwrite_existing=true`
parameter. It checks that the target exists after transfer, but does not claim
native content readback. Transfers are configured for automatic execution
without a per-call approval prompt. The precheck is not atomic against other CMS
sessions, and a failed send may leave a partial target. The fixed-80 plan-based
tool remains available when native readback verification is required.

The live validated source is on a CMS minidisk (A1 / label MNT191). IBM's CMS
documentation warns that CMS does not protect a minidisk from data loss when
multiple users have write access, and that concurrent writers must not update
it. A fresh two-read source comparison only proves a point-in-time consistency
check; it cannot reserve the disk or prevent a writer racing the next operation.
Therefore a production replacement must still be separately planned and scoped
to the exact target, storage ownership and writer-exclusion procedure. The
general CMS upload tool itself is available without per-call approval, but the
tool's existence does not prove a minidisk lock. For minidisks, replacement
requires an operator-verified quiescent disk and appropriate CP link
mode/ownership checks; `QUERY LINKS` alone is evidence, not a lock. If the source
is moved to SFS, use SFS file locking and an explicit commit/rollback design. A
production replacement should stage and verify the candidate, preserve a native
backup, compare exact original metadata and bytes immediately before commit,
then perform complete readback and build/test checks.
No atomic compare-and-swap or host rollback guarantee is currently implemented.

Live scratch validation created `ZV7C2E91 EXEC A1` from the approved candidate.
The first ASCII DFT readback omitted fixed-record padding and caused a false
negative; a separate native download verified all 63 F80 records (5040 bytes)
match the candidate hash exactly. The scratch file remains on A1, unexecuted and
unerased. The corrected padding comparison has offline coverage; the file was
not uploaded again because that target already exists.

This tooling lives in `mostangrymike/cms-tooling`. The separate production CMS
Git project is `mostangrymike/ibm-sandbox`; consult its
[handoff](https://github.com/mostangrymike/ibm-sandbox/blob/main/CHAT_STATE.md)
before production work. GitHub remains canonical. Codex CLI can replace manual
web-chat editing/testing/transfer handoffs with direct local work and verified
MCP operations as those capabilities become ready and authorized. Protected
production stage/index, modules and disks remain unchanged by tooling demos.

## Offline transaction failure rehearsal

`cms_rehearsal.py` models the proposed replacement/build stop boundaries without
implementing any host operation. It accepts only a complete local operation
review for a non-protected A1 source, pinned by exact SHA-256. It revalidates the
source plan, snapshot, baseline, working text, candidate, diff and operation
receipt before producing a read-only JSON report on stdout:

```sh
python -B cms_rehearsal.py --root /absolute/local/sources \
  --edit-id edit-<24-hex> --operation-id operation-<24-hex> \
  --operation-sha256 <64-hex> --all-faults
```

Omit `--all-faults` for the synthetic success path, or use `--fault before_write`,
`--fault replacement_transfer`, `--fault candidate_readback`,
`--fault step:<name>:rc`, or another exact checkpoint in the full matrix.
These are synthetic checks, not CMS commands. Faults stop at that boundary;
no later step, retry, automatic restore or cleanup is modeled. Reports distinguish
an unchanged target, uncertain/partial transfer, unverified candidate and verified
candidate; possibly created outputs remain at risk until their modeled check.

Every successful check is labeled `assumed_success`. A completed rehearsal does
not verify writer exclusion, real command semantics, output completeness, native
backup or rollback. All execution/host-operation/replacement-safety claims remain
false, and the original host blockers are retained. This is a model of required
fail-stop behavior, not qualification of an executor (none exists).

`python -B validate_cms_rehearsal.py` creates a disposable local fixture and
checks the actual CLI's full matrix. The isolated distribution build runs it and
retains `rehearsal-evidence.json`; CI uploads that report with the source archive.
No additional MCP tool, capability or terminal connection is introduced.

## Existing G-disk linkage, not initialization

The canonical [M173 runbook](https://github.com/mostangrymike/ibm-sandbox/blob/main/docs/M173_PERSISTENT_DISK_RUNBOOK.md) and
[directory plan](https://github.com/mostangrymike/ibm-sandbox/blob/main/docs/M173_DIRECTORY_CHANGE_PLAN.md) identify the existing
G disk as MAINT/0600, label GIT600, 3390/1600 cylinders, 4096-byte CMS blocks,
VMCOM1 / real 0127, starting at cylinder 6000 (ending 7599). It already contains
the protected M173NET STAGE and M174NET INDEX generation. Historical FORMAT and
import instructions are not a reattachment procedure: never repeat them.

An absent G row in QUERY DISK does not establish whether virtual 0600 is absent
or merely not accessed. The documented first checks are CP QUERY VIRTUAL DASD,
CP QUERY MDISK 0600 LOCATION and QUERY DISK. The historical own-minidisk
`CP LINK * 0600 0600 W` was conditional on 0600 being absent, exact directory
identity and no conflicting/overlapping fullpack writer. It is not an automatic
repair command. Verify the current attachment before selecting an authorized
CMS ACCESS operation; never release an unrelated G or change directory/DASD.
The overlapping PMAINT/0141 fullpack must not be linked for writes.

The command bridge remembers a bounded history of fully verified captures for
the current terminal only, so several completed short commands can remain on
the screen. Unknown or incomplete capture frames still block new input; the
history is discarded on disconnect. The source download validator supports
`--snapshot-only` for a verified native backup without claiming it matches the
candidate, and `--expected-source` for an exact local fixed-80 source comparison.

`validate_cms_gdisk.py --live --credential-file /owner-only/credentials.json
--output cms-gdisk-observation-evidence.json` captures five fixed diagnostics:
virtual DASD, current 0600 location, MAINT/0600 directory location, real 0127
volume links, and CMS QUERY DISK. No generic command tool is added. This local
validator uses the explicit link-observation capability; normal MCP defaults
and its fifteen-tool catalog are unchanged.

The separate explicit `--access-existing-g` option may issue exactly
`ACCESS 600 G`, never LINK, FORMAT, RELEASE, replacement or erasure. It refuses
unless the fresh diagnostics show the exact documented current/directory extent,
3390/1600-cylinder virtual geometry, unused G and 600, and the exact known
16-link VMCOM1 baseline. It then source-verifies the existing read-only runner
and captures QUERY DISK plus STATE for M173NET STAGE G1 and M174NET INDEX G1
with native protocol integrity and actual return codes. This verifies access
and file presence, not the complete protected files' content hashes. An access
failure stops without recovery or another attempt. These observations are not
writer exclusion and do not authorize any write to G or source replacement on A.

The screen observer captures each MORE/HOLDING page before one Clear, does not
repeat paging keys for unchanged output events, permits partial RUNNING pages
to finish passively, and matches the command echo after geometry-preserving
redaction. Startup also accepts fresh verified Ready arriving during the final
field recheck without sending another startup input.
