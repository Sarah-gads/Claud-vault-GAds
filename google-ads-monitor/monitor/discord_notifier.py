import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

_ISSUE_LABELS = {
    "ad_disapproval": "Ad Disapproval",
    "billing_issue": "Billing Issue",
    "account_verification_issue": "Account Verification",
    "zero_impressions": "Zero Impressions",
    "performance_drop": "Performance Drop",
    "conversion_tracking_issue": "Conversion Tracking Issue",
    "budget_overspend": "Budget Overspend ⚠️",
    "budget_underspend": "Budget Underspend ⚠️",
}

_COLOR_GREEN = 0x57F287
_COLOR_RED = 0xED4245


class DiscordNotifier:
    def __init__(self, webhook_url: str, mention_user_id: str):
        self.webhook_url = webhook_url
        self.mention = f"<@{mention_user_id}>"

    def notify(self, created_tasks: list[dict], total_issues: int, accounts_checked: int) -> None:
        if created_tasks:
            self._post_issues(created_tasks, accounts_checked)
            self._post_complete(accounts_checked, len(created_tasks))
        else:
            self._post_healthy(accounts_checked)

    def _post_healthy(self, accounts_checked: int) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
        self._send({
            "content": f"Hey {self.mention}, daily account audit completed successfully.",
            "embeds": [{
                "title": "✅ Google Ads Account Monitor — All Clear",
                "description": (
                    "**Status Summary:**\n"
                    f"• All {accounts_checked} monitored Google Ads accounts are healthy\n"
                    "• No billing, policy, or disapproval issues detected\n"
                    "• No urgent action required\n"
                    "• Campaigns are operating normally\n\n"
                    "Great news — everything is running smoothly today.\n\n"
                    f"🕒 Automated audit completed: {timestamp}"
                ),
                "color": _COLOR_GREEN,
            }]
        })

    def _post_complete(self, accounts_checked: int, issues_found: int) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")
        self._send({
            "embeds": [{
                "description": (
                    f"Daily audit complete — {accounts_checked} account(s) checked, "
                    f"{issues_found} issue(s) found and actioned above.\n\n"
                    f"🕒 {timestamp}"
                ),
                "color": 0x5865F2,
            }]
        })

    def _post_issues(self, created_tasks: list[dict], accounts_checked: int) -> None:
        sections = []
        for entry in created_tasks:
            issue = entry["issue"]
            task = entry["task"]
            analysis = entry.get("analysis", {})

            label = _ISSUE_LABELS.get(
                issue.get("type", ""),
                issue.get("type", "Unknown").replace("_", " ").title(),
            )
            account = issue.get("account_name", "Unknown Account")
            priority = analysis.get("severity", "Medium")
            url = task.get("url", "")
            task_link = f"[View Task]({url})" if url else "N/A"

            summary_lines = []
            desc = analysis.get("description") or issue.get("details", "")
            if desc:
                summary_lines.append(f"• {desc}")
            actions = analysis.get("recommended_actions", [])
            if actions:
                summary_lines.append(f"• {actions[0]}")
            if not summary_lines:
                summary_lines.append("• See ClickUp task for details.")

            sections.append(
                f"**Affected Account:** {account}\n"
                f"**Issue Type:** {label}\n"
                f"**Priority:** {priority}\n"
                f"**ClickUp Task Created:** {task_link}\n\n"
                f"**Summary:**\n" + "\n".join(summary_lines) + "\n\n"
                f"Please review and take action."
            )

        description = "\n\n─────────────────────\n\n".join(sections)

        self._send({
            "content": (
                f"🚨 **Google Ads Account Alert Detected** 🚨\n"
                f"Hey {self.mention}, issues were found during today's automated account audit."
            ),
            "embeds": [{
                "description": description,
                "color": _COLOR_RED,
                "footer": {
                    "text": f"{accounts_checked} account(s) monitored • {len(created_tasks)} issue(s) found"
                },
            }],
        })

    def _send(self, payload: dict) -> None:
        payload.setdefault("username", "Google Ads Daily Monitoring")
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("Discord notification sent.")
        except requests.RequestException as e:
            logger.error(f"Discord notification failed: {e}")
