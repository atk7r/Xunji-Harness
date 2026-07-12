# Proof-Oriented Sensors

Sensors are proof helpers. They produce candidate/evidence artifacts for the
driver to inspect and cite; they do not select targets, confirm findings, write
canonical `evidence.md`, or bypass the evidence gate.

Output convention:

- JSON artifacts live under `<run>/evidence/sensors/` when `--run` is supplied.
- Each artifact includes `sensor`, `candidate`, `artifact`, `control`, and
  `replicated` fields where applicable.
- A `candidate` is still not a finding. The driver must copy only supported
  facts into `evidence.md`, apply certainty rules, and attach controls.

Tools:

- `oob_listener.py` records callback proof events with a nonce.
- `mutate_payload.py` transforms an operator-supplied string into encoding and
  container variants. It does not ship payload lists.
- `blind_diff.py` samples baseline vs mutant URLs through `probe.send`.
- `upload_probe.py` sends a harmless multipart proof object through `probe.send`
  with a neutral unique marker/filename/boundary and can register cleanup
  obligations in `UploadRegistry`. Custom marker/filename values must keep the
  `proof-YYYYMMDD-<6-12hex>[.ext]` shape; the boundary uses
  `----proof-YYYYMMDD-<6-12hex>` derived from that upload's marker.
