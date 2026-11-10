# Work notes

## Goal and scope

The requested end goal is a fully functional Git client for IBM CMS. This
checkout is `cms-tooling`; its README identifies the native client as a separate
project in `ibm-sandbox`. Assumption: because the active repository is
`cms-tooling` and the task forbids touching files outside this repo, initially scoped the work to tooling; the operator has since authorized
working in any repository, so after this verified tooling step the work will
continue in the native client repository.

## Plan

1. Read repository instructions and establish the offline build/test baseline.
2. Inspect the current tooling checkpoint for a concrete, in-scope correctness
   or documentation gap that blocks reliable CMS Git work.
3. Implement one small fix, add or update regression coverage, run the full
   offline build/tests, and commit the verified step.
4. Report what this repository establishes and identify any end-goal work that
   remains outside this checkout.

## Progress

- Read `AGENTS.md`, `README.md`, `README-cms-mcp.md`, and
  `PIPELINE-READINESS.md`.
- Working tree was clean at start; branch `codex/cms-reconnect-startup` is one
  commit ahead of `origin` before this task.
- Offline baseline completed from an isolated extracted distribution: 274 tests
  passed, 0 failures/errors/skips; protocol defaults, upload gate, local review,
  operation review and failure rehearsal passed.
- Found the operator guide out of sync with the actual 18-tool MCP catalog: it
  said 16 and omitted `cms_abort_read`. Updating the guide and adding a regression
  check that binds the listed tools/count to the protocol validator.
- The isolated build after the change passed: 275 tests, 0 failures/errors/skips;
  archive reproduction, protocol defaults, upload gate, local edit/operation
  review and failure rehearsal all passed. Report: `builds/build-20261018T170829Z-37df90b2/build-report.json`.
- Next: commit this tooling documentation/regression step, then continue in the
  native client repository with its current project checkpoint.
