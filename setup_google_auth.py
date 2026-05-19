"""Run this ONCE on your local machine to get a Google refresh token.
After running, copy the printed refresh token into your GitHub secret.

Usage:
  pip install google-auth-oauthlib
  python setup_google_auth.py
"""

import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/business.manage",
]

# Paste your OAuth client JSON here (downloaded from Google Cloud Console)
# OR save it as client_secret.json in this directory
CLIENT_SECRET_FILE = "client_secret.json"

def main():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n" + "=" * 60)
    print("SUCCESS — copy these values into your GitHub secrets:")
    print("=" * 60)
    print(f"\nGOOGLE_CLIENT_ID:\n  {creds.client_id}")
    print(f"\nGOOGLE_CLIENT_SECRET:\n  {creds.client_secret}")
    print(f"\nGOOGLE_REFRESH_TOKEN:\n  {creds.refresh_token}")
    print("\n" + "=" * 60)

    # Also save to token.json for local testing
    with open("token.json", "w") as f:
        f.write(creds.to_json())
    print("Also saved to token.json (do not commit this file)")

if __name__ == "__main__":
    main()
