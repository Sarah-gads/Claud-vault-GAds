# Starter Kit

The files every participant gets. The install prompt (below) copies them into each participant's workspace and personalizes them.

## Files

| File | Purpose |
|------|---------|
| `INSTALL-PROMPT.md` | **The Day-1 prompt.** Participants paste this into Claude Code. |
| `CLAUDE.md.template` | Main Claude Code context file. Personalized by the install prompt (name, tech level, bounty, etc.). |
| `credentials.md.template` | API keys + usage snippets. Thanh personalizes per participant. |
| `git-workflow.md` | First-time git setup + daily commands. |
| `launchflow-guide.md` | How LaunchFlow auto-tracking works + troubleshooting. |
| `getting-unstuck.md` | Self-service triage for the top blockers. |
| `.env.example` | Env var template. Copied to `.env` by participant, filled by Thanh's credentials block. |

## Source of truth

These files are the **live** versions. Draft history lives in `msp-launchpad/projects/level-up-event/starter-kit-research/07-starter-kit-files.md` on Lodewijk's workspace — that file is now **SUPERSEDED** by the files in this folder. Do not iterate in the research file.

**To update a starter-kit file during the event:** edit it in this folder, commit, push. Every future `git pull` distributes the update.
