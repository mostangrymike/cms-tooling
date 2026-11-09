# Contributing to cms-tooling

`cms-tooling` provides tooling for z/VM CMS development and validation (CMS MCP/server helpers, upload/capture/edit utilities, the GitHub TLS bridge, and validation/fixture harnesses).

## Before you start
- Read `README.md` (and related docs like `README-cms-mcp.md`, `TELNET-DRIVER.md`, `CMS-C-RECIPE.md`) for context.
- Search existing issues/PRs to avoid duplicate work.

## Development notes
- Keep changes focused and preserve compatibility with existing CMS workflows/targets (Hercules, telnet/3270/FTP paths as applicable).
- **Never commit secrets.** Do not print or commit credentials, tokens, passwords, `GHCRED` material, or `Authorization` headers. Use local config (e.g. `~/.config/...`) and redacted logs.
- For the TLS bridge (`github_tls_bridge.py`), avoid adding request/response capture of sensitive data by default.

## Validation
- Run the relevant tests/validators for the area you changed, for example:
  - `python3 -m py_compile <changed>.py`
  - `python3 test_cms_*.py` / `python3 validate_cms_*.py` (as applicable to the change)
- Describe what you ran and, if target-dependent, the environment used. Host/CI validation is not the same as live CMS target proof.

## Pull requests
- Explain the problem, the fix, and any operational impact (ports, bind addresses, protocols, timeouts).
- Note security/privacy implications when touching transport, auth, or logging.
