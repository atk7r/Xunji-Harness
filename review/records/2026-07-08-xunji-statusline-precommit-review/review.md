# Peer Review Panel — 2026-07-08-xunji-statusline-precommit-review

_backend: panel:claude · 2026-07-08T08:40Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: NEEDS_DRIVER

_backend: panel:claude_  
_brain: codex_  
_bundle_hash: f3950cbdd9c26c52275faa0acdbf6c667121ed74_  
_evidence_index_hash: 80cb3715cb494554f36b1fb9628ac8817fae0591_  

## Findings
- [WARN] PR-001 review panel had backend errors; aggregation is partial | Evidence: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; minimax-m3: parse error; output tail: y check via mtime**: This is good - the selftest records mtime before/after render and confirms they're equal. But this only checks that the watched files aren't modified. It doesn't check that no OTHER files are modified. The script could potentially write to other locations not in the watch list. Let me look at the render code again...
    
    The render function calls:
    - `_load_json` - reads files
    - `_journal_summary` - reads file, parses JSON
    - `_agent_summary` - reads files
   ; glm-5.2: parse error; output tail: 0 lines, which is good. But there's no caching or throttling.

- **Concurrent file access**: The statusline reads state files that might be written by other processes. There's no file locking. If a file is being written while being read, `_load_json` would catch the exception and return the default. This seems handled.

- **Encoding issues**: The code uses `errors="replace"` when reading text, which is good for handling encoding issues. But the selftest uses `json.dumps(..., ensure_ascii=False)` | Why: At least one requested heterogeneous reviewer failed or was unavailable.

## Blind-spot check
- [claude] **Concurrent writer collision on `.tmp` file**: `set_active_run` at line 146-149 writes to `ACTIVE_RUN.name + ".tmp"` — two concurrent processes would race on the same temp file. While `Path.replace()` is atomic on POSIX, the intermediate `write_text` on a shared `.tmp` is not. Using `tempfile.mkstemp(dir=ACTIVE_RUN.parent)` would eliminate the collision.
- [claude] **`XUNJI_COLOR=1` vs `status_style.color_enabled()` disagreement**: The settings command hard-sets `XUNJI_COLOR=1` in the environment, but `main()` at line 408 defers to `status_style.color_enabled()`. If `NO_COLOR` or `XUNJI_NO_COLOR` is also set in the environment, `color_enabled()` may return False despite the explicit `XUNJI_COLOR=1`. The selftest explicitly unsets both (`env.pop("NO_COLOR", None); env.pop("XUNJI_NO_COLOR", None)`) at lines 350-351 during testing, meaning the production case where these are set is untested.
- [claude] **`loop_bootstrap.py` selftest patches module globals without hardened restore**: Lines 78-108 of the bootstrap selftest patch `_set_active_run`, `_find_run_by_slug`, `_refresh_loop_state`, `_print_launch_instructions`, and `subprocess.run`. If `finally` itself raises (e.g., during `subprocess.run = orig_subprocess_run`), the module retains patched globals, corrupting subsequent code. This is unlikely but the restore logic isn't hardened with nested try/except like the active-run pointer restore which already appears earlier in the same selftest.
- [claude] **The statusline reads `assignments.json` and `conflicts.json` in separate `_load_json` calls** (lines 200-204): between these two reads, the main session could update either file, producing an internally inconsistent summary. This is inherent to file-based IPC and harmless for a display, but the report doesn't acknowledge this minor inconsistency window.
- [claude] **`.gitignore` wildcard `xunji_active_run*` is broader than needed**: The code only ever writes `xunji_active_run` and `xunji_active_run.tmp`. While defensive, the wildcard would also ignore `xunji_active_run.backup` or similar variants that a future operator might create intentionally. This is comment-worthy but trivial.
- [claude] **No Windows path handling**: The settings command uses `$CLAUDE_PROJECT_DIR` with forward slashes and double-quotes, which works on Unix but not natively on Windows PowerShell. The official docs (`claude-code-statusline-excerpt.txt` excerpt 6) explicitly warn about backslash consumption on Windows and recommend forward slashes or PowerShell `-File` invocation. The current command neither addresses this nor documents that Windows is unsupported/untested.

## Context-limit notes
- [claude] The `status_style.py` module (imported at line 33 of the statusline) could not be read directly due to scope restrictions. I verified its functions (`tag`, `paint`, `color_enabled`) exist implicitly through the selftest passing (test-log.txt line 119-131) and the patch compile succeeding (line 1-2). The actual `color_enabled()` logic that determines whether `XUNJI_COLOR=1` takes effect was not inspected.
- [claude] The `loop_prompt.md` template placeholder mechanism (`{{PYTHON}}`, `{{RUN_DIR}}`) could not be verified by reading the existing template file. I inferred its correctness from the existing pattern (the patch adds one line using the same `{{PYTHON}}` syntax already present in the template) and the selftest passing (test-log.txt line 302: "loop command names run").
- [claude] The `review.md` file does not exist in the review directory — expected since this review output IS the review being produced. No review artifact cross-check was possible.
- arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; minimax-m3: parse error; output tail: y check via mtime**: This is good - the selftest records mtime before/after render and confirms they're equal. But this only checks that the watched files aren't modified. It doesn't check that no OTHER files are modified. The script could potentially write to other locations not in the watch list. Let me look at the render code again...
    
    The render function calls:
    - `_load_json` - reads files
    - `_journal_summary` - reads file, parses JSON
    - `_agent_summary` - reads files
   ; glm-5.2: parse error; output tail: 0 lines, which is good. But there's no caching or throttling.

- **Concurrent file access**: The statusline reads state files that might be written by other processes. There's no file locking. If a file is being written while being read, `_load_json` would catch the exception and return the default. This seems handled.

- **Encoding issues**: The code uses `errors="replace"` when reading text, which is good for handling encoding issues. But the selftest uses `json.dumps(..., ensure_ascii=False)`
- panel completed 1/2 required heterogeneous backends

> ERROR: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; minimax-m3: parse error; output tail: y check via mtime**: This is good - the selftest records mtime before/after render and confirms they're equal. But this only checks that the watched files aren't modified. It doesn't check that no OTHER files are modified. The script could potentially write to other locations not in the watch list. Let me look at the render code again...
    
    The render function calls:
    - `_load_json` - reads files
    - `_journal_summary` - reads file, parses JSON
    - `_agent_summary` - reads files
   ; glm-5.2: parse error; output tail: 0 lines, which is good. But there's no caching or throttling.

- **Concurrent file access**: The statusline reads state files that might be written by other processes. There's no file locking. If a file is being written while being read, `_load_json` would catch the exception and return the default. This seems handled.

- **Encoding issues**: The code uses `errors="replace"` when reading text, which is good for handling encoding issues. But the selftest uses `json.dumps(..., ensure_ascii=False)`