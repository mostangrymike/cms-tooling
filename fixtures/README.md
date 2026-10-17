# Offline terminal fixtures

`terminal-screens.json` contains six narrowly scoped fixtures extracted from
recorded local diagnostic captures. Rows and field geometry are retained;
locally configured credentials and editable fields were masked before export.
The original full captures remain local and are not distribution inputs.

| Fixture | Original local capture |
| --- | --- |
| hercules_banner | cms-live-evidence.json / connect.screen |
| login_form | cms-ec2-observation.json / final snapshot |
| vm_read | cms-login-evidence.json / login.screen |
| reconnect_running | cms-startup-running-timeout-evidence.json / startup.screen |
| cms_boundary | cms-startup-cms-line-evidence.json / startup screen, actions, outcome |
| failed_login | mainframe_surface.log / screen state 2 |

Tests get a fresh copy with `recorded_screen()` from `test_cms_fixtures.py`.
They do not require credentials, personal live evidence or network access.

## Disposable C qualification sources

`qualification/baseline/ZTQUAL.C` and `qualification/candidate/ZTQUAL.C` are
local C89 fixture sources for a proposed `ZTQUAL C A1` transaction. Baseline
prints `ZTQUAL BASELINE PASS 42`; candidate prints
`ZTQUAL CANDIDATE PASS 43`; both return 0 on success. Distinct markers let a
future test reject a stale baseline MODULE after candidate compilation. They
use no application file I/O. Both fit the conservative 63-column C source
limit and can be padded losslessly to F80 cp037 records.

These files have not been uploaded or compiled on CMS. The proposed CMS name
has not been checked for absence or authorized for creation/replacement. See
CMS-C-RECIPE.md and V1-PROGRESS.md for the remaining gates. Local host compile
results do not qualify GCCCMS, its outputs or the target transaction.
