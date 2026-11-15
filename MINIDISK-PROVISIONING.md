# MAINT minidisk provisioning

## Scope

`cms_mdisk_plan.py` is the first, read-only stage. It prompts for a CMS
filemode and requested size in MiB, then plans a MAINT 3390 minidisk from a
recent `cms-minidisk-inventory-v1` JSON snapshot. It does not connect to CMS,
edit a directory, issue `DIRECTXA`, format, link, or access a minidisk.

Live work in this tree uses line-mode Telnet for commands
(`cms_telnet_driver.py`) and FTP for file transfer. There is no 3270 path.

The plan includes a hash of the inventory and plan. A later provisioning stage
must require that exact plan hash before it changes CMS state. The chosen
directory-update method is `DIRECTXA`; no activation or format executor exists
yet.

## Inventory contract

The planner requires one complete snapshot containing:

- Capture time with timezone, no more than 15 minutes old.
- Complete active CP directory, CP allocation-map, and physical-volume geometry
  evidence.
- An administrator-reviewed MAINT virtual-address allowlist.
- Current used virtual addresses, accessed filemodes, and reserved filemodes.
- Each volume's verified cylinder count, 3390 4-KiB block geometry, eligibility,
  full-pack status, and every MDISK/system-reservation interval.

Full-pack volumes, ineligible volumes, overlapping intervals, stale snapshots,
incomplete evidence, CMS filemode `D`, and CP virtual address `0192` fail
closed. The planner selects the smallest fitting contiguous extent. It emits a
proposed `MDISK` statement and the future `FORMAT`/`ACCESS` lines only as
review data.

Do not create this inventory from `DIRMAP` alone. Existing project evidence
shows that `DIRMAP` can omit full-pack overlaps and assume geometry that differs
from CP. The inventory collector must reconcile the active directory,
`CP QUERY ALLOC MAP`, and verified volume geometry. A full-pack definition
reserves its entire volume for this planner.

## Future agentic executor

The executor must be a separate, disabled-by-default capability. It must:

1. Recollect inventory and reject stale or changed plan hashes.
2. Confirm the chosen directory source and unique backup target.
3. Create a protected backup and separate candidate; never edit the active
   directory in place.
4. Insert exactly one MAINT MDISK line and run `DIRECTXA candidate (EDIT`.
5. Stop for explicit approval before non-EDIT `DIRECTXA`.
6. Verify CP location and directory mapping before `CP LINK`.
7. Stop for a second explicit, plan-bound approval before destructive `FORMAT`.
8. Verify formatted geometry, label, and CMS `ACCESS` mode afterward.

No cleanup or extent release runs automatically after failure. Preserve
candidate, backup, and partial target for review.

## Similar projects and preferred interface

The closest public implementation is IBM's
[zvm_ansible_collection](https://github.com/IBM/zvm_ansible_collection):
`zvm_minidisk.py` calls SMAPI `Image_Disk_Create_DM` /
`Image_Disk_Delete_DM` through Feilong `smcli`. It needs an authorized Linux
management guest, zthin, SMAPI, and a configured directory manager. Its
optional formatting path runs Linux `dasdfmt`; that is not the right formatter
for this CMS minidisk.

IBM's native [DirMaint `AMDISK`](https://www.ibm.com/docs/en/zvm/7.2.0?topic=tasks-step-managing-users)
is a closer fit for MAINT: `AUTOG`, `AUTOR`, or `AUTOV` allocates from its
configured EXTENT CONTROL group, region, or volume. IBM describes DirMaint as
performing allocation checks and managing directory transactions. The
[SMAPI `Image_Disk_Create_DM`](https://www.ibm.com/docs/en/zvm/7.3.0?topic=interfaces-image-disk-create-dm)
API can create a CMS-formatted disk and may finish asynchronously; callers must
poll the operation ID.

IBM Cloud Infrastructure Center also allocates from configured DirMaint DASD
groups, but brings a much larger cloud-management stack. VMLINK only automates
links to already-authorized disks; it does not allocate extents.

The requested `DIRECTXA` route remains a possible fallback, not the preferred
allocator. It must not use `DIRMAP` alone or invent a free range. Current
project evidence says DirMaint was not operational and no verified free extent
was established. The direct route therefore stays disabled until a fresh,
complete inventory and directory-source backup procedure exist.

## Current target boundary

The repository's saved records do not prove a currently free extent. VMCOM1 has
a full-pack definition, and the recorded M01RES tail is only a DIRMAP estimate
with unresolved geometry/overlap evidence. No target provisioning or CMS data
change is part of the planner.
