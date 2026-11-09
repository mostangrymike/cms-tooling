# Security Policy

## Supported versions
`cms-tooling` is under active development. Only the latest code on the maintained branch(es) is supported with fixes on a best-effort basis.

## Reporting a vulnerability
Please **do not** open a public issue for a suspected security vulnerability.

- Use **GitHub Private Vulnerability Reporting / Security Advisories** for this repository if enabled.
- If private reporting is not available, contact the maintainer privately via GitHub with a clear description, impact, and reproduction steps.

Include (where possible): affected component (e.g. `github_tls_bridge.py`, MCP server, telnet/FTP/upload path), environment, steps to reproduce, and logs **with secrets redacted** (tokens, passwords, credentials, `Authorization` headers).

## Scope notes
- This tooling can handle credentials and transport access to CMS targets and to GitHub (via the TLS bridge). Protect local credential/config files and never commit them.
- Avoid enabling diagnostic capture/logging of sensitive traffic in shared or committed configurations.
