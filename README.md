# Launchpad Labs — Event Hub

Shared resources, scripts, and bounty specs for the Launchpad Labs 3-week hackathon (April 2026).

## Repo layout

| Folder | What lives here |
|--------|-----------------|
| `bounties/` | One markdown file per bounty — full brief, "Shipped + Proven" bar, suggested approach, dependencies |
| `shared/` | Foundation Frameworks that every participant pulls: visual brand, voice + copy, skill anatomy |
| `setup/` | Starter-kit files every participant gets: `CLAUDE.md` template, `credentials.md` template, `git-workflow.md`, `launchflow-guide.md`, `getting-unstuck.md`, `.env.example` |
| `scripts/` | Team-wide scripts (work tracker, install helpers, packaging tools) |

## Who can edit what

- **Thanh + Lodewijk:** everything (admins)
- **Participants:** **read-only.** Changes land via PR from a fork or from their personal repo under the same org. Thanh or Lodewijk merges.
- **CODEOWNERS** (`.github/CODEOWNERS`) auto-requests review on every PR.

> **Note on branch protection.** The org is on GitHub Free, where branch protection rules and rulesets require Team/Pro. Enforcement is via team convention + repo permissions (participants don't get push on `main`). For hard enforcement before the event, upgrade the org to Team or make this repo public — either unlocks rulesets that require PR + 1 review on `main`.

## Participant onboarding

Each participant gets their own repo under `MSPLaunchpadLabs` (format: `MSPLaunchpadLabs/<participant-name>-<bounty-slug>`). That repo is where they build. This `level-up` repo is the shared index.

Participants `git pull` this repo once per session to stay in sync with shared resources (frameworks, getting-unstuck updates, etc.).

## Live work tracking

Sessions register with LaunchFlow **automatically** via a Claude Code hook. One-time install: `node scripts/launchflow-setup.js`. After that, every Claude Code session auto-appears on the Live Work tab — participants never run a "start session" command. See `setup/launchflow-guide.md`.

The old Python script (`scripts/work-tracker.py`) is retained as a manual fallback; the hook is the default path.

LaunchFlow: https://launchflow.msplaunchpad.com (EVENT tab)

## Security

- **Never commit `.env` files, credentials, or API keys.** The `.gitignore` blocks common patterns, but don't rely on it — double-check before `git add`.
- **Executive Vault is off-limits.** Participants use only the `Launchpad Labs Sandbox` Supabase project. See `setup/credentials.md`.

## Questions

- Bounty scope, strategy: Lodewijk
- API access, infra, deployments: Thanh
- Stuck on build: check `setup/getting-unstuck.md` first, then Thanh
