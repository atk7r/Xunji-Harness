---
name: web-research
description: Xunji web research protocol — the recommended entry point for all external web searches during a run. Provides time-gating, knowledge-first ordering, and evidence integration rules. Invoke when any skill or agent needs to search the web for vulnerability intelligence, product documentation, exploit techniques, or security research.
---

# Web Research Protocol

This skill is a **protocol**, not a guard. It defines the recommended search
path and evidence-recording rules. Codex's native `WebSearch` / `WebFetch`
tools remain available — this skill ensures their output is correctly time-gated,
knowledge-grounded, and evidence-tracked.

## When to invoke

- Any agent needs to search for CVE/CNVD/safety-advisory details
- Researching a product/version for known vulnerabilities or configuration
- Looking up the latest bypass technique for a specific barrier class
- Finding current documentation for a framework's auth/upload/serialization
- Any external intelligence gathering that will feed into evidence or decisions

## Protocol (硬顺序 — do not reorder)

### Step 1: Time Gate

Before every external search, run the time gate:

```bash
python tools/timestamp_gate.py --search-hint --kind vuln   # CVE/CNVD searches
python tools/timestamp_gate.py --search-hint --kind generic # non-CVE research
```

The output is a time-constraint string from the single authoritative source.
Execute every constraint in it — the tool encodes the current date, year, and
verification rules; your job is to follow it, not reinterpret it.

### Step 2: Knowledge-First Check

**Before `WebSearch`**, check local knowledge base:

```bash
grep -ri "<product-name|vendor-name>" knowledge/ --include="*.md" -l
```

If a matching `knowledge/*.md` entry exists → Read it first. The knowledge base
contains verified signatures, CVE anchors, and weak-point notes that are more
reliable than raw web search results.

Only proceed to `WebSearch` after confirming the knowledge base has no coverage
for this product/signature.

### Step 3: Search & Fetch

- `WebSearch` for discovery: always include the current year in the query
- `WebFetch` for deep reading: verify the source is authoritative (NVD, vendor
  advisory, official docs, reputable exploit-db) before trusting
- Cross-validate claims: one search result → consider. Two+ independent sources → evidence

### Step 4: Record as Evidence

After completing research, record findings into the run ledger:

```bash
python tools/record_evidence.py --run <run_dir> \
  --source web-research \
  --query "<search query>" \
  --date "$(python tools/timestamp_gate.py --iso)" \
  --finding "<what was found>" \
  --provenance "<URL or source>"
```

If `record_evidence.py` is not available, write directly to `evidence.md` with:
```markdown
- Source: WebResearch, <date>
- Query: <search query>
- Finding: <what was found>
- Provenance: <URL>
- Confidence: low/medium/high (based on source authority + cross-validation)
```

### Step 5: Return to Caller

The web-research invocation is complete when the finding is recorded.
Return to the calling skill/agent with:
- The finding summary (one line)
- The evidence entry ID (if recorded)
- The confidence level

## What NOT to do

- Do NOT search for the target's internal domain names or IP addresses
- Do NOT search for project codenames or operator-identifying information
- Do NOT use the search results directly in a finding without recording them
  as evidence first — "I read it somewhere" is not evidence
- Do NOT trust a single search result at certainty ≥ 0.6 — cross-validate

## Anti-patterns

- Skipping the time gate → stale CVE numbers, wrong default passwords, outdated
  bypass techniques
- Skipping knowledge-first → consuming a wrong vendor's CVE when the correct
  `knowledge/*.md` entry exists unread (protocol error per retrospective #3/#15)
- Searching without recording → the run ledger has no trace of where a claim
  came from, breaking the evidence gate

## Integration with other skills

Other skills (xunji-exploit-techniques, captcha-solve, etc.) should route their
web research needs through this skill. Within a skill, when you need to search:

1. Note "invoke web-research" in your reasoning
2. Switch context: the Agent invokes this skill with the specific query
3. This skill returns the structured finding
4. The calling skill continues with the finding as input

## Reference

- `tools/timestamp_gate.py` — time gating tool (single authoritative source for all time/CVE-year constraints)
- `tools/anti_drift.py` — binding rules (TIER1: run timestamp_gate before search; TIER3: output tripwire — skip = protocol error)
- `knowledge/` — local verified intelligence base (check before external search)
- `tools/harness/guard.py` — guard layer (web-research traffic does NOT go through engagement proxy)
