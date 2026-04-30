import logging

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

logger = logging.getLogger(__name__)


class ConversionLinker:
    def __init__(self, client: GoogleAdsClient):
        self.client = client

    def list_conversion_actions(self, customer_id: str) -> list[dict]:
        service = self.client.get_service("GoogleAdsService")
        query = """
            SELECT
                conversion_action.id,
                conversion_action.name,
                conversion_action.status,
                conversion_action.type_
            FROM conversion_action
            WHERE conversion_action.status = 'ENABLED'
        """
        actions = []
        try:
            for row in service.search(customer_id=customer_id, query=query):
                actions.append({
                    "id": row.conversion_action.id,
                    "name": row.conversion_action.name,
                    "type": row.conversion_action.type_.name,
                })
        except GoogleAdsException as e:
            logger.error(f"Failed to list conversion actions: {e}")
        return actions

    def link_specific_goals(
        self,
        customer_id: str,
        campaign_resource: str,
        conversion_action_ids: list[int],
    ) -> None:
        """
        Override the campaign's conversion goals to use only specific actions.
        Skipped when inherit_account_goals: true (the recommended default).
        """
        if not conversion_action_ids:
            return

        service = self.client.get_service("CampaignConversionGoalService")
        operations = []

        for action_id in conversion_action_ids:
            conversion_action_resource = self.client.get_service(
                "ConversionActionService"
            ).conversion_action_path(customer_id, str(action_id))

            op = self.client.get_type("CampaignConversionGoalOperation")
            goal = op.update
            goal.campaign = campaign_resource
            goal.conversion_action = conversion_action_resource
            goal.biddable = True
            operations.append(op)

        try:
            service.mutate_campaign_conversion_goals(
                customer_id=customer_id, operations=operations
            )
            logger.info(
                f"Linked {len(conversion_action_ids)} specific conversion goal(s)"
            )
        except GoogleAdsException as e:
            logger.error(f"Failed to link conversion goals: {e}")
            raise
