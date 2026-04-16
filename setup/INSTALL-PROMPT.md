# Launchpad Labs — Install Prompt

> **Canonical copy lives in Supabase.** This file is a pointer.

The install prompt is no longer stored here. It lives as a row in the Team Operations Supabase project so that LaunchFlow can fetch and display it live, and edits propagate without needing a deploy.

## Where to find it

- **For team members (copy-paste flow):** open LaunchFlow → portrait icon → **Claude Code Install** → "Copy full prompt". Paste into a fresh Claude Code terminal.
- **For editors:** update the `body` column of `public.ob_install_prompt` (id = 1) in the Team Operations Supabase project (`ftzelkdvqsnaxajqyqui`). Version + history are tracked automatically via the `ob_install_prompt_history` audit table.

## Why one file, one row

Prior state drifted into multiple drafts — `starter-kit-research/04-claude-md-architecture.md`, `starter-kit-research/07-starter-kit-files.md`, a hardcoded 30-line string in LaunchFlow's `UserMenu.tsx`, and this file. Every edit had to be mirrored in 3-4 places and usually wasn't.

Keeping one row in Supabase, fetched live by LaunchFlow, means:

- One edit point (SQL editor or any Supabase client).
- Version history via the audit table.
- Live updates with no redeploy.
- No drift.

## Related

- Table migration: `create_ob_install_prompt` (Team Ops, 2026-04-16).
- LaunchFlow fetch logic: `src/components/launchflow/UserMenu.tsx` (commit `d14afff`).
- Session notes: `memory/claude-code-install-prompt-session.md` in the Claude Code workspace.
