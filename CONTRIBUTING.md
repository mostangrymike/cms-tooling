# Contributing to cms-tooling

`cms-tooling` provides tooling for z/VM CMS development and validation: the line-mode Telnet driver, the FTP transfer helper, the minidisk planner, the GitHub TLS bridge, and their tests.

## Before you start
- Read `README.md` (and related docs like `TELNET-DRIVER.md`, `MINIDISK-PROVISIONING.md`) for context.
- Search existing issues/PRs to avoid duplicate work.

## Development notes
- Keep changes focused and preserve compatibility with existing CMS workflows/targets (Hercules, telnet/FTP paths).
- **Never commit secrets.** Do not print or commit credentials, tokens, passwords, `GHCRED` material, or `Authorization` headers. Use local config (e.g. `~/.config/...`) and redacted logs.
- For the TLS bridge (`github_tls_bridge.py`), avoid adding request/response capture of sensitive data by default.

## Validation
- Run the relevant tests for the area you changed, for example:
  - `python3 -m py_compile <changed>.py`
  - `python3 -m unittest -v test_cms_build test_cms_telnet_driver test_cms_mdisk_plan test_github_tls_bridge`
  - `python3 -B build_cms_tooling.py`
- Describe what you ran and, if target-dependent, the environment used. Host/CI validation is not the same as live CMS target proof.

## Pull requests
- Explain the problem, the fix, and any operational impact (ports, bind addresses, protocols, timeouts).
- Note security/privacy implications when touching transport, auth, or logging.

## License

By submitting a contribution you agree that it is licensed under the same
terms as this project: the GNU General Public License, version 3 or (at your
option) any later version (`GPL-3.0-or-later`). See [LICENSE](LICENSE).
