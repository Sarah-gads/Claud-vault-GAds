import logging
from datetime import datetime
from pathlib import Path

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from .budget_manager import BudgetManager
from .geo_targeting import GeoTargeter
from .keyword_uploader import KeywordUploader
from .ad_builder import AdBuilder
from .extension_builder import ExtensionBuilder
from .image_uploader import ImageUploader
from .conversion_linker import ConversionLinker
from .validator import ConfigValidator, ValidationError, format_errors
from . import summary_generator

logger = logging.getLogger(__name__)


class ValidationFailed(Exception):
    def __init__(self, errors: list[ValidationError]):
        self.errors = errors
        super().__init__(format_errors(errors))


class CampaignBuilder:
    def __init__(self, client: GoogleAdsClient, templates_dir: str, assets_dir: str | None = None):
        self.client = client
        self.templates_dir = templates_dir
        self.assets_dir = Path(assets_dir) if assets_dir else None

    def build(self, config: dict) -> dict:
        # ── 0. Validate EVERYTHING before touching the API ──────────────────
        validator = ConfigValidator()
        errors = validator.validate(config, self.assets_dir)
        if errors:
            logger.error(format_errors(errors))
            raise ValidationFailed(errors)

        # ── Normalise config fields ─────────────────────────────────────────
        customer_id  = config["client"]["customer_id"].replace("-", "")
        client_name  = config["client"]["name"]
        campaign_name = config["campaign"]["name"]
        budget_micros = int(config["campaign"]["daily_budget"] * 1_000_000)
        final_url    = config["landing_page"]["final_url"]

        result = {
            "client_name":   client_name,
            "customer_id":   customer_id,
            "campaign_name": campaign_name,
            "final_url":     final_url,
            "status":        "pending",
            "created_at":    datetime.utcnow().isoformat(),
        }

        logger.info(f"Building campaign '{campaign_name}' for {client_name} ({customer_id})")

        try:
            # ── 1. Budget ────────────────────────────────────────────────────
            budget_resource = BudgetManager(self.client).create(
                customer_id=customer_id,
                name=f"Budget — {client_name}",
                amount_micros=budget_micros,
            )
            result["budget_resource"] = budget_resource

            # ── 2. Campaign (always PAUSED) ──────────────────────────────────
            campaign_resource = self._create_campaign(customer_id, config, budget_resource)
            result["campaign_resource"] = campaign_resource

            # ── 3. Campaign-level negative keyword lists ──────────────────────
            neg_lists = config.get("campaign_keywords", {}).get("negative_lists", [])
            if neg_lists:
                neg_count = KeywordUploader(self.client, self.templates_dir).upload_campaign_negatives(
                    customer_id=customer_id,
                    campaign_resource=campaign_resource,
                    negative_lists=neg_lists,
                )
                result["campaign_negatives"] = neg_count
                logger.info(f"Uploaded {neg_count} campaign-level negative keyword(s) across {len(neg_lists)} list(s)")

            # ── 4. Geo targeting + location exclusions + ad schedule ─────────
            targeting = config.get("targeting", {})
            GeoTargeter(self.client).apply(
                customer_id=customer_id,
                campaign_resource=campaign_resource,
                location_ids=[l["id"] for l in targeting.get("locations", [])],
                location_exclusion_ids=[l["id"] for l in targeting.get("location_exclusions", [])],
                ad_schedule=targeting.get("ad_schedule") or None,
            )

            # ── 5–7. Ad groups → keywords → RSAs ────────────────────────────
            ad_groups_cfg = config.get("ad_groups", [])
            if ad_groups_cfg:
                # Multi-ad-group flow: each group has its own keywords + 3 RSAs
                ag_results = []
                kw_uploader = KeywordUploader(self.client, self.templates_dir)
                ad_bldr     = AdBuilder(self.client, self.templates_dir)
                for ag_cfg in ad_groups_cfg:
                    ag_resource = self._create_ad_group_from_cfg(
                        customer_id, campaign_resource, ag_cfg
                    )
                    kw_counts = kw_uploader.upload_from_json(
                        customer_id=customer_id,
                        ad_group_resource=ag_resource,
                        campaign_resource=campaign_resource,
                        keywords_config=ag_cfg.get("keywords", {}),
                    )
                    rsa_resources = []
                    for rsa in ag_cfg.get("rsa", []):
                        if rsa.get("headlines") and rsa.get("descriptions"):
                            rsa_config = {**config, "ad_copy": rsa}
                            rsa_resources.append(
                                ad_bldr.create_rsa(
                                    customer_id=customer_id,
                                    ad_group_resource=ag_resource,
                                    config=rsa_config,
                                )
                            )
                    ag_results.append({
                        "name":      ag_cfg["name"],
                        "resource":  ag_resource,
                        "keywords":  kw_counts,
                        "rsa_count": len(rsa_resources),
                    })
                    logger.info(
                        f"Ad group '{ag_cfg['name']}': "
                        f"{kw_counts} keywords, {len(rsa_resources)} RSA(s)"
                    )
                result["ad_groups"]        = ag_results
                result["ad_group_resource"] = ag_results[0]["resource"]
                result["keywords"]          = ag_results[0]["keywords"]
                result["ad_resource"]       = None
            else:
                # Legacy single-ad-group flow
                ad_group_resource = self._create_ad_group(customer_id, campaign_resource, config)
                result["ad_group_resource"] = ad_group_resource
                kw_counts = KeywordUploader(self.client, self.templates_dir).upload_from_json(
                    customer_id=customer_id,
                    ad_group_resource=ad_group_resource,
                    campaign_resource=campaign_resource,
                    keywords_config=config.get("keywords", {}),
                )
                result["keywords"]  = kw_counts
                result["ad_resource"] = AdBuilder(self.client, self.templates_dir).create_rsa(
                    customer_id=customer_id,
                    ad_group_resource=ad_group_resource,
                    config=config,
                )

            # ── 7. Extensions (sitelinks, callouts, snippets, call) ──────────
            ext_counts = ExtensionBuilder(self.client, self.templates_dir).create_all(
                customer_id=customer_id,
                campaign_resource=campaign_resource,
                config=self._normalise_ext_config(config),
            )
            result["extensions"] = ext_counts

            # ── 8. Images / logo / business name ─────────────────────────────
            if self.assets_dir and config.get("business"):
                asset_counts = ImageUploader(self.client).upload_all(
                    customer_id=customer_id,
                    campaign_resource=campaign_resource,
                    config=config,
                    assets_dir=self.assets_dir,
                )
                result["assets"] = asset_counts
            else:
                result["assets"] = {}

            # ── 9. Conversion goals ──────────────────────────────────────────
            conv = config.get("conversion_actions", {})
            if not conv.get("inherit_account_goals", True) and conv.get("action_ids"):
                ConversionLinker(self.client).link_specific_goals(
                    customer_id=customer_id,
                    campaign_resource=campaign_resource,
                    conversion_action_ids=conv["action_ids"],
                )

            # ── 10. Summary ──────────────────────────────────────────────────
            result["status"]  = "created_paused"
            result["summary"] = summary_generator.generate(config, result)
            result["summary_markdown"] = summary_generator.generate_markdown(config, result)

            logger.info(result["summary"])

        except ValidationFailed:
            raise

        except GoogleAdsException as gae:
            error_msg = "; ".join(
                f"{e.error_code}: {e.message}" for e in gae.failure.errors
            )
            result["status"] = "error"
            result["error"]  = error_msg
            logger.error(f"Google Ads API error: {error_msg}")
            raise

        except Exception as e:
            result["status"] = "error"
            result["error"]  = str(e)
            logger.error(f"Unexpected error: {e}")
            raise

        return result

    def _normalise_ext_config(self, config: dict) -> dict:
        """
        Returns a config dict the ExtensionBuilder can consume.
        JSON configs store extensions at config["extensions"];
        we map them to the internal format.
        """
        ext = config.get("extensions", {})
        lp  = config.get("landing_page", {})
        base_url = lp.get("final_url", "").rstrip("/")
        # Strip path for the base — ExtensionBuilder uses base_url + url_suffix
        # But JSON sitelinks have final_url already, so base_url won't be used.
        return {
            "client":   config["client"],
            "campaign": config["campaign"],
            "landing_page": {"base_url": base_url, "path": ""},
            "call_tracking": {
                "phone_number": ext.get("call", {}).get("phone_number", ""),
                "country_code": ext.get("call", {}).get("country_code", "US"),
            },
            "extensions": {
                "use_default_sitelinks": False,
                "custom_sitelinks": ext.get("sitelinks", []),
                "use_default_callouts": False,
                "custom_callouts": ext.get("callouts", []),
                "use_default_structured_snippets": False,
                "custom_structured_snippets": ext.get("structured_snippets", []),
            },
        }

    def _create_campaign(self, customer_id: str, config: dict, budget_resource: str) -> str:
        service   = self.client.get_service("CampaignService")
        operation = self.client.get_type("CampaignOperation")
        campaign  = operation.create

        campaign.name   = config["campaign"]["name"]
        campaign.status = self.client.enums.CampaignStatusEnum.PAUSED
        campaign.advertising_channel_type = self.client.enums.AdvertisingChannelTypeEnum.SEARCH
        campaign.campaign_budget = budget_resource

        campaign.network_settings.target_google_search        = True
        campaign.network_settings.target_search_network       = True
        campaign.network_settings.target_partner_search_network = False
        campaign.network_settings.target_content_network      = False

        strategy = config["campaign"].get("bidding_strategy", "maximize_conversions")
        if strategy == "maximize_conversions":
            tgt_cpa = config["campaign"].get("target_cpa") or 0
            campaign.maximize_conversions.target_cpa_micros = int(tgt_cpa * 1_000_000)
        elif strategy == "target_cpa":
            campaign.target_cpa.target_cpa_micros = int(
                (config["campaign"].get("target_cpa") or 0) * 1_000_000
            )
        elif strategy == "manual_cpc":
            campaign.manual_cpc.enhanced_cpc_enabled = True

        try:
            response = service.mutate_campaigns(customer_id=customer_id, operations=[operation])
            resource = response.results[0].resource_name
            logger.info(f"Campaign created (PAUSED): {resource}")
            return resource
        except GoogleAdsException as e:
            logger.error(f"Failed to create campaign: {e}")
            raise

    def _create_ad_group_from_cfg(self, customer_id: str, campaign_resource: str, ag_cfg: dict) -> str:
        service   = self.client.get_service("AdGroupService")
        operation = self.client.get_type("AdGroupOperation")
        ag        = operation.create
        ag.name             = ag_cfg.get("name", "Ad Group")
        ag.campaign         = campaign_resource
        ag.type_            = self.client.enums.AdGroupTypeEnum.SEARCH_STANDARD
        ag.cpc_bid_micros   = int(ag_cfg.get("cpc_bid", 2.0) * 1_000_000)
        try:
            response = self.client.get_service("AdGroupService").mutate_ad_groups(
                customer_id=customer_id, operations=[operation]
            )
            resource = response.results[0].resource_name
            logger.info(f"Ad group created: {ag_cfg['name']} → {resource}")
            return resource
        except GoogleAdsException as e:
            logger.error(f"Failed to create ad group '{ag_cfg.get('name')}': {e}")
            raise

    def _create_ad_group(self, customer_id: str, campaign_resource: str, config: dict) -> str:
        service   = self.client.get_service("AdGroupService")
        operation = self.client.get_type("AdGroupOperation")
        ad_group  = operation.create

        ag_config = config.get("ad_group", {})
        ad_group.name = (
            ag_config.get("name")
            or f"{config['campaign']['name']} — General"
        )
        ad_group.campaign       = campaign_resource
        ad_group.type_          = self.client.enums.AdGroupTypeEnum.SEARCH_STANDARD
        ad_group.cpc_bid_micros = int(ag_config.get("cpc_bid", 2.0) * 1_000_000)

        try:
            response = service.mutate_ad_groups(customer_id=customer_id, operations=[operation])
            resource = response.results[0].resource_name
            logger.info(f"Ad group created: {resource}")
            return resource
        except GoogleAdsException as e:
            logger.error(f"Failed to create ad group: {e}")
            raise
