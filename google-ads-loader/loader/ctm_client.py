import logging

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.calltrackingmetrics.com/api/v1"


class CTMClient:
    """
    Optional Call Tracking Metrics integration.
    Provision a new tracking number for a client and return the number string.
    Set CTM_API_KEY, CTM_API_SECRET, and CTM_ACCOUNT_ID in the environment to enable.
    """

    def __init__(self, api_key: str, api_secret: str, account_id: str):
        self.account_id = account_id
        self.auth = (api_key, api_secret)

    def provision_number(
        self,
        name: str,
        tracking_label: str,
        area_code: str = "",
    ) -> str | None:
        """
        Provisions a new tracking number in CTM.
        Returns the formatted phone number string, e.g. '+12155550100'.
        """
        payload = {
            "name": name,
            "tracking_label": tracking_label,
        }
        if area_code:
            payload["area_code"] = area_code

        try:
            resp = requests.post(
                f"{_BASE_URL}/accounts/{self.account_id}/numbers/new",
                auth=self.auth,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            phone_number = data.get("number", {}).get("formatted_number", "")
            logger.info(f"CTM number provisioned: {phone_number} for '{name}'")
            return phone_number
        except requests.HTTPError as e:
            logger.error(
                f"CTM HTTP error {e.response.status_code}: {e.response.text}"
            )
        except requests.RequestException as e:
            logger.error(f"CTM request failed: {e}")
        return None

    def list_numbers(self) -> list[dict]:
        try:
            resp = requests.get(
                f"{_BASE_URL}/accounts/{self.account_id}/numbers",
                auth=self.auth,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("numbers", [])
        except requests.RequestException as e:
            logger.error(f"CTM list numbers failed: {e}")
            return []
