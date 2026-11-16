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
