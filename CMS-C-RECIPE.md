# Established CMS C build recipe

Inspected canonical mostangrymike/ibm-sandbox GitHub files on 2026-10-17.
This is source inspection for the tooling qualification plan, not a CMS run or
permission to rebuild production programs.

## Documented entry point

For ordinary C modules without native inflater dependencies:

```text
CMSCLNK name PLAIN
```

The source is `name C A`. Default mode is NAPI, which also assembles and links
GITCAPI and GITINFA. Version 1 should start with an isolated PLAIN fixture.
The compiler wrapper belongs with GCCCMS on F; verifying its actual installed
source and resolution is still required before live execution.

Sources inspected:

- [docs/NATIVE_REF.md, GCCCMS build checkpoint and usage](https://github.com/mostangrymike/ibm-sandbox/blob/main/docs/NATIVE_REF.md#gcccms-native-build-checkpoint-2026-09-26),
  Git blob `97fe8f3d78ff7c06bac470cb18891133235f62ae`.
- [README.md](https://github.com/mostangrymike/ibm-sandbox/blob/main/README.md),
  Git blob `996fcb839bf99615ac64496c4d4f7b853dc4fe86`; includes subsequent
  GITP26M PLAIN compile instructions.
- [CHAT_STATE.md](https://github.com/mostangrymike/ibm-sandbox/blob/main/CHAT_STATE.md),
  Git blob `983e07e9529f8458d9f4512898f9c2b989f33287`; records actual
  GITP26M PLAIN compile with no flagged assembler statements on 2026-10-13.
- [docs/CURRENT_STATE.md](https://github.com/mostangrymike/ibm-sandbox/blob/main/docs/CURRENT_STATE.md),
  Git blob `b07384d3567a1dbf635e02286072f20b5ddbc015`; records compile
  before application FILEDEF bindings. The build changes FILEDEF-related state.

The documents contain historical checkpoints. Their early statements that
PLAIN still needs testing are superseded by later recorded successful runs;
none verifies the current installed compiler in this task.

Additional source inspection of
[docs/M173_PERSISTENT_DISK_RUNBOOK.md](https://github.com/mostangrymike/ibm-sandbox/blob/main/docs/M173_PERSISTENT_DISK_RUNBOOK.md),
Git blob `ee0a9ceb4b3b12f0ca2410e93f1b45b4b722e419`, confirms retained C
sources regenerate ASSEMBLE intermediates; later cleanup records also identify
TEXT and LISTING byproducts. Those records are not a complete GCCE inventory
and authorize no cleanup here.

## Exact sequence confirmed against wrapper source

[src/CMSCLNK.EXEC](https://github.com/mostangrymike/ibm-sandbox/blob/main/src/CMSCLNK.EXEC),
Git blob `669c44f0eabfc60c24bb144cd109a074e5deba24`, contains this PLAIN path:

```text
GLOBAL MACLIB OSMACRO DMSGPI PDPCLIB
EXEC GCCE name C A (NOASM PARM STD380
ASSEMBLE name
GLOBAL TXTLIB PDPCLIB
LOAD name (NOAUTO NOMAP
GENMOD name
```

Each command is conditional on preceding success. The wrapper returns 12 for
C compilation failure, 16 for assembly failure, 20 for LOAD failure and 24 for
GENMOD failure; GLOBAL failures propagate their RC. Success returns RC0 and
prints `CMSCLNK: built name MODULE mode PLAIN`. Capture the actual RC as well
as markers. `name` here is a documentation placeholder, not a selected target.

## Required qualification work

Local fixture sources are now available at
`fixtures/qualification/{baseline,candidate}/ZTQUAL.C`. Proposed source target
is `ZTQUAL C A1`, with distinct backup `ZTQBACK C A1`; neither name has been
checked on CMS or authorized for host writes. Baseline execution must print
`ZTQUAL BASELINE PASS 42`, and the candidate must print
`ZTQUAL CANDIDATE PASS 43`, each with actual RC0. Proposed build entry point is
`CMSCLNK ZTQUAL PLAIN`, followed by `ZTQUAL` only after native source readback
and verified build completion. This is a review proposal, not an executable
recipe: GCCE side effects and full output inventory remain unresolved.

- Pin and verify installed CMSCLNK and compiler/library inputs. Do not install
  or replace CMSCLNK on F as part of a generic tooling demo.
- Enumerate generated ASSEMBLE, TEXT, LISTING, MODULE and any GCCE work files,
  their exact modes, replacement behavior and FILEDEF side effects. These
  output types are an audit checklist, not a claimed complete inventory.
  Inspect GCCE itself before accepting a recipe. NOASM/NOAUTO/NOMAP do not
  establish that all compiler or assembler scratch outputs are absent.
- Audit assembler SYSUT work files and loader map lifecycle as well as the C
  compiler's outputs. IBM's [ASSEMBLE reference](https://www.ibm.com/docs/en/zvm/7.3.0?topic=commands-assemble)
  documents default FILEDEFs for SYSUT1/2/3 and possible work-file spill to disk;
  the [LOAD reference](https://www.ibm.com/docs/en/zvm/7.4.0?topic=commands-load)
  includes an example where NOMAP removes existing map files. These are newer
  release references, not verified behavior on this 6.3 target. Recover the
  target-specific definitions before accepting any absence/nonreplacement
  claim. The existing planner's create-only A1 output contract cannot simply
  be treated as a complete model for temporary or implicitly erased files.
- Choose a fresh qualification namespace outside ZM/ZV, preserve the fixture
  baseline and back it up before replacement. Qualify recovery separately.
- Use fixed-80 cp037 source and a conservative 63-column C text limit from the
  documented GCCCMS checkpoint until a wider C source path is qualified.
- Require a known deterministic fixture result and actual RC0, plus native
  source/output checks and final terminal/FILEDEF postchecks. No existing
  production GITRUN or GITC26 regression is selected for this demo.
- The current read-only helper allowlist cannot dispatch CMSCLNK. The current
  uploader accepts only new ZV EXEC scratch files. Both remain unchanged;
  a C replacement/build capability requires its own implementation and gates.

No commands above have been submitted to CMS by this task. Old installation
COPYFILE/ERASE instructions in the production docs are historical context and
are not part of this qualification recipe.

## Installed-source audit checkpoint

The first read-only audit reached CMS Ready on 2026-10-17, but existing-helper
source verification failed because DFT did not start within 30 seconds. MORE
is visible in the retained failure screen. The terminal was terminated and no
helper or compiler was executed. See local ignored evidence
`zvm-compiler-audit-attempt-evidence.json`. GCCE source and the installed
CMSCLNK source remain unverified.

`validate_zvm_compiler.py` provides a fixed availability-only diagnostic for
accessed disks, IND$FILE MODULE on known search modes, and CMSCLNK/GCCE EXEC on
A/F. It uses no transfers or unverified helper EXEC. It reports terminal Ready
RCs and full sanitized snapshots; it does not claim native output integrity,
source equality, installed command resolution or a safe build recipe.

The first separate availability run stopped during reconnect startup before
issuing any of its thirteen queries: MORE appeared during field recheck after
the authorized BEGIN/Enter. Evidence:
`zvm-compiler-availability-live-evidence.json`. The optional
`--advance-startup-more` diagnostic flag requires separate operator recovery
authority. It permits only one Clear on the exact captured reconnect hold with
unchanged empty command field/geometry and BEGIN/Enter provenance; it sends no
additional startup keys and waits passively for fresh Ready. Another held page
stops the workflow. Normal MCP startup never clears that page automatically.

The reviewed follow-up command, authorized and run on 2026-10-17, was:

```sh
.venv/bin/python -B validate_zvm_compiler.py --live \
  --credential-file /Users/mikewommack/.config/ibm-zvm-cms/credentials.json \
  --advance-startup-more \
  --output zvm-compiler-availability-recovery-evidence.json
```

It then runs only the fixed QUERY DISK and literal STATE availability probes,
capturing pages before ordinary read-only output paging. It never enables
general input, alters disk access, retries DFT, uploads, compiles or cleans up.

That one-Clear run cleared the held page but did not reach fresh Ready in 20
seconds, so no probes ran and it disconnected. The operator subsequently
authorized full CMS read/write access. A dedicated serialized operator session
then recovered the bare CMS VM READ using captured paging/HX, resumed from CP,
and verified CMSLEVEL plus fresh Ready. All thirteen fixed availability probes
completed: IND$FILE MODULE S exists; CMSCLNK/GCCE EXEC F exist; A copies are
absent. QUERY DISK identifies F as GCCLIB/29D/RW/20 cylinders. Existing ZM537EF1
command-helper source verification passed by receive without provisioning.
Native compiler-source inspection is in progress. Evidence:
zvm-operator-session-evidence.json (local, owner-only).

Inspection subsequently completed. Installed native source SHA-256 values:

| File | Format | SHA-256 |
| --- | --- | --- |
| CMSCLNK EXEC F1 | 55 F80 records | 695482209368594b8493506240968aac27e34846922f276bb2f813de4c7b4bee |
| GCCE EXEC F1 | 143 V79 records | d0538a0d1bf0ce83aeffd527dc72394deb4efaeb181d5aee7a960bd104011888 |
| STD380 PARM F1 | 1 V54 record | a30a03f46abaec885053c550c1cc2d181a368bd5ca4af59488f63924e06b019d |

STD380 contains `-Os -DUSE_MEMMGR -o dd:out - -S -ansi -pedantic-errors`.
GCCE writes ZTQUAL WORK A then renames it to ASSEMBLE; it erases an existing
ASSEMBLE first. With CMSCLNK's NOASM flag it exits before GCCE's own assembler
and subsequent erase steps. CMSCLNK then invokes ASSEMBLE, LOAD (NOAUTO NOMAP,
and GENMOD. Existing outputs must therefore be absent for this disposable run.
The wrapper's two usage lines have different native bracket bytes from the
repository's cp037 reconstruction; the installed source is pinned as observed.

`validate_zvm_fixture.py` declares exact persistent outputs (ASSEMBLE, TEXT,
LISTING and MODULE A1) and possible transient WORK/SYSUT1-3/map files. It checks
absence before build and native output snapshots afterward. Initial FILEDEF
state must be empty; preexisting definitions stop it before source writes.
The dedicated helper exposes only fixed BUILD/TEST/FILEDEFS aliases; it cannot
receive a filename or arbitrary command. Native baseline/backup/candidate
readback and explicit successful-path recovery precede the final build/test.
The ordinary planner remains blocked for lack of verified production writer
exclusion/output semantics. A disposable qualification does not clear those gates.

IBM references used to bound possible effects:
[ASSEMBLE](https://www.ibm.com/docs/en/zvm/7.3.0?topic=commands-assemble) documents
default TEXT/LISTING and SYSUT work files; the target's actual output checks
remain required because this is a newer manual than the guest.
[COPYFILE](https://www.ibm.com/docs/en/zvm/7.2.0?topic=commands-copyfile) documents
its shared CMSUT1 work file. This workflow uses verified native bytes with DFT
to create its distinct backup instead, avoiding that shared work file.
