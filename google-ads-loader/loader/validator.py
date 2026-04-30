"""
Pre-flight config validator.
Call validate() before creating ANYTHING in Google Ads.
Returns a list of ValidationError. If the list is non-empty, abort.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


_MATCH_TYPES = {"BROAD", "PHRASE", "EXACT"}
_SNIPPET_HEADERS = {
    "Amenities", "Brands", "Courses", "Degree Programs", "Destinations",
    "Featured Hotels", "Insurance Coverage", "Models", "Neighborhoods",
    "Service Catalog", "Services", "Shows", "Styles", "Types",
}
_MAX_HEADLINE_LEN   = 30
_MAX_DESC_LEN       = 90
_MAX_CALLOUT_LEN    = 25
_MAX_SITELINK_TEXT  = 25
_MAX_SITELINK_DESC  = 35
_MAX_SNIPPET_VALUE  = 25
_IMAGE_EXTS         = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


@dataclass
class ValidationError:
    field: str
    message: str

    def __str__(self) -> str:
        return f"[{self.field}] {self.message}"


class ConfigValidator:
    """
    Validates a client config dict loaded from a JSON file.
    Pass assets_dir to also validate that image/logo paths exist on disk.
    """

    def validate(
        self,
        config: dict,
        assets_dir: Path | None = None,
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        errors += self._check_client(config)
        errors += self._check_campaign(config)
        errors += self._check_landing_page(config)
        # New multi-ad-group flow takes precedence over legacy single-group fields
        if config.get("ad_groups"):
            errors += self._check_ad_groups(config)
        else:
            errors += self._check_ad_copy(config)
            errors += self._check_keywords(config)
        errors += self._check_extensions(config)
        errors += self._check_targeting(config)
        if assets_dir is not None:
            errors += self._check_assets(config, assets_dir)
        return errors

    # ──────────────────────────────────────────────────────
    # Section checkers
    # ──────────────────────────────────────────────────────

    def _check_client(self, config: dict) -> list[ValidationError]:
        errors = []
        client = config.get("client", {})
        if not client.get("name", "").strip():
            errors.append(ValidationError("client.name", "Required — client business name is missing"))
        cid = client.get("customer_id", "").replace("-", "")
        if not cid:
            errors.append(ValidationError("client.customer_id", "Required — Google Ads customer ID is missing"))
        elif not re.fullmatch(r"\d{10}", cid):
            errors.append(ValidationError(
                "client.customer_id",
                f"Must be 10 digits (got '{client.get('customer_id')}'). Dashes are stripped automatically.",
            ))
        return errors

    def _check_campaign(self, config: dict) -> list[ValidationError]:
        errors = []
        campaign = config.get("campaign", {})
        if not campaign.get("name", "").strip():
            errors.append(ValidationError("campaign.name", "Required — campaign name is missing"))
        budget = campaign.get("daily_budget")
        if budget is None:
            errors.append(ValidationError("campaign.daily_budget", "Required — daily budget is missing"))
        elif not isinstance(budget, (int, float)) or budget <= 0:
            errors.append(ValidationError("campaign.daily_budget", f"Must be a positive number (got {budget!r})"))
        strategy = campaign.get("bidding_strategy", "")
        if strategy not in ("maximize_conversions", "target_cpa", "manual_cpc"):
            errors.append(ValidationError(
                "campaign.bidding_strategy",
                f"Must be maximize_conversions, target_cpa, or manual_cpc (got {strategy!r})",
            ))
        if campaign.get("status", "PAUSED") != "PAUSED":
            errors.append(ValidationError("campaign.status", "Must be PAUSED — campaigns are never auto-enabled"))
        return errors

    def _check_landing_page(self, config: dict) -> list[ValidationError]:
        errors = []
        lp = config.get("landing_page", {})
        url = lp.get("final_url", "").strip()
        if not url:
            errors.append(ValidationError("landing_page.final_url", "Required — final URL is missing"))
        else:
            parsed = urlparse(url)
            if parsed.scheme not in ("https", "http"):
                errors.append(ValidationError("landing_page.final_url", f"Must start with https:// (got {url!r})"))
            if not parsed.netloc:
                errors.append(ValidationError("landing_page.final_url", f"Invalid URL format: {url!r}"))
        return errors

    def _check_ad_groups(self, config: dict) -> list[ValidationError]:
        errors = []
        ad_groups = config.get("ad_groups", [])
        if not ad_groups:
            errors.append(ValidationError("ad_groups", "Required — at least one ad group is needed"))
            return errors
        for i, ag in enumerate(ad_groups):
            p = f"ad_groups[{i}]"
            if not ag.get("name", "").strip():
                errors.append(ValidationError(f"{p}.name", "Ad group name is required"))
            # Keywords
            kw = ag.get("keywords", {})
            positives = kw.get("positive", [])
            if not positives:
                errors.append(ValidationError(f"{p}.keywords.positive", "At least one positive keyword required"))
            for j, entry in enumerate(positives):
                if not isinstance(entry, dict):
                    errors.append(ValidationError(f"{p}.keywords.positive[{j}]", "Must be an object with 'text' and 'match_type'"))
                    continue
                if not entry.get("text", "").strip():
                    errors.append(ValidationError(f"{p}.keywords.positive[{j}].text", "Keyword text is empty"))
                if entry.get("match_type", "").upper() not in _MATCH_TYPES:
                    errors.append(ValidationError(f"{p}.keywords.positive[{j}].match_type", "Must be BROAD, PHRASE, or EXACT"))
            # RSAs
            rsa_list = ag.get("rsa", [])
            if not rsa_list:
                errors.append(ValidationError(f"{p}.rsa", "At least one RSA is required"))
            for j, rsa in enumerate(rsa_list):
                rp = f"{p}.rsa[{j}]"
                headlines    = [h for h in rsa.get("headlines", [])    if isinstance(h, str) and h.strip()]
                descriptions = [d for d in rsa.get("descriptions", []) if isinstance(d, str) and d.strip()]
                if len(headlines) < 3:
                    errors.append(ValidationError(f"{rp}.headlines", f"At least 3 headlines required, got {len(headlines)}"))
                elif len(headlines) > 15:
                    errors.append(ValidationError(f"{rp}.headlines", f"Max 15 headlines, got {len(headlines)}"))
                for k, h in enumerate(headlines):
                    if len(h) > _MAX_HEADLINE_LEN:
                        errors.append(ValidationError(f"{rp}.headlines[{k}]", f"Exceeds 30 chars ({len(h)}): '{h}'"))
                if len(descriptions) < 2:
                    errors.append(ValidationError(f"{rp}.descriptions", f"At least 2 descriptions required, got {len(descriptions)}"))
                for k, d in enumerate(descriptions):
                    if len(d) > _MAX_DESC_LEN:
                        errors.append(ValidationError(f"{rp}.descriptions[{k}]", f"Exceeds 90 chars ({len(d)}): '{d[:50]}...'"))
        return errors

    def _check_ad_copy(self, config: dict) -> list[ValidationError]:
        errors = []
        copy = config.get("ad_copy", {})
        headlines = [h for h in copy.get("headlines", []) if isinstance(h, str) and h.strip()]
        descriptions = [d for d in copy.get("descriptions", []) if isinstance(d, str) and d.strip()]

        if len(headlines) < 3:
            errors.append(ValidationError(
                "ad_copy.headlines",
                f"Required — at least 3 headlines needed, got {len(headlines)}",
            ))
        if len(headlines) > 15:
            errors.append(ValidationError("ad_copy.headlines", f"Max 15 headlines, got {len(headlines)}"))
        for i, h in enumerate(headlines):
            if len(h) > _MAX_HEADLINE_LEN:
                errors.append(ValidationError(
                    f"ad_copy.headlines[{i}]",
                    f"Exceeds {_MAX_HEADLINE_LEN} chars ({len(h)}): '{h}'",
                ))

        if len(descriptions) < 2:
            errors.append(ValidationError(
                "ad_copy.descriptions",
                f"Required — at least 2 descriptions needed, got {len(descriptions)}",
            ))
        if len(descriptions) > 4:
            errors.append(ValidationError("ad_copy.descriptions", f"Max 4 descriptions, got {len(descriptions)}"))
        for i, d in enumerate(descriptions):
            if len(d) > _MAX_DESC_LEN:
                errors.append(ValidationError(
                    f"ad_copy.descriptions[{i}]",
                    f"Exceeds {_MAX_DESC_LEN} chars ({len(d)}): '{d[:50]}...'",
                ))
        return errors

    def _check_extensions(self, config: dict) -> list[ValidationError]:
        errors = []
        ext = config.get("extensions", {})

        for i, sl in enumerate(ext.get("sitelinks", [])):
            prefix = f"extensions.sitelinks[{i}]"
            lt = sl.get("link_text", "").strip()
            url = sl.get("final_url", "").strip()
            if not lt:
                errors.append(ValidationError(f"{prefix}.link_text", "Sitelink link_text is empty"))
            elif len(lt) > _MAX_SITELINK_TEXT:
                errors.append(ValidationError(f"{prefix}.link_text", f"Exceeds {_MAX_SITELINK_TEXT} chars ({len(lt)}): '{lt}'"))
            if not url:
                errors.append(ValidationError(f"{prefix}.final_url", "Sitelink final_url is empty"))
            elif not urlparse(url).netloc:
                errors.append(ValidationError(f"{prefix}.final_url", f"Invalid URL: '{url}'"))
            for desc_key in ("description1", "description2"):
                desc = sl.get(desc_key, "")
                if desc and len(desc) > _MAX_SITELINK_DESC:
                    errors.append(ValidationError(
                        f"{prefix}.{desc_key}",
                        f"Exceeds {_MAX_SITELINK_DESC} chars ({len(desc)}): '{desc}'",
                    ))

        for i, callout in enumerate(ext.get("callouts", [])):
            if len(callout) > _MAX_CALLOUT_LEN:
                errors.append(ValidationError(
                    f"extensions.callouts[{i}]",
                    f"Exceeds {_MAX_CALLOUT_LEN} chars ({len(callout)}): '{callout}'",
                ))

        for i, snippet in enumerate(ext.get("structured_snippets", [])):
            header = snippet.get("header", "")
            if header not in _SNIPPET_HEADERS:
                errors.append(ValidationError(
                    f"extensions.structured_snippets[{i}].header",
                    f"'{header}' is not a valid Google snippet header. Valid: {sorted(_SNIPPET_HEADERS)}",
                ))
            values = snippet.get("values", [])
            if len(values) < 3:
                errors.append(ValidationError(
                    f"extensions.structured_snippets[{i}].values",
                    f"Minimum 3 values required, got {len(values)}",
                ))
            for j, val in enumerate(values):
                if len(val) > _MAX_SNIPPET_VALUE:
                    errors.append(ValidationError(
                        f"extensions.structured_snippets[{i}].values[{j}]",
                        f"Exceeds {_MAX_SNIPPET_VALUE} chars ({len(val)}): '{val}'",
                    ))

        call = ext.get("call", {})
        if call and not call.get("phone_number", "").strip():
            errors.append(ValidationError("extensions.call.phone_number", "Call extension present but phone_number is empty"))

        return errors

    def _check_keywords(self, config: dict) -> list[ValidationError]:
        errors = []
        kw = config.get("keywords", {})
        positives = kw.get("positive", [])
        if not positives:
            errors.append(ValidationError("keywords.positive", "Required — at least one positive keyword is needed"))
        for i, kw_entry in enumerate(positives):
            if not isinstance(kw_entry, dict):
                errors.append(ValidationError(f"keywords.positive[{i}]", "Must be an object with 'text' and 'match_type'"))
                continue
            if not kw_entry.get("text", "").strip():
                errors.append(ValidationError(f"keywords.positive[{i}].text", "Keyword text is empty"))
            if kw_entry.get("match_type", "").upper() not in _MATCH_TYPES:
                errors.append(ValidationError(
                    f"keywords.positive[{i}].match_type",
                    f"Must be BROAD, PHRASE, or EXACT (got '{kw_entry.get('match_type')}')",
                ))
        for i, neg_entry in enumerate(kw.get("negative", [])):
            if not isinstance(neg_entry, dict):
                errors.append(ValidationError(f"keywords.negative[{i}]", "Must be an object with 'text' and 'match_type'"))
                continue
            if not neg_entry.get("text", "").strip():
                errors.append(ValidationError(f"keywords.negative[{i}].text", "Negative keyword text is empty"))
        return errors

    def _check_targeting(self, config: dict) -> list[ValidationError]:
        errors = []
        targeting = config.get("targeting", {})
        locations = targeting.get("locations", [])
        if not locations:
            errors.append(ValidationError("targeting.locations", "Required — at least one target location is needed"))
        for i, loc in enumerate(locations):
            if not isinstance(loc, dict) or not loc.get("id"):
                errors.append(ValidationError(f"targeting.locations[{i}]", "Each location must have an 'id' field"))
        for i, exc in enumerate(targeting.get("location_exclusions", [])):
            if not isinstance(exc, dict) or not exc.get("id"):
                errors.append(ValidationError(f"targeting.location_exclusions[{i}]", "Each exclusion must have an 'id' field"))
        for i, sched in enumerate(targeting.get("ad_schedule", [])):
            if sched.get("day", "").upper() not in {
                "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"
            }:
                errors.append(ValidationError(f"targeting.ad_schedule[{i}].day", f"Invalid day: '{sched.get('day')}'"))
        return errors

    def _check_assets(self, config: dict, assets_dir: Path) -> list[ValidationError]:
        errors = []
        business = config.get("business", {})

        logo_path = business.get("logo", {}).get("path", "").strip()
        if logo_path:
            full = assets_dir / logo_path
            if not full.exists():
                errors.append(ValidationError("business.logo.path", f"File not found: {full}"))
            elif full.suffix.lower() not in _IMAGE_EXTS:
                errors.append(ValidationError("business.logo.path", f"Unsupported file type '{full.suffix}'. Use JPG, PNG, GIF, or WEBP."))

        for i, img in enumerate(business.get("images", [])):
            img_path = img.get("path", "").strip()
            if not img_path:
                continue
            full = assets_dir / img_path
            if not full.exists():
                errors.append(ValidationError(f"business.images[{i}].path", f"File not found: {full}"))
            elif full.suffix.lower() not in _IMAGE_EXTS:
                errors.append(ValidationError(
                    f"business.images[{i}].path",
                    f"Unsupported file type '{full.suffix}'. Use JPG, PNG, GIF, or WEBP.",
                ))

        return errors


def format_errors(errors: list[ValidationError]) -> str:
    if not errors:
        return ""
    lines = [f"  ✗ {e}" for e in errors]
    return "\n".join(["", f"Validation failed — {len(errors)} error(s):", *lines, ""])
