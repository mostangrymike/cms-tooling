# Standalone repository provenance

Imported from `mostangrymike/ibm-sandbox`, directory `src/cms-tooling`, at parent
commit `d5c55e059a4f2380a35fdb9fe18825c2bc3c0487`, plus the locally reviewed fixes for stale STATE echoes,
symlinked upload plans and optimized-Python validation checks.

This is a clean source import. Parent history stays in the original repository;
it is not included in this repository. The original checkout and MCP registration
are retained. Credentials, ignored legacy pipelines, captures, downloaded CMS
snapshots, edit workspaces and builds are excluded by the explicit distribution
inventory. Runtime snapshots and credentials must be migrated separately by the
operator; public Git is not their destination.

Standalone changes add this README and provenance note, relocate Actions to the
repository root, and update setup and external production-document links.
Historical validation entries in VALIDATION-cms-mcp.md describe the original
environment; they do not establish live qualification in a new checkout.

The separate GITC23 production wrapper host CI run
[38821852755](https://github.com/mostangrymike/ibm-sandbox/actions/runs/38821852755)
completed successfully at `c5153108bf755d10f709406819efc45e32612a16`.
Real CMS validation of that wrapper remains outstanding. This migration does not
authorize production replacement or CMS execution.
