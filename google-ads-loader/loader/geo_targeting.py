import logging

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

logger = logging.getLogger(__name__)

_DEFAULT_SCHEDULE = [
    ("MONDAY",    7, 19),
    ("TUESDAY",   7, 19),
    ("WEDNESDAY", 7, 19),
    ("THURSDAY",  7, 19),
    ("FRIDAY",    7, 19),
    ("SATURDAY",  9, 15),
]


class GeoTargeter:
    def __init__(self, client: GoogleAdsClient):
        self.client = client
        self.service = client.get_service("CampaignCriterionService")

    def apply(
        self,
        customer_id: str,
        campaign_resource: str,
        location_ids: list[int],
        location_exclusion_ids: list[int] | None = None,
        ad_schedule: list[dict] | None = None,
    ) -> None:
        operations = []
        day_enum    = self.client.enums.DayOfWeekEnum
        minute_enum = self.client.enums.MinuteOfHourEnum

        # Target locations
        for loc_id in location_ids:
            op = self.client.get_type("CampaignCriterionOperation")
            criterion = op.create
            criterion.campaign = campaign_resource
            criterion.location.geo_target_constant = f"geoTargetConstants/{loc_id}"
            operations.append(op)

        # Excluded locations — same structure but negative = True
        for loc_id in (location_exclusion_ids or []):
            op = self.client.get_type("CampaignCriterionOperation")
            criterion = op.create
            criterion.campaign = campaign_resource
            criterion.negative = True
            criterion.location.geo_target_constant = f"geoTargetConstants/{loc_id}"
            operations.append(op)

        # Ad schedule — use provided schedule, or the default if none given
        schedule_entries = (
            [(s["day"].upper(), s["start_hour"], s["end_hour"]) for s in ad_schedule]
            if ad_schedule
            else _DEFAULT_SCHEDULE
        )

        for day_name, start_hour, end_hour in schedule_entries:
            op = self.client.get_type("CampaignCriterionOperation")
            criterion = op.create
            criterion.campaign = campaign_resource
            criterion.ad_schedule.day_of_week = getattr(day_enum, day_name)
            criterion.ad_schedule.start_hour = start_hour
            criterion.ad_schedule.start_minute = minute_enum.ZERO
            criterion.ad_schedule.end_hour = end_hour
            criterion.ad_schedule.end_minute = minute_enum.ZERO
            operations.append(op)

        try:
            self.service.mutate_campaign_criteria(
                customer_id=customer_id, operations=operations
            )
            excl_count = len(location_exclusion_ids or [])
            logger.info(
                f"Geo: {len(location_ids)} target(s), {excl_count} exclusion(s), "
                f"{len(schedule_entries)} schedule window(s)"
            )
        except GoogleAdsException as e:
            logger.error(f"Failed to apply geo/schedule criteria: {e}")
            raise
