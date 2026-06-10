# DeepSeek Context Slice

Use this slice for most DeepSeek cycles.

Every cycle loads two things together: the run files (the templates instantiated
under `runs/<target>/`) and the one operating-mode file for the current phase.
The run files define which fields must be filled; the mode file defines how you
reason to fill them. They are not alternatives — the mode produces exactly the
fields the templates require. Always carry both in the slice, and record both in
`decisions.md` under `Loaded rule files this cycle:`.

## Always Include

- project summary: DeepSeek is the single autonomous driver with safety
  boundaries and evidence gates
- the phase mode for this cycle (exactly one):
  - Driver: `docs/deepseek/driver_mode.md`
  - Hunter: `docs/deepseek/hunter_mode.md`
  - Reviewer: `docs/deepseek/reviewer_mode.md`
- `target.md`
- `frontier.md`
- `hypotheses.md`
- latest relevant `decisions.md`
- latest 5 to 10 `evidence.md` entries
- relevant `false_positive.md` entries

## Include Only When Needed

- full `evidence.md`
- full `surface.md`
- full historical report
- `docs/cognition/README.md`
- previous `review.md`

## Do Not Include By Default

- unrelated old reports
- all observations
- large raw artifacts
- copied exploit writeups
- historical targets unrelated to the current run

## Output Contract

Every cycle should update at least one of:

- `frontier.md`
- `hypotheses.md`
- `evidence.md`
- `false_positive.md`
- `decisions.md`
- `review.md`

If no file should change, the model must explain why the run is blocked.
