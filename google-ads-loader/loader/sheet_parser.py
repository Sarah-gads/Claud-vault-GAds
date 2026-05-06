"""
Reads a client campaign brief from a Google Sheet and returns a campaign config dict.

Expected tabs: Campaign, Ad Groups, Keywords, Negatives, Ad Copy, Extensions, Targeting
"""
import os
import re
import logging

import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_sheets_client() -> gspread.Client:
    refresh_token = os.environ.get("GOOGLE_SHEETS_REFRESH_TOKEN", "").strip()
    client_id     = (os.environ.get("GOOGLE_SHEETS_CLIENT_ID") or os.environ.get("GOOGLE_ADS_CLIENT_ID", "")).strip()
    client_secret = (os.environ.get("GOOGLE_SHEETS_CLIENT_SECRET") or os.environ.get("GOOGLE_ADS_CLIENT_SECRET", "")).strip()
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SHEETS_SCOPES,
    )
    creds.refresh(Request())
    return gspread.Client(auth=creds)


def extract_sheet_id(url: str) -> str:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not match:
        raise ValueError("Invalid Google Sheet URL — could not extract sheet ID.")
    return match.group(1)


def _tab(spreadsheet: gspread.Spreadsheet, name: str) -> list[list]:
    """Return all rows from a tab, or [] if tab doesn't exist."""
    try:
        ws = spreadsheet.worksheet(name)
        return ws.get_all_values()
    except gspread.exceptions.WorksheetNotFound:
        logger.warning(f"Tab '{name}' not found in sheet — skipping.")
        return []


def _kv(rows: list[list]) -> dict:
    """Parse a two-column key-value tab into a dict."""
    result = {}
    for row in rows:
        if len(row) >= 2 and row[0].strip():
            result[row[0].strip().lower().replace(" ", "_")] = row[1].strip()
    return result


def parse_sheet(url: str) -> dict:
    """
    Open the Google Sheet at `url` and return a campaign config dict
    compatible with CampaignBuilder.build().
    """
    gc = get_sheets_client()
    sheet_id = extract_sheet_id(url)
    ss = gc.open_by_key(sheet_id)

    # ── Campaign tab ──────────────────────────────────────────────────────────
    camp_kv = _kv(_tab(ss, "Campaign"))
    campaign_name  = camp_kv.get("campaign_name", "")
    daily_budget   = float(camp_kv.get("daily_budget", 50) or 50)
    bidding        = camp_kv.get("bidding_strategy", "maximize_conversions").strip().lower().replace(" ", "_")
    final_url      = camp_kv.get("landing_page_url", "").strip()
    call_number    = camp_kv.get("call_number", "").strip()
    target_cpa     = float(camp_kv.get("target_cpa", 0) or 0)

    # ── Ad Groups tab ─────────────────────────────────────────────────────────
    ag_rows = _tab(ss, "Ad Groups")
    ad_group_map: dict[str, dict] = {}
    for row in ag_rows[1:]:  # skip header
        if not row or not row[0].strip():
            continue
        name    = row[0].strip()
        cpc_bid = float(row[1].strip() or 2.0) if len(row) > 1 else 2.0
        ad_group_map[name] = {"name": name, "cpc_bid": cpc_bid, "keywords": {"positive": []}, "rsa": []}

    # ── Keywords tab ──────────────────────────────────────────────────────────
    kw_rows = _tab(ss, "Keywords")
    for row in kw_rows[1:]:
        if len(row) < 2 or not row[0].strip() or not row[1].strip():
            continue
        ag_name    = row[0].strip()
        kw_text    = row[1].strip()
        match_type = (row[2].strip().upper() if len(row) > 2 and row[2].strip() else "PHRASE")
        if ag_name not in ad_group_map:
            ad_group_map[ag_name] = {"name": ag_name, "cpc_bid": 2.0, "keywords": {"positive": []}, "rsa": []}
        ad_group_map[ag_name]["keywords"]["positive"].append({"text": kw_text, "match_type": match_type})

    # ── Negatives tab ─────────────────────────────────────────────────────────
    neg_rows  = _tab(ss, "Negatives")
    neg_lists: dict[str, list] = {}
    for row in neg_rows[1:]:
        if len(row) < 2 or not row[0].strip() or not row[1].strip():
            continue
        list_name  = row[0].strip()
        kw_text    = row[1].strip()
        match_type = (row[2].strip().upper() if len(row) > 2 and row[2].strip() else "BROAD")
        neg_lists.setdefault(list_name, []).append({"text": kw_text, "match_type": match_type})

    campaign_keywords = {
        "negative_lists": [{"name": k, "keywords": v} for k, v in neg_lists.items()]
    }

    # ── Ad Copy tab ───────────────────────────────────────────────────────────
    copy_rows = _tab(ss, "Ad Copy")
    # Expected header: Ad Group | RSA # | H1 | H2 | ... | H15 | D1 | D2 | D3 | D4
    rsa_map: dict[str, dict[int, dict]] = {}
    for row in copy_rows[1:]:
        if not row or not row[0].strip():
            continue
        ag_name = row[0].strip()
        rsa_num = int(row[1].strip() or 1) if len(row) > 1 and row[1].strip().isdigit() else 1
        headlines    = [h.strip() for h in row[2:17] if len(row) > 2 and h.strip()][:15]
        descriptions = [d.strip() for d in row[17:21] if len(row) > 17 and d.strip()][:4]
        rsa_map.setdefault(ag_name, {})[rsa_num] = {
            "headlines":    headlines,
            "descriptions": descriptions,
            "pins":         {"headlines": {}, "descriptions": {}},
        }

    for ag_name, rsas in rsa_map.items():
        if ag_name not in ad_group_map:
            ad_group_map[ag_name] = {"name": ag_name, "cpc_bid": 2.0, "keywords": {"positive": []}, "rsa": []}
        sorted_rsas = [rsas[k] for k in sorted(rsas)]
        ad_group_map[ag_name]["rsa"] = sorted_rsas

    ad_groups = list(ad_group_map.values())

    # ── Extensions tab ────────────────────────────────────────────────────────
    ext_rows = _tab(ss, "Extensions")
    sitelinks, callouts, snippet_header, snippet_values = [], [], "Services", []
    for row in ext_rows[1:]:
        if not row or not row[0].strip():
            continue
        ext_type = row[0].strip().lower()
        vals = [v.strip() for v in row[1:]]
        if ext_type == "sitelink" and len(vals) >= 2:
            sitelinks.append({
                "link_text":    vals[0] if len(vals) > 0 else "",
                "final_url":    vals[1] if len(vals) > 1 else "",
                "description1": vals[2] if len(vals) > 2 else "",
                "description2": vals[3] if len(vals) > 3 else "",
            })
        elif ext_type == "callout" and vals:
            callouts.append(vals[0])
        elif ext_type == "snippet" and len(vals) >= 2:
            snippet_header = vals[0]
            snippet_values.append(vals[1])

    extensions = {
        "sitelinks": sitelinks,
        "callouts":  callouts,
        "structured_snippets": (
            [{"header": snippet_header, "values": snippet_values}] if snippet_values else []
        ),
        "call": {"phone_number": call_number, "country_code": "US"},
    }

    # ── Targeting tab ─────────────────────────────────────────────────────────
    tgt_rows = _tab(ss, "Targeting")
    locations = []
    for row in tgt_rows[1:]:
        if not row or not row[0].strip():
            continue
        loc_id   = row[0].strip()
        loc_name = row[1].strip() if len(row) > 1 else ""
        if loc_id.isdigit():
            locations.append({"id": int(loc_id), "name": loc_name})

    # ── Assemble final config ─────────────────────────────────────────────────
    return {
        "client":   {"name": "", "customer_id": ""},   # filled in by app from MCC dropdown
        "campaign": {
            "name":             campaign_name,
            "daily_budget":     daily_budget,
            "bidding_strategy": bidding,
            "target_cpa":       target_cpa if bidding == "target_cpa" else None,
            "status":           "PAUSED",
        },
        "landing_page": {"final_url": final_url, "tracking_template": ""},
        "business":     {"name": "", "logo": {"path": ""}, "images": []},
        "ad_groups":    ad_groups,
        "campaign_keywords": campaign_keywords,
        "extensions":   extensions,
        "targeting": {
            "locations":           locations,
            "location_exclusions": [],
            "ad_schedule":         [],
        },
        "conversion_actions": {"inherit_account_goals": True, "action_ids": []},
        "notifications": {
            "clickup_list_id": "", "clickup_assignee_id": "",
            "discord_enabled": False, "discord_mention_role": "",
        },
    }
