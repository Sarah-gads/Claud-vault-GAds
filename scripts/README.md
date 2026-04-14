# Scripts

Team-wide scripts shared with all participants.

## Files (to be added)

| File | Purpose |
|------|---------|
| `work-tracker.py` | Register sessions with LaunchFlow. Stdlib only — no deps. Works on Mac/Windows/Linux. Resolves session_id from `~/.claude/sessions/*.json`. |
| `install.sh` / `install.ps1` | Day-1 setup helpers (git init, create folder structure, personalize CLAUDE.md) |
| `packaging/extract-skill.py` | End-of-event packaging — collect shipped skills into unified Agency OS folder |

## work-tracker.py

Source: `msp-launchpad/scripts/work-tracker.py` in Lodewijk's workspace. Ported here for participants.

Usage (from participant CLAUDE.md):

```bash
# Start of session
python scripts/work-tracker.py start "Bounty Name" "What you're working on" --member "Your Name"

# Heartbeat (optional — keeps "live" indicator fresh)
python scripts/work-tracker.py heartbeat

# Pause or end session
python scripts/work-tracker.py pause
python scripts/work-tracker.py complete "What you shipped"
```

Required env vars (set in `.env`):

- `LAUNCHFLOW_SUPABASE_URL` — Team Ops Supabase URL
- `LAUNCHFLOW_SUPABASE_SERVICE_KEY` — service role key (Thanh provides)
- `LAUNCHFLOW_MEMBER_NAME` — your name (auto-set by install prompt)

Diagnostic: `python scripts/work-tracker.py whoami` shows resolved config.
