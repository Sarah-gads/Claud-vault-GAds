"""
Generates a human-readable setup summary after campaign creation.
Produces both a plain-text console version and a Markdown version for ClickUp.
"""
from datetime import datetime


_LINE = "─" * 54
_DOUBLE = "═" * 54


def generate(config: dict, result: dict) -> str:
    client_name = config["client"]["name"].upper()
    campaign_name = config["campaign"]["name"]
    customer_id = result.get("customer_id", "N/A")
    budget = config["campaign"]["daily_budget"]
    bidding = config["campaign"].get("bidding_strategy", "N/A")
    final_url = config["landing_page"]["final_url"]
    phone = config.get("extensions", {}).get("call", {}).get("phone_number", "None")

    headlines = config.get("ad_copy", {}).get("headlines", [])
    descriptions = config.get("ad_copy", {}).get("descriptions", [])

    pos_kws = config.get("keywords", {}).get("positive", [])
    neg_kws = config.get("keywords", {}).get("negative", [])

    ext = config.get("extensions", {})
    sitelinks = ext.get("sitelinks", [])
    callouts = ext.get("callouts", [])
    snippets = ext.get("structured_snippets", [])

    assets = result.get("assets", {})

    targeting = config.get("targeting", {})
    locations = targeting.get("locations", [])
    exclusions = targeting.get("location_exclusions", [])
    schedule = targeting.get("ad_schedule", [])

    loc_names = ", ".join(l.get("name", str(l.get("id", ""))) for l in locations) or "None"
    exc_names = ", ".join(l.get("name", str(l.get("id", ""))) for l in exclusions) or "None"
    sched_str = (
        "Mon–Fri 7am–7pm | Sat 9am–3pm (default)"
        if not schedule
        else f"{len(schedule)} custom window(s)"
    )

    snippet_str = "None"
    if snippets:
        s = snippets[0]
        snippet_str = f"{s['header']} ({len(s.get('values', []))} values)"

    lines = [
        "",
        _DOUBLE,
        f"  CAMPAIGN SETUP COMPLETE — {client_name}",
        _DOUBLE,
        "",
        f"  STATUS     ⚠  PAUSED — Awaiting manual review before launch",
        f"  CREATED    {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        _LINE,
        "  CAMPAIGN",
        _LINE,
        f"  Name        {campaign_name}",
        f"  Customer ID {customer_id}",
        f"  Budget      ${budget:.2f} / day",
        f"  Bidding     {bidding}",
        f"  Final URL   {final_url}",
        "",
        _LINE,
        "  AD COPY (RSA)",
        _LINE,
        f"  Headlines   {len(headlines)}  (first 3 pinned to H1 / H2 / H3)",
    ]
    for i, h in enumerate(headlines[:15]):
        pin = " 📌" if i < 3 else ""
        lines.append(f"    H{i+1:<2}{pin}  {h}")

    lines += [
        f"  Descriptions {len(descriptions)}",
    ]
    for i, d in enumerate(descriptions[:4]):
        lines.append(f"    D{i+1}   {d[:80]}{'...' if len(d) > 80 else ''}")

    lines += [
        "",
        _LINE,
        "  KEYWORDS",
        _LINE,
        f"  Positive    {len(pos_kws)} keyword(s)",
    ]
    match_summary: dict[str, int] = {}
    for kw in pos_kws:
        mt = kw.get("match_type", "UNKNOWN")
        match_summary[mt] = match_summary.get(mt, 0) + 1
    for mt, count in sorted(match_summary.items()):
        lines.append(f"              {count} × {mt}")
    lines += [
        f"  Negative    {len(neg_kws)} keyword(s) (shared list attached to campaign)",
    ]

    lines += [
        "",
        _LINE,
        "  EXTENSIONS",
        _LINE,
        f"  Sitelinks   {len(sitelinks)}",
        f"  Callouts    {len(callouts)}",
        f"  Snippets    {snippet_str}",
        f"  Call        {phone}",
    ]

    lines += [
        "",
        _LINE,
        "  ASSETS",
        _LINE,
        f"  Images      {assets.get('images', 0)}",
        f"  Logo        {'1' if assets.get('logo') else '0 (not uploaded)'}",
        f"  Business    {config.get('business', {}).get('name') or '—'}",
    ]

    lines += [
        "",
        _LINE,
        "  TARGETING",
        _LINE,
        f"  Targets     {loc_names}",
        f"  Exclusions  {exc_names}",
        f"  Schedule    {sched_str}",
    ]

    lines += [
        "",
        _LINE,
        "  NEXT STEPS",
        _LINE,
        f"  ✓ ClickUp task created: 'Review & Enable: {campaign_name}'",
        f"  ✓ Discord notification sent",
        "",
        "  1. Open Google Ads — confirm campaign is PAUSED",
        "  2. Check RSA Ad Strength in Ads UI",
        "  3. Verify location targeting on the map view",
        "  4. Confirm call tracking number is active",
        "  5. Review all assets in the Assets Library",
        "  6. Enable campaign when ready",
        "",
        _DOUBLE,
        "",
    ]

    return "\n".join(lines)


def generate_markdown(config: dict, result: dict) -> str:
    campaign_name = config["campaign"]["name"]
    customer_id = result.get("customer_id", "N/A")
    budget = config["campaign"]["daily_budget"]
    bidding = config["campaign"].get("bidding_strategy", "N/A")
    final_url = config["landing_page"]["final_url"]
    phone = config.get("extensions", {}).get("call", {}).get("phone_number", "None")

    headlines = config.get("ad_copy", {}).get("headlines", [])
    descriptions = config.get("ad_copy", {}).get("descriptions", [])
    pos_kws = config.get("keywords", {}).get("positive", [])
    neg_kws = config.get("keywords", {}).get("negative", [])
    ext = config.get("extensions", {})
    sitelinks = ext.get("sitelinks", [])
    callouts = ext.get("callouts", [])
    snippets = ext.get("structured_snippets", [])
    assets = result.get("assets", {})
    targeting = config.get("targeting", {})
    locations = targeting.get("locations", [])
    exclusions = targeting.get("location_exclusions", [])
    loc_names = ", ".join(l.get("name", str(l.get("id", ""))) for l in locations) or "None"
    exc_names = ", ".join(l.get("name", str(l.get("id", ""))) for l in exclusions) or "None"
    snippet_str = "None"
    if snippets:
        s = snippets[0]
        snippet_str = f"{s['header']} ({len(s.get('values', []))} values)"

    headline_lines = "\n".join(
        f"  - H{i+1}{'📌' if i < 3 else ''}: {h}" for i, h in enumerate(headlines[:15])
    )
    desc_lines = "\n".join(f"  - D{i+1}: {d}" for i, d in enumerate(descriptions[:4]))

    return f"""## Campaign Setup Summary — {config["client"]["name"]}

**STATUS: ⚠️ PAUSED — Do not enable until review is complete**

---

### Campaign
- **Name:** {campaign_name}
- **Customer ID:** `{customer_id}`
- **Daily Budget:** ${budget:.2f}
- **Bidding:** {bidding}
- **Final URL:** {final_url}

### Ad Copy (RSA)
**Headlines ({len(headlines)}) — first 3 pinned:**
{headline_lines}

**Descriptions ({len(descriptions)}):**
{desc_lines}

### Keywords
- **Positive:** {len(pos_kws)} keywords
- **Negative:** {len(neg_kws)} keywords (shared list)

### Extensions
- Sitelinks: {len(sitelinks)}
- Callouts: {len(callouts)}
- Structured Snippet: {snippet_str}
- Call Extension: {phone}

### Assets
- Images: {assets.get("images", 0)}
- Logo: {"Uploaded" if assets.get("logo") else "Not uploaded"}
- Business Name: {config.get("business", {}).get("name") or "—"}

### Targeting
- Locations: {loc_names}
- Exclusions: {exc_names}

---

### ✅ Review Checklist
- [ ] Campaign is PAUSED in Google Ads
- [ ] RSA Ad Strength reviewed
- [ ] Location targeting verified on map
- [ ] Call tracking number confirmed active
- [ ] Assets reviewed in Assets Library
- [ ] Budget and bidding confirmed correct
- [ ] Enable campaign when ready

*Auto-generated by MSP Campaign Loader — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*
"""
