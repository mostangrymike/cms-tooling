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
  field-aware login. Keep generic `--allow-input` disabled. Do not send BEGIN,
  CMS commands, file transfers, or password retries as part of login.
- Credentials belong in an owner-only file outside the repository, loaded locally
  at login. Never print values or put them in MCP arguments. Legacy constants may
  be imported once by AST extraction; never execute legacy scripts to obtain them.
- The operator then authorized continuing the established VM READ startup prompt
  to CMS Ready. `--allow-startup` allows one blank Enter at the verified logon
  input, or BEGIN to resume a verified CP READ reconnect. It does not authorize
  arbitrary CMS commands, existing-input replacement, or file operations.
- The fixed read-only QUERY CMSLEVEL probe was also authorized and returned
  CMS Level 27, Service Level 1302 and a fresh Ready prompt. `cms_startup` may
  run this exact guarded probe only with `verify_cms=true`; it is not a general
  command interface. Keep general terminal input and file operations disabled.
- The operator authorized arbitrary one-line CMS command capture and CMS file
  uploads/downloads without per-call approval. `--allow-arbitrary-commands`
  removes the read-only command allowlist while retaining the correlated runner;
  `--allow-input` remains disabled. Commands must be printable ASCII, at most 108
  characters, and cannot include `|` or `#` because those delimit capture stages
  and CMS logical lines. Full-screen, interactive, or session-ending commands may
  not return captured output. A command tool call itself is the requested command.
- `cms_download` remains a literal-file-ID native read path with two identical
  reads and matching metadata. `cms_upload_file` accepts local paths only beneath
  the configured Git worktree, exact CMS file IDs, and ASCII/binary DFT options.
  Existing targets require `overwrite_existing=true`; state checks are not atomic.
  It checks target presence after DFT but does not claim content readback. The
  reviewed fixed-80 `cms_upload_create_only` path still verifies native readback.
- Runner provisioning requires explicit `create=true` and creates only an absent
  randomly named ZMxxxxxx EXEC A with Exist=keep. Round-trip verify source before
  execution; never overwrite or erase a helper. Reuse a configured runner only
  after verifying its source again. The current command runner source changed, so
  do not reuse ZM537EF1; create and source-verify a new helper before commands.
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
- Never interpret keyboard unlock, a stale Ready prompt, or screen change as proof
  of CMS command completion. Command completion needs correlated output and RC.
- Do not scroll with sleeps to collect bulk output. Future transfers/capture must
  verify complete records and return codes, and manage scratch files explicitly.
- Keep stdout exclusively MCP JSON-RPC. Diagnostics go to stderr. Never log
  terminal input, passwords, nondisplay field contents, or raw ReadBuffer hex.
- Retain complete sanitized screen geometry and diagnostic evidence on failures.
- Run offline unit tests and protocol validation before any live test. The live
  smoke test must only connect, read screen/status, and terminate the terminal.
- Do not claim live or Codex discovery validation unless it actually ran.
- `cms_operation_plan` is local review only under --allow-local-edits. It binds
  a pinned changed source review to a declared recipe, lists missing inputs and
  unresolved execution gates, and must always retain execution_authorized=false,
  execution_implemented=false, replacement_safe=false and no host operations.
  Supplied writer-exclusion/rollback statements are not verified authority.
- `build_cms_tooling.py` performs complete offline distribution validation in a
  temporary extracted copy. Keep its explicit source inventory free of legacy
  pipelines, credentials, live evidence and CMS source/edit snapshots. Portable
  tests use sanitized fixtures under `fixtures/`; do not restore dependencies on
  machine-local capture files. Build artifacts and source distribution hashes
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
- Any IPL, LOGOFF, or broader recovery requires separate authorization.
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
