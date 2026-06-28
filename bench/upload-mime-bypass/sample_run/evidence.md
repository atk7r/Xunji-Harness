# Evidence Ledger

## E-001: Upload MIME validation bypass with harmless proof file
- Action: Uploaded a harmless proof text file with mismatched MIME metadata to a local fixture.
- Result: upload MIME validation bypass confirmed; harmless proof file was stored and retrievable.
- Certainty: 0.9
- Control: disallowed extension was rejected when MIME matched; allowed image upload accepted normally.
- Replicated: yes
- Cleanup: proof file deleted from fixture storage.
- Supports: H-001

## E-002: Image upload accepted
- Action: Uploaded a valid demo image.
- Result: image upload accepted as expected.
- Certainty: 0.8
- Refutes: H-009
