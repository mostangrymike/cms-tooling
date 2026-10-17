# Actual validation results

Latest result (2026-10-16): z/VM tooling is organized under `src/zvm-tooling`.
All 117 offline tests pass, Python compilation and stdio MCP validation pass,
and Codex app-server discovers the registered fourteen tools with
`tools_error=null`. A live read-only connect saw the transient Hercules banner;
bounded passive output observation then captured the z/VM login form through the
SSH tunnel to EC2. Field layout was valid and the session disconnected cleanly.
No login, password, guest command, AID key, or file transfer was submitted. See
`zvm-live-relocated-evidence.json`. Earlier sections record previous stages.

The later one-shot login validation submitted the local credentials once and
observed `CP READ`. A separately authorized guarded startup then submitted
`BEGIN` and the startup continuation keys, but did not observe CMS Ready before
timing out. A subsequent passive reconnect observed the combined login form
again, with empty input fields. One overlapping retry received
`HHC01030I Connection rejected, device 0200 unavailable` while the first
validator was still active; that retry submitted no credentials or input. See
the relocated login, startup, and passive-observation evidence files. Stop live
input here until the guest startup path is understood.

Executed on 2026-10-16 using
`/Users/mikewommack/ibm-sandbox/.venv/bin/python`.

- Installed MCP 1.30.0 into the existing virtual environment; py3270 0.3.5 was
  already installed. `pip check` reported no broken requirements.
- Initial offline suite: 15 tests passed before registration/live connection.
- Final offline suite: 18 tests passed, including regression coverage added from
  the captured Hercules banner, partial-input redaction and pipe-read deadlines.
- Syntax checks passed for all four new Python files.
- Real stdio MCP initialization negotiated protocol 2025-11-25; tools/list
  returned exactly the five requested tools. Offline startup and rejected input
  were verified. See zvm-offline-evidence.json.
- Registered `ibm-zvm-cms` in Codex CLI with the absolute virtual-environment
  interpreter and server path. The registration does not enable terminal input.
- Codex app-server discovered all five registered tools with `toolsError=null`.
  No model turn was used. See zvm-codex-discovery.json.
- One live MCP connection to `0200@127.0.0.1:3271` succeeded. Connect, screen,
  status, and disconnect all returned success. All 24 rows contain 80 positions.
  The parsed map contains 28 fields, all protected. Cursor: row 1, column 1.
  No field-layout error occurred. The dedicated terminal process terminated.
- The live screen is the Hercules banner for device 0:0200, not a z/VM login
  screen. No LOGON, password, CMS command, AID key, or file transfer was sent.
  See zvm-live-evidence.json for the complete original sanitized evidence.
- The initial classifier reported `unknown` for the Hercules banner. It was then
  extended to identify that banner as `logo` with `screen_kind=hercules_banner`
  and tested against the captured rows offline. The original live evidence was
  left unchanged. No second live connection was performed.

The existing shell scripts were not edited; their pre-existing working-tree
changes were preserved.

## Remaining boundary

The later read-only investigation established the guest login field layout (see
follow-up below). Credentials and CMS command execution remain unverified. Input
remains disabled in the registration.

## EC2 follow-up, 2026-10-16

- Confirmed SSH forwarding from Mac 3271 to EC2 localhost 3270. Remote Hercules
  PID 4331 runs from `/home/admin/vm630`, with 0200-0203 configured as 3270
  devices. No guest/operator commands, IPL, or remote configuration changes made.
- An initial passive `Snap(Wait,5,Output)` attempt crashed local s3270 4.5ga6.
  The macOS crash report shows SIGSEGV in `set_output_needed` / `snap_save` during
  incoming host output. That attempt did not complete the planned observation;
  `zvm-passive-observation.json` records the failed attempt.
- Replaced the server's output-wait path with `Wait(Output)`, armed by Ascii
  before the terminal action. Regression coverage verifies the ordering and
  absence of a CMS-completion claim.
- A subsequent passive read-only connection observed host output after about
  0.1 seconds and captured the z/VM ONLINE combined login form. The Hercules
  banner was transient. See `zvm-ec2-observation.json` for full evidence.
- Editable fields: USERID row 20 column 17 length 8; PASSWORD row 21 column 17
  length 8, nondisplay; COMMAND row 23 column 17 length 123, wrapping into row 24.
  Cursor: USERID row 20 column 17. The dedicated terminal process terminated.
- Corrected the classifier to identify the combined form as login rather than
  a password prompt. Original captured classifications are retained in evidence.
- Follow-up validation: all 20 offline tests passed; syntax checks and actual
  stdio MCP initialization/tool discovery passed after these changes.

- After relocating the tooling and updating Codex registration, a fresh live
  read-only validation first captured the Hercules banner (`logo`). The passive
  `zvm_screen(wait_output=true, timeout=10)` observation returned fresh host
  output and the login form (`login`): USERID at row 20 column 17 (8 positions),
  nondisplay PASSWORD at row 21 column 17 (8 positions), and COMMAND at row 23
  column 17 (123 positions). The cursor is at USERID, all three fields are
  empty, and field parsing had no error. Status also classified `login`. The
  dedicated terminal process terminated cleanly. See
  `zvm-live-relocated-evidence.json` for complete sanitized evidence. No input
  or credentials were sent.
- One-shot login succeeded and observed `CP READ`. A guarded startup validation
  then followed its recorded CP READ/VM READ boundaries, submitted `BEGIN` and
  three Enter actions, but timed out on an `unknown` screen showing `CMS` and a
  `RUNNING` indicator; it did not observe CMS Ready and issued no CMS command.
  The validator disconnected. A later passive reconnect returned the combined
  login form with empty USERID/PASSWORD/COMMAND fields, also followed by a clean
  disconnect. A retry briefly overlapped the first validator and received
  `HHC01030I Connection rejected, device 0200 unavailable`; that retry stopped
  before input. The CP READ identifier is masked in login evidence, and the
  configured credential values are absent. Evidence:
  `zvm-login-relocated-evidence.json`, `zvm-startup-relocated-evidence.json`,
  and `zvm-post-startup-passive-evidence.json`.

Next step: implement a local credential provider and explicitly authorized login
using the established field map, without putting passwords into MCP arguments.

## Local credentials and login follow-up

- Added `zvm_credentials.py`: validated owner-only JSON file provider and a
  one-time AST importer that never executes the old pipeline. Provisioned
  `~/.config/ibm-zvm-cms/credentials.json` with mode 0600, outside the repository.
  Credential values were not printed or placed into command/MCP arguments.
- Added `zvm_login(timeout)` with a separate `--allow-login` launch flag. It
  verifies the captured form, refuses existing/modified input, checks cursor and
  nondisplay attributes before typing, and submits once. Generic input remains
  disabled; no CMS commands, Clear, BEGIN, file transfers or automatic retries.
- Updated Codex registration with `--allow-login --credential-file <local-path>`;
  Codex app-server discovered all six tools with no discovery error.
- Before live login: 32 offline tests passed, syntax checks passed, and actual
  MCP stdio initialization and tool discovery passed.
- One authorized live login was submitted. Guest output included LOGON AT,
  z/VM V6.3.0 and VM READ at the bottom of the screen. Credentials were accepted,
  but the tool returned `login_transition_timeout` because it did not yet
  recognize VM READ. The process disconnected cleanly. No login retry was made.
- Preserved the original sanitized failure result in `zvm-login-evidence.json`.
  Added VM READ as a distinct stop state and verified it with that recorded
  screen plus synthetic login transitions. This correction was tested offline;
  it was not claimed as another successful live test.
- Corrected inline-credential redaction so it cannot consume the next physical
  row's version banner or the ordinary LOGON AT timestamp.
- Final validation: all 35 offline tests passed, all six changed/new Python
  files passed syntax checks, and actual stdio MCP initialization/tool discovery
  passed. Checked that neither local credential value appears in the login,
  offline-protocol or Codex-discovery JSON evidence artifacts.

Current boundary: guest login was accepted, but CMS Ready is unverified. The
guest stopped at VM READ. The next step is an explicitly authorized startup-prompt
continuation, followed by correlated CMS output/return-code capture.

## Startup continuation and confirmed CMS Ready

- Added separately enabled `zvm_startup`; current Codex registration includes
  `--allow-login --allow-startup` but not general `--allow-input`. Codex app-server
  discovered all seven tools without errors.
- Added raw-empty field metadata, startup provenance/cursor/field checks,
  at-most-once continuation for each observed startup state, and passive waits
  through transitional RUNNING screens. No input was cleared or replaced.
- Initial reconnects exposed an output-event race: Wait(Output) could time out
  even though the following snapshot contained new host output. Fixed detection
  to accept changed host-controlled display as well as the output event. Local
  editable input and keyboard unlock are excluded from this comparison.
- Preserved initial reconnect/startup outcomes separately in
  `zvm-startup-precontinuation-evidence.json`, `zvm-startup-running-evidence.json`,
  `zvm-startup-running-timeout-evidence.json`, and
  `zvm-startup-cms-line-evidence.json`. Several reconnects were required while
  correcting these observed transitions; no rejected password was retried.
- Blank startup continuation produced a bare CMS line, but no Ready prompt.
  Rather than declaring success or sending more blank input, prepared/tested and
  obtained live approval for one fixed read-only QUERY CMSLEVEL diagnostic.
- Actual successful probe: `CMS Level 27, Service Level 1302`, followed by
  `Ready; T=0.01/0.01 14:51:37`. The screen was classified cms_ready. The dedicated
  terminal disconnected cleanly. No file transfer, file edit, erase, replace,
  assemble, link, IPL, or arbitrary CMS command was performed.
- Full successful evidence: `zvm-cmslevel-probe-evidence.json`. The successful
  probe ran through the standalone diagnostic helper using the same Session
  adapter. The MCP startup tool subsequently gained `verify_cms=true` to expose
  that same fixed guarded probe; its wrapper was validated offline, not claimed
  as another live invocation.
- Final checks: 49 offline tests passed, syntax checks passed, real MCP stdio
  protocol/tool validation passed, and Codex discovery passed after the schema
  update. Generic terminal input and file operations remain disabled.

Current boundary: CMS Ready is now confirmed. General CMS command return-code
capture, bulk output, source editing, transfers and builds remain unimplemented.
Next concrete step: command execution with correlated complete output and actual
CMS return codes, starting with explicit read-only commands.

## Read-only command capture follow-up

- Added `ZMCPRUN.EXEC`, `zvm_capture.py`, `zvm_commands.py` and an explicit live
  command validator. The command allowlist is QUERY CMSLEVEL, QUERY DISK, literal
  STATE, and LISTFILE without options. The helper saves the CMS-stage RC
  immediately and transports nonce-correlated records with lengths, byte count,
  checksum, sequence numbers and acknowledgements. It creates no output files.
- Provisioning requires an explicit create request, a random helper name and a
  correlated STATE RC28 absence check. It never intentionally replaces/erases
  files and verifies source by download before execution. Exist=keep is a local
  receive guard, not an atomic remote create guard. Helpers are retained.
- Actual final offline run: 69 tests passed, including synthetic multi-screen
  capture, missing-file RC28, corruption/truncation refusal, credential masking,
  provisioning guards and a local Regina REXX protocol test. The Regina test
  substitutes synthetic records for the CMS-specific PIPE statement; it does
  not validate that statement on CMS.
- Syntax checks passed for eight server/validation Python files. Actual stdio
  initialization negotiated protocol 2025-11-25 and discovered all nine tools;
  offline startup and rejection of disabled operations passed. Evidence:
  `zvm-offline-evidence.json`.
- Codex registration enables login, startup and allowlisted commands, with no
  general terminal input and no configured helper. Client tool timeout is 360
  seconds. Startup still does not connect or log in automatically.
- After that registration change, actual `codex app-server` discovery returned
  all nine tools with `tools_error=null`. No model turn or mainframe connection
  was involved. See `zvm-codex-discovery.json`. All six current protocol,
  discovery, command and recovery JSON artifacts parsed successfully and were
  checked to contain neither local credential value.
- First live provisioning selected `ZM6360C6 EXEC A` after STATE returned RC28.
  The send Transfer returned immediately because AidWait was false; receiving
  then failed with `File transfer already in progress`. The dedicated process
  terminated. No helper was executed. Full sanitized failure evidence is in
  `zvm-command-transfer-overlap-evidence.json`.
- Corrected Transfer synchronization to temporarily enable AidWait and added
  regression coverage requiring that setting. This correction has passed
  offline tests but has not completed a live transfer.
- The subsequent live validator reconnected/logged in, but startup resumed an
  unformatted screen with no fields and could not establish CMS Ready. It
  stopped before provisioning another helper or running validation commands.
  See `zvm-command-evidence.json`.
- One PF2 cancellation attempt did not restore a verified screen. A separately
  approved recovery issued CP REQUEST only after verifying CP READ and its
  empty input field; VM READ was not observed, so HX was not sent. Both sessions
  disconnected cleanly. See `zvm-transfer-recovery-evidence.json` and
  `zvm-transfer-request-recovery-evidence.json`. No IPL, LOGOFF, erase or
  replacement was performed. The unformatted display is masked to avoid
  revealing credentials without a trustworthy field layout.

Current boundary: helper `ZM6360C6 EXEC A` may be partial; its source is unverified.
No live general command capture, actual captured CMS RC, or bulk listing has
passed. Next step is operator-assisted recovery of the outstanding IND$FILE
operation to a verified CMS Ready boundary, followed by source-verified helper
provisioning and the four read-only validation cases. Do not automatically retry
the failed upload or execute the partial candidate.

## Recovery and successful live command validation

- A bounded recovery resumed the known interrupted transfer, verified that the
  unformatted screen contained no nonblank data, and sent Clear once. The guest
  returned `INDFT099 ... file transfer canceled` followed by fresh CMS Ready.
  No HX, IPL, LOGOFF, erase or replacement was performed. Full evidence:
  `zvm-transfer-clear-recovery-evidence.json`.
- New helper `ZM537EF1 EXEC A` was absent before creation and uploaded
  successfully: the emulator reported 1633 bytes transferred in DFT mode. The
  immediate download exposed another race: DFT completion precedes restoration
  of the CMS command field. The guest received a truncated IND$FILE command and
  the receive timed out. No helper was executed on that attempt. Evidence:
  `zvm-command-recovered-evidence.json`.
- Added explicit empty-field/cursor verification before each transfer and a
  bounded wait for fresh CMS Ready after transfer completion. The offline fake
  now delays field restoration and rejects overlapping transfers. Reused the
  uploaded helper via download only; its source matched local ZMCPRUN.EXEC.
- Actual live MCP validation then passed all four cases:

  | Command | CMS RC | Records | Bytes | Verified frames |
  | --- | ---: | ---: | ---: | ---: |
  | QUERY CMSLEVEL | 0 | 1 | 32 | 5 |
  | STATE ZN57453B ZMCPMISS A | 28 | 1 | 45 | 5 |
  | QUERY DISK | 0 | 10 | 800 | 52 |
  | LISTFILE * * A | 0 | 345 | 6900 | 692 |

  Every result had output_complete, integrity_verified and cms_command_complete
  true; its RC matched the expected value. Record counts, native byte counts,
  checksums, frame sequences and fresh wrapper Ready were verified. The terminal
  disconnected and terminated cleanly. Full evidence:
  `zvm-command-verified-runner-evidence.json`.
- Failure responses now retain the sanitized command-capture screen history.
  Disconnect invalidates helper verification, so a new terminal session must
  verify the source again. These local safeguards were checked offline after
  the live run; no additional live invocation is claimed for them.
- Final offline suite: 70 tests passed. Syntax checks for the changed modules
  passed, and actual stdio MCP initialization and all nine tool checks passed
  again after the final safeguards.
- Codex registration now includes `--runner-name ZM537EF1`, with general input
  disabled and tool_timeout_sec=360. Actual subsequent Codex app-server discovery
  returned all nine tools with tools_error=null. It did not connect to Hercules.
- The five current recovery, provisioning, successful live, protocol and Codex
  discovery artifacts parse as JSON and contain neither credential value.

Current boundary: complete read-only command capture is live verified. The older
candidate ZM6360C6 EXEC A remains unverified and untouched. General source editing,
file replacement, builds and Git automation are not enabled. Next concrete step:
verified read-only CMS source download into a local Git worktree, preserving
file identifiers, record format and record lengths before designing writes.

## Native source-download follow-up

- Added `zvm_download.py`, `ZMCPGET.EXEC`, `test_zvm_download.py` and an explicit
  live validator. The separately enabled tool captures LISTFILE LABEL metadata,
  pins the numeric mode, captures native records twice and requires byte/record
  equality and identical before/after metadata. Host file input uses CMS
  Pipelines rather than text-mode IND$FILE, preserving record boundaries.
- Added a separate reader helper so `ZM537EF1 EXEC A` remains unchanged. Initial
  reader creation requires create_runner=true and live approval, with the same
  absent-name guard and source verification as command-helper provisioning.
- Local exports create only new snapshot directories under the configured root
  in an existing Git working tree. Native EBCDIC bytes, record lengths, per-record
  and whole-file SHA-256 hashes and CMS metadata are authoritative; printable
  UTF-8 text retains trailing blanks. No staging, commits or existing-file
  replacement occurs. Known credentials, symlink destinations, unsupported sizes,
  incomplete output and files that change during capture are refused. Matching
  reads/metadata are a consistency check, not an atomic host snapshot.
- Tightened generated terminal command identifiers to reject #, the CMS logical
  line separator. This also closes a hole in the existing STATE/LISTFILE Python
  allowlist; the existing command-helper source was not changed.
- Actual offline checks: 89 unit tests passed, including real local Regina REXX
  framing with only CMS input replaced, F/V and empty record preservation,
  checksum/length checks, changed-file refusal, credential refusal, destination
  checks, write-failure cleanup, short deadlines and shared-helper boundaries.
  Changed Python modules passed syntax checks. Actual stdio MCP validation
  discovered ten tools and verified downloads remain disabled by default.
- Codex registration enables downloads into this repository's `src/cms-sources`
  directory and keeps general input disabled. Actual Codex app-server discovery
  returned all ten tools with tools_error=null. No model turn or terminal
  connection was used by discovery.
- The first live download attempt stopped before creating a helper: bootstrap
  STATE correctly displayed RC28 but the parser selected an older Ready RC0
  above the echo during a partial host update. The absence guard refused
  creation. Evidence: `zvm-download-bootstrap-failure-evidence.json`. Fixed the
  parser to locate the echo on every snapshot and accept only Ready after that
  echo (or a verified continuation page). Added a regression test and retained
  bootstrap screen evidence on subsequent preparation failures.
- The subsequent explicit live retry created and source-verified reader
  `ZM02EA0B EXEC A`, then successfully downloaded `ZM537EF1 EXEC A1`:
  63 records, RECFM F, LRECL 80, 5040 native bytes. Both reads and before/after
  metadata matched. The validator compared every native byte against the local
  fixed-80 source; the native file, text view, per-record lengths and SHA-256
  were independently rechecked locally. SHA-256:
  `ea24607b7fef55373695ab40c18a178d0aad81880136791c787e26589c9ec063`.
- Saved native bytes, text and manifest in
  `cms-sources/snapshot-76f5d418b1716af321b80c94`. Full live protocol evidence:
  `zvm-download-evidence.json`. The terminal disconnected and terminated cleanly.
  No existing CMS source/helper was replaced or erased. The older partial
  candidate remains untouched. Git staging/commits were not performed.
- Updated the Codex registration to reuse reader ZM02EA0B, retaining the
  360-second tool timeout and disabled general input. Actual subsequent Codex
  discovery again returned all ten tools with tools_error=null. Registration
  and manifest configuration checks passed. Seven current evidence/snapshot
  files were checked to contain neither local credential value, including native
  data decoded from EBCDIC.

Current boundary: read-only native source download is live verified for F80.
Variable records, empty records and binary data have offline coverage only.
Reader preparation observes the overall download deadline. No source upload,
replacement, build or autonomous Git commit interface is enabled. Next concrete
step: a local edit/diff workflow that preserves a verified original hash and
record metadata, followed by an explicitly authorized, guarded upload design.

## Local edit/diff workflow and Codex CLI project handoff

- Added `zvm_edit.py` and two separately enabled tools, zvm_edit_prepare and
  zvm_edit_plan. They validate local snapshot hashes and native record boundaries,
  preserve pinned baseline bytes/metadata, and create separate working files.
  No terminal connection or CMS operation is used. Local credentials are loaded
  for redaction even without a guest login.
- Planning rejects changed originals/baselines, symlink files or parents,
  unencodable characters, ambiguous line endings, record overflow, binary text
  and known credentials. Fixed records are restored to the original width;
  variable trailing blanks remain significant. Full diff, native candidate,
  expected-original metadata/hashes, candidate hashes and record-change ranges
  are saved in a fresh plan directory. Identifier collisions never replace or
  delete older edit/plan directories.
- Actual full offline run: 106 tests passed (17 new edit tests), covering no-op
  native round trips, F/V/blank records, encoding, mutation/retarget detection,
  credential loading without login, collision preservation, symlink/FIFO/size
  rejection and partial-write cleanup. Syntax checks passed. Actual stdio MCP
  validation discovered thirteen tools and verified local editing is disabled by
  default, alongside the other default-disabled operations.
- Actual MCP local workflow validation used the recorded F80 helper snapshot.
  The no-op candidate matched every original byte. A comment-only edit changed
  record 1 and preserved the other 62 records; the candidate remained 63 F80
  records / 5040 bytes. Both source snapshot and original baseline stayed intact.
  Before/after status remained disconnected; disconnect reported no terminal
  process to terminate. Evidence: `zvm-edit-evidence.json`.
- Reviewable local demonstration:
  `cms-sources/edits/edit-cf2e85c4964a03e6b16360da/plan-5b7f9948798227f37cd66412/`.
  Its source.diff shows only the first-line comment change. Its plan explicitly
  declares upload_implemented=false, upload_authorized=false and no host
  operations. Native candidate/diff hashes were independently rechecked.
- Updated registration with --allow-local-edits, retaining verified helper names,
  disabled general input and 360-second tool timeout. Actual subsequent Codex
  app-server discovery returned all thirteen tools with tools_error=null. Fourteen
  current evidence/edit/plan artifacts were checked to contain neither local
  credential value, including native bytes decoded as EBCDIC.
- Read the local ../CHAT_STATE.md handoff for mostangrymike/ibm-sandbox. The latest
  recorded checkpoint is the GITC23 thin compatibility wrapper pending final
  host CI and real CMS validation; those external gates were not reverified in
  this tooling turn. Recorded the GitHub-first project and protected G generation,
  modules/disks and rollback requirements in AGENTS.md. Adapted manual web-chat
  handoff rules for authorized direct Codex CLI editing, testing, Git and MCP use.
  CHAT_STATE.md and production project source were not changed.

## Create-only upload validation

- Added `zvm_upload.py` and `zvm_upload_create_only`, separately disabled unless
  `--allow-create-only-upload` is configured. It accepts only a changed plan,
  exact plan and candidate hashes, fixed 80-byte printable records and the
  disposable `ZVxxxxxx EXEC A1` namespace. Immediately before transfer it runs
  `STATE` and refuses any result except CMS RC 28 (absent). IND$FILE uses
  `Exist=keep`; the s3270 manual defines this as failing when the destination
  exists. It then receives the file and checks exact native bytes against the
  approved candidate. The scratch file is retained; no cleanup or build occurs.
- The transfer and readback use the existing verified CMS command/reader helpers
  and the persistent serialized session. A failed/ambiguous transfer returns the
  sanitized diagnostic evidence and terminates that session. No replacement or
  erase path exists. Only fixed-80 source is supported; variable records are
  refused. No atomicity claim is made across the preflight and host transfer.
- Offline verification actually ran: 112 tests passed, including create-only
  success with simulated transfer/readback, occupied-target refusal, disabled
  capability, plan/candidate hash mismatch and no terminal access. Syntax checks
  passed. Real stdio MCP reported thirteen tools and confirmed upload disabled by
  default. Codex app-server independently discovered all thirteen; tools_error
  was null. Evidence: `zvm-upload-offline-evidence.json` and
  `zvm-codex-upload-discovery.json`.
- First approved live attempt connected, saw the transient 24x80 Hercules banner
  and stopped without input. On retry, `zvm_screen(wait_output=true)` observed the
  next host output event, which was the recorded login form. The already authorized
  login and startup flow reached CMS Ready; ZM537EF1 source verification passed.
- The exact absent target `ZV7C2E91 EXEC A1` was created from the approved plan.
  The first uploader result was a false negative: its ASCII transfer readback
  omitted F80 trailing padding. No existing CMS file was touched. A separate
  verified native download then completed twice with matching metadata and
  returned 63 F80 records / 5040 bytes whose SHA-256 exactly equals the candidate
  (`ce87917f84fe964aeffa33b65fc17930b06ebe4bdc92f57fad5d34da8fd55029`).
  Evidence: `zvm-upload-live-evidence.json` (initial direct-readback error) and
  `zvm-upload-host-readback-evidence.json` (native equality confirmed).
- Fixed the local DFT comparison to restore the declared 80-byte F-record width
  before comparing native bytes. The corrected code passes the offline regression
  suite (112 tests); it has not been rerun against CMS because the exact target now
  exists and must not be overwritten. The verified scratch file remains on A1;
  it has not been executed or erased. The standard Codex registration still does
  not enable create-only writes. Existing source replacement remains unavailable.

Current boundary: local edits pass offline validation and the live scratch file's
native contents match the approved candidate. The corrected ASCII padding branch
has offline coverage only. Existing CMS source replacement, build orchestration
and automatic Git commit are not enabled.

## Isolated minidisk-link observation

- An earlier helper-based implementation was removed because creating its
  `EXEC A` could modify the minidisk being queried. The current `zvm_query_links`
  accepts only a three-digit hexadecimal address, submits exactly `CP QUERY
  LINKS nnn` through a verified empty CMS command field, and advances observed
  MORE/HOLDING output only after a captured page. It reports complete output
  only with the exact command echo and a subsequent Ready prompt. Its results
  remain observational (`replacement_safe=false`, `link_query_is_lock=false`).
- This tool is separately gated by `--allow-query-links`; the installed Codex
  registration leaves it disabled. No live connection or query was attempted.
  `QUERY LINKS` is not a lock or a guarantee of future quiescence. CMS file
  replacement remains unavailable pending an operator-established single-writer
  procedure.
- For the current relocation and direct-screen query revision: all 116 offline
  tests pass, Python compilation passes, and stdio MCP validation returns the
  expected fourteen tools while disconnected. Codex CLI registration now points
  into `src/zvm-tooling` and uses `src/zvm-tooling/cms-sources` for local
  snapshots. These checks were run locally; no EC2/Hercules endpoint was used.

## 2026-10-16 connection diagnostics and live command validation

- Earlier rejected connections displayed `HHC01030I Connection rejected, device
  0200 unavailable`. The tunnel was reachable; the requested terminal device was
  unavailable. This was not established to be a login-layout or tunnel failure.
- Connect now rejects an observed Hercules rejection screen immediately, retains
  sanitized screen evidence and closes its emulator. A synthetic regression
  verifies that no input is sent on rejection. All 118 offline tests and the
  disconnected fourteen-tool MCP protocol check passed.
- The command validator passively waits for initial host output before login.
  Final live run reused source-verified ZM537EF1 without creating a helper.
  Startup verified CMS Level 27, Service Level 1302 and a fresh Ready prompt.
- All four command captures passed completeness and integrity verification:
  QUERY CMSLEVEL RC 0 (1 record), missing-file STATE RC 28 (1 record), QUERY DISK
  RC 0 (10 records), LISTFILE * * A RC 0 (347 records). Disconnect terminated
  the dedicated emulator. Evidence: `zvm-command-device-check-evidence.json`.
- Device selection remains explicitly 0200@. No CMS source replacement,
  scratch-file creation, cleanup, or build execution was performed.

## 2026-10-16 download/edit review workflow and terminal selection

This checkpoint supersedes the fixed-selector limitation above. All work is
local unless a live validation is explicitly identified below.

- `zvm_connect` now accepts `auto`, a four-hex-digit address plus `@`, or a
  1..8 alphanumeric group name plus `@` starting with a letter. Server `--device`
  configures the default; an explicit tool argument overrides it. The default
  remains `0200@`, and the host/port stay fixed at `127.0.0.1:3271`.
- New offline tests cover automatic, explicit and named-group selection,
  default/override behavior, host/action injection rejection, and invalid timeout
  types. All 120 unit tests pass. Default and `--device auto` stdio protocol
  checks expose fourteen tools, start disconnected and retain every capability
  gate. Python syntax parsing and tracked-diff whitespace checks also passed.
- Live observation-only pool test connected with `auto`, observed the login
  form, and disconnected cleanly without input. The Hercules banner identified
  `0:SYSG`; unrestricted selection can include the integrated console. A named
  automation group is preferable when deployment needs a restricted terminal
  pool. Named-group support has offline coverage only; no group was configured
  or tested live. Standard registration was not changed.
- Recognize both Hercules welcome-banner forms as `logo` so login's existing
  bounded passive observation can wait for the guest form. The observation
  validator now exits unsuccessfully if screen/status/disconnect fails after
  an initially successful connection.
- Live read-only download on `0200@` reused verified reader `ZM02EA0B` and
  downloaded `ZM537EF1 EXEC A1`: 63 F80 records, 5040 bytes. Both native reads
  and before/after metadata matched; native content exactly matched the local
  known helper source. This is a consistency check, not an atomic CMS snapshot.
  Session disconnect terminated the dedicated emulator. Evidence:
  `zvm-download-workflow-evidence.json`.
- New snapshot: `cms-sources/snapshot-ef93f03bf15f151212a00d3f`.
  The actual MCP local review validator prepared edit
  `edit-54528b6b91a0174491b3ac67`, verified a native no-op round trip, then
  changed only the first comment record in its separate working file. Both
  snapshot bytes and manifest remain unchanged; baseline, candidate and plan
  SHA-256 hashes independently matched. All eight review verification flags
  passed; no host session was opened by local editing. Evidence:
  `zvm-edit-workflow-evidence.json`.
- Review artifacts are under
  `cms-sources/edits/edit-54528b6b91a0174491b3ac67/plan-60bcb0204e85e69780025e4d/`:
  `source.diff`, `candidate.ebcdic`, and `plan.json`. The plan explicitly
  authorizes no upload. No scratch target was created, replaced or erased.
- Codex discovery succeeded through the installed app-server: exactly fourteen
  registered tools, `tools_error=null`, no model turn or terminal connection.
  Evidence: `zvm-codex-workflow-discovery.json`. This closes the previous sandbox
  failure of the discovery verifier; running with local runtime access resolved
  it without changing server registration.

The read-only download/local-edit/review milestone is complete. Existing CMS
source replacement and build orchestration remain unavailable. The previously
verified `ZV7C2E91 EXEC A1` scratch file remains retained; this checkpoint did not
re-exercise create-only uploads or establish production replacement safety.
Tooling source and generated evidence are still local/uncommitted; no Git push
or production project checkpoint change was performed.

## 2026-10-16 portable source distribution checkpoint

- Extracted six credential-sanitized recorded-screen fixtures into
  `fixtures/terminal-screens.json` with provenance in `fixtures/README.md`.
  Existing login/startup/screen tests now load fresh copies via
  `test_zvm_fixtures.py`; full live capture files and diagnostic logs are no
  longer test dependencies. Original local evidence was retained.
- Added local ignore rules for the credential-bearing legacy pipelines,
  captures, snapshots, edit workspaces, caches and builds. These files were not
  deleted or modified. No legacy credentials were included in the distribution.
- Added `build_zvm_tooling.py`: explicit 36-file source inventory, reproducible
  gzip/tar metadata, per-file SHA-256 source manifest, optional configured-password
  scan, extracted-source hash verification and complete isolated offline checks.
  Every build uses a new output directory and preserves its report on failure.
- The initial isolated distribution build passed all 122 tests with zero skips,
  both disconnected MCP protocol configurations, the default upload gate, and
  the actual MCP local-edit/review demo against a synthetic helper snapshot.
  The build's configured-password scan passed. It required no local live
  evidence or external Git checkout and made no guest connection.
- Improved create-only upload failure evidence: retain the exact target identity,
  whether a transfer was attempted, whether a partial host file may exist, and
  explicit false values for readback verification, retry and cleanup. New tests
  simulate a failed send and a readback mismatch; both stop without another send
  or cleanup. No live scratch creation was attempted for these changes.
- Standalone live download/local review and Codex discovery qualification from
  the preceding checkpoint remain valid evidence of those specific tested
  revisions. This checkpoint establishes offline packaging and failure-path
  tests, not a new live upload or production source-replacement qualification.

Current handoff: run `build_zvm_tooling.py` for a source bundle and report under
`builds/`. The source package is ready for review. All tooling remains local and
uncommitted. Any next live create-only test needs an exact absent disposable
target; the retained `ZV7C2E91 EXEC A1` must not be overwritten or erased.
Production source replacement additionally needs the operator-established
single-writer procedure, backup/rollback and exact target authorization before
implementation or activation. CMS build execution remains disabled.

## 2026-10-16 corrected create-only upload LIVE PASS

- Scoped live approval covered exactly one absent disposable target:
  `ZVF69FE6 EXEC A1`, using edit `edit-54528b6b91a0174491b3ac67`, plan
  `plan-60bcb0204e85e69780025e4d`, plan SHA-256
  `e211f35230f8fe91cdacc3c10ac7f4a55a49f026b98db39a907a9e0c68807551`, and
  candidate SHA-256
  `ce87917f84fe964aeffa33b65fc17930b06ebe4bdc92f57fad5d34da8fd55029`.
- The updated live validator checks every prerequisite result, persists each
  completed stage, reports an actual failing exit status on failure, and can
  run optional independent native verification. It accepts the common terminal
  selector without changing the default `0200@` or standard registration.
- Live connection/login/startup passed, QUERY CMSLEVEL established the fixed
  CMS-level/fresh-Ready boundary, and configured helper ZM537EF1 was source
  verified. Fresh target absence was required before DFT creation. Corrected
  ASCII DFT readback restored F80 padding and matched the candidate directly:
  63 records / 5040 native bytes. This closes the previously offline-only
  corrected-padding qualification gap for this tested source format.
- The existing source-verified reader ZM02EA0B independently downloaded the
  target with matching before/after metadata and two identical native reads.
  Both FILEREAD captures reported RC 0, 63 records, 5040 bytes, complete output
  and verified integrity. Downloaded SHA-256 exactly matched the candidate.
  Snapshot: `cms-sources/snapshot-23196ea12f1e9c0830b8d16f`.
- Final validator result: `passed=true`, `native_candidate_equal=true`.
  Disconnect terminated its dedicated emulator. Full sanitized evidence:
  `zvm-upload-native-qualified-evidence.json`.
- Retain `ZVF69FE6 EXEC A1` and the older `ZV7C2E91 EXEC A1`. Neither was
  executed or erased. No existing CMS source, production MODULE, protected
  original G stage/index, or standard registration was replaced.
- New regression cases require failed stages and mismatched/missing native
  verification to prevent PASS. Async flow tests prove failed startup prevents
  upload and failed native verification never repeats a successful upload.
  The isolated distribution check passes all 128 tests with zero skips, both
  disconnected protocol configurations, the default upload gate and local
  review. The explicit source inventory now contains 37 files, including
  `PIPELINE-READINESS.md`.

Current status: guarded download/edit/review/create-only scratch workflow is
qualified for the tested fixed-80 source path. Production replacement and CMS
build/test execution remain unavailable. The next implementation needs an
exact source target and build/test recipe plus operator-established writer
exclusion and backup/rollback authority, as detailed in PIPELINE-READINESS.md.
These transaction inputs have been requested; a generic continuation does not
select a production file or establish writer exclusion. Source and evidence
remain local/uncommitted.

## 2026-10-16 replacement/build transaction planner checkpoint

- Added `zvm_operation_plan` under the existing local-edit capability gate.
  This is a fifteenth MCP tool and has no terminal/execution interface. It
  validates a pinned changed source plan, original snapshot/metadata, edit
  definition, baseline bytes, current working text, encoded candidate, record
  hashes and diff before writing one new local operation manifest.
- Recipe review requires exact command tokens, numeric file IDs, unique step
  names, create-only A1 outputs, expected RCs and printable output markers.
  It checks the 139-character command-field limit, input/output collisions,
  external input hashes and producer-before-consumer order. Administrative and
  destructive verbs, separators, wildcard/path-like IDs, protected helper/scratch
  outputs and retargeted source/rollback identities are rejected.
- Incomplete recipes return explicit missing inputs. Supplied writer-exclusion
  and rollback descriptions remain unverified claims. Even complete reviews
  retain execution_authorized=false, execution_implemented=false,
  replacement_safe=false and host_operations_performed=false. G/non-A1 source
  targets and helper/scratch namespaces remain explicitly blocked. Command
  semantics and implicit output inventories remain unverified.
- Added fifteen offline planner tests covering binding, changed artifacts,
  missing fields, input/output ownership, forward dependencies, injection,
  protected targets, redaction, failure cleanup and non-overwrite collisions.
  The complete isolated source build passes 143 tests with zero skips.
- Added `validate_zvm_operations.py` and an actual disconnected MCP operation
  review to the distribution build. Eight independent verification flags check
  receipt hash/source-plan binding and disabled execution/host-operation states.
  The explicit distribution inventory now contains 40 source/fixture files.
- Actual local demo against the retained command-helper edit produced
  operation `operation-6d7ca5e5983bcd6583cd9cd6`, SHA-256
  `305e7bd1bf78869e07c7f23f175299b9f9e4417bc45dc9210346b629ccf2e341`.
  It correctly reports target `ZM537EF1 EXEC A1` as protected and requires the
  build/test recipe, operator writer-exclusion procedure and rollback procedure.
  It does not propose activating or replacing that helper. Evidence:
  `zvm-operation-review-evidence.json`.
- Installed Codex client discovery succeeded with exactly fifteen tools and no
  catalog error. Evidence: `zvm-codex-operation-discovery.json`. No model turn
  or CMS connection was started. Standard registration arguments were unchanged.
- No guest session, CMS write, source replacement, build/test execution or
  scratch cleanup occurred for this planner work. Previously qualified scratch
  files remain retained. Source, manifests and reports remain local/uncommitted.

Current handoff: transaction review is implemented and packaged. Production
execution is still unavailable; the planner makes the missing exact transaction
inputs and unresolved host-safety/semantic gates inspectable instead of
implicitly treating a generic continuation as production write authority.

## 2026-10-16 source-control and CI checkpoint

- Prepared the first local source-control checkpoint of the guarded tooling:
  41 explicitly listed source/fixture/template files plus the new repository
  `.github/workflows/zvm-tooling.yml`. Credential-bearing legacy pipelines,
  captures, live evidence, CMS snapshots, edit workspaces, caches and generated
  builds are excluded and retained locally. Unrelated production/transfer-script
  modifications are excluded from the checkpoint.
- The new dedicated workflow has Ubuntu 24.04 jobs for Python 3.12 and 3.14,
  read-only contents permission, credential persistence disabled at checkout,
  source-area push/PR triggers, optional manual dispatch and 30-day build artifact
  retention. It performs only offline build/tests; no credential file, model turn,
  TN3270 tunnel, live validator or CMS write is part of the job.
- Added packaged workflow template `ci/zvm-tooling.yml` and installed an exact
  byte-identical repository copy. The existing native staging workflow is
  unchanged. Both new workflow copies passed official actionlint 1.7.12 syntax
  and expression validation (optional shellcheck/pyflakes integrations disabled)
  and independent structure/permission/matrix/parity checks.
- Build reports now record runtime/package identities and tool paths. Archive
  reproduction is enforced inside every build, before isolated extraction/tests,
  rather than relying only on a separate manual comparison.
- This checkpoint is local. It does not assert a GitHub push, a completed Linux
  matrix run or a new full native staging CI result. Actual remote CI qualification
  follows publication and inspection of the exact committed revision.

## 2026-10-16 published CI compatibility correction

- Published checkpoint `f07fe210a4b13acf901b12447f3e844901d6571b` to canonical
  `main`. The existing native staging workflow passed in run `38995811834`.
- The new offline matrix run `38995811848` installed all dependencies and
  verified workflow parity, but both Python jobs failed the real local emulator
  test: Ubuntu's s3270 4.1 rejects `-set aidWait=false`. This was a launch-option
  compatibility failure, not a CMS connection or a host qualification failure.
- Replaced assignment syntax with portable `-clear aidWait -clear trace`.
  The real offline emulator test now also asserts the launch arguments and
  queries both effective settings as false before taking a disconnected
  snapshot. Local s3270 4.5 passes; Linux qualification requires inspecting the
  follow-up matrix run, not assuming that a local pass proves compatibility.
- No guest session, CMS command or CMS write was used for this correction.

## 2026-10-16 offline failure-rehearsal implementation

- Commit `86e1cba0cdbf7d1c73ef25ac147502f6ea510b58` passed both Ubuntu tooling
  jobs in run `38996039265` (143 tests each; zero failures/errors/skips), and
  native staging run `38996039236`. Both Linux archives matched the Mac archive
  SHA-256 `d13d0dd493e74f9665ff5f3adddef8d5a19dabe7cc4588b2d9ac38608f872cb6`.
  Local receipt: `zvm-ci-qualified-evidence.json`.
- Added a standalone read-only symbolic transaction rehearsal. It pins the exact
  operation manifest SHA-256 and reconstructs that receipt after revalidating the
  source review, native snapshot, baseline, current working text, candidate and
  diff. Noncanonical/tampered receipts, stale source artifacts, incomplete recipes,
  protected targets, disabled local edits and symlink files are refused.
- Shared operation receipt construction between the planner and revalidator;
  the planner's existing schema, authority flags and blockers are unchanged.
- The full two-step fixture matrix covers one synthetic success path and nineteen
  injected failures. It models prewrite aborts, uncertain partial transfers,
  unverified/verified candidate states, per-step stop boundaries, possible output
  files and final-check failures. No failure continues or triggers automatic
  recovery. Every successful checkpoint is an explicit synthetic assumption.
- New unit tests cover every stop prefix, multistep dispatch ordering, uncertainty,
  tampering/stale artifacts, no local artifact mutation, CLI JSON and secret-free
  errors. A separate isolated validator exercises the CLI, checks the matrix and
  retains all twenty traces in `rehearsal-evidence.json` during a package build.
- Source inventory grows from 41 to 44 files. CI's reviewed template adds the
  rehearsal report to retained artifacts. This entry records implementation scope,
  not an unobserved remote result for the follow-up commit.
- No host adapter, MCP capability, CMS session, source replacement, build/test
  execution, retry, restore or scratch cleanup is added or performed.

## 2026-10-16 existing G attachment and direct-screen diagnostic qualification

- Fixed direct-screen paging after a real virtual-DASD query reached MORE.
  The observer now captures a changed host page before one Clear, never repeats
  paging input for unchanged output events, and permits an incomplete RUNNING
  page to finish without sending keys. A final page need not repeat the original
  command echo; it must have fresh Ready below its output. Return codes are not
  inferred from these observational diagnostic screens.
- Corrected echo matching when the configured userid is masked in the fixed
  directory query. Returned command/evidence remain redacted. Output rows now
  exclude unrelated earlier console text and are retained across captured pages.
- Added a regression for Ready arriving during startup's final field recheck:
  it is observed without unnecessary Enter or BEGIN. Existing layout/provenance
  checks and generic-input prohibition remain in place.
- Actual fixed read-only inspection completed for virtual DASD, 0600 location,
  its MAINT directory location, real 0127 volume links, and QUERY DISK. Both
  location responses identify VMCOM1/0127 start6000 size1600; virtual 0600 is
  already attached R/W. G is not accessed. The sixteen volume links match the
  documented baseline and no PMAINT/0141 link appears. Evidence:
  `zvm-gdisk-observation-evidence.json`. Do not self-LINK an already present 0600.
- Added a separately explicit existing-filesystem ACCESS option guarded by that
  exact identity/link baseline and unused G/600. It never LINKs, FORMATs, RELEASEs,
  erases or replaces. Postchecks use the source-verified read-only runner, actual
  RC and complete native output. Actual access results, if run, are retained
  separately in `zvm-gdisk-access-evidence.json`; this entry alone claims no access.
- The 45-file source package includes the fixed local validator. New regressions
  cover all query choices, paging fragments/no repeated keys, redacted echoes,
  startup races and rejection of mapping, volume-link and mode collisions. No new
  MCP tool or default-enabled capability is introduced. Production replacement,
  CMS build/test execution and automatic recovery remain unavailable.

Actual follow-up access PASS: `ACCESS 600 G` restored the already attached
filesystem without LINK, FORMAT or import. The verified native runner captured
QUERY DISK with `GIT600 600 G R/W 1600 3390 4096`, and STATE for both
`M173NET STAGE G1` and `M174NET INDEX G1` returned actual RC 0 with complete,
integrity-verified output. This proves access and file presence, not full content
hashes. The dedicated terminal disconnected normally. Source replacement,
build/test execution, erasure and rollback were not performed. Durable local
evidence: `zvm-gdisk-access-evidence.json`.
