# Evidence Ledger

## E-001: Path normalization bypass reaches fixture marker
- Action: Compared direct traversal with a normalized path variant against fixture-owned marker data.
- Result: path normalization bypass confirmed; direct traversal blocked while normalized variant reached marker.
- Certainty: 0.9
- Control: direct traversal blocked; benign path returned expected public resource.
- Replicated: yes
- Supports: H-001

## E-002: Direct traversal blocked
- Action: Tried the simplest traversal form.
- Result: direct traversal blocked by filter.
- Certainty: 0.8
- Refutes: H-009
