# Decisions

- D-001: Repair source normalization, not `loop_bootstrap.py`; the adapter correctly
  routed a valid existing run once the turn contract supplied the right identity.
- D-002: Validate the stripped candidate with `_run_name_from_path()` after path
  resolution. Do not trust a lexical `/runs/` substring by itself.
- D-003: Preserve run-internal subpaths because their suffix begins with `/`, not the
  existing attached-operator boundary.
- D-004: Preserve one-use prompt authority. Previously malformed contracts require a
  new top-level operator prompt; no state file is edited or deleted to migrate them.
- D-005: Count the first isolated Claude driver run as failed. It exposed the
  `/tmp` versus `/private/tmp` equivalent-path gap and was fixed before rerun.
