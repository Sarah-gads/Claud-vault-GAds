import logging
from pathlib import Path

import yaml
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

logger = logging.getLogger(__name__)


class ExtensionBuilder:
    def __init__(self, client: GoogleAdsClient, templates_dir: str):
        self.client = client
        self.templates_dir = Path(templates_dir)
        self._asset_service = client.get_service("AssetService")
        self._campaign_asset_service = client.get_service("CampaignAssetService")

    def create_all(
        self,
        customer_id: str,
        campaign_resource: str,
        config: dict,
    ) -> dict:
        ext_config = config.get("extensions", {})
        base_url = config["landing_page"]["base_url"].rstrip("/")
        phone = config.get("call_tracking", {}).get("phone_number", "")
        country_code = config.get("call_tracking", {}).get("country_code", "US")

        counts = {}

        # Sitelinks
        sitelinks = []
        if ext_config.get("use_default_sitelinks", True):
            sitelinks.extend(self._load_yaml("extensions/sitelinks.yaml")["sitelinks"])
        sitelinks.extend(ext_config.get("custom_sitelinks", []))
        if sitelinks:
            counts["sitelinks"] = self._create_sitelinks(
                customer_id, campaign_resource, sitelinks, base_url
            )

        # Callouts
        callouts = []
        if ext_config.get("use_default_callouts", True):
            callouts.extend(self._load_yaml("extensions/callouts.yaml")["callouts"])
        callouts.extend(ext_config.get("custom_callouts", []))
        if callouts:
            counts["callouts"] = self._create_callouts(
                customer_id, campaign_resource, callouts
            )

        # Structured snippets — custom (from web UI) takes priority over defaults
        snippets = []
        if ext_config.get("use_default_structured_snippets", True):
            snippets.extend(
                self._load_yaml("extensions/structured_snippets.yaml")[
                    "structured_snippets"
                ]
            )
        snippets.extend(ext_config.get("custom_structured_snippets", []))
        if snippets:
            counts["structured_snippets"] = self._create_structured_snippets(
                customer_id, campaign_resource, snippets
            )

        # Call extension
        if phone:
            self._create_call_extension(
                customer_id, campaign_resource, phone, country_code
            )
            counts["call"] = 1

        return counts

    def _create_sitelinks(
        self,
        customer_id: str,
        campaign_resource: str,
        sitelinks: list[dict],
        base_url: str,
    ) -> int:
        field_type = self.client.enums.AssetFieldTypeEnum.SITELINK
        created = 0

        for sl in sitelinks:
            try:
                asset_op = self.client.get_type("AssetOperation")
                asset = asset_op.create
                asset.name = f"Sitelink - {sl['link_text']}"
                sitelink_asset = asset.sitelink_asset
                sitelink_asset.link_text = sl["link_text"]
                sitelink_asset.description1 = sl.get("description1", "")
                sitelink_asset.description2 = sl.get("description2", "")
                # JSON configs supply a full final_url; YAML configs use url_suffix
                if sl.get("final_url"):
                    sitelink_asset.final_urls.append(sl["final_url"])
                else:
                    sitelink_asset.final_urls.append(base_url + sl.get("url_suffix", ""))

                asset_resp = self._asset_service.mutate_assets(
                    customer_id=customer_id, operations=[asset_op]
                )
                asset_resource = asset_resp.results[0].resource_name

                self._link_asset_to_campaign(
                    customer_id, campaign_resource, asset_resource, field_type
                )
                created += 1
            except GoogleAdsException as e:
                logger.error(f"Failed to create sitelink '{sl.get('link_text')}': {e}")

        logger.info(f"Created {created} sitelink(s)")
        return created

    def _create_callouts(
        self,
        customer_id: str,
        campaign_resource: str,
        callouts: list[str],
    ) -> int:
        field_type = self.client.enums.AssetFieldTypeEnum.CALLOUT
        created = 0

        for callout_text in callouts:
            try:
                asset_op = self.client.get_type("AssetOperation")
                asset = asset_op.create
                asset.name = f"Callout - {callout_text}"
                asset.callout_asset.callout_text = callout_text

                asset_resp = self._asset_service.mutate_assets(
                    customer_id=customer_id, operations=[asset_op]
                )
                asset_resource = asset_resp.results[0].resource_name

                self._link_asset_to_campaign(
                    customer_id, campaign_resource, asset_resource, field_type
                )
                created += 1
            except GoogleAdsException as e:
                logger.error(f"Failed to create callout '{callout_text}': {e}")

        logger.info(f"Created {created} callout(s)")
        return created

    def _create_structured_snippets(
        self,
        customer_id: str,
        campaign_resource: str,
        snippets: list[dict],
    ) -> int:
        field_type = self.client.enums.AssetFieldTypeEnum.STRUCTURED_SNIPPET
        created = 0

        for snippet in snippets:
            try:
                asset_op = self.client.get_type("AssetOperation")
                asset = asset_op.create
                asset.name = f"Snippet - {snippet['header']}"
                snippet_asset = asset.structured_snippet_asset
                snippet_asset.header = snippet["header"]
                snippet_asset.values.extend(snippet["values"])

                asset_resp = self._asset_service.mutate_assets(
                    customer_id=customer_id, operations=[asset_op]
                )
                asset_resource = asset_resp.results[0].resource_name

                self._link_asset_to_campaign(
                    customer_id, campaign_resource, asset_resource, field_type
                )
                created += 1
            except GoogleAdsException as e:
                logger.error(
                    f"Failed to create structured snippet '{snippet.get('header')}': {e}"
                )

        logger.info(f"Created {created} structured snippet(s)")
        return created

    def _create_call_extension(
        self,
        customer_id: str,
        campaign_resource: str,
        phone_number: str,
        country_code: str,
    ) -> None:
        field_type = self.client.enums.AssetFieldTypeEnum.CALL

        try:
            asset_op = self.client.get_type("AssetOperation")
            asset = asset_op.create
            asset.name = f"Call - {phone_number}"
            call_asset = asset.call_asset
            call_asset.country_code = country_code
            call_asset.phone_number = phone_number

            asset_resp = self._asset_service.mutate_assets(
                customer_id=customer_id, operations=[asset_op]
            )
            asset_resource = asset_resp.results[0].resource_name

            self._link_asset_to_campaign(
                customer_id, campaign_resource, asset_resource, field_type
            )
            logger.info(f"Created call extension: {phone_number}")
        except GoogleAdsException as e:
            logger.error(f"Failed to create call extension: {e}")
            raise

    def _link_asset_to_campaign(
        self,
        customer_id: str,
        campaign_resource: str,
        asset_resource: str,
        field_type,
    ) -> None:
        op = self.client.get_type("CampaignAssetOperation")
        campaign_asset = op.create
        campaign_asset.campaign = campaign_resource
        campaign_asset.asset = asset_resource
        campaign_asset.field_type = field_type

        self._campaign_asset_service.mutate_campaign_assets(
            customer_id=customer_id, operations=[op]
        )

    def _load_yaml(self, relative_path: str) -> dict:
        path = self.templates_dir / relative_path
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
