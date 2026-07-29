# Target

- Object: `tools/turn_contract.py` and the matching lifecycle architecture checkpoint.
- Issue: `/loop /absolute/repository/runs/name继续` was compiled as a new file source
  instead of an existing-run resume. A clean relative retry then failed because the
  one-use authority was bound to the malformed absolute token.
- Author/integrator: Codex. Codex self-review is not an independent vote.
- Scope class: repository maintenance with no Guanlan recon and no target-facing
  security assessment. Pentest coverage/asset requirements are not applicable;
  lifecycle authority and forbidden local effects remain in scope.
- Baseline: `2dae071` already contains the framework deadlock repair for durable
  Reviewer replay, typed foreground peer review, split wire/saved replay identity,
  evidence-CAS review persistence, and typed-cycle Coda accounting.
