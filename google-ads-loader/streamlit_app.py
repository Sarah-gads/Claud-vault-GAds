"""
MSP Campaign Loader — Local Web UI
Run:  cd google-ads-loader && streamlit run streamlit_app.py
"""
import json
import logging
import os
import re
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
from dotenv import load_dotenv

BASE_DIR    = Path(__file__).parent
CONFIGS_DIR = BASE_DIR / "client_configs"
ASSETS_DIR  = CONFIGS_DIR / "assets"
sys.path.insert(0, str(BASE_DIR))
load_dotenv(BASE_DIR / ".env")

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MSP Campaign Loader",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown("""
<style>
.block-container{padding-top:1.4rem}
.stTabs [data-baseweb="tab"]{font-size:.95rem}
.err-box{background:#fff1f0;border:1px solid #ffa39e;border-radius:6px;padding:10px 14px;margin:4px 0}
.ok-badge{color:#21c55d;font-size:.78rem}
.warn-badge{color:#f59e0b;font-size:.78rem}
.over-badge{color:#ef4444;font-size:.78rem}
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
_REQUIRED_ENV = [
    "GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",   "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    "CLICKUP_API_TOKEN", "CLICKUP_LIST_ID", "CLICKUP_ASSIGNEE_ID",
]
_BIDDING_LABELS = {
    "maximize_conversions": "Maximize Conversions",
    "target_cpa":           "Target CPA",
    "manual_cpc":           "Manual CPC (Enhanced)",
}
_SNIP_HEADERS  = [
    "Services", "Products", "Brands", "Styles", "Types", "Courses",
    "Destinations", "Featured Hotels", "Insurance Coverage",
    "Neighborhoods", "Service Catalog", "Shows",
]


# ── Session state ─────────────────────────────────────────────────────────────
def _default_ad_group(name: str = "") -> dict:
    return {
        "name": name,
        "cpc_bid": 2.0,
        "pos_kw_raw": "",
        "rsa": [
            {"headlines_raw": "", "descriptions_raw": "", "h1_pin": "", "h2_pin": "", "h3_pin": "", "d1_pin": "", "d2_pin": ""},
            {"headlines_raw": "", "descriptions_raw": "", "h1_pin": "", "h2_pin": "", "h3_pin": "", "d1_pin": "", "d2_pin": ""},
            {"headlines_raw": "", "descriptions_raw": "", "h1_pin": "", "h2_pin": "", "h3_pin": "", "d1_pin": "", "d2_pin": ""},
        ],
    }


def _init():
    defaults = {
        # Client / campaign
        "selected_account_id": "",
        "client_name": "", "customer_id": "", "campaign_name": "",
        "daily_budget": 5.0, "bidding": "maximize_conversions",
        "target_cpa": 0.0, "final_url": "",
        "neg_kw_lists": [{"name": "General Negatives", "raw": ""}],
        # Ad groups (each has name, cpc_bid, positive keywords, 3 RSAs)
        "ad_groups": [_default_ad_group()],
        # Business assets
        "business_name": "",
        "logo_file": None, "logo_saved_path": "",
        "image_files": [], "image_saved_paths": [],
        # Extensions
        "sitelinks": [{"link_text":"","final_url":"","desc1":"","desc2":""} for _ in range(4)],
        "callouts_raw": "",
        "snippet_header": "Services", "snippet_values_raw": "",
        "call_phone": "",
        # Targeting
        "location_ids_raw": "", "location_names_raw": "",
        "excl_ids_raw": "",    "excl_names_raw": "",
        "geo_query": "", "geo_results": [],
        "custom_schedule": False,
        "schedule_rows": [],
        # Claude AI analysis result
        "claude_analysis": None,
        # Upload key counter (incremented to reset the uploader widget)
        "image_upload_key": 0,
        # State
        "last_result": None, "last_log": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Helpers ───────────────────────────────────────────────────────────────────
def _char(text: str, limit: int) -> str:
    n   = len(text)
    cls = "ok-badge" if n <= limit else "over-badge"
    if limit * .9 < n <= limit:
        cls = "warn-badge"
    return f'<span class="{cls}">{"✓" if n<=limit else "✗"} {n}/{limit}</span>'


def _lines(raw: str) -> list[str]:
    return [l.strip() for l in raw.splitlines() if l.strip() and not l.strip().startswith("#")]


def _neg_raw_to_json(raw: str) -> list[dict]:
    results = []
    for line in _lines(raw):
        if line.startswith("[") and line.endswith("]"):
            results.append({"text": line[1:-1].strip(), "match_type": "EXACT"})
        elif line.startswith('"') and line.endswith('"'):
            results.append({"text": line[1:-1].strip(), "match_type": "PHRASE"})
        else:
            results.append({"text": line, "match_type": "BROAD"})
    return results


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _save_upload(uploaded_file, subdir: str, filename: str) -> Path:
    dest = ASSETS_DIR / subdir
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / filename
    path.write_bytes(uploaded_file.getbuffer())
    return path


# ── MCC account list ──────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def _load_mcc_accounts() -> list[dict]:
    """Return all active non-manager sub-accounts under the MCC."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        client = GoogleAdsClient.load_from_dict({
            "developer_token":   os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
            "client_id":         os.environ["GOOGLE_ADS_CLIENT_ID"],
            "client_secret":     os.environ["GOOGLE_ADS_CLIENT_SECRET"],
            "refresh_token":     os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
            "login_customer_id": os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
            "use_proto_plus": True,
        })
        mcc_id = os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"].replace("-", "")
        svc    = client.get_service("GoogleAdsService")
        query  = """
            SELECT
              customer_client.id,
              customer_client.descriptive_name,
              customer_client.currency_code,
              customer_client.time_zone,
              customer_client.status
            FROM customer_client
            WHERE customer_client.manager = FALSE
              AND customer_client.status = 'ENABLED'
              AND customer_client.level <= 3
            ORDER BY customer_client.descriptive_name
        """
        rows = svc.search(customer_id=mcc_id, query=query)
        accounts = []
        seen = set()
        for row in rows:
            cid = str(row.customer_client.id)
            if cid not in seen:
                seen.add(cid)
                accounts.append({
                    "id":       cid,
                    "name":     row.customer_client.descriptive_name or f"Account {cid}",
                    "currency": row.customer_client.currency_code,
                    "tz":       row.customer_client.time_zone,
                })
        return accounts
    except Exception as e:
        return [{"error": str(e)}]


# ── Geo search ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _search_geo(query: str) -> list[dict]:
    try:
        from google.ads.googleads.client import GoogleAdsClient
        client = GoogleAdsClient.load_from_dict({
            "developer_token":   os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
            "client_id":         os.environ["GOOGLE_ADS_CLIENT_ID"],
            "client_secret":     os.environ["GOOGLE_ADS_CLIENT_SECRET"],
            "refresh_token":     os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
            "login_customer_id": os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
            "use_proto_plus": True,
        })
        svc = client.get_service("GeoTargetConstantService")
        resp = svc.suggest_geo_target_constants(
            request={"locale": "en", "search_term": query}
        )
        return [
            {"id": s.geo_target_constant.id,
             "name": s.geo_target_constant.name,
             "type": s.geo_target_constant.target_type,
             "country": s.geo_target_constant.country_code}
            for s in resp.geo_target_constant_suggestions
        ][:25]
    except Exception as e:
        return [{"error": str(e)}]


# ── Build config dict ─────────────────────────────────────────────────────────
def _build_config() -> dict:
    s = st.session_state

    # ── Campaign-level negative keyword lists ─────────────────────────────────
    neg_kw_lists = [
        {
            "name": lst.get("name") or f"Negative List {i + 1}",
            "keywords": _neg_raw_to_json(lst.get("raw", "")),
        }
        for i, lst in enumerate(s.neg_kw_lists)
        if _neg_raw_to_json(lst.get("raw", ""))
    ]

    # ── Ad groups ─────────────────────────────────────────────────────────────
    ad_groups_out = []
    for i, ag in enumerate(s.ad_groups):
        pos_kws = _neg_raw_to_json(ag.get("pos_kw_raw", ""))
        rsa_list = []
        for rsa in ag.get("rsa", [{}, {}, {}]):
            hl_list = _lines(rsa.get("headlines_raw", ""))[:15]
            dl_list = _lines(rsa.get("descriptions_raw", ""))[:4]
            hl_pins = {}
            for pos, key in [("H1", "h1_pin"), ("H2", "h2_pin"), ("H3", "h3_pin")]:
                t = rsa.get(key, "")
                if t and t in hl_list:
                    hl_pins[pos] = t
            dl_pins = {}
            for pos, key in [("D1", "d1_pin"), ("D2", "d2_pin")]:
                t = rsa.get(key, "")
                if t and t in dl_list:
                    dl_pins[pos] = t
            rsa_list.append({
                "headlines":    hl_list,
                "descriptions": dl_list,
                "pins": {"headlines": hl_pins, "descriptions": dl_pins},
            })
        ad_groups_out.append({
            "name":     ag.get("name") or f"Ad Group {i + 1}",
            "cpc_bid":  float(ag.get("cpc_bid", 2.0)),
            "keywords": {"positive": pos_kws},
            "rsa":      rsa_list,
        })

    # ── Extensions ────────────────────────────────────────────────────────────
    sitelinks = [
        {
            "link_text":    sl["link_text"],
            "final_url":    sl["final_url"],
            "description1": sl["desc1"],
            "description2": sl["desc2"],
        }
        for sl in s.sitelinks
        if sl.get("link_text") and sl.get("final_url")
    ]
    callouts         = _lines(s.callouts_raw)
    snippet_values   = _lines(s.snippet_values_raw)
    structured_snippets = (
        [{"header": s.snippet_header, "values": snippet_values}] if snippet_values else []
    )

    # ── Targeting ─────────────────────────────────────────────────────────────
    def _parse_ids(raw: str) -> list[int]:
        return [int(p) for p in re.split(r"[,\s]+", raw.strip()) if p.isdigit()]
    def _parse_names(raw: str) -> list[str]:
        return [n.strip() for n in raw.split(",") if n.strip()]

    loc_ids    = _parse_ids(s.location_ids_raw)
    loc_names  = _parse_names(s.location_names_raw)
    excl_ids   = _parse_ids(s.excl_ids_raw)
    excl_names = _parse_names(s.excl_names_raw)
    schedule   = [
        {"day": r["day"], "start_hour": int(r["start"]), "end_hour": int(r["end"])}
        for r in s.schedule_rows if r.get("day")
    ] if s.custom_schedule else []

    # ── Business assets ───────────────────────────────────────────────────────
    def _rel(p: str) -> str:
        try:   return str(Path(p).relative_to(CONFIGS_DIR))
        except ValueError: return p

    logo_rel   = _rel(s.logo_saved_path) if s.logo_saved_path else ""
    image_rels = [{"name": Path(p).stem, "path": _rel(p)} for p in s.image_saved_paths]

    return {
        "client":   {"name": s.client_name, "customer_id": s.customer_id},
        "campaign": {
            "name":             s.campaign_name or f"{s.client_name} - MSP Services - Search",
            "daily_budget":     float(s.daily_budget),
            "bidding_strategy": s.bidding,
            "target_cpa":       float(s.target_cpa) if s.bidding == "target_cpa" else None,
            "status":           "PAUSED",
        },
        "landing_page": {"final_url": s.final_url.strip(), "tracking_template": ""},
        "business": {
            "name":   s.business_name,
            "logo":   {"path": logo_rel},
            "images": image_rels,
        },
        "ad_groups": ad_groups_out,
        "campaign_keywords": {"negative_lists": neg_kw_lists},
        "extensions": {
            "sitelinks":           sitelinks,
            "callouts":            callouts,
            "structured_snippets": structured_snippets,
            "call": {"phone_number": s.call_phone.strip(), "country_code": "US"},
        },
        "targeting": {
            "locations":            [{"id": i, "name": n} for i, n in
                                     zip(loc_ids, loc_names + [""]*len(loc_ids))],
            "location_exclusions":  [{"id": i, "name": n} for i, n in
                                     zip(excl_ids, excl_names + [""]*len(excl_ids))],
            "ad_schedule":          schedule,
        },
        "conversion_actions": {"inherit_account_goals": True, "action_ids": []},
        "notifications": {
            "clickup_list_id": "", "clickup_assignee_id": "",
            "discord_enabled": False, "discord_mention_role": "",
        },
    }


# ── Tab renderers ─────────────────────────────────────────────────────────────
def _tab_campaign():
    st.subheader("Campaign Setup")

    # ── Account picker ────────────────────────────────────────────────────────
    with st.spinner("Loading accounts from MCC…"):
        accounts = _load_mcc_accounts()

    if accounts and "error" in accounts[0]:
        st.error(f"Could not load MCC accounts: {accounts[0]['error']}")
        st.session_state.customer_id = st.text_input("Customer ID *", st.session_state.customer_id, placeholder="123-456-7890")
    else:
        acct_options = {f"{a['name']} ({a['id']})": a for a in accounts}
        labels       = ["— Select an account —"] + list(acct_options.keys())
        cur_label    = next(
            (lbl for lbl, a in acct_options.items() if a["id"] == st.session_state.selected_account_id),
            labels[0],
        )
        chosen_label = st.selectbox("Ad Account *", labels, index=labels.index(cur_label))
        if chosen_label != "— Select an account —":
            acct = acct_options[chosen_label]
            if acct["id"] != st.session_state.selected_account_id:
                st.session_state.selected_account_id = acct["id"]
                st.session_state.customer_id         = acct["id"]
                st.session_state.client_name         = acct["name"]
                st.rerun()
            st.caption(f"Currency: `{acct['currency']}` · Timezone: `{acct['tz']}`")
        else:
            st.session_state.selected_account_id = ""
            st.session_state.customer_id = ""
            st.session_state.client_name = ""

    c1, c2 = st.columns(2)
    with c1:
        st.session_state.campaign_name = st.text_input("Campaign Name",   st.session_state.campaign_name, placeholder="Acme IT - MSP Services - Search (auto if blank)")
        st.session_state.final_url     = st.text_input("Landing Page URL *", st.session_state.final_url,  placeholder="https://acmeit.com/managed-services")
    with c2:
        st.session_state.daily_budget = st.number_input("Daily Budget ($) *", min_value=1.0, value=st.session_state.daily_budget, step=0.50)
        bidding_label = st.selectbox("Bidding Strategy", list(_BIDDING_LABELS.values()),
            index=list(_BIDDING_LABELS.keys()).index(st.session_state.bidding))
        st.session_state.bidding = {v: k for k, v in _BIDDING_LABELS.items()}[bidding_label]
        if st.session_state.bidding == "target_cpa":
            st.session_state.target_cpa = st.number_input("Target CPA ($)", min_value=0.0, value=st.session_state.target_cpa, step=1.0)
        st.info("⚠️ Campaign will be created in **PAUSED** status. You must manually enable it after review.")

    st.divider()
    st.markdown("**Campaign-Level Negative Keyword Lists**")
    st.caption('Each list gets its own name in Google Ads · One keyword per line · `[exact]` · `"phrase"` · plain = broad')

    s = st.session_state
    to_remove_neg = None
    for ni, neg_list in enumerate(s.neg_kw_lists):
        with st.expander(f"🚫 {neg_list.get('name') or f'List {ni + 1}'}", expanded=(ni == 0)):
            nc1, nc2 = st.columns([4, 0.5])
            with nc1:
                neg_list["name"] = st.text_input(
                    "List Name", neg_list.get("name", ""),
                    key=f"neg_name_{ni}",
                    placeholder="General Negatives",
                )
            with nc2:
                st.write(""); st.write("")
                if len(s.neg_kw_lists) > 1 and st.button("✕", key=f"neg_rm_{ni}"):
                    to_remove_neg = ni
            neg_list["raw"] = st.text_area(
                "neg_kw", neg_list.get("raw", ""), height=160,
                key=f"neg_raw_{ni}",
                placeholder='free\njobs\ntraining\ncertification\nsoftware\n"it support jobs"\n[free it support]',
                label_visibility="collapsed",
            )
            count = len(_neg_raw_to_json(neg_list.get("raw", "")))
            if count:
                st.caption(f"{count} keyword(s) in this list")

    if to_remove_neg is not None:
        s.neg_kw_lists.pop(to_remove_neg)
        st.rerun()

    if st.button("＋ Add Negative List"):
        s.neg_kw_lists.append({"name": "", "raw": ""})
        st.rerun()


def _tab_ad_groups():
    st.subheader("Ad Groups")
    st.caption("Each ad group has its own keywords and 3 RSAs. Keywords: `[exact]` · `\"phrase\"` · plain = broad")

    s = st.session_state

    if st.button("＋ Add Ad Group"):
        s.ad_groups.append(_default_ad_group(f"Ad Group {len(s.ad_groups) + 1}"))
        st.rerun()

    to_remove = None
    for i, ag in enumerate(s.ad_groups):
        label = ag.get("name") or f"Ad Group {i + 1}"
        with st.expander(f"📁 {label}", expanded=(i == 0)):
            nc1, nc2, nc3 = st.columns([3, 1.5, 0.5])
            with nc1:
                ag["name"] = st.text_input(
                    "Ad Group Name", ag.get("name", ""),
                    key=f"ag_name_{i}", placeholder=f"Ad Group {i + 1} — General",
                )
            with nc2:
                ag["cpc_bid"] = st.number_input(
                    "Default CPC ($)", min_value=0.01,
                    value=float(ag.get("cpc_bid", 2.0)), step=0.10,
                    key=f"ag_cpc_{i}",
                    help="Google overrides this for Maximize Conversions / Target CPA.",
                )
            with nc3:
                st.write(""); st.write("")
                if len(s.ad_groups) > 1 and st.button("✕", key=f"ag_rm_{i}"):
                    to_remove = i

            st.divider()
            st.markdown("**Positive Keywords**")
            st.caption('One per line · `[exact]` · `"phrase"` · plain = broad')
            ag["pos_kw_raw"] = st.text_area(
                "pos_kw", ag.get("pos_kw_raw", ""), height=160,
                key=f"ag_pos_{i}",
                placeholder='"managed it services"\n[it support philadelphia]\nmanaged service provider',
                label_visibility="collapsed",
            )
            parsed_pos = _neg_raw_to_json(ag.get("pos_kw_raw", ""))
            pos_counts: dict[str, int] = {}
            for kw in parsed_pos:
                pos_counts[kw["match_type"]] = pos_counts.get(kw["match_type"], 0) + 1
            pos_summary = ", ".join(f"{v} {k.lower()}" for k, v in pos_counts.items())
            st.caption(f"{len(parsed_pos)} keyword(s) — {pos_summary}" if parsed_pos else "0 keywords")

            st.divider()
            st.markdown("**RSAs** — 3–15 headlines (≤30 chars each) · 2–4 descriptions (≤90 chars each) · first 3 headlines pinned")
            rsa_tabs = st.tabs(["RSA 1", "RSA 2", "RSA 3"])
            rsa_list = ag.get("rsa", [{}, {}, {}])
            for j, rsa_tab in enumerate(rsa_tabs):
                rsa = rsa_list[j] if j < len(rsa_list) else {}
                with rsa_tab:
                    rc1, rc2 = st.columns(2)
                    with rc1:
                        st.markdown("**Headlines** — 3 to 15 · max 30 chars")
                        rsa["headlines_raw"] = st.text_area(
                            "hl", rsa.get("headlines_raw", ""), height=240,
                            key=f"ag_{i}_rsa_{j}_hl",
                            placeholder="Managed IT Services\n24/7 Help Desk\nCall for a Free Quote\nFlat-Rate IT Support",
                            label_visibility="collapsed",
                        )
                        hl_lines = _lines(rsa.get("headlines_raw", ""))
                        for k, line in enumerate(hl_lines):
                            st.markdown(f"`H{k+1}` {line}  {_char(line, 30)}", unsafe_allow_html=True)
                        n_hl = len(hl_lines)
                        if n_hl < 3:
                            st.warning(f"Need at least 3 — you have {n_hl}")
                        elif n_hl > 15:
                            st.warning("Only first 15 will be used")

                        if hl_lines:
                            st.markdown("**📌 Pin headlines**")
                            hl_opts = [""] + hl_lines
                            for pos, key in [("H1", "h1_pin"), ("H2", "h2_pin"), ("H3", "h3_pin")]:
                                cur = rsa.get(key, "")
                                idx = hl_opts.index(cur) if cur in hl_opts else 0
                                rsa[key] = st.selectbox(
                                    pos, options=hl_opts, index=idx,
                                    key=f"ag_{i}_rsa_{j}_{key}",
                                    format_func=lambda x: "— unpinned —" if x == "" else x,
                                )

                    with rc2:
                        st.markdown("**Descriptions** — 2 to 4 · max 90 chars")
                        rsa["descriptions_raw"] = st.text_area(
                            "dl", rsa.get("descriptions_raw", ""), height=160,
                            key=f"ag_{i}_rsa_{j}_dl",
                            placeholder="Expert managed IT for small businesses. No contracts. Call today.\n24/7 help desk, cybersecurity & Microsoft 365. Flat monthly rate.",
                            label_visibility="collapsed",
                        )
                        dl_lines = _lines(rsa.get("descriptions_raw", ""))
                        for k, line in enumerate(dl_lines):
                            st.markdown(f"`D{k+1}` {line[:70]}{'…' if len(line)>70 else ''}  {_char(line, 90)}", unsafe_allow_html=True)
                        n_dl = len(dl_lines)
                        if n_dl < 2:
                            st.warning(f"Need at least 2 — you have {n_dl}")

                        if dl_lines:
                            st.markdown("**📌 Pin descriptions**")
                            dl_opts = [""] + dl_lines
                            for pos, key in [("D1", "d1_pin"), ("D2", "d2_pin")]:
                                cur = rsa.get(key, "")
                                idx = dl_opts.index(cur) if cur in dl_opts else 0
                                rsa[key] = st.selectbox(
                                    pos, options=dl_opts, index=idx,
                                    key=f"ag_{i}_rsa_{j}_{key}",
                                    format_func=lambda x: "— unpinned —" if x == "" else x,
                                )

                        st.divider()
                        st.markdown("**Preview**")
                        raw_url = s.final_url if "//" in s.final_url else "https://" + s.final_url
                        display_url = urlparse(raw_url).netloc or "yourwebsite.com"
                        h_prev = " | ".join(hl_lines[:3]) if hl_lines else "Headline 1 | Headline 2 | Headline 3"
                        d_prev = " ".join(dl_lines[:2]) if dl_lines else "Description goes here."
                        st.markdown(
                            f'<div style="font-family:Arial,sans-serif;border:1px solid #ddd;border-radius:8px;padding:14px;background:#fff">'
                            f'<div style="color:#1558d6;font-size:16px;font-weight:500">{h_prev}</div>'
                            f'<div style="color:#202124;font-size:12px;margin:3px 0">{display_url}</div>'
                            f'<div style="color:#4d5156;font-size:13px">{d_prev}</div></div>',
                            unsafe_allow_html=True,
                        )

    if to_remove is not None:
        s.ad_groups.pop(to_remove)
        st.rerun()


def _tab_extensions():
    st.subheader("Ad Extensions")

    with st.expander("🔗 Sitelinks", expanded=True):
        st.caption("Link Text max 25 chars · Descriptions max 35 chars · Full URL required")
        to_rm = None
        for i, sl in enumerate(st.session_state.sitelinks):
            c1, c2, c3, c4, c5 = st.columns([2, 2.5, 2, 2, 0.5])
            with c1:
                sl["link_text"] = st.text_input("Link Text", sl["link_text"], key=f"sl_lt_{i}", placeholder="See Our Pricing")
                st.markdown(_char(sl["link_text"], 25), unsafe_allow_html=True)
            with c2:
                sl["final_url"] = st.text_input("Final URL", sl["final_url"], key=f"sl_url_{i}", placeholder="https://acmeit.com/pricing")
            with c3:
                sl["desc1"] = st.text_input("Desc 1", sl["desc1"], key=f"sl_d1_{i}", placeholder="Flat-rate IT plans")
                st.markdown(_char(sl["desc1"], 35), unsafe_allow_html=True)
            with c4:
                sl["desc2"] = st.text_input("Desc 2", sl["desc2"], key=f"sl_d2_{i}", placeholder="No hidden fees")
                st.markdown(_char(sl["desc2"], 35), unsafe_allow_html=True)
            with c5:
                st.write(""); st.write("")
                if st.button("✕", key=f"sl_rm_{i}"): to_rm = i
        if to_rm is not None:
            st.session_state.sitelinks.pop(to_rm); st.rerun()
        if st.button("＋ Sitelink") and len(st.session_state.sitelinks) < 10:
            st.session_state.sitelinks.append({"link_text":"","final_url":"","desc1":"","desc2":""}); st.rerun()

    with st.expander("📣 Callouts", expanded=True):
        st.caption("One per line · Max 25 chars each · Recommended 8–12")
        st.session_state.callouts_raw = st.text_area("co", st.session_state.callouts_raw, height=160,
            placeholder="24/7 Help Desk Support\nNo Long-Term Contracts\nFree IT Assessment\nFlat Monthly Pricing",
            label_visibility="collapsed")
        over = [c for c in _lines(st.session_state.callouts_raw) if len(c) > 25]
        if over: st.error(f"Over 25 chars: {', '.join(over)}")

    with st.expander("📋 Structured Snippet", expanded=True):
        c1, c2 = st.columns([1, 2])
        with c1:
            st.session_state.snippet_header = st.selectbox("Header", _SNIP_HEADERS,
                index=_SNIP_HEADERS.index(st.session_state.snippet_header))
        with c2:
            st.session_state.snippet_values_raw = st.text_area("sv", st.session_state.snippet_values_raw, height=130,
                placeholder="Managed IT Support\nCybersecurity\nCloud Solutions\nMicrosoft 365\nHelp Desk Support",
                label_visibility="collapsed")
            vals = _lines(st.session_state.snippet_values_raw)
            over_vals = [v for v in vals if len(v) > 25]
            if over_vals: st.error(f"Over 25 chars: {', '.join(over_vals)}")
            elif vals: st.caption(f"{len(vals)} value(s) ready")

    with st.expander("📞 Call Extension", expanded=True):
        st.caption("Phone number that appears in your call extension.")
        st.session_state.call_phone = st.text_input(
            "Call Tracking Number",
            st.session_state.call_phone,
            placeholder="+1-215-555-0100",
        )


def _tab_assets():
    st.subheader("Business Assets")
    st.caption("Upload your prepared logo and image assets. These are attached at the campaign level.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Business Name**")
        st.session_state.business_name = st.text_input("Business name for brand extensions",
            st.session_state.business_name, placeholder="Acme IT Solutions")

        st.markdown("**Logo**")
        st.caption("Square or horizontal logo · Min 128×128 · PNG or JPG")
        logo_file = st.file_uploader("Upload logo", type=["png", "jpg", "jpeg"], key="logo_upload")
        if logo_file:
            slug = _slug(st.session_state.client_name or "client")
            saved = _save_upload(logo_file, slug, logo_file.name)
            st.session_state.logo_saved_path = str(saved)
            st.image(logo_file, width=120, caption=logo_file.name)
        elif st.session_state.logo_saved_path:
            st.caption(f"Saved: `{Path(st.session_state.logo_saved_path).name}`")

    with c2:
        st.markdown("**Ad Images**")
        st.caption("Landscape images preferred · 1200×628 · JPG or PNG · Select multiple at once or add more in batches")

        # Grid of saved images with individual remove buttons
        if st.session_state.image_saved_paths:
            to_remove_img = None
            img_cols = st.columns(3)
            for idx, p in enumerate(st.session_state.image_saved_paths):
                with img_cols[idx % 3]:
                    st.image(p, use_container_width=True, caption=Path(p).name)
                    if st.button("✕ Remove", key=f"img_rm_{idx}"):
                        to_remove_img = idx
            if to_remove_img is not None:
                st.session_state.image_saved_paths.pop(to_remove_img)
                st.rerun()
            st.caption(f"{len(st.session_state.image_saved_paths)} image(s) saved")

        # Uploader key is incremented after each batch so the widget resets
        image_files = st.file_uploader(
            "Add images", type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key=f"image_upload_{st.session_state.image_upload_key}",
        )
        if image_files:
            slug = _slug(st.session_state.client_name or "client")
            for f in image_files:
                saved = _save_upload(f, slug, f.name)
                path_str = str(saved)
                if path_str not in st.session_state.image_saved_paths:
                    st.session_state.image_saved_paths.append(path_str)
            st.session_state.image_upload_key += 1
            st.rerun()


def _tab_targeting():
    st.subheader("Targeting")
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**Target Locations**")
        st.session_state.location_ids_raw   = st.text_input("Location IDs (comma-separated)", st.session_state.location_ids_raw, placeholder="1014044, 1015198")
        st.session_state.location_names_raw = st.text_input("Location labels (reference only)", st.session_state.location_names_raw, placeholder="Philadelphia PA, Wilmington DE")

        st.markdown("**Location Exclusions**")
        st.session_state.excl_ids_raw   = st.text_input("Excluded location IDs", st.session_state.excl_ids_raw, placeholder="1022508")
        st.session_state.excl_names_raw = st.text_input("Excluded location labels", st.session_state.excl_names_raw, placeholder="Camden NJ")

        st.markdown("**Search by City**")
        qc, bc = st.columns([3, 1])
        with qc: st.session_state.geo_query = st.text_input("City/region", st.session_state.geo_query, placeholder="Philadelphia", label_visibility="collapsed")
        with bc:
            if st.button("Search", use_container_width=True) and st.session_state.geo_query:
                with st.spinner("Searching..."):
                    st.session_state.geo_results = _search_geo(st.session_state.geo_query)

        if st.session_state.geo_results:
            results = st.session_state.geo_results
            if results and "error" in results[0]:
                st.error(results[0]["error"])
            else:
                for r in results:
                    ra, rb = st.columns([3, 1])
                    with ra: st.caption(f"**{r['name']}** ({r.get('type','')}, {r.get('country','')}) — `{r['id']}`")
                    with rb:
                        if st.button("+ Target", key=f"tgt_{r['id']}"):
                            ids = st.session_state.location_ids_raw.strip()
                            if str(r["id"]) not in ids:
                                st.session_state.location_ids_raw = (ids + ", " if ids else "") + str(r["id"])
                                names = st.session_state.location_names_raw.strip()
                                st.session_state.location_names_raw = (names + ", " if names else "") + r["name"]
                            st.rerun()
                        if st.button("− Exclude", key=f"exc_{r['id']}"):
                            ids = st.session_state.excl_ids_raw.strip()
                            if str(r["id"]) not in ids:
                                st.session_state.excl_ids_raw = (ids + ", " if ids else "") + str(r["id"])
                                names = st.session_state.excl_names_raw.strip()
                                st.session_state.excl_names_raw = (names + ", " if names else "") + r["name"]
                            st.rerun()

    with c2:
        st.markdown("**Ad Schedule**")
        st.session_state.custom_schedule = st.checkbox(
            "Use custom schedule (default: Mon–Fri 7am–7pm · Sat 9am–3pm)",
            not st.session_state.custom_schedule,
        )
        st.session_state.custom_schedule = not st.session_state.custom_schedule

        if st.session_state.custom_schedule:
            days = ["MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY","SUNDAY"]
            rows = st.session_state.schedule_rows or [{"day": d, "start": 7, "end": 19} for d in days[:5]]
            st.session_state.schedule_rows = rows
            for row in rows:
                dc, sc, ec = st.columns([2, 1, 1])
                with dc: row["day"]   = st.selectbox("Day", days, index=days.index(row["day"]) if row["day"] in days else 0, key=f"sd_{row['day']}", label_visibility="collapsed")
                with sc: row["start"] = st.number_input("Start", 0, 23, int(row["start"]), key=f"ss_{row['day']}", label_visibility="collapsed")
                with ec: row["end"]   = st.number_input("End",   1, 24, int(row["end"]),   key=f"se_{row['day']}", label_visibility="collapsed")
        else:
            st.info("Mon–Fri 7:00am – 7:00pm\nSaturday 9:00am – 3:00pm\nSunday — off\n*(account timezone)*")


def _tab_launch():
    st.subheader("Review & Launch")

    config = _build_config()

    # ── Run validator ──
    from loader.validator import ConfigValidator, format_errors
    errors = ConfigValidator().validate(config, ASSETS_DIR)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Campaign**")
        st.markdown(f"- Client: `{config['client']['name'] or '—'}`")
        st.markdown(f"- Customer ID: `{config['client']['customer_id'] or '—'}`")
        st.markdown(f"- Name: `{config['campaign']['name']}`")
        st.markdown(f"- Budget: `${config['campaign']['daily_budget']:.2f}/day`")
        st.markdown(f"- Bidding: `{config['campaign']['bidding_strategy']}`")
        st.markdown(f"- Final URL: `{config['landing_page']['final_url'] or '—'}`")
        st.markdown(f"- Status: **PAUSED**")
        st.markdown(f"- Ad Groups: `{len(config.get('ad_groups', []))}`")
    with c2:
        st.markdown("**Ad Groups**")
        for ag in config.get("ad_groups", []):
            pos_count = len(ag.get("keywords", {}).get("positive", []))
            rsa_count = len([r for r in ag.get("rsa", []) if r.get("headlines")])
            st.markdown(f"**{ag['name']}**")
            st.markdown(f"- CPC `${ag['cpc_bid']:.2f}` · `{pos_count}` pos kws · `{rsa_count}` RSA(s)")
        neg_lists = config.get("campaign_keywords", {}).get("negative_lists", [])
        for nl in neg_lists:
            st.markdown(f"- 🚫 **{nl['name']}**: `{len(nl['keywords'])}` keywords")
    with c3:
        st.markdown("**Assets & Targeting**")
        sl   = config["extensions"]["sitelinks"]
        co   = config["extensions"]["callouts"]
        sn   = config["extensions"]["structured_snippets"]
        locs = config["targeting"]["locations"]
        excls = config["targeting"]["location_exclusions"]
        st.markdown(f"- Sitelinks: `{len(sl)}`")
        st.markdown(f"- Callouts: `{len(co)}`")
        st.markdown(f"- Snippets: `{'Yes — '+sn[0]['header'] if sn else 'None'}`")
        st.markdown(f"- Phone: `{config['extensions']['call']['phone_number'] or '—'}`")
        st.markdown(f"- Targets: `{', '.join(l.get('name','') or str(l.get('id','')) for l in locs) or '—'}`")
        st.markdown(f"- Exclusions: `{', '.join(l.get('name','') or str(l.get('id','')) for l in excls) or 'None'}`")
        imgs = config.get("business", {}).get("images", [])
        logo = config.get("business", {}).get("logo", {}).get("path", "")
        st.markdown(f"- Images: `{len([i for i in imgs if i.get('path')])}` | Logo: `{'Yes' if logo else 'No'}`")

    st.divider()

    if errors:
        st.error(f"**{len(errors)} validation error(s) — fix before launching:**")
        for e in errors:
            st.markdown(f'<div class="err-box">✗ <code>{e.field}</code> — {e.message}</div>', unsafe_allow_html=True)
        st.stop()

    st.success("✅ All required fields validated — ready to launch.")

    with st.expander("Preview full JSON config"):
        st.json(config)

    # ── Claude AI Quality Check ───────────────────────────────────────────────
    st.divider()
    st.markdown("#### 🤖 AI Quality Check")
    st.caption("Claude reviews your campaign for copy quality, keyword relevance, and potential issues before you launch.")

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    col_btn, col_reset = st.columns([2, 1])
    with col_btn:
        run_check = st.button("Run AI Quality Check", use_container_width=True, disabled=not anthropic_key)
    with col_reset:
        if st.session_state.claude_analysis and st.button("Clear", use_container_width=True):
            st.session_state.claude_analysis = None
            st.rerun()

    if not anthropic_key:
        st.caption("Add `ANTHROPIC_API_KEY` to your `.env` to enable AI review.")

    if run_check and anthropic_key:
        with st.spinner("Claude is reviewing your campaign…"):
            from loader.claude_assistant import ClaudeAssistant
            st.session_state.claude_analysis = ClaudeAssistant(anthropic_key).analyze(config)
        st.rerun()

    analysis = st.session_state.claude_analysis
    if analysis:
        if analysis.get("notes"):
            st.info(f"**Assessment:** {analysis['notes']}")
        if analysis.get("blocking"):
            st.error("**Blocking issues — fix before launching:**")
            for issue in analysis["blocking"]:
                st.markdown(f"- ❌ {issue}")
        if analysis.get("warnings"):
            st.warning("**Warnings:**")
            for w in analysis["warnings"]:
                st.markdown(f"- ⚠️ {w}")
        if not analysis.get("blocking") and not analysis.get("warnings"):
            st.success("✅ Claude found no issues.")

    # ── Launch ────────────────────────────────────────────────────────────────
    st.divider()
    st.warning("⚠️ The campaign will be created **PAUSED**. A ClickUp review task will be created automatically.")

    ai_block = bool(analysis and analysis.get("blocking"))
    if ai_block:
        st.error("Fix the AI-flagged blocking issues above before launching.")
    else:
        if st.button("🚀 Create Campaign (PAUSED)", type="primary", use_container_width=True):
            st.session_state.claude_analysis = None  # reset for next run
            _run_launch(config)

    result = st.session_state.last_result
    if result:
        if result.get("status") == "created_paused":
            st.success(f"✅ **{result['campaign_name']}** created and PAUSED.")
            with st.expander("📋 Setup Summary", expanded=True):
                st.code(result.get("summary", ""), language=None)
            with st.expander("ClickUp description (Markdown)"):
                st.markdown(result.get("summary_markdown", ""))
        else:
            st.error(f"❌ Failed: {result.get('error', 'Unknown error')}")
            if st.session_state.last_log:
                with st.expander("Error log"):
                    st.code("\n".join(st.session_state.last_log[-40:]))


class _LogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[str] = []
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s — %(message)s"))
    def emit(self, record):
        self.records.append(self.format(record))


def _run_launch(config: dict):
    handler = _LogHandler()
    logging.getLogger().addHandler(handler)
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from loader.campaign_builder import CampaignBuilder, ValidationFailed
        from loader.clickup_client import ClickUpClient


        with st.status("Creating campaign…", expanded=True) as status:
            st.write("Connecting to Google Ads API…")
            gc = GoogleAdsClient.load_from_dict({
                "developer_token":   os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
                "client_id":         os.environ["GOOGLE_ADS_CLIENT_ID"],
                "client_secret":     os.environ["GOOGLE_ADS_CLIENT_SECRET"],
                "refresh_token":     os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
                "login_customer_id": os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
                "use_proto_plus": True,
            })
            builder = CampaignBuilder(gc, str(BASE_DIR / "templates"), str(ASSETS_DIR))

            st.write("Running pre-flight validation…")
            st.write("Creating campaign, ad group, keywords, extensions, and assets…")
            result = builder.build(config)

            st.write("Saving config and registry…")
            _save_config(config)
            _save_registry(result)

            st.write("Creating ClickUp review task…")
            cu = ClickUpClient(os.environ["CLICKUP_API_TOKEN"], os.environ["CLICKUP_LIST_ID"], os.environ["CLICKUP_ASSIGNEE_ID"])
            cu.create_campaign_review_task_from_summary(
                campaign_name=result["campaign_name"],
                summary_markdown=result["summary_markdown"],
                client_name=result["client_name"],
            )

            status.update(label="Campaign created!", state="complete")

        st.session_state.last_result = result
        st.session_state.last_log    = handler.records

    except Exception as e:
        st.session_state.last_result = {
            "status": "error",
            "campaign_name": config["campaign"]["name"],
            "error": str(e),
        }
        st.session_state.last_log = handler.records + [traceback.format_exc()]
        st.rerun()
    finally:
        logging.getLogger().removeHandler(handler)


def _save_config(config: dict):
    CONFIGS_DIR.mkdir(exist_ok=True)
    slug = _slug(config["client"]["name"])
    path = CONFIGS_DIR / f"{slug}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def _save_registry(result: dict):
    reg_path = BASE_DIR / "campaign_registry.json"
    registry = {"campaigns": []}
    if reg_path.exists():
        try: registry = json.loads(reg_path.read_text(encoding="utf-8"))
        except Exception: pass
    registry["campaigns"].append({k: v for k, v in result.items() if k not in ("summary","summary_markdown")})
    reg_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    _init()

    st.title("🚀 MSP Campaign Loader")
    st.caption("Input your prepared assets and launch a new client campaign — all in one place.")

    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        st.error(f"Missing environment variables: `{'`, `'.join(missing)}`\n\nCopy `.env.example` → `.env` in the `google-ads-loader/` folder and add your credentials.")
        st.stop()

    tabs = st.tabs([
        "📋 Campaign", "👥 Ad Groups", "🔗 Extensions",
        "🖼️ Assets", "📍 Targeting", "🚀 Review & Launch",
    ])
    with tabs[0]: _tab_campaign()
    with tabs[1]: _tab_ad_groups()
    with tabs[2]: _tab_extensions()
    with tabs[3]: _tab_assets()
    with tabs[4]: _tab_targeting()
    with tabs[5]: _tab_launch()


if __name__ == "__main__":
    main()
