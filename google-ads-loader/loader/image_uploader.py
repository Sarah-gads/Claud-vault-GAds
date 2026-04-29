import logging
import mimetypes
from pathlib import Path

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

logger = logging.getLogger(__name__)

_MIME_TYPE_MAP = {
    "image/jpeg": "IMAGE_JPEG",
    "image/png":  "IMAGE_PNG",
    "image/gif":  "IMAGE_GIF",
    "image/webp": "IMAGE_WEBP",
}


def _mime_enum(client: GoogleAdsClient, path: Path):
    mime_str, _ = mimetypes.guess_type(str(path))
    enum_name = _MIME_TYPE_MAP.get(mime_str or "", "IMAGE_JPEG")
    return getattr(client.enums.MimeTypeEnum, enum_name)


class ImageUploader:
    """
    Uploads image assets, logo, and business name to a campaign.
    All uploads are campaign-level assets — they apply across all ad groups.
    """

    def __init__(self, client: GoogleAdsClient):
        self.client = client
        self._asset_service = client.get_service("AssetService")
        self._campaign_asset_service = client.get_service("CampaignAssetService")

    def upload_all(
        self,
        customer_id: str,
        campaign_resource: str,
        config: dict,
        assets_dir: Path,
    ) -> dict:
        business = config.get("business", {})
        counts: dict[str, int] = {}

        if business.get("name", "").strip():
            try:
                self._upload_business_name(customer_id, campaign_resource, business["name"])
                counts["business_name"] = 1
            except Exception as e:
                logger.error(f"Business name upload failed: {e}")

        logo_path = business.get("logo", {}).get("path", "").strip()
        if logo_path:
            try:
                full_path = assets_dir / logo_path
                self._upload_logo(customer_id, campaign_resource, full_path, business["name"])
                counts["logo"] = 1
            except Exception as e:
                logger.error(f"Logo upload failed: {e}")

        image_count = 0
        for img in business.get("images", []):
            img_path = img.get("path", "").strip()
            if not img_path:
                continue
            try:
                full_path = assets_dir / img_path
                self._upload_image(
                    customer_id, campaign_resource, full_path,
                    img.get("name") or Path(img_path).stem,
                )
                image_count += 1
            except Exception as e:
                logger.error(f"Image upload failed ({img_path}): {e}")

        if image_count:
            counts["images"] = image_count

        return counts

    def _upload_business_name(
        self, customer_id: str, campaign_resource: str, business_name: str
    ) -> None:
        asset_op = self.client.get_type("AssetOperation")
        asset = asset_op.create
        asset.name = f"Business Name — {business_name}"
        asset.business_name_asset.business_name = business_name

        resp = self._asset_service.mutate_assets(
            customer_id=customer_id, operations=[asset_op]
        )
        asset_resource = resp.results[0].resource_name
        self._link(
            customer_id, campaign_resource, asset_resource,
            self.client.enums.AssetFieldTypeEnum.BUSINESS_NAME,
        )
        logger.info(f"Business name asset uploaded: {business_name}")

    def _upload_logo(
        self,
        customer_id: str,
        campaign_resource: str,
        path: Path,
        business_name: str,
    ) -> None:
        image_data = path.read_bytes()
        asset_op = self.client.get_type("AssetOperation")
        asset = asset_op.create
        asset.name = f"Logo — {business_name}"
        asset.image_asset.data = image_data
        asset.image_asset.mime_type = _mime_enum(self.client, path)

        resp = self._asset_service.mutate_assets(
            customer_id=customer_id, operations=[asset_op]
        )
        asset_resource = resp.results[0].resource_name
        self._link(
            customer_id, campaign_resource, asset_resource,
            self.client.enums.AssetFieldTypeEnum.LOGO,
        )
        logger.info(f"Logo uploaded: {path.name}")

    def _upload_image(
        self,
        customer_id: str,
        campaign_resource: str,
        path: Path,
        name: str,
    ) -> None:
        image_data = path.read_bytes()
        asset_op = self.client.get_type("AssetOperation")
        asset = asset_op.create
        asset.name = f"Image — {name}"
        asset.image_asset.data = image_data
        asset.image_asset.mime_type = _mime_enum(self.client, path)

        resp = self._asset_service.mutate_assets(
            customer_id=customer_id, operations=[asset_op]
        )
        asset_resource = resp.results[0].resource_name
        self._link(
            customer_id, campaign_resource, asset_resource,
            self.client.enums.AssetFieldTypeEnum.IMAGE,
        )
        logger.info(f"Image uploaded: {path.name}")

    def _link(
        self,
        customer_id: str,
        campaign_resource: str,
        asset_resource: str,
        field_type,
    ) -> None:
        op = self.client.get_type("CampaignAssetOperation")
        ca = op.create
        ca.campaign = campaign_resource
        ca.asset = asset_resource
        ca.field_type = field_type
        self._campaign_asset_service.mutate_campaign_assets(
            customer_id=customer_id, operations=[op]
        )
