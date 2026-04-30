"""
MSP Campaign Loader — Google Sheets Edition
Run: cd google-ads-loader && streamlit run streamlit_sheet_app.py --server.port 8502
"""
import logging
import os
import sys
import traceback
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

BASE_DIR    = Path(__file__).parent
CONFIGS_DIR = BASE_DIR / "client_configs"
ASSETS_DIR  = CONFIGS_DIR / "assets"
sys.path.insert(0, str(BASE_DIR))
load_dotenv(BASE_DIR / ".env")

st.set_page_config(
    page_title="MSP Campaign Loader",
    page_icon="🚀",
    layout="centered",
    initial_sidebar_state="collapsed",
)
st.markdown("""
<style>
.block-container{padding-top:1.6rem;max-width:780px}
.stTabs [data-baseweb="tab"]{font-size:.95rem}
.summary-box{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px 20px;margin:8px 0}
</style>
""", unsafe_allow_html=True)

_REQUIRED_ENV = [
    "GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",   "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    "CLICKUP_API_TOKEN", "CLICKUP_LIST_ID", "CLICKUP_ASSIGNEE_ID",
]


# ── MCC account loader ────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def _load_mcc_accounts() -> list[dict]:
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
            SELECT customer_client.id, customer_client.descriptive_name,
                   customer_client.currency_code, customer_client.time_zone,
                   customer_client.status
            FROM customer_client
            WHERE customer_client.manager = FALSE
              AND customer_client.status = 'ENABLED'
              AND customer_client.level <= 3
            ORDER BY customer_client.descriptive_name
        """
        rows, seen, accounts = svc.search(customer_id=mcc_id, query=query), set(), []
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


# ── Session state ─────────────────────────────────────────────────────────────
def _init():
    defaults = {
        "selected_account_id": "",
        "customer_id":  "",
        "client_name":  "",
        "sheet_url":    "",
        "sheet_config": None,
        "sheet_error":  "",
        "last_result":  None,
        "last_log":     [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Summary renderer ──────────────────────────────────────────────────────────
def _render_summary(config: dict):
    camp  = config.get("campaign", {})
    ads   = config.get("ad_groups", [])
    exts  = config.get("extensions", {})
    tgt   = config.get("targeting", {})
    negs  = config.get("campaign_keywords", {}).get("negative_lists", [])

    st.markdown("#### Campaign Summary")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Name:** {camp.get('name') or '—'}")
        st.markdown(f"**Budget:** ${camp.get('daily_budget', 0):.2f}/day")
        st.markdown(f"**Bidding:** {camp.get('bidding_strategy', '—')}")
        st.markdown(f"**URL:** {config.get('landing_page', {}).get('final_url') or '—'}")
        st.markdown(f"**Status:** PAUSED")
    with c2:
        locs = tgt.get("locations", [])
        st.markdown(f"**Locations:** {', '.join(l.get('name') or str(l.get('id','')) for l in locs) or '—'}")
        st.markdown(f"**Sitelinks:** {len(exts.get('sitelinks', []))}")
        st.markdown(f"**Callouts:** {len(exts.get('callouts', []))}")
        st.markdown(f"**Phone:** {exts.get('call', {}).get('phone_number') or '—'}")
        neg_total = sum(len(nl['keywords']) for nl in negs)
        st.markdown(f"**Negative lists:** {len(negs)} ({neg_total} keywords)")

    if ads:
        st.markdown("#### Ad Groups")
        for ag in ads:
            pos = len(ag.get("keywords", {}).get("positive", []))
            rsa = len([r for r in ag.get("rsa", []) if r.get("headlines")])
            st.markdown(f"- **{ag['name']}** — {pos} keywords · {rsa} RSA(s) · CPC ${ag.get('cpc_bid', 2):.2f}")


# ── Launch logic ──────────────────────────────────────────────────────────────
class _LogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[str] = []
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s — %(message)s"))
    def emit(self, record):
        self.records.append(self.format(record))


def _run_launch(config: dict):
    import json
    handler = _LogHandler()
    logging.getLogger().addHandler(handler)
    try:
        from google.ads.googleads.client import GoogleAdsClient
        from loader.campaign_builder import CampaignBuilder
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

            st.write("Creating campaign, ad groups, keywords, extensions…")
            result = builder.build(config)

            st.write("Saving config…")
            CONFIGS_DIR.mkdir(exist_ok=True)
            slug = config["client"]["name"].lower().replace(" ", "_")
            (CONFIGS_DIR / f"{slug}.json").write_text(
                json.dumps(config, indent=2), encoding="utf-8"
            )

            st.write("Creating ClickUp review task…")
            cu = ClickUpClient(
                os.environ["CLICKUP_API_TOKEN"],
                os.environ["CLICKUP_LIST_ID"],
                os.environ["CLICKUP_ASSIGNEE_ID"],
            )
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


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    _init()
    s = st.session_state

    st.title("🚀 MSP Campaign Loader")
    st.caption("Fill in your Google Sheet, paste the link, and launch.")

    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        st.error(f"Missing environment variables: `{'`, `'.join(missing)}`")
        st.stop()

    st.divider()

    # ── Step 1: Account ───────────────────────────────────────────────────────
    st.markdown("### 1 · Select Ad Account")
    with st.spinner("Loading accounts…"):
        accounts = _load_mcc_accounts()

    if accounts and "error" in accounts[0]:
        st.error(f"Could not load MCC accounts: {accounts[0]['error']}")
        s.customer_id = st.text_input("Customer ID", s.customer_id, placeholder="123-456-7890")
        s.client_name = st.text_input("Client Name", s.client_name)
    else:
        acct_options = {f"{a['name']} ({a['id']})": a for a in accounts}
        labels       = ["— Select an account —"] + list(acct_options.keys())
        cur_label    = next(
            (lbl for lbl, a in acct_options.items() if a["id"] == s.selected_account_id),
            labels[0],
        )
        chosen = st.selectbox("Ad Account", labels, index=labels.index(cur_label), label_visibility="collapsed")
        if chosen != "— Select an account —":
            acct = acct_options[chosen]
            # Always sync — fixes state loss after reruns
            s.selected_account_id = acct["id"]
            s.customer_id         = acct["id"]
            s.client_name         = acct["name"]
            st.caption(f"`{acct['currency']}` · {acct['tz']}")

    st.divider()

    # ── Step 2: Google Sheet ──────────────────────────────────────────────────
    st.markdown("### 2 · Paste Google Sheet URL")

    sheets_token = os.environ.get("GOOGLE_SHEETS_REFRESH_TOKEN") or os.environ.get("GOOGLE_ADS_REFRESH_TOKEN")
    if not sheets_token:
        st.warning("No Sheets token found. Run `python setup_sheets_auth.py` once to generate one.")

    col_url, col_btn = st.columns([4, 1])
    with col_url:
        s.sheet_url = st.text_input(
            "sheet_url", s.sheet_url,
            placeholder="https://docs.google.com/spreadsheets/d/...",
            label_visibility="collapsed",
        )
    with col_btn:
        load_clicked = st.button("Load Sheet", use_container_width=True, disabled=not s.sheet_url.strip())

    if load_clicked and s.sheet_url.strip():
        with st.spinner("Reading sheet…"):
            try:
                from loader.sheet_parser import parse_sheet
                config = parse_sheet(s.sheet_url.strip())
                s.sheet_config = config
                s.sheet_error  = ""
            except Exception as e:
                s.sheet_config = None
                s.sheet_error  = str(e)
        st.rerun()

    if s.sheet_error:
        st.error(f"Could not load sheet: {s.sheet_error}")

    if s.sheet_config:
        with st.expander("📋 Preview", expanded=True):
            _render_summary(s.sheet_config)

    st.divider()

    # ── Step 3: Launch ────────────────────────────────────────────────────────
    st.markdown("### 3 · Create Campaign")

    acct_ok  = bool(s.customer_id)
    sheet_ok = bool(s.sheet_config)
    ready    = acct_ok and sheet_ok

    c1, c2 = st.columns(2)
    c1.markdown(f"{'✅' if acct_ok  else '⬜'} Ad account {'selected' if acct_ok else 'not selected'}")
    c2.markdown(f"{'✅' if sheet_ok else '⬜'} Sheet {'loaded' if sheet_ok else 'not loaded'}")

    if ready:
        from loader.validator import ConfigValidator
        config = dict(s.sheet_config)
        config["client"] = {"name": s.client_name, "customer_id": s.customer_id}

        errors = ConfigValidator().validate(config, ASSETS_DIR)
        if errors:
            st.error(f"**{len(errors)} issue(s) in your sheet — fix before launching:**")
            for e in errors:
                st.markdown(f"- `{e.field}` — {e.message}")
        else:
            st.warning("⚠️ Campaign will be created **PAUSED** for manual review. A ClickUp task will be created.")

    if st.button("🚀 Create Campaign (PAUSED)", type="primary", use_container_width=True, disabled=not ready):
        _run_launch(config)

    result = s.last_result
    if result:
        if result.get("status") == "created_paused":
            st.success(f"✅ **{result['campaign_name']}** created and PAUSED.")
            with st.expander("Setup Summary", expanded=True):
                st.code(result.get("summary", ""), language=None)
        else:
            st.error(f"❌ Failed: {result.get('error', 'Unknown error')}")
            if s.last_log:
                with st.expander("Error log"):
                    st.code("\n".join(s.last_log[-40:]))


if __name__ == "__main__":
    main()
