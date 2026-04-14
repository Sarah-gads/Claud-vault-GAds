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
- **Participants:** open PRs against `main` — no direct push
- **Guests:** read-only

## Participant onboarding

Each participant gets their own repo under `MSPLaunchpadLabs` (format: `MSPLaunchpadLabs/<participant-name>-<bounty-slug>`). That repo is where they build. This `level-up` repo is the shared index.

Participants `git pull` this repo once per session to stay in sync with shared resources (frameworks, getting-unstuck updates, etc.).

## Live work tracking

All sessions register with LaunchFlow via `scripts/work-tracker.py`. See `setup/launchflow-guide.md`.

LaunchFlow: https://launchflow.msplaunchpad.com (EVENT tab)

## Security

- **Never commit `.env` files, credentials, or API keys.** The `.gitignore` blocks common patterns, but don't rely on it — double-check before `git add`.
- **Executive Vault is off-limits.** Participants use only the `Launchpad Labs Sandbox` Supabase project. See `setup/credentials.md`.

## Questions

- Bounty scope, strategy: Lodewijk
- API access, infra, deployments: Thanh
- Stuck on build: check `setup/getting-unstuck.md` first, then Thanh
