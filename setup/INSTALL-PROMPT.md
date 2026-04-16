# Launchpad Labs — Install Prompt

> **Source of truth.** This is THE live install prompt. Do not fork it into drafts elsewhere — iterate in this file.
> **Where it lives:** `MSPLaunchpadLabs/level-up/setup/INSTALL-PROMPT.md`
> **Superseded:** `starter-kit-research/04-claude-md-architecture.md` (old single draft), `starter-kit-research/07-starter-kit-files.md` §INSTALL-PROMPT.md (3-path draft — never approved).

---

## How to use it

1. Copy everything between the two horizontal rules below.
2. Fill in the six fields at the top (Name, Role, Bounty, Discord, Tech level, Credentials).
3. Open Claude Code in an empty folder.
4. Paste. Claude handles the rest.

---

Set up my Launchpad Labs workspace.

**My info (fill these in before pasting):**
- Name: [YOUR FULL NAME]
- Role at MSP Launchpad: [YOUR ROLE]
- Bounty: [BOUNTY # + NAME — e.g. "#44 GBP Image Set Generator"]
- Discord handle: [YOUR DISCORD USERNAME]
- Tech level (pick one, type it verbatim):
  - "new to code" — never used git, terminal, or APIs
  - "intermediate" — comfortable with computers, new to git/terminal
  - "experienced" — comfortable with code, git, and APIs
- Credentials from Thanh:
  [PASTE THE CREDENTIAL BLOCK THANH SENT YOU — the lines starting with ANTHROPIC_API_KEY=, LAUNCHFLOW_SUPABASE_URL=, LAUNCHFLOW_SUPABASE_SERVICE_KEY=, etc.]

---

**Your job, Claude:**

**Step 0 — Calibrate how you talk to me.** Read my tech level above, then act as follows for the rest of this session AND persist it into my CLAUDE.md so every future session behaves the same:
- "new to code" → plain language, explain each step before running it, pause after big moves, give browser click-by-click when I need to log in somewhere.
- "intermediate" → narrate what you're doing, briefly explain every command you run, don't over-explain.
- "experienced" → terse, just work, one-line confirmations.

**Step 1 — Clone the repo.** `git clone https://github.com/MSPLaunchpadLabs/level-up.git ~/launchpad-labs` (skip if already cloned). Then `cd ~/launchpad-labs`.

**Step 2 — Create my working branch.** `git checkout -b [first-name-lowercase]/main` then `git push -u origin [first-name-lowercase]/main`.

**Step 3 — Copy starter-kit files** from `setup/` into the root of my workspace:
- `CLAUDE.md.template` → `CLAUDE.md`
- `credentials.md.template` → `setup/credentials.md`
- `git-workflow.md`, `launchflow-guide.md`, `getting-unstuck.md` → `setup/` (as-is)

**Step 4 — Personalize my CLAUDE.md.** Replace every `[PLACEHOLDER]` with my info above. CRITICAL: my name, tech level, and coaching mode must all appear under the "Who You Are" section. Future Claude sessions read these and adjust.
- `**Name:** [my name]`
- `**Tech level:** [what I typed above]`
- `**Coaching mode:** [map from Step 0 — "Plain-language, confirm each step" | "Narrate + explain commands" | "Terse, just work"]`

**Step 5 — Bounty scaffolding.** Copy `bounties/BOUNTY-TEMPLATE.md` → `bounty/BOUNTY.md` and `bounties/PROGRESS-TEMPLATE.md` → `bounty/PROGRESS.md` in my workspace root.

**Step 6 — Set up .env.** Copy `setup/.env.example` → `.env`. Paste the credentials I gave you. Verify these are set:
- `LAUNCHFLOW_MEMBER_NAME=[my full name]` — used by LaunchFlow to show my sessions to the team
- `LAUNCHFLOW_SUPABASE_URL=…` (from credentials)
- `LAUNCHFLOW_SUPABASE_SERVICE_KEY=…` (from credentials)
- `SUPABASE_SANDBOX_URL=https://dtfljepvwblmgfcjvkkz.supabase.co` (pre-filled)
- `SUPABASE_SANDBOX_ANON_KEY=…` (from credentials)
- `ANTHROPIC_API_KEY=…` (only if my bounty needs programmatic Claude calls — most don't)

**Step 7 — Install the LaunchFlow auto-tracker (one-time).** Run `node scripts/launchflow-setup.js`. When it asks for name / Supabase URL / service key, use the values from my `.env`. After this, my Claude Code sessions auto-register to Lodewijk's LaunchFlow dashboard via hooks — I'll never run a "start session" command again. The installer is idempotent; safe to re-run if anything looks off.

**Step 8 — Commit setup and push.** `git add .` then a clean commit. **Verify `.env` is NOT staged** — it should be git-ignored. If git-ignored correctly, `git status` after `add .` will not show `.env`.

**Step 9 — Summary.** Show me:
- What files now exist in `~/launchpad-labs/` (one-level listing)
- One line each: my name, tech level, and coaching mode as written to CLAUDE.md
- A 3-line "First work session" cheat sheet for tomorrow.

**Step 10 — Read my bounty.** Open `bounty/BOUNTY.md` and tell me the smallest thing I could build today that would prove the bounty works. Don't start building — wait for me to say "go."

**If anything fails:** tell me exactly what went wrong in plain language and what to do about it. Don't silently skip steps.

---

## Notes for Thanh (not participants)

- **Before Day 1, per participant:**
  - Create their personalized credentials block (GREEN + any YELLOW/ORANGE their bounty needs) and send it over Discord DM.
  - Make sure they have: Claude Code installed, `gh` CLI installed and authed, Node.js ≥ 18.
  - Add them to the `MSPLaunchpadLabs` org with write access to the `level-up` repo.
  - Assign their build buddy (see `starter-kit-research/03-team-needs-matrix.md`).
- **If the install prompt itself needs updating during the event:** edit THIS file in the repo, push to main. Every future participant gets the new version on `git pull`. Don't create a "v2" prompt in chat or a research folder.
