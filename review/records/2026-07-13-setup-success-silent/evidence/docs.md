# Policy excerpts

`CLAUDE.md`:

> Mechanical Setup inside `setup_run.py` is the one display exception: record
> its start/end in the journal, but keep a successful setup stdout-silent
> because the selected-run statusline is the operator-facing display. Keep
> failures and degraded setup diagnostics on stderr; explicit
> `--help`/`--selftest` output is not normal setup progress.

`docs/WORKFLOW.md`:

> `setup_run.py` 的机械 Setup 是显示例外：仍写入 Setup 的 `phase_start` /
> `phase_end` journal 事件，但成功路径不向 stdout 打印进度或 banner，由选中
> run 的 statusline 承担显示；失败和降级诊断继续写 stderr。显式 `--help` /
> `--selftest` 不属于普通 setup 进度。其他实际进入的 Router 阶段继续显示
> start/end marker。

`.claude/skills/xunji-run-lifecycle/SKILL.md`:

> For mechanical `Setup`, `tools/setup_run.py` keeps a successful invocation
> stdout-silent; the selected-run statusline is its visible state. Failures and
> degraded setup diagnostics remain on stderr. For `/loop`, follow
> `docs/templates/loop_prompt.md`: enter Root Orchestrator before the state graph
> pass, Hunter before proof/verification/Agent action, Reviewer before
> merge/evidence/closure checks, and Report only when report material is being
> drafted or finalized.
