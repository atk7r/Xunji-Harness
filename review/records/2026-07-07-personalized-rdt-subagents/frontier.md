# Frontier

## Open Fronts

### F-001
- Front: Add per-run personalized RDT profile without creating a new runtime
- Status: implemented
- Current depth: reviewed by local tests
- Barrier class: none
- Same barrier failures: 0
- Vectors tried: context pack injection, assignment scaffold, setup scaffold, docs
- Untried classes: independent review

### F-002
- Front: Preserve compatibility for existing run agents
- Status: implemented
- Current depth: regression smoke tested
- Barrier class: old-agent schema drift
- Same barrier failures: 1
- Vectors tried: agent-check on `runs/oppo_20260707_20260707`, targeted workers selftest
- Untried classes: full historical run sweep

