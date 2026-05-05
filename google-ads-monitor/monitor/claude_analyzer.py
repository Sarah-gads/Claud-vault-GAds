import json
import logging

import anthropic

logger = logging.getLogger(__name__)

# Cached system prompt — stable across all issue analyses in a daily run
_SYSTEM_PROMPT = """You are an expert Google Ads account manager at an MSP digital marketing agency.
Analyze Google Ads issues and produce clear, actionable output for the ads team.

Severity classification rules:
- Urgent: Active ad disapprovals blocking spend, billing failure stopping campaigns, account suspension risk
- High: Performance drop >70% WoW, conversion tracking broken, policy violations at escalation risk, budget overspend >110% of expected pace
- Medium: Performance drop 50–70%, zero impressions on active campaigns, non-critical policy warnings, budget underspend <70% of expected pace
- Low: Minor fluctuations, informational policy notices, campaigns with historically low volume

Respond ONLY with valid JSON matching this exact schema — no markdown, no extra keys:
{
  "severity": "Urgent" | "High" | "Medium" | "Low",
  "title": "<task title, max 80 chars>",
  "description": "<ClickUp task body, max 400 words>",
  "recommended_actions": ["<action 1>", "<action 2>", "<action 3>"],
  "business_impact": "<one sentence on business impact>"
}"""

_SEVERITY_FALLBACK = {
    "ad_disapproval": "High",
    "billing_issue": "Urgent",
    "account_verification_issue": "Urgent",
    "zero_impressions": "Medium",
    "performance_drop": "High",
    "conversion_tracking_issue": "High",
    "budget_overspend": "High",
    "budget_underspend": "Medium",
}


class ClaudeAnalyzer:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def analyze_issue(self, issue: dict) -> dict:
        try:
            response = self.client.messages.create(
                model="claude-opus-4-7",
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": _SYSTEM_PROMPT,
                        # Cache the system prompt — it's identical for every issue in the run
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Analyze this Google Ads issue and return the JSON response:\n\n"
                            + json.dumps(issue, indent=2)
                        ),
                    }
                ],
            )

            raw = response.content[0].text.strip()
            # Strip markdown code fences if the model wraps output
            if raw.startswith("```"):
                parts = raw.split("```")
                raw = parts[1].lstrip("json").strip() if len(parts) >= 2 else raw

            result = json.loads(raw)

            logger.debug(
                f"Cache usage — creation: {response.usage.cache_creation_input_tokens}, "
                f"read: {response.usage.cache_read_input_tokens}"
            )
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            return self._fallback(issue)
        except anthropic.RateLimitError:
            logger.warning("Claude API rate limited — using fallback analysis")
            return self._fallback(issue)
        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            return self._fallback(issue)

    def _fallback(self, issue: dict) -> dict:
        issue_type = issue.get("type", "")
        account = issue.get("account_name", "Unknown Account")
        label = issue_type.replace("_", " ").title()
        return {
            "severity": _SEVERITY_FALLBACK.get(issue_type, "Medium"),
            "title": f"[{label}] {account}"[:80],
            "description": issue.get("details", "Issue detected. Manual review required."),
            "recommended_actions": [
                "Review issue in Google Ads dashboard",
                "Check account and campaign settings",
                "Escalate to senior ads manager if unresolved within 24h",
            ],
            "business_impact": "Unable to assess automatically — manual review required.",
        }
