# Status

**Canonical current-state file for `cms-tooling`.** If any other document
disagrees with this page, this page wins. Last updated 2026-11-16.

## Right now

| Field | Value |
|---|---|
| Branch | `main` |
| Latest commit | `d77b9c4` — register profile test modules as build entry points |
| Build | `python3 -B build_cms_tooling.py` (offline, no CMS) |
| Tests | 116 tests, 0 failures/errors; Python 3.12 and 3.14 |
| CI | `cms tooling offline build` and `Offline tests (profiles)` — **green** |

## What works

- Line-mode Telnet driver with one-command-at-a-time capture, RC, intervention
  and recovery (`cms_telnet_driver.py`); credentials paths expand `~`.
- FTP transfer driven from the same Telnet session (`cms_ftpput.py`).
- Profile-driven destinations: `cms_profiles.py`, `~/.config/cms-tooling/cms_profiles.json`,
  selected by `--profile` / `profile_name`. **No destination environment variables.**
- Credentials loaded from `~/.config/ibm-zvm-cms/credentials.json`; never in
  source, profiles, or arguments.
- Read-only minidisk planner, directory plan, inventory, and receipt-gated
  lifecycle (`cms_mdisk_*`).
- Host-side plain-HTTP-to-HTTPS bridge with policy/credential boundary
  (`github_tls_bridge.py`).

## What is not done

- No live production rollout; planner and lifecycle are offline/read-only.
- Deletion remains plan-only behind signed receipts.
- No dedicated offline end-to-end lifecycle harness (plan → create → activate
  → delete) beyond profile resolution tests.

## Read next

1. [`ROADMAP.md`](ROADMAP.md) — remaining work.
2. [`docs/INDEX.md`](docs/INDEX.md) — what every doc is.
3. [`CHANGELOG.md`](CHANGELOG.md) — delivered work, newest first.
4. [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`AGENTS.md`](AGENTS.md) — validation and rules.
5. [`NOTES.md`](NOTES.md) — detailed work log.
