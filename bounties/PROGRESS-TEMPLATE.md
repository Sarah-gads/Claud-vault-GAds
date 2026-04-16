# Session Progress -- [BOUNTY_NAME]

Claude appends to this file at the end of every session. Never overwrite previous entries. Always append at the bottom.

Each entry follows this format:

---

## [DATE] -- Session [NUMBER]

**What was built:**
- [Specific thing 1]
- [Specific thing 2]

**Current state:** [Working / Partially working / Broken -- one sentence on what does and does not work]

**Blockers:**
- [Blocker 1 -- what is stuck and why]
- [None if nothing is blocked]

**Next session -- do these first:**
1. [Most important thing to do next]
2. [Second priority]
3. [Third priority]

**Decisions made:**
- [Any scope, approach, or architecture decisions -- so you remember why you chose this path]

**Files created or changed:**
- `path/to/file.js` -- [what it does]

---

## Example Entry

---

## 2026-04-22 -- Session 3

**What was built:**
- Keyword extraction function that pulls top 50 keywords from SEMrush for a given domain
- Basic scoring system that ranks keywords by volume * (1 - difficulty/100)
- CSV export of scored keywords

**Current state:** Partially working. Extraction and scoring work. CSV export throws an error when keywords contain special characters.

**Blockers:**
- CSV encoding issue with non-ASCII characters (accented city names in Spanish MSP data)

**Next session -- do these first:**
1. Fix CSV encoding (use UTF-8 BOM header)
2. Add competitor keyword gap analysis (compare client vs. top 3 competitors)
3. Test on Alexant and Slate client data

**Decisions made:**
- Using SEMrush API directly via curl instead of MCP because MCP needs re-auth
- Scoring formula: volume * (1 - KD/100) * intent_weight -- intent_weight is 1.5 for commercial, 1.0 for informational

**Files created or changed:**
- `src/extract.py` -- SEMrush keyword extraction
- `src/score.py` -- Keyword scoring algorithm
- `output/sample-keywords.csv` -- Test output (do not commit real client data)