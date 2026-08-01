# Knowledge Scaffold

This public repository contains only the knowledge-base contract and templates.
Actual grounding intelligence and weaponized material are operator-local and are
ignored by Git.

```text
knowledge/
├── README.md                 public contract
├── _TEMPLATE.md              local grounding-entry template
├── _lexicon.md               canonical class-name scaffold
└── weaponized/
    ├── README.md             local weaponized-tier contract
    └── .gitkeep              empty-directory scaffold
```

Local grounding entries live at `knowledge/<id>.md`. They may contain recognition
signatures, aliases, weak-point classes, mechanisms, primary references, proof-only
verification principles, and false-positive controls. They must not contain raw
payloads, exploit chains, request bodies, credentials, target identifiers, internal
paths, or engagement artifacts.

Local weaponized entries live under `knowledge/weaponized/`. They are never part of
the public repository. Runtime use remains match-gated:

```text
live fingerprint -> one matching local entry -> target-specific hypothesis
-> guarded proof/control -> evidence gate
```

`tools/check_knowledge.py` validates local grounding structure. Passing that check
does not make an entry safe to publish; the repository publication contract is
scaffold-only.
