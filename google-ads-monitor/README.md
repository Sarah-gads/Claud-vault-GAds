# Google Ads Monitor

Runs daily via GitHub Actions. Checks all connected Google Ads accounts for issues, analyzes each one with Claude, and creates ClickUp tasks for the Ads team.

## What it detects

| Issue | Severity default |
|---|---|
| Ad disapprovals (active campaigns) | High |
| Billing not approved | Urgent |
| Account status not ENABLED | Urgent |
| Campaign with 0 impressions last 7 days | Medium |
| Impressions dropped ≥50% week-over-week | High |
| Conversions dropped to 0 (had conversions prior week) | High |

Claude re-classifies severity based on full context — defaults are used only when the API is unavailable.

## Setup

### 1. Google Ads API credentials

1. Enable the Google Ads API in [Google Cloud Console](https://console.cloud.google.com/).
2. Create an OAuth 2.0 Client ID (Desktop app type).
3. Apply for a [developer token](https://developers.google.com/google-ads/api/docs/first-call/dev-token) in Google Ads → Tools → API Center.
4. Generate a refresh token using the OAuth flow for your MCC account.

### 2. ClickUp

- **API token**: ClickUp → Settings → Apps → API Token
- **List ID**: Open the target list, copy the numeric ID from the URL (`/v/li/LIST_ID`)
- **Assignee ID**: Call `GET https://api.clickup.com/api/v2/team` with your token; find the user's numeric `id`

### 3. Anthropic API key

Create a key at [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys).

### 4. Add GitHub Actions secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|---|---|
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Your developer token |
| `GOOGLE_ADS_CLIENT_ID` | OAuth2 client ID |
| `GOOGLE_ADS_CLIENT_SECRET` | OAuth2 client secret |
| `GOOGLE_ADS_REFRESH_TOKEN` | OAuth2 refresh token |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | MCC account ID (digits only) |
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `CLICKUP_API_TOKEN` | `pk_...` |
| `CLICKUP_LIST_ID` | Numeric list ID |
| `CLICKUP_ASSIGNEE_ID` | Numeric ClickUp user ID |

### 5. Schedule

The workflow runs at **09:00 UTC daily**. Edit `.github/workflows/ads-monitor.yml` to change the cron schedule. You can also trigger it manually from the Actions tab.

## Local development

```bash
cd google-ads-monitor
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# fill in .env with real values
python main.py
```

## Project structure

```
google-ads-monitor/
├── main.py                          # entry point — wires everything together
├── requirements.txt
├── .env.example
├── monitor/
│   ├── ads_checker.py               # Google Ads API — issue detection
│   ├── claude_analyzer.py           # Anthropic API — severity + task copy
│   ├── clickup_client.py            # ClickUp API — task creation
│   └── dedup.py                     # fingerprint-based duplicate prevention
└── .github/
    └── workflows/
        └── ads-monitor.yml          # scheduled GitHub Actions workflow
```

## Duplicate prevention

Each issue is fingerprinted by `account_id + type + campaign_id + ad_id`. If the same fingerprint was already seen today, no new ClickUp task is created. State is persisted in `dedup_state.json` and cached between GitHub Actions runs using a rolling cache key — so re-running the workflow on the same day won't spam the team.
