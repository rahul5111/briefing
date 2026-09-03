"""One-time Gmail OAuth setup.

Opens a browser, you sign in and approve read-only access, and this script
prints the three secrets to add to GitHub (and to your local .env). Never
commits anything. Run this once — the refresh token stays valid until you
revoke it at https://myaccount.google.com/permissions.

Usage:
    python -m pipeline.gmail_auth path/to/credentials.json

Where credentials.json is the OAuth Desktop client secrets you download from
GCP Console → APIs & Services → Credentials.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main(creds_path: str) -> int:
    p = Path(creds_path)
    if not p.exists():
        print(f"credentials.json not found at {p}")
        print("Download it from GCP Console → APIs & Services → Credentials → "
              "OAuth 2.0 Client IDs → Download JSON")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(p), SCOPES)
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        authorization_prompt_message=(
            "\nYour browser will open. Sign in with the Gmail account you want "
            "to read newsletters from, then click Allow.\n"
        ),
        success_message=(
            "You can close this browser tab. The refresh token is printed in "
            "the terminal — do NOT share it."
        ),
    )

    client_data = json.loads(p.read_text())
    installed = client_data.get("installed") or client_data.get("web") or {}
    client_id = installed.get("client_id")
    client_secret = installed.get("client_secret")

    print("\n" + "═" * 60)
    print("Add these three values to GitHub Secrets and to your local .env:")
    print("═" * 60)
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print(f"GMAIL_CLIENT_ID={client_id}")
    print(f"GMAIL_CLIENT_SECRET={client_secret}")
    print("═" * 60)
    print("\nCommands to push to GH (paste these):\n")
    print(f"  echo -n '{creds.refresh_token}' | gh secret set GMAIL_REFRESH_TOKEN --repo rahul5111/briefing")
    print(f"  echo -n '{client_id}' | gh secret set GMAIL_CLIENT_ID --repo rahul5111/briefing")
    print(f"  echo -n '{client_secret}' | gh secret set GMAIL_CLIENT_SECRET --repo rahul5111/briefing")
    print("\nThen delete credentials.json (no longer needed) and revoke anytime at")
    print("  https://myaccount.google.com/permissions")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m pipeline.gmail_auth path/to/credentials.json")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
