# Offline terminal fixtures

`terminal-screens.json` contains six narrowly scoped fixtures extracted from
recorded local diagnostic captures. Rows and field geometry are retained;
locally configured credentials and editable fields were masked before export.
The original full captures remain local and are not distribution inputs.

| Fixture | Original local capture |
| --- | --- |
| hercules_banner | zvm-live-evidence.json / connect.screen |
| login_form | zvm-ec2-observation.json / final snapshot |
| vm_read | zvm-login-evidence.json / login.screen |
| reconnect_running | zvm-startup-running-timeout-evidence.json / startup.screen |
| cms_boundary | zvm-startup-cms-line-evidence.json / startup screen, actions, outcome |
| failed_login | mainframe_surface.log / screen state 2 |

Tests get a fresh copy with `recorded_screen()` from `test_zvm_fixtures.py`.
They do not require credentials, personal live evidence or network access.
