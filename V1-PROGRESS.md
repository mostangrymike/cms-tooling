# Version 1 progress and restart checkpoint

Updated: 2026-10-17. Repository: mostangrymike/zvm-tooling.

## Qualified version 1 fixture checkpoint

The disposable ZTQUAL C development cycle is qualified. The original live
journal proves native baseline/backup creation, candidate replacement,
explicit successful-path source recovery and reapply, one CMSCLNK build with
actual CMS-stage RC0 and one ZTQUAL execution with actual RC0 and complete
`ZTQUAL CANDIDATE PASS 43` output. The resumed audit did not repeat those writes,
the build or the execution.

Final audit: zvm-fixture-output-qualified-evidence.json, all 22 steps complete,
passed=true, source_recovery_qualified=true, postbuild_audit_passed=true.
Journal SHA256: 58e02425f55b224c396a5b726095bbc46900d2ef918650be168b4fd6ca420eb7.
The exact original and completed-output journals remain bound by their hashes.

| Retained native output | Records / bytes | SHA256 |
| --- | --- | --- |
| ZTQUAL ASSEMBLE A1 | 47 F80 / 3760 | cb0fd2b0eeee7dc26df726bb12a60e9dd44a2c90bf9f3509904e250183853df9 |
| ZTQUAL TEXT A1 | 10 F80 / 800 | 06b33b399c592ba799d1493623dc9d1a583530a99732ec5b6a537afeda6d46ab |
| ZTQUAL LISTING A1 | 234 F121 / 28314 | cab6145f56b7d2a1eb2f8ed75dfc26031119ff81bdf765d96a8af9913b7bc73b |
| ZTQUAL MODULE A1 | 3 V52312 / 56280 | d2512ab7d095851ad254db02dba32869a8e50dd93c9e805b0a361c4240468707 |

MODULE native record lengths are [80, 52312, 3888]. The output-only reader
ZME09C7C EXEC A was created absent and source-verified, and must be retained.
It is separate from all existing helpers. MODULE passed two identical native
reads and matching metadata. Earlier ASSEMBLE/TEXT/LISTING snapshots were
revalidated locally and retained honestly as earlier host-read evidence.

Fresh final source and backup native hashes matched the approved candidate
and baseline respectively. All six declared transients returned actual RC28;
exact ZTQUAL and ZTQBACK inventories returned actual RC0. FILEDEF returned
actual RC0 and exactly `DMSFLD324I No user defined FILEDEFs in effect`, followed
by the correlated fresh Ready boundary. Disconnect terminated=true.

All qualification files, outputs and helpers remain retained. No fixture source
write, rebuild, execution or cleanup occurred during this resumed audit; its
only CMS file creation was the new output-only helper. Production qualification,
writer exclusion and replacement safety remain false. Successful-path fixture
recovery, offline failure tests and observed read-capture fail-stops do not
qualify general production recovery or fault injection.

Implementation passed 245 offline tests with zero failures/errors/skips and
all isolated protocol/review/rehearsal gates. The exact published source commit
f0a38d222db224b6f090b43e3f15c5cf61607317 passed both GitHub Actions runs
39052151534 and 39052154783. This subsequent checkpoint records the final
qualification documentation; implementation/source contract remains
9ad185a569d211cdfb1af36affba93ff73d47158aacf2e977e07a1e3cb4fdf19.

No live continuation is needed. Do not rerun create/build to reproduce evidence.
No dedicated terminal remains active. The separate production project and thin
GITC23 wrapper are outside this completed tooling-fixture qualification.

## Qualification history (historical checkpoints)

Resume inspection (2026-10-17): the formerly active session66836 has ended.
The authoritative journal stopped at `native output ZTQUAL LISTING A1` with
CaptureError, after one complete 234-record / 28314-byte native read and a
partial second read. No LISTING snapshot, MODULE verification or final audit
pass exists. Prior journal SHA256:
422d5b641ffdf6460c4c4cb23a8bf3ea6dde5ee59750e909125b00cd4a4bde3d.
The source recovery, candidate reapply, build/test, ASSEMBLE and TEXT results
remain complete. Do not rerun the original create/build workflow.

Authorized login/startup during resume reached a fresh Ready(00012) below
`ZM1 91CDA5088C6974C7 F 660 ACK`: the abandoned reader terminated with an
acknowledgement failure. The unchanged command guard then refused helper
verification because unresolved protocol output remained visible and terminated
its terminal. No files were written or commands/builds repeated. Sanitized
observation: zvm-fixture-resume-observation-evidence.json. No terminal remains.

Prepared validate_zvm_fixture_audit.py as a separate default-off read-only
post-build continuation. It binds the exact prior journal and current source
contract, re-verifies both helpers without creation, and retains a new journal.
The explicit --recover-failed-reader option permits only one guarded Clear then
QUERY CMSLEVEL, requiring the exact failed nonce/sequence and fresh Ready(00012)
at a blank verified command field. The operator explicitly approved this
recovery and subsequent read-only audit with "approval yes", followed by
"approved for all" during this resume. Isolated offline build passed all 235
tests with zero failures/errors/skips plus protocol/review/rehearsal gates:
builds/build-20261017T163247Z-8481a798/build-report.json. Archive SHA256
2a45dd4cef85f63e2c6d384dfbbf359dabddd15340cff2a242aaa2febf9ba0d0.
The first audit attempt stopped safely before Clear: reconnect startup's fixed
CMSLEVEL probe reached clean Ready and the exact failed-frame recovery boundary
was no longer present. No Clear or fixture/file audit operation ran. Retain
zvm-fixture-postbuild-audit-evidence.json. Terminal terminated on guard refusal.
A new read-only audit, with recovery disabled, completed ASSEMBLE, TEXT and
LISTING native verification. LISTING is 234 F121 records / 28314 bytes, SHA256
cab6145f56b7d2a1eb2f8ed75dfc26031119ff81bdf765d96a8af9913b7bc73b,
snapshot cms-sources/snapshot-2b23124e76dd15c37615d8af. The audit then stopped
before MODULE reading because its metadata exceeds existing capture limits.
Evidence: zvm-fixture-postbuild-final-evidence.json; terminal terminated=true.
No implementation changed between attempts; all 235-test offline gates apply.
The fixed read-only FILEMETA diagnosis completed and disconnected normally:
zvm-fixture-module-meta-evidence.json. Exact MODULE geometry is V52312, three
records, 14 blocks on MNT191; standard source reader limit is 4096 bytes/record.
Prepared ZMCPOUT.EXEC / zvm_fixture_output.py for only this retained MODULE.
The standalone audit's explicit --create-output-reader can create one absent
random source-verified helper, retaining every old helper. It emits bounded
4096-byte native chunks with an original logical-record-length map; two reads
and metadata must match before an immutable output-only snapshot is saved.
Source editing/download limits and standard command deadlines remain unchanged.
The long-output reader alone permits bounded 600-second captures with a
1500-second overall read deadline. Previously verified output snapshots can
be revalidated locally and bound via the exact completed-output journal hash;
they remain explicitly retained evidence, not fresh host reads. Changed-source
offline qualification passed: all 245 tests, zero failures/errors/skips and
all protocol/review/rehearsal gates. Report:
builds/build-20261017T165242Z-5b91ea48/build-report.json. Archive SHA256
f57f55e57e88c906bc139b767ae02b6fb4602b651e2c1538803b017a8cae8cad.
The operator's full approval covers this fixture continuation and explicit new
output-reader provisioning. Final live audit is now active in session79976,
evidence zvm-fixture-output-qualified-evidence.json, contract
9ad185a569d211cdfb1af36affba93ff73d47158aacf2e977e07a1e3cb4fdf19.
It pins completed-output journal SHA256
2861abdf4e55065b3316d8e9c3b784e2c378e3a562b1276c385aa5fddb16ae91.
Do not open another terminal or edit bound implementation files while active.
MODULE/final audit remain unqualified until their successful journal results.
New output-only helper ZME09C7C EXEC A was created absent and source-verified
by round-trip download. Retain it; never overwrite or erase it in a continuation.
Any later audit must explicitly --output-reader ZME09C7C and reverify its source,
without --create-output-reader. Native MODULE capture is currently active.
The audit allows a 900-second total download budget while preserving 300-second
individual captures and standard MCP limits/defaults. It never calls BUILD,
TEST, source transfer, restoration, erasure or cleanup. Offline validation of
these new changes passed 47 targeted tests and the full isolated build. This
progress prose was updated after the bundle; no implementation changed. All
older active-process prose below is historical.

Post-build artifact checkpoint: native ASSEMBLE verification passed (47 F80
records / 3760 bytes; cb0fd2b0eeee7dc26df726bb12a60e9dd44a2c90bf9f3509904e250183853df9)
and native binary TEXT verification passed (10 F80 records / 800 bytes;
06b33b399c592ba799d1493623dc9d1a583530a99732ec5b6a537afeda6d46ab).
LISTING native verification is active in session66836. Do not claim MODULE,
LISTING, final inventory or whole-run pass before their journal results exist.
Source recovery/build/test have passed and must not be repeated just to obtain
later read-only evidence. Current implementation is saved on GitHub at
a11645bae0c84d076ecdbe6d13c7e978b1809a2c, PR1; CI223 passed. Local progress
updates after that source checkpoint are being retained separately.

Core live cycle passed: explicit source recovery matched the baseline native
bytes, then candidate reapply matched its exact native hash. All declared
outputs/transients were absent immediately before the one build. CMSCLNK build
returned actual CMS-stage RC0 with the expected built marker. ZTQUAL execution
returned actual RC0 and complete verified native output `ZTQUAL CANDIDATE PASS 43`.
The run is NOT yet marked passed: native ASSEMBLE/TEXT/LISTING/MODULE output
snapshots and final source/backup/transient/inventory/FILEDEF checks remain.
Current active step is native output ZTQUAL ASSEMBLE A1 in session66836.
Retain generated artifacts and the native baseline backup. Never rerun build
or create to collect evidence; use the journal's completed build/test results.

Live write/recovery checkpoint: baseline creation/readback, local pinned edit
review, new ZTQBACK C A1 native backup and candidate replacement/readback all
passed. Fresh backup native verification also passed. Explicit successful-path
source recovery is now running, followed by candidate reapply and one build.
ZTQUAL C A1 and ZTQBACK C A1 now exist; they are retained qualification files.
Do not rerun the create workflow, erase either file, or infer their current
content from this prose; the journal records each native hash and later step.
Canonical baseline native hash61b02abb63e32204ceff16c0ac61a8729f45a5a1942fc0d4f94bb774b73f8003;
candidate41586cfd4d6c5b5c62d5f4550636b0c7e7bb6699121ef812c7b5ea7167eb6ae2.

Current live boundary: third run passed all source pins, namespace absence,
global-map absence and exact empty user-FILEDEF check. Step55 `create baseline
and native readback` has started. ZTQUAL C A1 MAY NOW EXIST (including partial
state until the journal confirms native readback); never rerun create blindly.
Process exec session66836 remains active and owns the only dedicated terminal.
Inspect zvm-fixture-qualified-live-evidence.json for the newer authoritative
result; all journal writes are flushed/fsynced before/after each step.

Remote CI run39047781434 completed successfully for a11645bae0c84d076ecdbe6d13c7e978b1809a2c.
Third live attempt is active in exec session66836 (one dedicated s3270).
Startup CMSLEVEL verification and re-verification of ZM537EF1/ZM000175 passed;
fresh compiler preconditions are running. The authoritative current state is
zvm-fixture-qualified-live-evidence.json. Do not start a second terminal or
modify bound implementation files while it is running. Progress documentation
can be updated independently; source contract validation runs before every step.

Third attempt starting after successful full isolated validation:
builds/build-20261017T160307Z-3181285a/build-report.json, 223 tests, zero
failures/errors/skips, all protocol/review/rehearsal gates passed. Bundle SHA256
85e6923a7fbec0096bdabe12d750d19bee856c0aca2c29ebcf662b7927c4e40f.
Exact contract 177b1481ad1571b3a407cccee70b0974178e5bfe87e3d803f349b7dca43c088f.
New evidence zvm-fixture-qualified-live-evidence.json; --reuse-fixture-helper
re-verifies ZM000175 instead of creating another helper. Local commit87c6799
matches remote commit a11645bae0c84d076ecdbe6d13c7e978b1809a2c by source tree
0a05e693fcca5db68280aacfbc7f227e9bae5095. Remote CI run39047781434 is in progress.
Do not run this again if a source/backup/partial output now exists; inspect the
persisted journal and exact affected native files before any continuation.

Second live attempt stopped safely at FILEDEF precheck, before baseline/backup
creation. All three installed native source pins matched. Actual complete
FILEDEF result was RC0 and exactly `DMSFLD324I No user defined FILEDEFs in effect`.
The guard expected different wording and refused; updated to allow this exact
verified empty-state record only. No source/backup, compile, restore or cleanup
occurred. ZM000175 EXEC A was created and retained source-verified, and the
session disconnected cleanly. New --reuse-fixture-helper re-verifies only this
fixed retained helper instead of creating another; no arbitrary helper name.
New tests cover this message, reuse, real partial-transfer fail-stop, metadata
change before replacement and existing-backup refusal. Full offline validation
must pass before a third run with a new evidence filename. Do not overwrite
zvm-fixture-probe-live-evidence.json or its helper.

Remote checkpoint validation: draft PR
https://github.com/mostangrymike/zvm-tooling/pull/1 at remote commit
7ce6948066c59022a612eb26ca550a2a9252f27c. GitHub Actions run 39047453523
completed with conclusion=success (observed through the connector), URL:
https://github.com/mostangrymike/zvm-tooling/actions/runs/39047453523.
This is real remote CI for that source checkpoint, not live CMS qualification.
During the active second live run, CMSCLNK native hash revalidation passed;
GCCE native readback is currently in progress. Journal remains the authoritative
step-by-step state if this prose is older than the active process.

Live continuation (second attempt): guarded CMSLEVEL probe reached fresh Ready;
existing ZM537EF1 command helper was source-verified. Created and source-verified
new fixed-action helper ZM000175 EXEC A (BUILD/TEST/FILEDEFS only). Retain it;
do not overwrite/erase or assume its session verification persists after a
disconnect. It is separate from all older command/download/scratch helpers.
Fresh disk identity, all declared command-shadow absences and GCC/ASSEMBLE
binary presence checks passed. Re-downloading/pinning installed compiler sources
is in progress in exec session45033, evidence zvm-fixture-probe-live-evidence.json.
No fixture source or backup created yet. Never start another terminal while
this workflow owns its dedicated process.

Latest checkpoint: reconnect/probe and failed-result-journal fixes passed the
full isolated build: builds/build-20261017T155611Z-6c0bd98f/build-report.json,
218 tests, no failures/errors/skips, all protocol/review/rehearsal checks pass.
Bundle SHA256 4eb06298f7e80c2a992a2e75476ee85fdefa09ee36a6f2d0394902dfe78b226d.
Current live contract bc559b9bfccf4d7c3682c7ee81cb5906851bfa9621ffe5287e950b6c23e98436.
Second attempt evidence will be zvm-fixture-probe-live-evidence.json.
Local commits 00b7c4d and 38b596c are saved. Via the GitHub connector, identical
source tree ba2735ff4af03d848d2a083ac482806d569ce2ce was saved at remote commit
7ce6948066c59022a612eb26ca550a2a9252f27c on
https://github.com/mostangrymike/zvm-tooling/tree/codex/disposable-c-qualification.
Remote and local commit IDs differ because the connector creates commits;
their source tree identity was checked. No merge into main or production write.

Live attempt zvm-fixture-live-evidence.json stopped at reconnect startup before
helper/source creation. Login reached CP READ; BEGIN printed bare CMS at row9
with an empty verified field but no Ready. No source writes, builds or helper
creation occurred; disconnect terminated=true. Failure screen preserved. Fixed
executor now requests the existing explicit QUERY CMSLEVEL verification probe.
Its guard additionally accepts only the exact observed bare-CMS/BEGIN/banner
shape after actions BEGIN,Enter; arbitrary RUNNING/input screens remain refused.
Added offline guard and failed-result journal tests; all offline gates must
pass before a new attempt. Existing evidence must not be overwritten.
Implementation saved in local commit 00b7c4d on branch
codex/disposable-c-qualification. Shell Git push failed due absent HTTPS
credentials; no remote branch/CI yet. Current reconnect/probe fixes are newer
uncommitted work. Native backup/source have still not been created.

Ready for live fixed qualification: latest isolated build
builds/build-20261017T155226Z-5b386974/build-report.json passed all 216 tests,
no failures/errors/skips, plus all protocol/review/rehearsal gates. 58-file
archive SHA256 98bd840d6a9397cd630057b61609900d8aa2431f0683b7c8cce924e7bba718e1.
Only explanatory documentation changed after this bundle. Exact fixed execution
contract SHA256 b2a24eaabb85a8f63bf100da8e266477941c18c8078c46a1614e28cf16d9ffb6.
Next live evidence file: zvm-fixture-live-evidence.json. Explicit recovery
qualification is enabled for only the freshly created ZTQUAL source. Do not
repeat this run if evidence already exists; inspect its last intent/result first.

Implementation checkpoint: added validate_zvm_fixture.py (default-off fixed
ZTQUAL executor) and ZMCPQUAL.EXEC (only BUILD/TEST/FILEDEFS; unchanged native
capture protocol tail). Existing MCP allowlists/registration and review-only
planner remain unchanged. New test_zvm_fixture.py initially passes 10 tests,
including every workflow failure boundary, wrong contract/recovery flag,
protected targets, native/RC/marker failures, pinned local artifact tampering
and exclusive owner-only journaling. Full isolated build and live run pending.
The fixed workflow creates a baseline and distinct native backup, replaces
candidate, explicitly restores backup on the successful path, reapplies candidate,
builds/tests once, then verifies native outputs and transient absence. It does
not establish writer exclusion or production safety. Every step retains an
intent record before terminal activity; failures retain partial/uncertain state.

Full-build attempt builds/build-20261017T154939Z-234f2137 stopped because new
fixture tests emitted progress lines to stdout, confusing the build JSON parser.
Corrected the test harness to capture those lines; no live path was attempted.
Expanded offline fixture coverage to 11 tests, including nonempty FILEDEF
refusal before source creation and exact final namespace inventory. The full
isolated build is running again (exec session48600). Old operator evidence
confirms disconnect terminated=true; no dedicated live terminal remains.

Build builds/build-20261017T155045Z-a8651b18 passed 216 tests, zero failures,
errors or skips, plus all isolated protocol/review/rehearsal gates. Bundle SHA
ca8939108976e859533ebde15d4473f263be6e6edd07eb431c91b83ea307c4eb (58 files).
Afterward added fresh QUERY DISK checks for MNT191/191/A/RW and GCCLIB/29D/F/RW,
STATE absence guards against earlier compiler command/parameter shadows, and
presence of GCC MODULE F1 and ASSEMBLE MODULE S2. Updated targeted fixture tests
pass all 11. Final full build of these additional checks is pending. No live
fixture helper or source created yet.

Restart checkpoint after permissions change: Codex now has Full access with
approval policy never. User requested quota monitoring and checkpoints; no
remaining subscription quota API is available, so save progress incrementally
rather than promise detection of zero. Active operator driver 3051/session1632
was interrupted with SIGINT to execute its disconnect/finally block after
write_stdin to the old approved session was rejected by the changed policy.
Verify session_terminated in zvm-operator-session-evidence.json before reconnect.
All queued read-only queries finished: ZTQUAL SYSUT1/2/3 A4, ZTQUAL LOADMAP A5,
LOAD MAP A5 and ZTQBACK C A1 were absent (actual RC28); LISTFILE ZTQUAL * A
returned RC28. No source has been uploaded, replaced or compiled yet.
STD380 PARM F1 download completed: snapshot-d06efde5e5fbe6594ed7b50d,
one V54 record, SHA256 a30a03f46abaec885053c550c1cc2d181a368bd5ca4af59488f63924e06b019d.
Effective parameters: -Os -DUSE_MEMMGR -o dd:out - -S -ansi -pedantic-errors.
Next implementation: fixed standalone ZTQUAL workflow, leaving general MCP
and operation-review gates unchanged. Retain native baseline backup ZTQBACK;
use native download bytes to create it, avoiding COPYFILE's shared CMSUT1 work
file. Explicit recovery qualification restores only the newly created source,
then reapplies candidate before a single compile/test. No automatic recovery
after failure. Re-run all offline distribution gates before this new live path.

Latest operator authorization (2026-10-17): "you have my approval for full
read/write access to CMS, backups are on github". Continue authorized CMS
inspection and the disposable ZTQUAL workflow without repeatedly requesting
the same access permission. Use a dedicated serialized terminal, field guards,
exact reviewed targets and retained native evidence. Preserve production
sources, helpers, retained scratch files, G data/MODULEs and disks. GitHub
source recovery does not by itself capture native record metadata or MODULE
rollback bytes; retain native backups for anything the workflow changes.

The approved single-Clear diagnostic ran. Exactly one Clear was sent; the held
page cleared but no fresh Ready appeared within 20 seconds. Subsequent screens
were blank RUNNING and locked/unformatted, so no availability probes ran.
The dedicated process disconnected. Evidence:
zvm-compiler-availability-recovery-evidence.json. Do not label this successful
CMS recovery or infer the cause of the original DFT failure. The later broad
read/write approval permits continued diagnosis. A single serialized operator
session is active under that authority (local driver
/private/tmp/zvm_operator_console.py, exec session 1632). Evidence is saved
after every operation in zvm-operator-session-evidence.json. The CP console
answered QUERY VIRTUAL DASD across two captured pages, confirming attached
029D (20-cylinder compiler disk) and 0600 (1600-cylinder VMCOM1). BEGIN resumed
the guest without producing CMS Ready. One HX immediate command was submitted
to halt the stalled guest program; further output is being observed and held
pages are captured before Clear. No source write, compile, cleanup, disk-access
change, IPL or LOGOFF has occurred. Do not open another terminal in parallel.

Live continuation: after captured paging, HX led to the bare CMS VM READ.
PA1 inspection and BEGIN returned to that CMS input; QUERY CMSLEVEL produced
CMS Level 27, Service Level 1302 and a fresh Ready. The fixed thirteen compiler
availability probes then completed with correlated terminal Ready RCs: F is
GCCLIB/29D/RW/20 cylinders, IND$FILE MODULE S exists, CMSCLNK EXEC F and GCCE
EXEC F exist, and their A copies are absent. G is not currently accessed; its
0600 device remains attached. No access/attachment changes were made.
Existing ZM537EF1 source verification now passed by DFT receive (created=false).
Native download of installed CMSCLNK EXEC F1 passed via the source-verified
ZM02EA0B reader: 55 F80 records / 4400 bytes, two identical reads and matching
metadata. Snapshot: cms-sources/snapshot-54f7c52346174e592ea0da27; SHA-256:
695482209368594b8493506240968aac27e34846922f276bb2f813de4c7b4bee.
The installed native bytes do NOT equal the repository wrapper reconstructed
as cp037 F80: square brackets in the usage comment/message display as Ý/¨ in cp037. Preserve and
report the difference; do not normalize downloaded bytes or claim an exact
canonical match. GCCE EXEC F1 native download passed: 143 V79 records / 2785
bytes, native SHA-256 d0538a0d1bf0ce83aeffd527dc72394deb4efaeb181d5aee7a960bd104011888,
snapshot cms-sources/snapshot-42038081c47caffcede07c90. This is the first
actually observed V-format download here (two identical native reads and
matching metadata); do not generalize beyond this tested V79 file.
Installed GCCE shows explicit WORK output, ASSEMBLE erase/rename when present,
and FILEDEF SYSPRINT/SYSPARM/OUT/SYSIN setup/clear. CMSCLNK's NOASM path exits
before GCCE's own ASMAHL and later ASSEMBLE/LISTING erases. STD380 PARM F1
native download is in progress to inspect the effective compiler parameters.
Session 1632 remains active and serialized. The user additionally reaffirmed
authorization to send terminal input; do not ask again for that same scope.

User requested proceeding after the offline prerequisite checkpoint. The fresh
offline build passed all 190 tests and protocol checks before live inspection:
builds/build-20261017T145132Z-90987d25/build-report.json.

One read-only MCP attempt connected to 0200, observed the verified combined
login form, used existing one-shot login/startup authority and reached CMS
Ready. Existing helper ZM537EF1 STATE returned RC0, but its DFT receive failed
with "Transfer did not start within 30s". The sanitized failure screen shows
MORE. This is an observation, not an established root cause. The server
terminated its dedicated process; a follow-up screen correctly reported no
session and disconnect confirmed no active terminal. No helper was created or
executed, no source download completed, and no compile/upload occurred.
Complete evidence: zvm-compiler-audit-attempt-evidence.json (local, ignored).
Do not retry DFT blindly or treat the helper as verified.

Added validate_zvm_compiler.py, a fixed read-only availability diagnostic that
does not need helper execution, DFT or compiler execution. Its exact commands
are QUERY DISK, STATE IND$FILE MODULE on A/B/D/E/F/S/T/Y, and STATE CMSCLNK/GCCE
EXEC on A/F. It records echoed-command terminal Ready RCs and sanitized screens,
not native integrity-qualified output. No arbitrary command/disk-access option.
Evidence files are exclusive and owner-only; failures stop without retries.

Hardened internal fixed-command observation against repeated held pages,
Ready on an incomplete console page, and paging before the command echo.
Targeted compiler/bootstrap tests passed 20 tests; the isolated changed-source
build passed all 197 tests and protocol checks:
builds/build-20261017T145838Z-bd1d788a/build-report.json.

The standalone availability diagnostic first encountered a sandbox localhost
denial (zvm-compiler-availability-evidence.json, no input). The approved
unsandboxed diagnostic reached CP READ and sent the authorized BEGIN once.
During startup recheck it observed MORE instead of the expected blank RUNNING
boundary and correctly stopped without extra Enter or Clear. No availability
queries ran. The process terminated; complete sanitized evidence is in
zvm-compiler-availability-live-evidence.json. This is not a repeated DFT attempt.

Added an explicit startup_page_hold_observed stop result (no paging action by
normal startup) and a default-off --advance-startup-more option in the local
compiler diagnostic. It requires the captured reconnect BEGIN/Enter provenance,
same held page, blank field, cursor/geometry recheck, then permits one Clear.
It observes passively afterward and stops on another held page; no second
Clear, Enter, BEGIN, transfer or compile follows from that option. Separate
operator recovery authorization is required before running this option.
The full isolated follow-up build passed all 202 tests and protocol checks:
builds/build-20261017T150451Z-7aedf16f/build-report.json. Two additional startup/
driver integration regressions subsequently passed in a 28-test targeted run.
The final 55-file isolated source package passed all 204 tests (zero failures,
errors or skips) and all protocol/review/rehearsal gates:
builds/build-20261017T150644Z-4c6971fb/build-report.json. Archive SHA-256:
a7bfb9cc1ef932e953da3689928b65d5106e8f8005f8b82b1091dc0ae38ff8a5.
Only documentation and a diagnostic comment were adjusted after bundling;
implementation and test code are unchanged. Syntax checks, pip check and
git diff --check pass. All three live-attempt evidence files are owner-only
and were checked to exclude both locally configured credential values.
The operator explicitly granted approval for one guarded startup Clear and the
fixed read-only probes on 2026-10-17. The reviewed command has now been started
with --advance-startup-more; results will be recorded in
zvm-compiler-availability-recovery-evidence.json. No DFT retry, compiler run,
disk-access change, upload or cleanup is authorized by this approval.
No DFT-recovery fix has been claimed or implemented.

## Agreed finish line

Qualify one explicitly authorized disposable CMS C project through download,
local edit, hash-pinned review, verified backup, replacement, compile, test,
native output verification and archived evidence. Production deployment is a
separate target-qualification and approval step. Neither existing helpers nor
retained ZV scratch files are disposable qualification targets.

## Current state

- Starting tooling commit: cda5305a1f494d7c735bd5d6ec5b83836f6c81b5;
  working tree was clean at the start of this task.
- Existing planner and symbolic fail-stop rehearsal retain false execution and
  replacement-safety flags. The new standalone fixed disposable executor is
  implemented offline; see the active checkpoint above for live qualification.
- User authorized proceeding toward this finish line and asked for durable
  progress notes. User then directed inspection of ibm-sandbox Markdown for
  the established CMS C compile commands. That inspection is complete; see
  CMS-C-RECIPE.md for sources, exact commands and unresolved output inventory.
- The initial offline prerequisite used no CMS session. The subsequent
  read-only inspection attempts are recorded above. No upload, replacement,
  compiler execution, cleanup or production repository change has occurred.
- Created repository .venv using Python 3.14 and installed
  requirements-zvm-mcp.txt. pip check passes. Dependency bootstrap required
  approved network access; the first sandboxed attempt could not resolve PyPI.
- Initial offline build passed 177 tests with zero failures/errors/skips and
  real disconnected stdio protocol checks. Report:
  builds/build-20261017T144618Z-17c83bb6/build-report.json. This precedes the
  new native comparison implementation.
- Implemented zvm_native_review.py: offline native snapshot comparison bound
  to the exact operation and snapshot manifest hashes, with baseline, backup,
  candidate and restored roles. No host adapter or new MCP capability. It
  preserves all operation blockers and false execution/safety flags.
- Added 13 native-comparison regressions, including the C fixture edit/review
  path, mismatched hashes/layouts/identity, stale artifacts, protected backups,
  symlinks, secret rejection, CLI behavior and artifact immutability.
  Targeted run passed all 13; the full isolated build passed all 190 tests,
  zero failures/errors/skips, plus default/auto MCP protocol validation,
  disabled-upload checks, local edit and operation review, and the twenty
  symbolic failure-rehearsal scenarios. Report:
  builds/build-20261017T144918Z-f2800486/build-report.json.
  The 53-file source bundle SHA-256 is
  d05e2a7a09d8ded15491e94ff89d1288ad565fbc5ee8e660d19b912ba0859979.
  Final progress/validation notes and fixture README formatting were updated
  after that bundle; no implementation changed afterward. Do not equate that
  bundle hash with the final documentation tree.
- Added local baseline/candidate C89 fixtures. Strict host cc compilation
  (-x c -std=c89 -pedantic-errors -Wall -Wextra -Werror) and executions passed:
  RC0 with ZTQUAL BASELINE PASS 42 and ZTQUAL CANDIDATE PASS 43 respectively.
  The first attempt needed -x c because uppercase .C defaults to C++ on Mac.
  Both files round-trip to cp037 F80 and use at most 48 source columns.
  These are host-only checks, not GCCCMS qualification.
- Syntax compilation and git diff --check pass. All work remains local and
  uncommitted. No GitHub push, remote CI or Codex discovery was run this task.

## Milestones and acceptance evidence

| Milestone | Status | Required evidence |
| --- | --- | --- |
| Reproducible offline baseline in this checkout | Pass, before new code | 177 tests, no skips; builds/build-20261017T144618Z-17c83bb6/build-report.json |
| Recover established C compiler recipe | Complete for source inspection | CMS-C-RECIPE.md, Markdown and wrapper blob identities |
| Bind native before/backup/after/restore evidence | Offline pass | 13 targeted tests; full 190-test isolated build |
| Define disposable transaction | Fixed standalone contract implemented | ZTQUAL C A1 / ZTQBACK C A1; installed source pins and declared side effects; broad CMS authority recorded |
| Implement narrowly gated host transaction | Pass for the fixed fixture | Default-off standalone capability; pinned contracts; durable failure evidence; standard MCP unchanged |
| Qualify replacement and separate recovery | Pass for disposable ZTQUAL only | Original native recovery/reapply receipts; production writer exclusion remains false |
| Complete one live compile/test cycle | Pass | RC0 build/test; all four native outputs; final source/backup, transient, inventory and FILEDEF checks |
| Publish qualified version 1 checkpoint | Pass | Implementation f0a38d2 and CI39052151534/39052154783 passed; final native qualification documented here |

## Resume here

1. Read the qualified checkpoint above and preserve all retained fixtures,
   native snapshots, journals and helpers. The development cycle has passed;
   no host command or reconnect is needed to resume local review.
2. Inspect Git status and canonical GitHub checkpoint/CI before further edits.
   Use .venv/bin/python; rerun offline qualification after implementation changes.
3. Do not rerun validate_zvm_fixture.py --live against this existing namespace.
   Do not create another output helper merely to reread retained evidence.
   Any specifically requested read-only re-audit must reverify ZME09C7C with
   --output-reader ZME09C7C, bind exact prior journal hashes and use new evidence.
4. Production work requires its separate project handoff, exact targets,
   recipe/output inventory, native rollback and operator-established writer
   exclusion. The fixture pass supplies none of that production authority.
