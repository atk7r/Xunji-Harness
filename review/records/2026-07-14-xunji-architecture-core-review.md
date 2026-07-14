# Xunji 核心与架构记忆变更复审记录（2026-07-14）

diff_fingerprint: 0761f95a464bf35e
reviewed_diff: 0761f95a464bf35e

## 1. 对象与作者矩阵

- Author / final synthesis: Codex。
- Review target: `AGENTS.md`、`CLAUDE.md`、`README.md`、
  `docs/ARCHITECTURE.md`、`tools/check_rules.py`。
- Scope kind: repository maintenance / architecture documentation；不是 live
  pentest run，不适用 recon、certainty、finding-artifact 或 run-closure rubric。
- Required independent matrix: arkcli panel + Claude Code fresh-context；Codex
  自审不计独立票。

最终文件 SHA-256：

| File | SHA-256 |
|---|---|
| `AGENTS.md` | `852bb98906e750b8a26898331762941fcf2ea8f30c4b71c3c52266b8023e8fa5` |
| `CLAUDE.md` | `2a5c0bd160b71c69a86c089441f737e08220c1a2673345463acde2fea9c63890` |
| `README.md` | `eff82803724740aa47108a67fcc7315666d4a76d168f744641e5cc87b546a11b` |
| `docs/ARCHITECTURE.md` | `eae3224e5d0781ef752538b456fa618c28a0e7167124b849c2f0de214a65c4c7` |
| `tools/check_rules.py` | `6498d9205dde063586d2d4664d2cde3dd58ad0be752b9e14a6e7444b4c0af29f` |

## 2. Reviewer 运行结果

| Round | Backend | Result | Record |
|---|---|---|---|
| Initial | Claude Code fresh-context | `PASS` + 1 actionable WARN | `2026-07-14-xunji-architecture-core-claude.md` |
| Initial | arkcli Kimi + GLM panel | `WARN`; Kimi returned findings, GLM parse failed | `2026-07-14-xunji-architecture-core-arkcli.md` |
| Revised full | Claude Code fresh-context | `PASS`, no findings | `2026-07-14-xunji-architecture-core-claude-final.md` |
| Revised full | arkcli Kimi + GLM panel | `WARN`; one content finding, GLM parse failed | `2026-07-14-xunji-architecture-core-arkcli-final.md` |
| Final delta | arkcli panel | no new content finding; Kimi output parse failed | `2026-07-14-xunji-architecture-core-arkcli-delta.md` |
| Final delta | Claude Code fresh-context | parser `ERROR` after two no-verdict responses | `2026-07-14-xunji-architecture-core-claude-delta.md` |

The revised full artifact therefore has a clean Claude independent vote and an
arkcli content review with no blocker. The final small checkpoint-validator delta
was directly requested by arkcli and verified locally, but its confirmation calls
did not produce two parseable votes. That limitation remains `WARN`; it is not
rewritten as approval.

## 3. Findings 与处置

| ID | Reviewer finding | Disposition | Evidence / result |
|---|---|---|---|
| R-01 | `Architecture impact: none` could be recorded only in ephemeral chat. | Accepted. | Every non-trivial maintenance round now updates the single persistent `Maintenance Checkpoint` in `docs/ARCHITECTURE.md`; AGENTS and CLAUDE name the same location. |
| R-02 | A top-level “recently verified” date encourages timestamp-only churn. | Accepted. | The standalone date was removed. The checkpoint requires scope, impact, verification and review; Git history retains previous checkpoints. |
| R-03 | Current and target were sectioned, but transitional architecture was not. | Accepted. | Added a current/transitional/target table with per-boundary completion gates and explicit prohibition on a second runtime truth. |
| R-04 | `check_rules.py` did not pin owner map or invariants. | Accepted. | Required headings now include transition, target, owner map, change protocol, invariants and checkpoint. |
| R-05 | Checkpoint heading alone can survive while durable fields disappear. | Accepted. | Added `check_maintenance_checkpoint()` requiring non-empty, non-placeholder Date, Scope, Architecture impact, Verification and Independent review fields. Positive/negative fixtures pass. |
| R-06 | `.claude` and `.agents` safety skills could drift without an explicit authority distinction. | Accepted. | Owner map now states `.claude/skills/src-safety-boundary` is the live-driver declaration; `.agents/...` is an auxiliary mirror/entry and not enforcement. |
| R-07 | `src-safety-boundary` was claimed not to exist. | Dismissed as factual error. | Both `.claude/skills/src-safety-boundary/SKILL.md` and `.agents/skills/src-safety-boundary/SKILL.md` exist in the reviewed checkout. The final doc uses explicit paths. |
| R-08 | Existing wording that Codex retains synthesis/decision responsibility grants self-approval. | Dismissed. | The same section explicitly requires external reviewers and says Codex self-review is not independent. “Synthesis” means disposition/integration responsibility, not a bypass of review or operator/Git authority. This wording predated the change and is the repository's author matrix. |
| R-09 | AGENTS + architecture doc add context cost. | Noted, no change. | AGENTS contains only fused invariants/autonomy/continuity; detailed architecture is loaded for non-trivial maintenance, not every routine answer. The operator explicitly requested durable project-core context. |

## 4. Verification

- `python3 tools/check_rules.py`: PASS.
- `python3 -m py_compile tools/check_rules.py`: PASS.
- Checkpoint positive/negative in-memory fixtures: PASS. The negative fixture
  also caught and caused repair of an initial cross-line `\s*` regex bug.
- `git diff --check`: PASS.
- `python3 tools/selftest_all.py`: **60 passed, 0 failed** on the final files.

No target actions or live-run mutations were performed. Pre-existing user changes
to `TODO.md`, `tools/harness/privacy.py`, deletion of
`docs/XUNJI_PROJECT_INTRO.md`, and untracked run/evidence artifacts were not
modified or treated as this change's review scope.

## 5. Final synthesis

**Verdict: WARN — design is reasonable and ready to use; no unresolved content
blocker.**

The fused principles preserve the correct split: model judgment and autonomous
front selection remain open, while authority, safety/privacy, state, evidence,
review and closure remain deterministic. The architecture document distinguishes
implemented Python/Claude behavior from transitional conformance work and target
CCB-native tools. The single checkpoint satisfies the operator's “update every
round” requirement without turning the design body into timestamp churn.

Residual WARN is review-tool reliability: GLM failed structured parsing in both
full arkcli rounds, and the final delta confirmation did not return two parseable
votes. The accepted delta was the reviewer's own requested checkpoint-field guard,
is narrow, has positive/negative fixtures, and the full 60-suite regression is
green. Future changes should continue recording backend parse failures rather than
treating partial panels as unanimous approval.

Architecture impact: yes — project core, autonomy, owner boundaries, transition
model and architecture-memory protocol were intentionally changed and recorded in
`docs/ARCHITECTURE.md`.
