"""
One-time script to generate a Google Sheets refresh token.
Run: python setup_sheets_auth.py
Then add the printed token to your .env as GOOGLE_SHEETS_REFRESH_TOKEN
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv(Path(__file__).parent / ".env")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

client_id     = (os.environ.get("GOOGLE_SHEETS_CLIENT_ID") or os.environ.get("GOOGLE_ADS_CLIENT_ID", "")).strip()
client_secret = (os.environ.get("GOOGLE_SHEETS_CLIENT_SECRET") or os.environ.get("GOOGLE_ADS_CLIENT_SECRET", "")).strip()

if not client_id or not client_secret:
    print("ERROR: Set GOOGLE_SHEETS_CLIENT_ID and GOOGLE_SHEETS_CLIENT_SECRET in .env")
    exit(1)

flow = InstalledAppFlow.from_client_config(
    {
        "installed": {
            "client_id":     client_id,
            "client_secret": client_secret,
            "redirect_uris": ["http://localhost"],
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
        }
    },
    SCOPES,
)

creds = flow.run_local_server(port=8080, prompt="consent", access_type="offline")

print("\n" + "="*60)
print("Add this to your .env file:")
print(f"GOOGLE_SHEETS_REFRESH_TOKEN={creds.refresh_token}")
print("="*60 + "\n")
