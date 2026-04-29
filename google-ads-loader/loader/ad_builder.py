import logging
from pathlib import Path

import yaml
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

logger = logging.getLogger(__name__)

_HEADLINE_LIMIT = 30
_DESCRIPTION_LIMIT = 90


def _validate_assets(headlines: list[str], descriptions: list[str]) -> None:
    for h in headlines:
        if len(h) > _HEADLINE_LIMIT:
            raise ValueError(
                f"Headline exceeds {_HEADLINE_LIMIT} chars ({len(h)}): '{h}'"
            )
    for d in descriptions:
        if len(d) > _DESCRIPTION_LIMIT:
            raise ValueError(
                f"Description exceeds {_DESCRIPTION_LIMIT} chars ({len(d)}): '{d}'"
            )
    if len(headlines) < 3:
        raise ValueError(f"RSA requires at least 3 headlines, got {len(headlines)}")
    if len(descriptions) < 2:
        raise ValueError(f"RSA requires at least 2 descriptions, got {len(descriptions)}")


class AdBuilder:
    def __init__(self, client: GoogleAdsClient, templates_dir: str):
        self.client = client
        self.templates_dir = Path(templates_dir)

    def create_rsa(
        self,
        customer_id: str,
        ad_group_resource: str,
        config: dict,
    ) -> str:
        # Custom copy from web UI takes priority; templates are the fallback
        custom_copy = config.get("ad_copy", {})
        if custom_copy.get("headlines") and custom_copy.get("descriptions"):
            headlines = list(custom_copy["headlines"])[:15]
            descriptions = list(custom_copy["descriptions"])[:4]
        else:
            templates = self._load_templates()
            headlines = list(templates["headlines"])[:15]
            descriptions = list(templates["descriptions"])[:4]

        # JSON configs use final_url directly; legacy YAML configs use base_url + path
        lp = config.get("landing_page", {})
        final_url = lp.get("final_url") or (
            lp.get("base_url", "").rstrip("/") + lp.get("path", "")
        )

        _validate_assets(headlines, descriptions)

        service = self.client.get_service("AdGroupAdService")
        operation = self.client.get_type("AdGroupAdOperation")
        ad_group_ad = operation.create
        ad_group_ad.status = self.client.enums.AdGroupAdStatusEnum.ENABLED
        ad_group_ad.ad_group = ad_group_resource

        rsa = ad_group_ad.ad.responsive_search_ad
        served_enum = self.client.enums.ServedAssetFieldTypeEnum

        _HL_PIN_MAP = {
            "H1": served_enum.HEADLINE_1,
            "H2": served_enum.HEADLINE_2,
            "H3": served_enum.HEADLINE_3,
        }
        _DL_PIN_MAP = {
            "D1": served_enum.DESCRIPTION_1,
            "D2": served_enum.DESCRIPTION_2,
        }

        pins = custom_copy.get("pins", None)
        if pins is not None:
            # Explicit pins from the UI — build text→position lookup
            hl_pin_by_text = {text: pos for pos, text in pins.get("headlines", {}).items()}
            dl_pin_by_text = {text: pos for pos, text in pins.get("descriptions", {}).items()}
            for text in headlines:
                asset = self.client.get_type("AdTextAsset")
                asset.text = text
                pos = hl_pin_by_text.get(text)
                if pos and pos in _HL_PIN_MAP:
                    asset.pinned_field = _HL_PIN_MAP[pos]
                rsa.headlines.append(asset)
            for text in descriptions:
                asset = self.client.get_type("AdTextAsset")
                asset.text = text
                pos = dl_pin_by_text.get(text)
                if pos and pos in _DL_PIN_MAP:
                    asset.pinned_field = _DL_PIN_MAP[pos]
                rsa.descriptions.append(asset)
        else:
            # Legacy / template path — auto-pin first 3 headlines
            auto_pins = [served_enum.HEADLINE_1, served_enum.HEADLINE_2, served_enum.HEADLINE_3]
            for i, text in enumerate(headlines):
                asset = self.client.get_type("AdTextAsset")
                asset.text = text
                if i < len(auto_pins):
                    asset.pinned_field = auto_pins[i]
                rsa.headlines.append(asset)
            for text in descriptions:
                asset = self.client.get_type("AdTextAsset")
                asset.text = text
                rsa.descriptions.append(asset)

        ad_group_ad.ad.final_urls.append(final_url)

        try:
            response = service.mutate_ad_group_ads(
                customer_id=customer_id, operations=[operation]
            )
            resource_name = response.results[0].resource_name
            logger.info(
                f"RSA created: {len(headlines)} headlines, "
                f"{len(descriptions)} descriptions — {resource_name}"
            )
            return resource_name
        except GoogleAdsException as e:
            logger.error(f"Failed to create RSA: {e}")
            raise

    def _load_templates(self) -> dict:
        template_path = self.templates_dir / "ads" / "rsa_templates.yaml"
        with template_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
