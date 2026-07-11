# Frontier

## Open Fronts

### F-001 Contract transition correctness
- Status: probing
- Barrier class: app-layer
- Current depth: deep
- Assets: `tools/turn_contract.py`, `tools/xunji_statusline.py`
- Next autonomous move: independently review pending, transfer, explicit-pointer, and session binding paths

### F-002 Control-plane bypass resistance
- Status: probing
- Barrier class: auth-layer
- Current depth: deep
- Assets: `tools/turn_contract.py`, setup/resume/statusline commands
- Next autonomous move: test direct pointer edits, unrelated set-active, unauthorized setup, and control-script impersonation

### F-003 Stop re-entry and output truth
- Status: probing
- Barrier class: app-layer
- Current depth: deep
- Assets: `.claude/hooks/output_gate.py`, `.claude/hooks/run_gate.py`
- Next autonomous move: review first-block versus retry behavior and no-front denial envelope compatibility

### F-004 Regression and documentation parity
- Status: probing
- Barrier class: none
- Current depth: moderate
- Assets: selftests, Claude-primary skills, workflow docs
- Next autonomous move: compare implementation, tests, and documented recovery sequence

## Deferred Fronts

## Closed Fronts

