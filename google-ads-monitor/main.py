import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from monitor.ads_checker import AdsChecker
from monitor.claude_analyzer import ClaudeAnalyzer
from monitor.clickup_client import ClickUpClient
from monitor.dedup import DedupChecker
from monitor.discord_notifier import DiscordNotifier

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_REQUIRED_ENV = [
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    "ANTHROPIC_API_KEY",
    "CLICKUP_API_TOKEN",
    "CLICKUP_LIST_ID",
    "CLICKUP_ASSIGNEE_ID",
]


def _load_env() -> dict:
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)
    return {k: os.environ[k] for k in _REQUIRED_ENV}


def main():
    env = _load_env()

    google_credentials = {
        "developer_token": env["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": env["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": env["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": env["GOOGLE_ADS_REFRESH_TOKEN"],
        "login_customer_id": env["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
        "use_proto_plus": True,
    }

    checker = AdsChecker(google_credentials)
    analyzer = ClaudeAnalyzer(env["ANTHROPIC_API_KEY"])
    clickup = ClickUpClient(
        api_token=env["CLICKUP_API_TOKEN"],
        list_id=env["CLICKUP_LIST_ID"],
        assignee_id=env["CLICKUP_ASSIGNEE_ID"],
    )
    dedup = DedupChecker()

    raw_allowlist = os.environ.get("MONITOR_ACCOUNT_IDS", "")
    account_allowlist = [a.strip().replace("-", "") for a in raw_allowlist.split(",") if a.strip()] or None

    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    discord_user_id = os.environ.get("DISCORD_USER_ID", "")
    accounts_checked = len(account_allowlist) if account_allowlist else 0

    budgets = None
    budgets_file = Path("budgets.json")
    if budgets_file.exists():
        with open(budgets_file) as f:
            budgets = json.load(f)
        logger.info("Loaded budget config for budget pacing checks.")

    logger.info("Starting Google Ads account check...")
    issues = checker.check_all_accounts(account_allowlist=account_allowlist, budgets=budgets)

    if not issues:
        logger.info("No Google Ads issues detected.")
        if discord_webhook:
            DiscordNotifier(discord_webhook, discord_user_id).notify([], 0, accounts_checked)
        return

    logger.info(f"Found {len(issues)} issue(s). Analyzing and creating tasks...")

    created = 0
    skipped = 0
    created_tasks = []

    for issue in issues:
        if dedup.is_duplicate(issue):
            logger.info(
                f"Skipping duplicate issue: {issue['type']} on account {issue['account_id']}"
            )
            skipped += 1
            continue

        analysis = analyzer.analyze_issue(issue)
        task = clickup.create_task(analysis, issue)

        if task:
            dedup.mark_seen(issue)
            created += 1
            created_tasks.append({"issue": issue, "task": task, "analysis": analysis})
        else:
            logger.warning(
                f"Failed to create ClickUp task for issue: {issue['type']} "
                f"on account {issue['account_id']}"
            )

    logger.info(
        f"Run complete — {created} task(s) created, {skipped} duplicate(s) skipped."
    )

    if discord_webhook:
        DiscordNotifier(discord_webhook, discord_user_id).notify(
            created_tasks, total_issues=len(issues), accounts_checked=accounts_checked
        )


if __name__ == "__main__":
    main()
