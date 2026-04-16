# LaunchFlow Tracker — Team Setup

Auto-registers your Claude Code sessions to the LaunchFlow **Live Work** tab so the team can see what you're working on. **No Python required. No manual registration.**

## What it does

- Every time you open Claude Code inside an MSP Launchpad directory, a row is created on the Live Work tab.
- The description updates from your first prompt, then shows live activity ("now: editing foo.ts").
- Heartbeats keep the row alive while you work; it auto-expires 2 hours after the last heartbeat if Claude Code crashes.
- When the session ends cleanly, the row is marked completed.
- Works in all modes, including `--dangerously-skip-permissions`.

## What you need

1. **Node.js** — already bundled with Claude Code, nothing to install.
2. **Your name** — how you want to appear on the Live Work tab.
3. **LaunchFlow Supabase URL + service role key** — ask Lodewijk or check the team vault. Same values every team member uses.

## Install (one-time)

From the `msp-launchpad/scripts/` directory:

```bash
node launchflow-setup.js
```

You'll be prompted for your name and the two Supabase values. The installer:
1. Copies `launchflow-tracker.js` to `~/.claude/hooks/`
2. Writes `~/.launchflow/.env` with your config
3. Patches `~/.claude/settings.json` to wire up the 5 hook events (backs up first)
4. Runs a diagnostic to verify everything resolves

If you prefer a one-liner:

```bash
node launchflow-setup.js \
  --name "Your Name" \
  --url "https://<project>.supabase.co" \
  --key "<service-role-jwt>"
```

## Verify

```bash
node ~/.claude/hooks/launchflow-tracker.js whoami
```

Should show `MSP Launchpad ctx? : YES`, a set service key, and your name.

## Backfill already-open sessions

If you already had Claude Code windows open before running the installer, they aren't tracked yet. Run:

```bash
node ~/.claude/hooks/launchflow-tracker.js retro
```

This scans `~/.claude/sessions/` for active Claude Code sessions, checks each against LaunchFlow, and creates rows for any MSP Launchpad sessions that are missing — pulling the first user prompt from the transcript as the description.

## Skipping personal sessions

If you're doing something personal inside an MSP Launchpad directory and don't want it on the Live Work tab, start that Claude Code session with:

```bash
LAUNCHFLOW_SKIP=1 claude
```

The tracker will silently no-op for that session.

## Debugging

Add `LAUNCHFLOW_DEBUG=1` to `~/.launchflow/.env` to log every hook invocation to `~/.launchflow/hook-debug.log`. Tail it:

```bash
tail -f ~/.launchflow/hook-debug.log
```

Failures never block Claude Code — the tracker always fails silently. The debug log is the only place errors surface.

## Uninstall

1. Remove `~/.claude/hooks/launchflow-tracker.js`
2. Remove `~/.launchflow/` (or just delete `.env` if you want to keep the debug log)
3. Open `~/.claude/settings.json` and remove the 5 entries pointing to `launchflow-tracker.js`. A backup was saved when the installer first ran — check `settings.json.backup-*`.

## Architecture (for the curious)

- One Node.js file at `~/.claude/hooks/launchflow-tracker.js`. No dependencies beyond Node's stdlib.
- Wired into 5 Claude Code hook events: `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `Stop`, `SessionEnd`.
- Makes direct HTTPS calls to Supabase REST API (`ob_live_work` table). No intermediary service.
- Session state (heartbeat throttle, initial description) persists in `~/.launchflow/hook-state.json`.
- Throttled so `PostToolUse` only heartbeats every 10 minutes. Total Supabase calls per multi-hour session: ~30. Network overhead: ~30KB. CPU overhead: under 3 seconds spread across the whole session.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| My sessions aren't appearing on Live Work | Tracker thinks you're not in an MSP Launchpad directory | Run `whoami` — check `MSP Launchpad ctx?` is YES. Fast path requires CWD containing `claude code` or `msp-launchpad`. |
| Member name shows blank | `LAUNCHFLOW_MEMBER_NAME` not set | Edit `~/.launchflow/.env` or re-run the installer |
| `HTTP 401` in debug log | Wrong Supabase key | Re-run installer with the correct service role key |
| `HTTP 404` in debug log | Wrong Supabase URL | Re-run installer with the correct project URL |
| Old session stuck as "active" on Live Work | Claude Code crashed before `SessionEnd` fired | Server-side job auto-expires after 2h of no heartbeat. No action needed. |
| I'm using the old `work-tracker.py` | Both can coexist | The Python script still works for manual/scripting use. The hook handles the auto-tracking layer. |
