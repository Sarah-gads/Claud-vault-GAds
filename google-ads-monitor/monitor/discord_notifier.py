import logging

import requests

logger = logging.getLogger(__name__)

_ISSUE_LABELS = {
    "ad_disapproval": "Ad Disapproval",
    "billing_issue": "Billing Issue",
    "account_verification_issue": "Account Verification Issue",
    "zero_impressions": "Zero Impressions",
    "performance_drop": "Performance Drop",
    "conversion_tracking_issue": "Conversion Tracking Issue",
}

_COLOR_GREEN = 0x57F287
_COLOR_RED = 0xED4245


class DiscordNotifier:
    def __init__(self, webhook_url: str, mention_user_id: str):
        self.webhook_url = webhook_url
        self.mention = f"<@{mention_user_id}>"

    def notify(self, created_tasks: list[dict], total_issues: int, accounts_checked: int) -> None:
        if total_issues == 0:
            self._post_healthy(accounts_checked)
        elif created_tasks:
            self._post_issues(created_tasks, accounts_checked)

    def _post_healthy(self, accounts_checked: int) -> None:
        self._send({
            "embeds": [{
                "title": "✅ Google Ads Monitor — All Clear",
                "description": f"All {accounts_checked} monitored account(s) healthy. No issues detected today.",
                "color": _COLOR_GREEN,
            }]
        })

    def _post_issues(self, created_tasks: list[dict], accounts_checked: int) -> None:
        lines = []
        for entry in created_tasks:
            issue = entry["issue"]
            task = entry["task"]
            label = _ISSUE_LABELS.get(issue.get("type", ""), issue.get("type", "Unknown"))
            account = issue.get("account_name", "Unknown Account")
            url = task.get("url", "")
            line = f"🔴 **{account}** — {label}"
            if url:
                line += f"\n↳ [View ClickUp Task]({url})"
            lines.append(line)

        self._send({
            "content": self.mention,
            "embeds": [{
                "title": f"⚠️ Google Ads Monitor — {len(created_tasks)} Issue(s) Found",
                "description": "\n\n".join(lines),
                "color": _COLOR_RED,
                "footer": {"text": f"{accounts_checked} account(s) monitored"},
            }]
        })

    def _send(self, payload: dict) -> None:
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("Discord notification sent.")
        except requests.RequestException as e:
            logger.error(f"Discord notification failed: {e}")
