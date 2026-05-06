import logging

import requests

logger = logging.getLogger(__name__)

_COLOR_SUCCESS = 0x57F287   # green
_COLOR_WARNING = 0xFEE75C   # yellow
_COLOR_ERROR   = 0xED4245   # red
_COLOR_INFO    = 0x5865F2   # blurple


_SENDER_NAME = "Google Ads Daily Monitoring"


class DiscordNotifier:
    def __init__(self, webhook_url: str, user_id: str = ""):
        self.webhook_url = webhook_url
        self.user_id = user_id

    def campaign_created(self, result: dict, config: dict) -> None:
        budget_daily = config["campaign"]["budget_micros"] / 1_000_000
        geo_names = config["geo_targeting"].get(
            "location_names", config["geo_targeting"]["location_ids"]
        )
        ext = result.get("extensions", {})
        mention = self._role_mention(config)

        payload = {
            "content": f"{mention}New MSP campaign ready for review.",
            "embeds": [
                {
                    "title": f"Campaign Created (PAUSED): {result['campaign_name']}",
                    "color": _COLOR_SUCCESS,
                    "fields": [
                        {"name": "Client", "value": result["client_name"], "inline": True},
                        {"name": "Customer ID", "value": result["customer_id"], "inline": True},
                        {"name": "Daily Budget", "value": f"${budget_daily:.2f}", "inline": True},
                        {
                            "name": "Geo Targets",
                            "value": ", ".join(str(g) for g in geo_names),
                            "inline": False,
                        },
                        {"name": "Landing Page", "value": result["landing_page"], "inline": False},
                        {
                            "name": "Assets",
                            "value": (
                                f"Keywords: {result.get('keywords_uploaded', 0)} | "
                                f"Sitelinks: {ext.get('sitelinks', 0)} | "
                                f"Callouts: {ext.get('callouts', 0)} | "
                                f"Call ext: {'Yes' if ext.get('call') else 'No'}"
                            ),
                            "inline": False,
                        },
                        {
                            "name": "Next Step",
                            "value": "Review in Google Ads UI → enable when ready.",
                            "inline": False,
                        },
                    ],
                    "footer": {"text": "Google Ads Campaign Loader"},
                }
            ],
        }
        self._send(payload)

    def campaign_error(self, result: dict, error: str) -> None:
        payload = {
            "embeds": [
                {
                    "title": f"Campaign Load FAILED: {result.get('campaign_name', 'Unknown')}",
                    "description": f"```{error[:1800]}```",
                    "color": _COLOR_ERROR,
                    "fields": [
                        {
                            "name": "Client",
                            "value": result.get("client_name", "N/A"),
                            "inline": True,
                        },
                        {
                            "name": "Customer ID",
                            "value": result.get("customer_id", "N/A"),
                            "inline": True,
                        },
                    ],
                    "footer": {"text": "Google Ads Campaign Loader"},
                }
            ]
        }
        self._send(payload)

    def daily_check_summary(
        self,
        issues: list[dict],
        landing_issues: list[dict],
        mention_role: str = "",
    ) -> None:
        total = len(issues) + len(landing_issues)
        color = _COLOR_ERROR if total > 0 else _COLOR_SUCCESS
        mention = f"<@{self.user_id}> " if self.user_id else (f"<@&{mention_role}> " if mention_role else "")

        if total == 0:
            summary = "All campaign checks passed. No issues detected."
        else:
            issue_lines = "\n".join(
                f"• [{i['type'].replace('_', ' ').title()}] {i['account_name']} — {i['campaign_name']}"
                for i in issues[:10]
            )
            landing_lines = "\n".join(
                f"• Landing page error [{i['status_code']}] — {i['url']}"
                for i in landing_issues[:5]
            )
            summary = "\n".join(filter(None, [issue_lines, landing_lines]))

        user_mention = f"<@{self.user_id}>" if self.user_id else "Team"
        content = (
            f"🚨 Google Ads Account Alert 🚨\n"
            f"Hey {user_mention}, today's automated account audit is complete. "
            f"Please review the findings and take action where needed."
        )

        payload = {
            "content": content,
            "embeds": [
                {
                    "title": f"Daily Check — {total} Issue(s) Found",
                    "description": summary[:2000] if summary else "All clear.",
                    "color": color,
                    "footer": {"text": "Google Ads Campaign Loader — Daily Check"},
                }
            ],
        }
        self._send(payload)

    def _role_mention(self, config: dict) -> str:
        role_id = (
            config.get("notifications", {})
            .get("discord", {})
            .get("mention_role", "")
        )
        return f"<@&{role_id}> " if role_id else ""

    def _send(self, payload: dict) -> None:
        payload.setdefault("username", _SENDER_NAME)
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Discord notification failed: {e}")
