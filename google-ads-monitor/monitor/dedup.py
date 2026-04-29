import hashlib
import json
import logging
import os
from datetime import date

logger = logging.getLogger(__name__)

_STATE_FILE = os.environ.get("DEDUP_STATE_FILE", "dedup_state.json")


class DedupChecker:
    """
    Tracks issue fingerprints seen today so the same problem doesn't create
    multiple ClickUp tasks when the workflow runs again within the same day.
    State is persisted to a JSON file — in GitHub Actions this file is cached
    between runs using actions/cache with a rolling key pattern.
    """

    def __init__(self, state_file: str = _STATE_FILE):
        self.state_file = state_file
        self.today = date.today().isoformat()
        self.state = self._load()

    def _load(self) -> dict:
        if not os.path.exists(self.state_file):
            return {}
        try:
            with open(self.state_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not load dedup state ({e}) — starting fresh.")
            return {}

    def _save(self):
        # Prune stale entries (keep today only) to prevent unbounded file growth
        pruned = {k: v for k, v in self.state.items() if v == self.today}
        try:
            with open(self.state_file, "w") as f:
                json.dump(pruned, f, indent=2)
        except OSError as e:
            logger.error(f"Could not save dedup state: {e}")

    def fingerprint(self, issue: dict) -> str:
        key = ":".join([
            issue.get("account_id", ""),
            issue.get("type", ""),
            issue.get("campaign_id", ""),
            issue.get("ad_id", ""),
        ])
        return hashlib.sha256(key.encode()).hexdigest()[:20]

    def is_duplicate(self, issue: dict) -> bool:
        fp = self.fingerprint(issue)
        return self.state.get(fp) == self.today

    def mark_seen(self, issue: dict):
        fp = self.fingerprint(issue)
        self.state[fp] = self.today
        self._save()
