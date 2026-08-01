# Review Scope

Codex changed the normal successful path of `tools/setup_run.py` to be silent.
The selected-run statusline is now the only normal setup display.

Review questions:

1. Does a successful setup emit nothing on stdout and no diagnostic on stderr?
2. Are failure and degraded-path messages still visible on stderr?
3. Are explicit `--help` and `--selftest` outputs intentionally preserved?
4. Are the Setup `phase_start` / `phase_end` journal events and atomic active-run
   selection preserved?
5. Do the Claude-primary instructions describe this narrow mechanical-Setup
   exception without removing visible markers from later Router phases?
6. Does `loop_bootstrap.py` avoid printing a blank line when the now-silent
   setup subprocess returns empty stdout?

This is repository maintenance only. It does not authorize or perform target
traffic.
