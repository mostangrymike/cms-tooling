# Roadmap

**Canonical gap/TODO list for `cms-tooling`.** Keep the repository in steady
state before adding features: every item below needs offline tests and must not
claim live-CMS validation it does not have.

## 1. Offline lifecycle coverage

- Add an offline end-to-end harness for plan → create → activate → delete that
  simulates CMS responses without touching a live system.
- Cover rollback/restore paths after failed activation.
- Add edge-case tests: malformed profile, missing profile file, duplicate
  profile names, invalid ports, missing credentials file.

## 2. Runbook hardening

- Add rollback, monitoring/alerting hooks, and incident-response steps to
  `Production_Runbook.md`.
- Document promotion gates (offline build, credential scan, review) explicitly.
- Link the runbook from `README.md`.

## 3. Profile system polish

- Document the full profile schema and precedence in `Profiles_Runbook.md`.
- Confirm no destination environment variables remain anywhere; profiles are
  the only destination selector.
- Add a `--list-profiles` style read-only helper (optional).

## 4. Build and CI

- Keep `build_cms_tooling.py` authoritative: every new test module must be added
  to `ENTRY_POINTS` or to `EXCLUDED_SOURCES` with a reason (a missed module is a
  build error by design).
- Add a PR-level credential scan step if not already covered.

## 5. Repository hygiene

- `STEADY_STATE.md` and `PR_DESCRIPTION.md` are planning drafts; fold useful
  content into `STATUS.md`/`ROADMAP.md` and retire the drafts.
- Keep `NOTES.md` append-only history.

## 6. In-guest tooling (z/VM 6.3)

Verified environment facts are in `docs/OE_BFS.md` and
`docs/TLS_ASSESSMENT.md`. Remaining work:

- **CMS↔BFS bridge.** Move files between `fn ft fm` and BFS without truncation
  or record-format damage. Do the EBCDIC/ASCII translation in code: the guest
  `iconv` has only the `IBM-1047` charmap, and `tar` fails with the same NLS
  error.
- **`mkmodule` driver.** Stage BFS sources as CMS files, run CMSCLNK, capture
  the listing and RC, copy the MODULE back. `make`/`c89` in the guest cannot
  emit a CMS MODULE.
- **Long-line handling.** CMS records are 80 columns; BFS is byte stream. Pick
  a framing rule and test it at both ends.
- **No outbound HTTPS.** Keep the gateway pattern; do not attempt native TLS.
  If the model endpoint is local and plain HTTP, skip the gateway.
- **Agent harness.** Shell loop that uses `cms` for build and publish, with an
  append-only audit log. Never run generated code in the agent guest; use a
  separate userid with read-only links and CPU/storage caps.
- **Missing utilities** in the guest: `patch`, `jq`, `curl`, `base64`,
  `sha256sum`, `timeout`. Decide per tool: small C implementation, or a shell
  substitute (`diff` + `ed` for `patch`).
