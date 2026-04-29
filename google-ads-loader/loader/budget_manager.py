import logging

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

logger = logging.getLogger(__name__)


class BudgetManager:
    def __init__(self, client: GoogleAdsClient):
        self.client = client
        self.service = client.get_service("CampaignBudgetService")

    def create(self, customer_id: str, name: str, amount_micros: int) -> str:
        operation = self.client.get_type("CampaignBudgetOperation")
        budget = operation.create
        budget.name = name
        budget.amount_micros = amount_micros
        budget.delivery_method = self.client.enums.BudgetDeliveryMethodEnum.STANDARD

        try:
            response = self.service.mutate_campaign_budgets(
                customer_id=customer_id, operations=[operation]
            )
            resource_name = response.results[0].resource_name
            logger.info(
                f"Budget created: {name} (${amount_micros / 1_000_000:.2f}/day)"
                f" — {resource_name}"
            )
            return resource_name
        except GoogleAdsException as e:
            logger.error(f"Failed to create budget '{name}': {e}")
            raise
