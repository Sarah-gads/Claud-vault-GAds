#!/usr/bin/env python3
"""
Live Work Tracker — updates ob_live_work table in Supabase.

Usage:
  python work-tracker.py start "Project Name" "Description" [--label "Label"] [--member "Name"] [--session-id UUID]
  python work-tracker.py heartbeat
  python work-tracker.py update "New description"
  python work-tracker.py pause
  python work-tracker.py resume
  python work-tracker.py complete "Completion note"
  python work-tracker.py list
  python work-tracker.py cleanup
  python work-tracker.py whoami   (diagnostic: prints resolved session_id, member, env source)

Environment variables (participant-friendly; override .env values):
  LAUNCHFLOW_SUPABASE_URL            Team Ops Supabase URL (fallback: SUPABASE_TEAM_OPS_URL)
  LAUNCHFLOW_SUPABASE_SERVICE_KEY    Service role key     (fallback: SUPABASE_TEAM_OPS_SERVICE_KEY)
  LAUNCHFLOW_MEMBER_NAME             Your name as shown on the Live Work tab
  LAUNCHFLOW_SESSION_ID              Optional stable session UUID for this terminal
  LAUNCHFLOW_ENV_FILE                Optional absolute path to a .env file
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── .env discovery ──────────────────────────────────────────────────────────

DEFAULT_ENV_FILENAMES = (".env", ".env.local")

# Script-relative fallback (e.g., msp-launchpad/.env when running from the repo).
# NOT hardcoded to an absolute path — resolved from this script's location.
SCRIPT_DIR = Path(__file__).resolve().parent

# Candidate search paths, in priority order. First hit wins.
# Participants can override everything by setting env vars directly.
def env_candidates():
    yield from (Path(os.environ[k]) for k in ("LAUNCHFLOW_ENV_FILE",) if os.environ.get(k))
    cwd = Path.cwd()
    # Walk up from cwd looking for .env
    for parent in (cwd, *cwd.parents):
        for name in DEFAULT_ENV_FILENAMES:
            yield parent / name
    # Walk up from script dir
    for parent in (SCRIPT_DIR, *SCRIPT_DIR.parents):
        for name in DEFAULT_ENV_FILENAMES:
            yield parent / name
    # User-level fallbacks (participant-friendly)
    home = Path.home()
    for base in (home / ".launchflow", home / "launchpad-labs", home / ".launchpad-labs"):
        for name in DEFAULT_ENV_FILENAMES:
            yield base / name


def load_env():
    """Return (env_dict, source_path_or_None). Never raises — empty dict if nothing found."""
    seen = set()
    for path in env_candidates():
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if not resolved.exists() or not resolved.is_file():
            continue
        env = {}
        try:
            for line in resolved.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip().strip('"').strip("'")
        except Exception:
            continue
        return env, resolved
    return {}, None


def get_config():
    """Resolve Supabase URL + service key + member from env + .env. Returns dict."""
    env_file, env_path = load_env()

    def pick(*keys):
        for k in keys:
            if os.environ.get(k):
                return os.environ[k].strip()
            if env_file.get(k):
                return env_file[k].strip()
        return None

    return {
        "url": pick("LAUNCHFLOW_SUPABASE_URL", "SUPABASE_TEAM_OPS_URL"),
        "service_key": pick("LAUNCHFLOW_SUPABASE_SERVICE_KEY", "SUPABASE_TEAM_OPS_SERVICE_KEY"),
        "member": pick("LAUNCHFLOW_MEMBER_NAME"),
        "session_id_override": pick("LAUNCHFLOW_SESSION_ID"),
        "env_path": str(env_path) if env_path else None,
    }


# ── Session ID resolution ───────────────────────────────────────────────────
#
# Why cwd-keyed?
#
# We want each terminal to have its own stable session_id across many tracker
# calls, so rows don't collide. We can't walk up the process tree reliably —
# Claude Code spawns bash subshells detached from their parent (PPID=1 inside
# the shell). The cleanest signal available is the current working directory.
#
# The guidance in msp-launchpad/projects/CLAUDE.md already says each GSD project
# runs in its own subdirectory. That means cwd naturally differs per terminal
# in the intended workflow — perfect for keying session IDs.
#
# When two Claude Code instances DO share a cwd (rare, but Lodewijk hit this
# with 6 interactive sessions all at C:\Users\mlave\Claude Code\), the script
# prints a visible warning telling the user to set LAUNCHFLOW_SESSION_ID per
# terminal. Behavior is still deterministic — all sharers see the same row —
# but the warning makes the collision debuggable instead of silent.

CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
LAUNCHFLOW_STATE_DIR = Path.home() / ".launchflow" / "sessions"


def _count_claude_sessions_sharing_cwd() -> int:
    """How many interactive Claude Code sessions share our cwd?

    Used only to surface a warning — not to pick a session.
    """
    if not CLAUDE_SESSIONS_DIR.exists():
        return 0
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        return 0
    count = 0
    for f in CLAUDE_SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("kind") != "interactive":
            continue
        sess_cwd = data.get("cwd")
        if not sess_cwd:
            continue
        try:
            if Path(sess_cwd).resolve() == cwd:
                count += 1
        except Exception:
            pass
    return count


def _cwd_keyed_session_id() -> str:
    """Return (or create) the stable session_id for this working directory."""
    LAUNCHFLOW_STATE_DIR.mkdir(parents=True, exist_ok=True)
    import hashlib
    key = hashlib.sha1(str(Path.cwd().resolve()).encode("utf-8")).hexdigest()[:16]
    f = LAUNCHFLOW_STATE_DIR / f"cwd-{key}.txt"
    if f.exists():
        content = f.read_text(encoding="utf-8").strip()
        if content:
            return content
    new_id = str(uuid.uuid4())
    f.write_text(new_id, encoding="utf-8")
    # GC files older than 30 days
    cutoff = time.time() - 30 * 86400
    for old in LAUNCHFLOW_STATE_DIR.glob("cwd-*.txt"):
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except Exception:
            pass
    return new_id


def resolve_session_id(cli_override: str | None, cfg_override: str | None) -> tuple[str, str]:
    """Return (session_id, source_label). See top-of-section comment for rationale."""
    if cli_override:
        return cli_override, "cli --session-id"
    if cfg_override:
        return cfg_override, "LAUNCHFLOW_SESSION_ID env/.env"

    sharers = _count_claude_sessions_sharing_cwd()
    if sharers > 1:
        print(
            f"WARNING: {sharers} Claude Code interactive sessions share this cwd "
            f"({Path.cwd()}). Without LAUNCHFLOW_SESSION_ID set per terminal, they "
            f"will all share the same LaunchFlow row and overwrite each other. "
            f"Set LAUNCHFLOW_SESSION_ID=<uuid> in the terminal's shell, or run each "
            f"Claude Code from a project-specific subdirectory (e.g. the GSD project "
            f"folder under msp-launchpad/projects/).",
            file=sys.stderr,
        )

    return _cwd_keyed_session_id(), (
        f"cwd-keyed (~/.launchflow/sessions/cwd-*.txt)"
        + (f" — WARNING: {sharers} Claude sessions share this cwd" if sharers > 1 else "")
    )


# ── Supabase REST client ────────────────────────────────────────────────────

class SupabaseClient:
    def __init__(self, url: str, service_key: str):
        self.base_url = f"{url.rstrip('/')}/rest/v1/ob_live_work"
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _request(self, method: str, params: str = "", body: dict | None = None):
        url = self.base_url + (f"?{params}" if params else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self.headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            print(f"ERROR {e.code}: {error_body}", file=sys.stderr)
            sys.exit(1)
        except urllib.error.URLError as e:
            print(f"ERROR (network): {e.reason}", file=sys.stderr)
            sys.exit(1)

    def select(self, params: str) -> list:
        r = self._request("GET", params)
        return r if isinstance(r, list) else []

    def insert(self, body: dict) -> list:
        r = self._request("POST", "", body)
        return r if isinstance(r, list) else ([r] if r else [])

    def update(self, params: str, body: dict) -> list:
        r = self._request("PATCH", params, body)
        return r if isinstance(r, list) else ([r] if r else [])


# ── Commands ────────────────────────────────────────────────────────────────

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_flags(args: list) -> tuple[list, dict]:
    """Extract --label/--member/--session-id flags. Returns (positional, flags)."""
    positional = []
    flags = {}
    i = 0
    while i < len(args):
        tok = args[i]
        if tok in ("--label", "--member", "--session-id") and i + 1 < len(args):
            flags[tok.lstrip("-")] = args[i + 1]
            i += 2
        else:
            positional.append(tok)
            i += 1
    return positional, flags


def cmd_start(client: SupabaseClient, session_id: str, args: list, member_default: str | None):
    """start "Project Name" "Description" [--label X] [--member Y]

    Dedupe by session_id (NOT project_name). Each terminal gets its own row.
    """
    positional, flags = _parse_flags(args)
    if len(positional) < 2:
        print('Usage: work-tracker.py start "Project" "Description" [--label X] [--member Y]', file=sys.stderr)
        sys.exit(1)

    project_name = positional[0]
    description = positional[1]
    label = flags.get("label")
    member = flags.get("member") or member_default

    ts = now_iso()

    # Check if THIS session already has a row (any status) — resume/retitle
    encoded_sid = urllib.parse.quote(session_id)
    existing = client.select(
        f"session_id=eq.{encoded_sid}&status=in.(active,paused,blocked)&order=last_heartbeat.desc&limit=1"
    )

    if existing:
        item = existing[0]
        body = {
            "project_name": project_name,
            "description": description,
            "status": "active",
            "last_heartbeat": ts,
        }
        if label is not None:
            body["terminal_label"] = label
        if member is not None:
            body["member_name"] = member
        client.update(f"id=eq.{item['id']}", body)
        print(f"Resumed session (same terminal): {project_name}")
        print(f"  Description: {description}")
        if label: print(f"  Label: {label}")
        if member: print(f"  Member: {member}")
        print(f"  Session: {session_id}")
        print(f"  ID: {item['id']}")
        return

    # Fresh row for this session_id
    row = {
        "project_name": project_name,
        "description": description,
        "status": "active",
        "terminal_label": label,
        "session_id": session_id,
        "started_at": ts,
        "last_heartbeat": ts,
        "completed_at": None,
        "progress_notes": None,
        "metadata": {"member_name": member} if member else {},
    }
    if member:
        row["member_name"] = member

    result = client.insert(row)
    if not result:
        print("ERROR: insert returned empty", file=sys.stderr)
        sys.exit(1)
    item = result[0]
    print(f"Started: {project_name}")
    print(f"  Description: {description}")
    if label: print(f"  Label: {label}")
    if member: print(f"  Member: {member}")
    print(f"  Session: {session_id}")
    print(f"  ID: {item.get('id', 'unknown')}")


def _this_session_rows(client: SupabaseClient, session_id: str, statuses: tuple[str, ...]) -> list:
    encoded_sid = urllib.parse.quote(session_id)
    status_filter = ",".join(statuses)
    return client.select(f"session_id=eq.{encoded_sid}&status=in.({status_filter})&select=id,project_name,status")


def cmd_heartbeat(client: SupabaseClient, session_id: str):
    active = _this_session_rows(client, session_id, ("active",))
    if not active:
        return  # silent no-op for cron-style calls
    encoded_sid = urllib.parse.quote(session_id)
    client.update(f"session_id=eq.{encoded_sid}&status=eq.active", {"last_heartbeat": now_iso()})
    names = [i["project_name"] for i in active]
    print(f"Heartbeat updated for {len(active)} item(s): {', '.join(names)}")


def cmd_update(client: SupabaseClient, session_id: str, args: list):
    if not args:
        print('Usage: work-tracker.py update "New description"', file=sys.stderr)
        sys.exit(1)
    description = args[0]
    active = _this_session_rows(client, session_id, ("active",))
    if not active:
        print("No active work items for this session.", file=sys.stderr)
        sys.exit(1)
    encoded_sid = urllib.parse.quote(session_id)
    client.update(
        f"session_id=eq.{encoded_sid}&status=eq.active",
        {"description": description, "last_heartbeat": now_iso()},
    )
    print(f"Updated description: {description}")


def cmd_pause(client: SupabaseClient, session_id: str):
    active = _this_session_rows(client, session_id, ("active",))
    if not active:
        print("No active work items for this session.", file=sys.stderr)
        sys.exit(1)
    encoded_sid = urllib.parse.quote(session_id)
    client.update(
        f"session_id=eq.{encoded_sid}&status=eq.active",
        {"status": "paused", "last_heartbeat": now_iso()},
    )
    print(f"Paused: {', '.join(i['project_name'] for i in active)}")


def cmd_resume(client: SupabaseClient, session_id: str):
    paused = _this_session_rows(client, session_id, ("paused",))
    if not paused:
        print("No paused work items for this session.", file=sys.stderr)
        sys.exit(1)
    encoded_sid = urllib.parse.quote(session_id)
    client.update(
        f"session_id=eq.{encoded_sid}&status=eq.paused",
        {"status": "active", "last_heartbeat": now_iso()},
    )
    print(f"Resumed: {', '.join(i['project_name'] for i in paused)}")


def cmd_complete(client: SupabaseClient, session_id: str, args: list):
    note = args[0] if args else None
    rows = _this_session_rows(client, session_id, ("active", "paused", "blocked"))
    if not rows:
        print("No work items for this session.", file=sys.stderr)
        sys.exit(1)
    ts = now_iso()
    body = {"status": "completed", "completed_at": ts, "last_heartbeat": ts}
    if note:
        body["progress_notes"] = note
    encoded_sid = urllib.parse.quote(session_id)
    client.update(f"session_id=eq.{encoded_sid}&status=in.(active,paused,blocked)", body)
    print(f"Completed: {', '.join(i['project_name'] for i in rows)}")
    if note:
        print(f"  Note: {note}")


def cmd_list(client: SupabaseClient):
    items = client.select("status=in.(active,paused,blocked)&order=last_heartbeat.desc")
    completed = client.select("status=eq.completed&order=completed_at.desc&limit=10")
    rows = items + completed
    if not rows:
        print("No work items found.")
        return
    symbols = {"active": "[*]", "paused": "[-]", "completed": "[v]", "blocked": "[!]"}
    print(f"\n{'Status':<12} {'Member':<12} {'Project':<26} {'Description':<36} {'Session':<13}")
    print("-" * 105)
    for item in rows:
        status = item.get("status", "?")
        sym = symbols.get(status, "[?]")
        member = (item.get("member_name") or "")[:10]
        project = (item.get("project_name") or "")[:24]
        desc = (item.get("description") or "")[:34]
        sess = (item.get("session_id") or "")[:12]
        print(f"{sym} {status:<8} {member:<12} {project:<26} {desc:<36} {sess:<13}")
    print()


def cmd_cleanup(client: SupabaseClient):
    """Dedupe old rows: if >1 active/paused per (member, project), keep newest, complete rest."""
    items = client.select("status=in.(active,paused,blocked)&order=last_heartbeat.desc")
    if not items:
        print("No active/paused items to clean up.")
        return
    groups: dict[tuple, list] = {}
    for it in items:
        key = (it.get("member_name") or "", it.get("project_name") or "")
        groups.setdefault(key, []).append(it)
    ts = now_iso()
    dupes = 0
    for key, entries in groups.items():
        if len(entries) <= 1:
            continue
        # Keep newest, complete rest
        keep, *rest = entries
        for d in rest:
            client.update(
                f"id=eq.{d['id']}",
                {"status": "completed", "completed_at": ts, "progress_notes": "Auto-cleaned: duplicate entry"},
            )
            dupes += 1
        print(f"  {key[0] or '?'}/{key[1]}: kept {keep['session_id'][:8]}, completed {len(rest)} dupe(s)")
    if dupes == 0:
        print("No duplicates found.")
    else:
        print(f"\nCleaned up {dupes} duplicate(s).")


def cmd_whoami(cfg: dict, session_id: str, session_source: str, member_default: str | None):
    print("work-tracker.py — resolved config")
    print(f"  env file        : {cfg.get('env_path') or '(none found)'}")
    print(f"  supabase url    : {cfg.get('url') or '(MISSING)'}")
    print(f"  service key     : {'set' if cfg.get('service_key') else '(MISSING)'}")
    print(f"  member default  : {member_default or '(not set — pass --member or set LAUNCHFLOW_MEMBER_NAME)'}")
    print(f"  session id      : {session_id}")
    print(f"  session source  : {session_source}")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()
    args = sys.argv[2:]

    # Pull --session-id out before anything else
    positional, flags = _parse_flags(args)

    cfg = get_config()

    # Session resolution
    session_id, session_source = resolve_session_id(
        cli_override=flags.get("session-id"),
        cfg_override=cfg.get("session_id_override"),
    )

    if command == "whoami":
        cmd_whoami(cfg, session_id, session_source, cfg.get("member"))
        return

    if not cfg.get("url") or not cfg.get("service_key"):
        print(
            "ERROR: could not resolve Supabase URL + service key.\n"
            "Set LAUNCHFLOW_SUPABASE_URL + LAUNCHFLOW_SUPABASE_SERVICE_KEY (or legacy "
            "SUPABASE_TEAM_OPS_URL + SUPABASE_TEAM_OPS_SERVICE_KEY) in one of:\n"
            f"  • .env in cwd or any parent\n"
            f"  • .env next to the script ({SCRIPT_DIR})\n"
            "  • ~/.launchflow/.env or ~/launchpad-labs/.env\n"
            "  • process environment\n"
            "Run: python work-tracker.py whoami   for a diagnostic.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = SupabaseClient(cfg["url"], cfg["service_key"])
    member_default = cfg.get("member")

    # Re-assemble args without --session-id for sub-commands (they use _parse_flags internally)
    # For start we pass the original args (includes --member/--label). For others, positional only.
    if command == "start":
        cmd_start(client, session_id, args, member_default)
    elif command == "heartbeat":
        cmd_heartbeat(client, session_id)
    elif command == "update":
        cmd_update(client, session_id, positional)
    elif command == "pause":
        cmd_pause(client, session_id)
    elif command == "resume":
        cmd_resume(client, session_id)
    elif command == "complete":
        cmd_complete(client, session_id, positional)
    elif command == "list":
        cmd_list(client)
    elif command == "cleanup":
        cmd_cleanup(client)
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
