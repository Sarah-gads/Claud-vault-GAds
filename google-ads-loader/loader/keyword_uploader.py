import logging
from pathlib import Path

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

logger = logging.getLogger(__name__)

_MAX_BATCH = 2_000


class KeywordUploader:
    def __init__(self, client: GoogleAdsClient, templates_dir: str | None = None):
        self.client = client
        self.templates_dir = Path(templates_dir) if templates_dir else None

    def upload_from_json(
        self,
        customer_id: str,
        ad_group_resource: str,
        campaign_resource: str,
        keywords_config: dict,
    ) -> dict:
        """
        Primary method for JSON-format configs.
        keywords_config = {
            "positive": [{"text": "...", "match_type": "PHRASE"}, ...],
            "negative": [{"text": "...", "match_type": "BROAD"}, ...],
        }
        """
        positives = [
            (kw["text"].strip(), kw.get("match_type", "BROAD").upper())
            for kw in keywords_config.get("positive", [])
            if kw.get("text", "").strip()
        ]
        negatives = [
            (kw["text"].strip(), kw.get("match_type", "BROAD").upper())
            for kw in keywords_config.get("negative", [])
            if kw.get("text", "").strip()
        ]

        pos_count = self._upload_positive_keywords(customer_id, ad_group_resource, positives)

        if negatives:
            self._upload_negative_list(customer_id, campaign_resource, negatives)

        return {"positive": pos_count, "negative": len(negatives)}

    def _upload_positive_keywords(
        self,
        customer_id: str,
        ad_group_resource: str,
        keywords: list[tuple[str, str]],
    ) -> int:
        if not keywords:
            return 0
        service = self.client.get_service("AdGroupCriterionService")
        match_enum  = self.client.enums.KeywordMatchTypeEnum
        status_enum = self.client.enums.AdGroupCriterionStatusEnum
        operations  = []

        for text, match_name in keywords:
            op = self.client.get_type("AdGroupCriterionOperation")
            criterion = op.create
            criterion.status   = status_enum.ENABLED
            criterion.ad_group = ad_group_resource
            criterion.keyword.text       = text
            criterion.keyword.match_type = getattr(match_enum, match_name)
            operations.append(op)

        for i in range(0, len(operations), _MAX_BATCH):
            try:
                service.mutate_ad_group_criteria(
                    customer_id=customer_id, operations=operations[i : i + _MAX_BATCH]
                )
            except GoogleAdsException as e:
                logger.error(f"Keyword batch {i} failed: {e}")
                raise

        logger.info(f"Uploaded {len(keywords)} positive keyword(s)")
        return len(keywords)

    def upload_campaign_negatives(
        self,
        customer_id: str,
        campaign_resource: str,
        negative_lists: list[dict],
    ) -> int:
        """
        negative_lists: [{name: str, keywords: [{text, match_type}]}]
        Creates one named shared negative set per list entry.
        """
        total = 0
        for lst in negative_lists:
            name = lst.get("name") or "Negative List"
            negatives = [
                (kw["text"].strip(), kw.get("match_type", "BROAD").upper())
                for kw in lst.get("keywords", [])
                if kw.get("text", "").strip()
            ]
            if negatives:
                self._upload_negative_list(customer_id, campaign_resource, negatives, list_name=name)
                total += len(negatives)
        return total

    def _upload_negative_list(
        self,
        customer_id: str,
        campaign_resource: str,
        negatives: list[tuple[str, str]],
        list_name: str | None = None,
    ) -> None:
        shared_set_service          = self.client.get_service("SharedSetService")
        shared_criterion_service    = self.client.get_service("SharedCriterionService")
        campaign_shared_set_service = self.client.get_service("CampaignSharedSetService")

        client_label = campaign_resource.split("/")[1]

        ss_op = self.client.get_type("SharedSetOperation")
        ss = ss_op.create
        ss.name   = list_name or f"Negatives — {client_label}"
        ss.type_  = self.client.enums.SharedSetTypeEnum.NEGATIVE_KEYWORDS

        try:
            ss_resp     = shared_set_service.mutate_shared_sets(customer_id=customer_id, operations=[ss_op])
            ss_resource = ss_resp.results[0].resource_name
        except GoogleAdsException as e:
            logger.error(f"Failed to create shared negative set: {e}")
            raise

        match_enum = self.client.enums.KeywordMatchTypeEnum
        criterion_ops = []
        for text, match_name in negatives:
            op = self.client.get_type("SharedCriterionOperation")
            criterion = op.create
            criterion.shared_set          = ss_resource
            criterion.keyword.text        = text
            criterion.keyword.match_type  = getattr(match_enum, match_name, match_enum.BROAD)
            criterion_ops.append(op)

        for i in range(0, len(criterion_ops), _MAX_BATCH):
            try:
                shared_criterion_service.mutate_shared_criteria(
                    customer_id=customer_id, operations=criterion_ops[i : i + _MAX_BATCH]
                )
            except GoogleAdsException as e:
                logger.error(f"Negative keyword batch {i} failed: {e}")
                raise

        link_op = self.client.get_type("CampaignSharedSetOperation")
        link = link_op.create
        link.campaign   = campaign_resource
        link.shared_set = ss_resource
        try:
            campaign_shared_set_service.mutate_campaign_shared_sets(
                customer_id=customer_id, operations=[link_op]
            )
        except GoogleAdsException as e:
            logger.error(f"Failed to link negative list: {e}")
            raise

        logger.info(f"Uploaded {len(negatives)} negative keyword(s) and linked shared set")
