# LaunchFlow Work Tracking

## What Is LaunchFlow?

LaunchFlow is our team dashboard. It shows what everyone's working on in real time. During Launchpad Labs, Lodewijk uses the **EVENT tab** to see who's active, what bounties are being built, and where people might be stuck.

**Dashboard:** https://launchflow.msplaunchpad.com → click **EVENT** at the top.

## Why It Matters

When your session is registered, your name and bounty show up live. This means:
- Lodewijk can see who's working and on what, right now
- If you get stuck, he can reach out proactively
- Your work time is visible — it counts toward your contribution

If you're not registered, you're invisible to the team. No registration = no help, no credit.

## The Short Version

**You don't run any commands.** The install prompt set up a Claude Code hook that auto-registers every session you open. Session starts, prompts, file edits, and session ends all ping LaunchFlow in the background.

Open Claude Code → you appear on EVENT tab within seconds. Close Claude Code → session is marked completed.

## How the Hook Works (Technical)

The hook lives at `~/.claude/hooks/launchflow-tracker.js` and fires on 5 Claude Code events:
- **SessionStart** — creates a new row on the dashboard
- **UserPromptSubmit** — updates the description from "Starting session…" to what you're actually doing
- **PostToolUse** (on file writes/edits) — updates the description tail with the file you're editing
- **Stop** (every 10 min during work) — keeps the heartbeat fresh so your row stays "active"
- **SessionEnd** — marks the row `completed`

The hook reads your config from `~/.launchflow/.env` (created by the installer). That file holds:
- `LAUNCHFLOW_MEMBER_NAME` — your name as shown on the dashboard
- `LAUNCHFLOW_SUPABASE_URL` — where the tracker writes
- `LAUNCHFLOW_SUPABASE_SERVICE_KEY` — auth for writes

## If Nothing Shows Up for You

1. **Verify install.** Run `node scripts/launchflow-setup.js whoami` from the cloned `level-up` repo. It prints your resolved config + diagnoses the most common issues.
2. **Re-run install.** `node scripts/launchflow-setup.js`. It's idempotent — safe to run as many times as you want. Re-running fixes missing hook wiring, bad env values, and wrong settings.json entries.
3. **Check your `~/.launchflow/.env`.** If `LAUNCHFLOW_MEMBER_NAME` or the Supabase URL/key is blank, copy the right values from your workspace `.env` into `~/.launchflow/.env` and re-run the installer.
4. **Enable debug logging.** Set `LAUNCHFLOW_DEBUG=1` in your shell, run Claude Code, then read `~/.launchflow/hook-debug.log`.
5. **Ask Thanh.**

## Opting Out for a Specific Session

If you're doing personal/off-event work and don't want it tracked, set `LAUNCHFLOW_SKIP=1` in your shell before launching Claude Code:

```bash
export LAUNCHFLOW_SKIP=1
```

The hook silently skips registration for that session.

## Manual Fallback (Only If the Hook Is Broken)

The old Python tracker (`scripts/work-tracker.py`) is kept as a backstop. It requires Python 3.12 and takes the same inputs:

```bash
python scripts/work-tracker.py start "YOUR BOUNTY" "What you're doing" --member "YOUR NAME"
python scripts/work-tracker.py update "New task within same bounty"
python scripts/work-tracker.py complete "What you finished"
python scripts/work-tracker.py pause
```

But the hook is the default — only reach for this if Thanh tells you to.

## What Shows Up on the EVENT Tab

- **Your name** and the bounty you're working on
- **A live description** — initially the first prompt you gave Claude, then auto-updated to "…now: editing `foo.md`" as you work
- **How long** you've been in this session
- **A stale warning** if your session hasn't pinged in >30 min (just means no recent activity, not that you're in trouble)

## Privacy Note

The hook reports the file name you're editing in the description — e.g. "now: editing bounty/BOUNTY.md" — so the team can see progress shape. It does **not** report file contents, prompts in full, or tool outputs. If you're editing something you'd rather not have shown, rename the file or `export LAUNCHFLOW_SKIP=1` for that session.
