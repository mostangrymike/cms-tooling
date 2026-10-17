# Version 1 progress and restart checkpoint

Updated: 2026-10-17. Repository: mostangrymike/zvm-tooling.

## Active continuation: compiler inventory audit

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
| Implement narrowly gated host transaction | Offline tests pass; live pending | Default-off standalone capability; exact contract binding; durable failure evidence; standard MCP unchanged |
| Qualify replacement and separate recovery | Pending | Explicit live authority, operator writer exclusion; disposable fixture evidence |
| Complete one live compile/test cycle | Pending | Native readback, complete correlated output and actual RCs; declared outputs and fresh final Ready |
| Publish qualified version 1 checkpoint | Pending | Sanitized source, documentation, exact-revision CI and evidence references |

## Resume here

1. Read AGENTS.md, the active checkpoint at the top of this file,
   CMS-C-RECIPE.md and PIPELINE-READINESS.md. The latest explicit full CMS
   read/write and terminal input authority supersedes the earlier narrow
   one-Clear diagnostic approval. Preserve production and retained helpers.
2. Inspect git status; preserve existing work. Use .venv/bin/python and the
   pinned requirements. Run the full offline build after implementation.
3. Offline comparison prerequisite is complete. Revalidate only after changes;
   retained build reports above describe the actual executed checks. Do not
   reuse synthetic evidence as live proof.
4. Check the latest full-build report and source contract. Once all offline
   gates pass, invoke validate_zvm_fixture.py with --live --qualify-recovery,
   its exact --contract-sha256, local credential path and a new exclusive
   evidence filename. No further repeat access approval is needed for this
   authorized fixture. Never rerun a partial transaction blindly: examine the
   persisted last step and freshly inspect affected native files first.
5. Verify complete native build/test output with RCs, output snapshots, final
   source/backup hashes, transient absence and FILEDEF state. Preserve all
   created files; no cleanup or production replacement is part of this run.
6. Production writer exclusion is unresolved and must remain false. The fixed
   disposable qualification cannot be generalized into production safety.

Do not mark version 1 complete until the live cycle and its failure/recovery
qualification actually pass. Keep this checkpoint current when stopping.
