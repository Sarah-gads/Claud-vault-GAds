import logging
from datetime import datetime, timedelta

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

logger = logging.getLogger(__name__)


class AdsChecker:
    def __init__(self, credentials: dict):
        self.client = GoogleAdsClient.load_from_dict(credentials)

    def get_accessible_customers(self) -> list[str]:
        service = self.client.get_service("CustomerService")
        try:
            response = service.list_accessible_customers()
            return [r.split("/")[-1] for r in response.resource_names]
        except GoogleAdsException as e:
            logger.error(f"Failed to list accessible customers: {e}")
            return []

    def check_all_accounts(self, account_allowlist: list[str] | None = None) -> list[dict]:
        issues = []
        customer_ids = self.get_accessible_customers()
        if not customer_ids:
            logger.warning("No accessible customer accounts found.")
            return []

        if account_allowlist:
            original = len(customer_ids)
            customer_ids = [c for c in customer_ids if c in account_allowlist]
            logger.info(f"Allowlist applied — monitoring {len(customer_ids)}/{original} accounts.")

        for customer_id in customer_ids:
            if not self._has_active_campaigns(customer_id):
                logger.debug(f"Skipping account {customer_id} — no active campaigns or not accessible.")
                continue
            logger.info(f"Checking account {customer_id}")
            try:
                issues.extend(self._check_disapprovals(customer_id))
                issues.extend(self._check_billing(customer_id))
                issues.extend(self._check_account_status(customer_id))
                issues.extend(self._check_zero_impressions(customer_id))
                issues.extend(self._check_performance_drops(customer_id))
                issues.extend(self._check_conversion_tracking(customer_id))
            except Exception as e:
                logger.error(f"Unexpected error checking account {customer_id}: {e}")

        return issues

    def _has_active_campaigns(self, customer_id: str) -> bool:
        query = """
            SELECT campaign.id
            FROM campaign
            WHERE campaign.status = 'ENABLED'
            LIMIT 1
        """
        try:
            return any(True for _ in self._search(customer_id, query))
        except GoogleAdsException:
            return False

    def _search(self, customer_id: str, query: str):
        ga_service = self.client.get_service("GoogleAdsService")
        return ga_service.search(customer_id=customer_id, query=query)

    def _check_disapprovals(self, customer_id: str) -> list[dict]:
        issues = []
        query = """
            SELECT
                customer.id,
                customer.descriptive_name,
                campaign.id,
                campaign.name,
                ad_group.id,
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
                    "ad_group_id": str(row.ad_group.id),
                    "ad_group_name": row.ad_group.name,
                    "ad_id": str(row.ad_group_ad.ad.id),
                    "policy_topics": topics,
                    "details": (
                        f"Ad {row.ad_group_ad.ad.id} disapproved in campaign "
                        f"'{row.campaign.name}'. Policy topics: {', '.join(topics) or 'unspecified'}."
                    ),
                })
        except GoogleAdsException as e:
            logger.error(f"[{customer_id}] Error checking disapprovals: {e}")
        return issues

    def _check_billing(self, customer_id: str) -> list[dict]:
        issues = []
        query = """
            SELECT
                customer.id,
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
                    "ad_id": "",
                    "billing_status": row.billing_setup.status.name,
                    "details": (
                        f"Billing issue on account '{row.customer.descriptive_name}'. "
                        f"Status: {row.billing_setup.status.name}."
                    ),
                })
        except GoogleAdsException as e:
            logger.error(f"[{customer_id}] Error checking billing: {e}")
        return issues

    def _check_account_status(self, customer_id: str) -> list[dict]:
        issues = []
        query = """
            SELECT
                customer.id,
                customer.descriptive_name,
                customer.status
            FROM customer
            WHERE customer.status != 'ENABLED'
        """
        try:
            for row in self._search(customer_id, query):
                issues.append({
                    "type": "account_verification_issue",
                    "account_id": customer_id,
                    "account_name": row.customer.descriptive_name,
                    "campaign_id": "",
                    "ad_id": "",
                    "account_status": row.customer.status.name,
                    "details": (
                        f"Account '{row.customer.descriptive_name}' has status "
                        f"{row.customer.status.name} — expected ENABLED."
                    ),
                })
        except GoogleAdsException as e:
            logger.error(f"[{customer_id}] Error checking account status: {e}")
        return issues

    def _check_zero_impressions(self, customer_id: str) -> list[dict]:
        issues = []
        end_date = datetime.today().strftime("%Y-%m-%d")
        start_date = (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        # GAQL doesn't support HAVING with date-segmented queries — aggregate in Python
        query = f"""
            SELECT
                customer.id,
                customer.descriptive_name,
                campaign.id,
                campaign.name,
                metrics.impressions
            FROM campaign
            WHERE campaign.status = 'ENABLED'
              AND segments.date BETWEEN '{start_date}' AND '{end_date}'
        """
        try:
            totals: dict[str, dict] = {}
            for row in self._search(customer_id, query):
                cid = str(row.campaign.id)
                if cid not in totals:
                    totals[cid] = {
                        "name": row.campaign.name,
                        "account_name": row.customer.descriptive_name,
                        "impressions": 0,
                    }
                totals[cid]["impressions"] += row.metrics.impressions

            for cid, data in totals.items():
                if data["impressions"] == 0:
                    issues.append({
                        "type": "zero_impressions",
                        "account_id": customer_id,
                        "account_name": data["account_name"],
                        "campaign_id": cid,
                        "campaign_name": data["name"],
                        "ad_id": "",
                        "period": f"{start_date} to {end_date}",
                        "details": (
                            f"Campaign '{data['name']}' received 0 impressions "
                            f"in the last 7 days ({start_date} to {end_date})."
                        ),
                    })
        except GoogleAdsException as e:
            logger.error(f"[{customer_id}] Error checking zero impressions: {e}")
        return issues

    def _check_performance_drops(self, customer_id: str) -> list[dict]:
        issues = []
        today = datetime.today()
        recent_end = today.strftime("%Y-%m-%d")
        recent_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        prev_end = (today - timedelta(days=8)).strftime("%Y-%m-%d")
        prev_start = (today - timedelta(days=14)).strftime("%Y-%m-%d")

        def _get_metrics(start: str, end: str) -> dict:
            result = {}
            q = f"""
                SELECT
                    customer.descriptive_name,
                    campaign.id,
                    campaign.name,
                    metrics.impressions,
                    metrics.clicks
                FROM campaign
                WHERE campaign.status = 'ENABLED'
                  AND segments.date BETWEEN '{start}' AND '{end}'
            """
            try:
                for row in self._search(customer_id, q):
                    cid = str(row.campaign.id)
                    result[cid] = {
                        "name": row.campaign.name,
                        "account_name": row.customer.descriptive_name,
                        "impressions": row.metrics.impressions,
                        "clicks": row.metrics.clicks,
                    }
            except GoogleAdsException as e:
                logger.error(f"[{customer_id}] Error fetching campaign metrics: {e}")
            return result

        recent = _get_metrics(recent_start, recent_end)
        prev = _get_metrics(prev_start, prev_end)

        for cid, r in recent.items():
            p = prev.get(cid)
            if not p or p["impressions"] == 0:
                continue
            drop_pct = (p["impressions"] - r["impressions"]) / p["impressions"] * 100
            if drop_pct >= 50:
                issues.append({
                    "type": "performance_drop",
                    "account_id": customer_id,
                    "account_name": r["account_name"],
                    "campaign_id": cid,
                    "campaign_name": r["name"],
                    "ad_id": "",
                    "drop_percentage": round(drop_pct, 1),
                    "recent_impressions": r["impressions"],
                    "previous_impressions": p["impressions"],
                    "details": (
                        f"Campaign '{r['name']}' impressions dropped {drop_pct:.1f}% "
                        f"week-over-week (from {p['impressions']:,} to {r['impressions']:,})."
                    ),
                })
        return issues

    def _check_conversion_tracking(self, customer_id: str) -> list[dict]:
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
                    result[cid] = {
                        "name": row.campaign.name,
                        "account_name": row.customer.descriptive_name,
                        "conversions": row.metrics.conversions,
                    }
            except GoogleAdsException as e:
                logger.error(f"[{customer_id}] Error fetching conversion data: {e}")
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
                    "ad_id": "",
                    "recent_conversions": r["conversions"],
                    "previous_conversions": p["conversions"],
                    "details": (
                        f"Campaign '{r['name']}' had {p['conversions']:.0f} conversions "
                        f"last week but 0 this week — possible conversion tracking breakage."
                    ),
                })
        return issues
