import logging
from datetime import datetime, timedelta

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

logger = logging.getLogger(__name__)


class DailyChecker:
    """
    Targeted daily checks for active MSP campaigns.
    Complements the google-ads-monitor by focusing on conversion tracking
    and disapprovals specific to the campaigns we manage.
    """

    def __init__(self, client: GoogleAdsClient):
        self.client = client
        self._ga_service = client.get_service("GoogleAdsService")

    def run_all_checks(self, customer_ids: list[str]) -> list[dict]:
        issues = []
        for customer_id in customer_ids:
            logger.info(f"Running daily checks for account {customer_id}")
            try:
                issues.extend(self._check_disapprovals(customer_id))
                issues.extend(self._check_billing(customer_id))
                issues.extend(self._check_conversion_tracking(customer_id))
            except Exception as e:
                logger.error(f"Error checking account {customer_id}: {e}")
        return issues

    def _search(self, customer_id: str, query: str):
        return self._ga_service.search(customer_id=customer_id, query=query)

    def _check_disapprovals(self, customer_id: str) -> list[dict]:
        issues = []
        query = """
            SELECT
                customer.descriptive_name,
                campaign.id,
                campaign.name,
                ad_group.name,
                ad_group_ad.ad.id,
                ad_group_ad.policy_summary.approval_status,
                ad_group_ad.policy_summary.policy_topic_entries
            FROM ad_group_ad
            WHERE ad_group_ad.policy_summary.approval_status = 'DISAPPROVED'
              AND campaign.status = 'ENABLED'
              AND ad_group.status = 'ENABLED'
              AND ad_group_ad.status = 'ENABLED'
        """
        try:
            for row in self._search(customer_id, query):
                topics = [
                    e.topic
                    for e in row.ad_group_ad.policy_summary.policy_topic_entries
                ]
                issues.append({
                    "type": "ad_disapproval",
                    "account_id": customer_id,
                    "account_name": row.customer.descriptive_name,
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "ad_id": str(row.ad_group_ad.ad.id),
                    "policy_topics": topics,
                    "details": (
                        f"Ad {row.ad_group_ad.ad.id} disapproved in "
                        f"'{row.campaign.name}'. Topics: {', '.join(topics) or 'unspecified'}"
                    ),
                })
        except GoogleAdsException as e:
            logger.error(f"[{customer_id}] Disapproval check failed: {e}")
        return issues

    def _check_billing(self, customer_id: str) -> list[dict]:
        issues = []
        query = """
            SELECT
                customer.descriptive_name,
                billing_setup.status
            FROM billing_setup
            WHERE billing_setup.status != 'APPROVED'
        """
        try:
            for row in self._search(customer_id, query):
                issues.append({
                    "type": "billing_issue",
                    "account_id": customer_id,
                    "account_name": row.customer.descriptive_name,
                    "campaign_id": "",
                    "campaign_name": "",
                    "details": (
                        f"Billing issue on '{row.customer.descriptive_name}': "
                        f"status {row.billing_setup.status.name}"
                    ),
                })
        except GoogleAdsException as e:
            logger.error(f"[{customer_id}] Billing check failed: {e}")
        return issues

    def _check_conversion_tracking(self, customer_id: str) -> list[dict]:
        """Flag campaigns that had conversions last week but zero this week."""
        issues = []
        today = datetime.today()
        recent_end = today.strftime("%Y-%m-%d")
        recent_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        prev_end = (today - timedelta(days=8)).strftime("%Y-%m-%d")
        prev_start = (today - timedelta(days=14)).strftime("%Y-%m-%d")

        def _get_conversions(start: str, end: str) -> dict:
            result = {}
            q = f"""
                SELECT
                    customer.descriptive_name,
                    campaign.id,
                    campaign.name,
                    metrics.conversions
                FROM campaign
                WHERE campaign.status = 'ENABLED'
                  AND segments.date BETWEEN '{start}' AND '{end}'
            """
            try:
                for row in self._search(customer_id, q):
                    cid = str(row.campaign.id)
                    if cid not in result:
                        result[cid] = {
                            "name": row.campaign.name,
                            "account_name": row.customer.descriptive_name,
                            "conversions": 0,
                        }
                    result[cid]["conversions"] += row.metrics.conversions
            except GoogleAdsException as e:
                logger.error(f"[{customer_id}] Conversion query failed: {e}")
            return result

        recent = _get_conversions(recent_start, recent_end)
        prev = _get_conversions(prev_start, prev_end)

        for cid, r in recent.items():
            p = prev.get(cid)
            if not p or p["conversions"] <= 0:
                continue
            if r["conversions"] == 0:
                issues.append({
                    "type": "conversion_tracking_issue",
                    "account_id": customer_id,
                    "account_name": r["account_name"],
                    "campaign_id": cid,
                    "campaign_name": r["name"],
                    "details": (
                        f"'{r['name']}' had {p['conversions']:.0f} conversions last week "
                        f"but 0 this week — possible tracking breakage."
                    ),
                })
        return issues
