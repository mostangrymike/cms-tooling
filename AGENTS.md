# Local z/VM CMS automation

- Preserve existing source and transfer scripts; do not reset unrelated changes.
- Use the repository `.venv/bin/python` and requirements-cms-mcp.txt. Bootstrap
  with Python 3.12+; a preexisting operator environment may be used for migration validation.
- MCP starts offline. Connect only when explicitly authorized. The TN3270 endpoint
  is 127.0.0.1:3271; the default device is 0200@. The configured selector or
  explicit connect argument may use auto or an existing terminal group. The
  host and port remain fixed; this is NOT a c3270 script port.
- Initial operation is observation-only. Do not enable `--allow-input`, send LOGON,
  credentials, CMS commands, AID keys, or transfers until the operator authorizes
  input after connection and field layout have been established.
- The operator subsequently authorized local credentials and login after the
  combined guest form was established. `--allow-login` permits only that one-shot
  field-aware login. Do not send BEGIN, CMS commands, file transfers, or password
  retries as part of login; subsequent actions follow the standing CMS
  authorization recorded below.
- Credentials belong in an owner-only file outside the repository, loaded locally
  at login. Never print values or put them in MCP arguments. Legacy constants may
  be imported once by AST extraction; never execute legacy scripts to obtain them.
- The operator then authorized continuing the established VM READ startup prompt
  to CMS Ready. `--allow-startup` allows one blank Enter at the verified logon
  VM READ input or BEGIN to resume a verified CP READ reconnect. A z/VM guest
  reconnect banner with RUNNING and an empty field is not a CMS `Ready;` prompt.
  IBM documents RUNNING as ambiguous between work in progress and a
  command-ready environment; a null input line distinguishes CP READ from VM
  READ. Do not run CMS commands or transfers from that banner. Require a fresh
  CMS Ready prompt for command/transfer boundaries and correlated Ready output
  for completion.
- Earlier M272 instructions authorized one fixed `Clear` only at a freshly
  observed, formatted MORE/HOLDING page. The standing authorization below
  supersedes that limit. IBM also documents PA2 as an immediate page advance
  that preserves the input area; the M272 paging path now uses PA2, advancing
  exactly one page and waiting for readable output.
- A 3270 `MORE...` prompt may be followed by the current z/VM host name (for
  example, `TACOTICO`). That suffix is an informational, changeable host
  identifier, not part of the MORE prompt; detect and advance on MORE itself.
- On 2026-10-19, the operator authorized Codex to take any action on CMS without
  per-action confirmation and asked that this authority be recorded for future
  reference. This standing authorization supersedes the narrower CMS
  terminal-input, paging, command, recovery, and file-operation approval limits
  in this document for future CMS work. Continue to record each action and
  observed result; use only actions needed for the active task. MCP capability
  flags still describe what the configured server can perform; authorization
  does not enable a disabled capability by itself.
- M272 recovery candidate `ZM9A512F EXEC A` was sent with DFT `Exist=keep`, but
  transfer ended with TRANS14; its later read-only receive also ended with
  TRANS14. Treat it as possibly partial: do not execute, overwrite, or erase it
  without first resolving the transfer state and source contents.
- The fixed read-only QUERY CMSLEVEL probe was also authorized and returned
  CMS Level 27, Service Level 1302 and a fresh Ready prompt. `cms_startup` may
  run this exact guarded probe only with `verify_cms=true`; it is not a general
  command interface.
- On 2026-10-20, the original terminal 0200 showed MORE after a null Enter;
  PA2 produced an unformatted 24x80 all-asterisk buffer. On a later 0200
  reconnect, another null Enter also led to an unformatted buffer. A fixed
  QUERY CMSLEVEL was typed but never submitted. These attempts completed no
  CMS command or transfer. The source-verified runner boundary now requires a
  fresh CMS Ready prompt and refuses the ambiguous reconnect RUNNING banner.
  For MORE during reconnect logon messages, IBM Getting Started documentation
  says to press Clear. On the fresh terminal, Clear advanced the observed MORE
  page to CP READ with the `Already logged on GRAF 0200` response.
- On 2026-10-20, a fresh automatically assigned terminal first reached CP READ
  and reported MAINT already logged on at GRAF 0200. IBM LOGON syntax is
  `LOGON userid HERE` (without parentheses) to reconnect an already logged-on
  user at the current terminal. The first parenthesized attempt was rejected;
  the corrected command reached a hidden CP password field. `cms_mcp.py` now
  exposes `cms_login(reconnect_here=True)` and can resume only one empty
  nondisplay CP field after moving to and rechecking its cursor. The local
  credential provider submitted the password once. A null Enter on the fresh
  formatted RUNNING banner exposed `Ready;`; `cms_startup` observed that Ready,
  and `cms_prepare_runner(create=false)` freshly verified `ZM581503 EXEC A`.
- In that 2026-10-20 session, `cms_download(GIT EXEC A, create_runner=true)`
  failed during read-only capture. The screen remained locked at VM READ on
  token `7D3472E4A80B67C7`, sequence 165 (`ZM1 ... D`); passive checks showed
  no progress. `cms_restart_runner` correctly rejected recovery because there
  was no final failed-frame ACK followed by Ready(12), and sent no input. The
  subsequent reconnect exposed final `F 165 ACK` and Ready(12), allowing
  `cms_restart_runner` to mark it incomplete. `cms_prepare_runner` then
  reverified `ZM581503`. A second read-only capture of `GITUPD EXEC A` also
  failed with Ready(12), token `934A58E998021CC8`, sequence 93; that failed
  capture was reset and the command runner reverified. `STATE GITUPD EXEC A`
  returned RC 0 and `LISTFILE GITUPD EXEC A` confirmed the file exists.
- A command-runner `TYPE GITUPD EXEC A` source read then exceeded its 120-second
  tool timeout and was interrupted. On reconnect, it returned to Ready(12) with
  token `04C3A6DC7840B255`, sequence 62, but the visible ACK row had a trailing
  malformed suffix, so `cms_restart_runner` refused the boundary. The terminal
  was disconnected without more input. No M273 EXEC was uploaded or replaced.
  The two `cms_download(create_runner=true)` attempts may have left newly
  created random reader EXECs on A; their names were omitted by the temporary
  local MCP client formatter. Preserve any new ZMxxxxxx EXECs until inventory
  identifies them. M273 CMS validation remains pending; do not submit input
  from an unresolved or malformed runner frame.
- The operator authorized arbitrary one-line CMS command capture and CMS file
  uploads/downloads without per-call approval. `--allow-arbitrary-commands`
  removes the read-only command allowlist while retaining the correlated runner;
  commands must be printable ASCII, at most 108 characters, and cannot include
  `|` or `#` because those delimit capture stages and CMS logical lines.
  Full-screen, interactive, or session-ending commands may not return captured
  output. A command tool call itself is the requested command.
- `cms_download` remains a literal-file-ID native read path with two identical
  reads and matching metadata. `cms_upload_file` accepts local paths only beneath
  the configured Git worktree, exact CMS file IDs, and ASCII/binary DFT options.
  Existing targets require `overwrite_existing=true`; state checks are not atomic.
  It checks target presence after DFT but does not claim content readback. The
  reviewed fixed-80 `cms_upload_create_only` path still verifies native readback.
- Runner provisioning requires explicit `create=true` and uses a random
  ZMxxxxxx EXEC A with DFT `Exist=keep`, which fails rather than replacing an
  existing destination. A CMS STATE absence result is useful when correlated
  Ready/RC output is available, but is not required for the no-replace transfer.
  Round-trip verify source before execution; never overwrite or erase a helper.
  The M272 command runner `ZM581503 EXEC A` passed exact round-trip verification
  on 2026-10-19. Reuse it only after verifying its source again in each session;
  it was freshly source-verified on 2026-10-20 before the download capture stalled.
  The terminal/server then disconnected, so any future session must verify its
  source again before running commands.
- Command output uses numbered, nonce-correlated native records with lengths,
  byte counts, checksum and acknowledgements. Paging advances only on observed
  MORE/HOLDING after capture; no timed scrolling. Mask encoded payload in all
  diagnostic screens. Never claim partial capture as complete output or an RC.
- Never modify protected CMS files, disks, directory entries, or other sessions.
  Never erase or replace a CMS file without explicit authorization for that file.
- Minidisk `CP QUERY LINKS` is observational only; it is not a disk/file lock and
  never establishes replacement safety. The fixed direct-screen query is disabled
  unless `--allow-query-links` is set. It may submit only the exact command and
  address validated by `cms_link_query.py`; it must not provision CMS files. A
  production write still requires an operator-established single-writer/quiescence
  procedure.
- `validate_cms_gdisk.py` is a local, fixed MAINT/0600 diagnostic workflow using
  link-observation authority. Its five queries cannot accept arbitrary commands.
  Separate explicit `--access-existing-g` allows only ACCESS 600 G after exact
  fresh geometry/current+directory extent, known volume-link set and unused-mode
  checks. Never LINK, FORMAT, RELEASE, initialize or erase from this workflow.
  Verify GIT600 metadata and protected stage/index presence afterward. This
  changes CMS access, not production source authority; observations remain no lock.
- Live G access was restored with that exact ACCESS workflow on 2026-10-16.
  Native QUERY DISK verified GIT600/600/G/R/W/1600/3390/4096; both protected
  stage/index STATE calls returned actual RC0. No LINK, FORMAT, import, erase or
  protected-content write occurred. Evidence: cms-gdisk-access-evidence.json.
- Do not use a CMS command to modify protected stage/index, MODULEs, disks, DASD,
  rollback sources, or the retained scratch files unless the specific target and
  operation are explicitly part of the current task. The presence of an
  approval-free general command tool is not blanket production-write authority.
- Use one dedicated persistent s3270 process; serialize every terminal operation.
- Keep that session open whenever a bounded fresh-screen capture confirms the
  terminal is connected and readable, including after a command/capture error.
  Never retry the failed command automatically. Terminate s3270 only when its
  process has exited or the screen pipe cannot be resynchronized and a complete
  connected screen cannot be recovered; return sanitized failure evidence.
- Never interpret keyboard unlock, a stale Ready prompt, or screen change as proof
  of CMS command completion. Command completion needs correlated output and RC.
- Do not scroll with sleeps to collect bulk output. Future transfers/capture must
  verify complete records and return codes, and manage scratch files explicitly.
- Keep stdout exclusively MCP JSON-RPC. Diagnostics go to stderr. Never log
  terminal input, passwords, nondisplay field contents, or raw ReadBuffer hex.
- Retain complete sanitized screen geometry and diagnostic evidence on failures.
- M272 flat-tree checkout passed on CMS on 2026-10-19. The current configured
  command runner is `ZM581503 EXEC A`, created with DFT `Exist=keep` and
  verified by exact round trip. The operator's current CMS registration has
  `--allow-input` and `--runner-name ZM581503`. A server started before that
  config update was terminated after use; future server starts should read the
  current registration.
- The M272 tree fixture remains as `Z272TR REPO A`, and the checkout created
  `Z272A TXT A` and `Z272B TXT A` plus the worktree map entry. Both independent
  HASH-WORKFILE results matched blob
  `1A9E9EB8561B10E9D146BFE9933974882B74940E`. The unattached commit is
  `3F324CA0CE1685FA1579F9E897DB353DE5DF5DC6`; no ref update was run.
- `ZM02EA0B EXEC A` failed source round-trip verification and is no longer
  configured as the download runner. Do not execute, overwrite, or erase it
  without first resolving its exact contents. Older uncertain candidates
  `ZMD898D4`, `ZM9A512F`, and `ZM6D541B` also remain unverified; preserve them.
- CMS runner output can briefly show a locked VM READ field while an ACK is
  pending. Wait only within the same verified token/frame boundary. After the
  final ACK, Ready may replace the visible `Z DONE` row; correlate the exact
  `ZA1 <token> <sequence>` echo with Ready and the in-memory completed token.
- On the final M272 recovery, failed read-only capture
  `F788EDC4624E2EFA` was observed as sequence 4 ACK followed by `Ready(00012)`.
  `cms_restart_runner` marked it incomplete; `cms_prepare_runner(create=false)`
  reverified `ZM581503`; a read-only `STATE Z272B TXT A` returned RC 0; then
  `cms_resolve_failed_capture` resumed commands. The failed ref-display output
  remains incomplete; do not infer a ref value from that capture.
- Run offline unit tests and protocol validation before any live test. The live
  smoke test must only connect and read screen/status; leave a connected,
  responsive terminal open rather than disconnecting to end the smoke test.
- Do not claim live or Codex discovery validation unless it actually ran.
- `cms_operation_plan` is local review only under --allow-local-edits. It binds
  a pinned changed source review to a declared recipe, lists missing inputs and
  unresolved execution gates, and must always retain execution_authorized=false,
  execution_implemented=false, replacement_safe=false and no host operations.
  Supplied writer-exclusion/rollback statements are not verified authority.
- `build_cms_tooling.py` performs complete offline distribution validation in a
  temporary extracted copy. Its manifest is derived: explicit support files and
  entry points, then local imports by AST. Keep legacy pipelines, credentials,
  live evidence and CMS source/edit snapshots out of the bundle only with a
  written reason in `EXCLUDED_SOURCES`; a tracked module that is neither
  reachable nor excluded fails the build. Portable tests use sanitized fixtures
  under `fixtures/`; do not restore dependencies on machine-local capture files.
  Build artifacts and source distribution hashes
  do not establish CMS target qualification or authorize uploads/builds.
- `cms_rehearsal.py` is an offline symbolic fail-stop model, not an executor.
  Revalidate the exact operation hash and all bound local source artifacts first.
  Never turn assumed_success checkpoints into host qualification claims. Preserve
  execution blockers and false execution/host/replacement-safety flags. Failure
  scenarios must not continue, retry, restore or clean up; uncertain/partial target
  and output states must remain explicit. No host adapter or new capability is
  authorized by rehearsal success.
- Interrupted provisioning of ZM6360C6 EXEC A was canceled with one Clear on a
  verified blank unformatted screen. That candidate remains unverified and may
  be partial: never execute, overwrite or erase it without specific approval.
- ZM537EF1 EXEC A was subsequently uploaded and source-verified by download.
  The Codex registration reuses it; each new session must verify its source with
  cms_prepare_runner before execution. General terminal input remains disabled.
- Transfer completion precedes restoration of the CMS command field. Use both
  AidWait for transfer completion and fresh Ready/empty-field/cursor verification
  before another transfer. Do not infer readiness from transfer completion alone.
- The approved retained-fixture audit created source-verified ZME09C7C EXEC A
  for exact ZTQUAL MODULE A1 native reads only. It transports bounded chunks
  with original record lengths for the observed three-record V52312 output.
  Retain it; never overwrite/erase it. Reuse only with explicit --output-reader
  ZME09C7C and fresh source verification. Standard source download/edit limits
  and Codex registration remain unchanged; this grants no source write/build.
- The retained ZTQUAL fixture cycle completed on 2026-10-17. Final audit
  cms-fixture-output-qualified-evidence.json passed all 22 steps and terminated
  its terminal. MODULE native records [80,52312,3888] total 56280 bytes, hash
  d2512ab7d095851ad254db02dba32869a8e50dd93c9e805b0a361c4240468707.
  Source/backup hashes, six transient absences, exact inventories and empty
  FILEDEF passed. Never rerun the fixture create/build workflow against these
  retained files. No production qualification or replacement safety follows.
- The operator next authorized verified read-only source downloads into the local
  Git working tree. Enable only with --allow-downloads and a configured
  --download-root. Keep CMS source edits and replacements disabled. Download
  tools do not stage/commit; separate authorized Git work may use Codex CLI.
  Use a separate ZMCPGET.EXEC reader, source-verified every session.
- Explicit create_runner=true may provision one absent random ZMxxxxxx EXEC A
  reader under the same live approval and round-trip verification rules. Do not
  replace the working ZM537EF1 command helper or the older partial candidate.
- Download literal file IDs only. Reject # (CMS logical line separator),
  wildcards, controls, options and path components. Preserve native records and
  trailing blanks. Verify two identical reads and matching before/after metadata;
  describe this honestly as a consistency check, not an atomic host snapshot.
- Write only new local snapshot directories containing native bytes, record
  lengths, hashes and optional printable UTF-8 text. Refuse credential-containing
  captures, symlink destinations, destinations outside Git worktrees, and file
  changes during capture. Do not claim live support for untested record formats.
- ZM02EA0B EXEC A is the source-verified download reader configured in Codex.
  Live validation downloaded ZM537EF1 EXEC A1: 63 F80 records / 5040 bytes,
  with two identical native reads and an exact comparison to local source.
  Variable records have offline coverage only; no live V-format result is claimed.
- The operator authorized local edit/diff workspaces and review-only upload plans.
  Enable with --allow-local-edits and --download-root; no host session is needed.
  Keep downloaded snapshots and edit baselines intact. Edit only the returned
  working file, then validate with cms_edit_plan. A plan authorizes no upload.
- Require exact baseline/snapshot hashes and record boundaries; strict cp037,
  LF-terminated records and original LRECL limits. F records may be repadded
  without truncation; V trailing blanks remain significant. Never silently
  normalize CRLF, replace unencodable characters, or grow record width.
- The operator authorized local edit/diff workspaces and review-only upload
  plans; this does not itself authorize a host write. The separate
  `cms_upload_create_only` capability is disabled unless
  `--allow-create-only-upload` is configured. It accepts one explicit changed
  plan hash, candidate hash and exact `ZVxxxxxx EXEC A1` disposable target,
  requires a fresh `STATE` absence result, creates only fixed-80 files, then
  requires native readback equality. It never replaces or erases. Retain the
  scratch file for later separately authorized cleanup. Absence check and DFT
  create are not atomic against other CMS sessions. Do not enable this capability
  in the standard Codex registration until the operator explicitly authorizes
  live scratch-file creation; no production source upload follows from it.
- The approved live scratch validation first observed the transient Hercules
  banner, then used bounded event-based output observation to reach the guest
  login form. Authorized login/startup reached CMS Ready; command helper source
  was verified. The exact absent scratch target `ZV7C2E91 EXEC A1` was created.
  ASCII DFT readback omitted fixed-record trailing padding and the first validator
  reported a mismatch. A separate verified native read-only download then
  confirmed all 63 F80 records / 5040 bytes exactly match the candidate hash.
  The local comparison now restores F80 padding before comparison and passes
  offline. Keep the scratch file; do not erase it or overwrite it. No source was
  executed. Evidence: cms-upload-live-evidence.json and
  cms-upload-host-readback-evidence.json.
- Subsequent live qualification created exactly `ZVF69FE6 EXEC A1` from the
  reviewed comment-only candidate. The corrected DFT readback passed directly;
  two independent native reads and matching metadata confirmed 63 F80 records /
  5040 bytes with candidate hash
  ce87917f84fe964aeffa33b65fc17930b06ebe4bdc92f57fad5d34da8fd55029.
  Keep this file as well as ZV7C2E91. Neither may be overwritten, executed or
  erased by a generic continuation. Evidence:
  cms-upload-native-qualified-evidence.json. Production replacement/build
  boundaries are specified in PIPELINE-READINESS.md; exact target, recipe and
  operator-established writer exclusion remain required.
- Tooling repository: mostangrymike/cms-tooling. The separate production project
  remains mostangrymike/ibm-sandbox. Read its CHAT_STATE.md and README.md
  at https://github.com/mostangrymike/ibm-sandbox before production work. Finish z/VM tooling first. GitHub is canonical.
  Codex CLI may perform direct local edits/tests/Git work and verified MCP actions;
  older web-chat manual handoff steps may be adapted to these capabilities.
  This does not authorize CMS source replacement, protected operations, or
  bypassing target validation. Preserve G's 7736-object stage/index, MODULEs,
  A/G disks/DASD, rollback sources and exact scratch-cleanup rules.
- Latest CHAT_STATE checkpoint: thin GITC23 compatibility wrapper awaits complete
  host CI and real CMS validation. Do not assume those gates passed or deploy the
  wrapper until verified. Preserve the proven inline GITC26 worker and old
  GITC23 rollback. No production source changes are part of local tooling demos.
- On 2026-10-17 the operator authorized arbitrary command capture and file
  transfers without per-call approval. Codex registration enables those paths
  from the canonical tooling checkout. This is a capability setting, not
  authorization to run a particular command or alter a particular production
  file; preserve protected targets and require the exact target/operation in the
  current task. Do not claim CMS target qualification or atomic write safety.

- 2026-10-20 CMS M273 continuation: the operator explicitly authorized any CMS
  actions and asked this to persist for future reference. EC2 entry is
  `admin@3.17.164.13`; Telnet CMS endpoint is `192.168.200.2`. Treat the z/VM
  banner host suffix as mutable and ignore it. Reconnect with Telnet `send brk`,
  `LOGON MAINT HERE`, password, then Telnet `send ip`, CP `BEGIN`, and one null
  Enter if CMS Ready does not appear. For a fresh logon, issue `IPL CMS` and
  `ACCESS 600 G`. CMS level observed: 27 / service level 1302. IBM
  `QUERY TERMINAL` returned TYPE TTY, PROMPT TTY, SCROLL CONT, SYS3270 OFF;
  3270 MORE screen advancement therefore does not apply to this Telnet line.
- M273 CMS setup on 2026-10-20 used a temporary read-only FTP source server on
  `192.168.200.1:2121` and a verified-TLS GitHub bridge on
  `192.168.200.1:9443`, both reached from CMS and restricted to the needed files
  and fixed GitHub destination. Shut these temporary processes down when the
  session is complete. Do not record or expose CMS credentials.
- `GITREMOT.EXEC` fixes from this session: preserve remote URL case by parsing
  the action without `PARSE UPPER`, and treat a parsed URL path as success
  unless the result is `ERROR`. CMS `GITREMOT REPO A` contains the configured
  `origin` remote for `https://github.com/mostangrymike/cms-git.git`.
- M273 fetch framing defect found on CMS: `GITFPACK` emits a long verified-pack
  summary which CMS `PIPE ... STEM` wraps at column 80, including in the middle
  of the 40-character OID. `GIT PULL` now concatenates wrapped STEM fragments
  before validating the 11-word summary. This correction is in local
  `cms-git/src/GIT.EXEC` and was uploaded to CMS `GIT EXEC A`; pre-debug and
  debug backups are `M273B007 EXEC G` and `M273B008 EXEC G` respectively.
- Direct CMS `GITFPACK` succeeded for GitHub `main`, OID
  `7A9B72EA68D865BC611A04E15BD55E0A76564275`, pack size 3,529,494 bytes,
  11,816 objects. The corrected pull framing retained `M273P010 STAGE G`.
  `EXEC GIT FETCH-ACTIVATE M273P010 M273I010 G` was then interrupted with
  Telnet IP and CP LOGOFF after `QUERY TIME` reported 17:44.99 virtual CPU over
  a 19:37 connection. Fresh CMS inspection confirmed the stage exists and
  `M273I010 INDEX G` is absent. No ref update was run; no successful full M273
  pull is confirmed. Preserve the pack and stage for retry.
- Performance diagnosis: `GITFACT EXEC` invokes `GITPLOAD` separately for each
  indexed object. `GITPLOAD.C` opens/seeks `dd:STGIN`, writes `dd:OBJOUT`, and
  hashes each object; `GITFACT` then invokes `GIT VERIFY-OBJECT` per installed
  object. The existing assembler FSREAD helpers are not integrated into this
  M273 path: M199 `GITBX9.ASSEMBLE` reads only the hard-coded
  `M173NET STAGE G1` range into `GITR199 DATA A1`. Do not describe that prior
  optimization as covering M273 until a generalized reader and batch path are
  connected and target-validated. Earlier retained fetch packs include
  `M273PACK`, `M273P003`, `M273P004`, `M273P005`, and `M273P006`. The local
  `src/GIT.EXEC` fetch-summary framing fix remains deployed as `GIT EXEC A`.
- 2026-10-20 M273 performance candidate work uses the documented CMS C build
  command `CMSCLNK name PLAIN` from `CMS-C-RECIPE.md`; do not use `CC`. Candidate
  sources `M274LD C A` and `M274FCT EXEC A` were transferred to CMS. The first
  `CMSCLNK M274LD PLAIN` stopped at C compilation with RC 12 because GCCCMS's
  installed `errno.h` does not define `ENOENT`; `M274LD ASSEMBLE A` was
  confirmed absent afterward. A diagnostic `M274ERR C A` was transferred to
  measure CMS `fopen`/`errno` behavior, but was not built or run. The Telnet
  endpoint `192.168.200.2:23` then stopped accepting connections from EC2, and
  read-only EC2 inspection found no running Hercules/3270/CMS process. No batch
  loader module, index, loose objects, or ref update is confirmed. Resume only
  after restoring the endpoint and resolving the `ENOENT` portability issue;
  preserve the transferred candidates and inspect all compiler outputs before
  any rebuild.
- 2026-10-21 Hercules on EC2 was restarted in tmux session `hercules` after
  restoring host `tap0`; z/VM FORCE start completed, TCPIP autologged, QETH
  opened `tap0`, and guest Telnet `192.168.200.2:23` accepted a connection.
  The MAINT Telnet attempt reached the z/VM 6.3 banner but did not confirm CMS
  `Ready;`. See `HERCULES-EC2-STARTUP.md` for commands, recovery prompts, CCKD
  repair observations, and the exact validation limit.
- 2026-10-21 enabled systemd units `hercules-tap0.service` and
  `hercules.service` for boot persistence. The TAP unit idempotently creates
  host `tap0`; the emulator unit uses a separate `hercules-autoboot.rc` to IPL
  `0123`, attempt `.warm`, then answer `.no`. Automatic FORCE is intentionally
  omitted. `systemd-analyze verify` passed and the TAP unit started on the live
  interface; Hercules was not started twice and no reboot was performed. The
  next EC2 reboot remains the end-to-end check. See `HERCULES-EC2-STARTUP.md`.

- 2026-10-21 CMS M273 performance run: after `GITFIMP M273P010 G` returned
  `FETCH IMPORT VERIFIED M273P010 -> M273P010 STAGE G OBJECTS 11816 PACK
  7A9B72EA68D865BC611A04E15BD55E0A76564275`, read-only checks confirmed the
  stage exists, `M273P010 META A` reports 3,529,494 bytes / 11,816 objects,
  and `QUERY DISK G` showed 67,263 blocks free. No FILEDEFs were set. The
  operator requested that the next long run be interrupted as impractical.
  `M274F5 M273P010 M273I011 G` had run about 1 hour 48 minutes with CP01
  saturated near 100–200 MIPS and no I/O; it had produced no captured CMS
  completion text. Following IBM's CMS interrupt procedure, Telnet IP was sent,
  then `HX` (with a CP `REQUEST` step attempted after the first HX did not
  return output). Hercules `qproc` then reported both CPUs at 0 MIPS in
  repeated samples. The local Telnet driver and SSH child were terminated to
  clear the hung terminal; Hercules logged `TCPIP2 DISCONNECT MAINT ... FORCED
  BY SYSTEM`. The CMS `Ready` message and command RC were not captured. Preserve
  `M273P010 STAGE G` and any partial `M273I011 INDEX G`/loose objects; inspect
  their state before retrying or cleaning anything. No ref update was run.
  IBM interruption reference: https://www.ibm.com/docs/en/zvm/7.4?topic=execution-interrupting-your-programs
