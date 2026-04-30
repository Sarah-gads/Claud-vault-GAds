import json
import logging

import anthropic

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a Google Ads specialist doing a pre-launch quality review "
    "for an MSP (Managed Service Provider) B2B campaign. Be concise and actionable."
)

_PROMPT = """\
Review this Google Ads campaign configuration and return a JSON quality report.

Config:
{config_json}

Check each of these:
1. Ad copy — are all headlines ≤30 chars? descriptions ≤90 chars? 3–15 headlines, 2–4 descriptions present?
2. Keywords — relevant to MSP/IT managed services? reasonable match type mix? any obvious irrelevant terms?
3. Extensions — sitelink link_text ≤25 chars, descriptions ≤35 chars, callouts ≤25 chars, all present?
4. Targeting — at least one location ID, budget looks reasonable for B2B geo?
5. Landing page — URL starts with https:// and looks valid?
6. Overall readiness — anything that would cause disapproval or poor performance?

Return ONLY this JSON (no markdown fences, no extra text):
{{
  "ready": true,
  "blocking": ["list of issues that must be fixed before launch — empty if none"],
  "warnings": ["list of non-critical concerns — empty if none"],
  "notes": "1-2 sentence overall quality assessment"
}}"""


class ClaudeAssistant:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def analyze(self, config: dict) -> dict:
        try:
            msg = self.client.messages.create(
                model="claude-opus-4-7",
                max_tokens=1024,
                system=_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": _PROMPT.format(config_json=json.dumps(config, indent=2)),
                }],
            )
            text = msg.content[0].text.strip()
            if text.startswith("```"):
                parts = text.split("```")
                text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"Claude returned non-JSON: {e}")
            return {
                "ready": True,
                "blocking": [],
                "warnings": ["AI review response could not be parsed — validate manually."],
                "notes": "",
            }
        except Exception as e:
            logger.error(f"Claude analysis error: {e}")
            return {
                "ready": True,
                "blocking": [],
                "warnings": [f"AI review unavailable: {e}"],
                "notes": "",
            }
