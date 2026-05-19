"""Run this anytime to check if Google has approved your GBP API quota request.

Usage: python check_gbp.py

If approved, prints the GBP_LOCATION_NAME value to paste into the GitHub secret.
If still pending, says so.
"""
import os, certifi, json
os.environ["SSL_CERT_FILE"]      = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

with open("token.json") as f:
    data = json.load(f)
creds = Credentials.from_authorized_user_info(data, data.get("scopes", []))
creds.refresh(Request())
headers = {"Authorization": f"Bearer {creds.token}"}

r = requests.get(
    "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
    headers=headers, timeout=15,
)

if r.status_code == 429:
    print("STILL WAITING — Google hasn't approved the quota yet.")
    print("Check the email tied to your Google Cloud project for updates.")
    raise SystemExit

if r.status_code != 200:
    print(f"Unexpected response ({r.status_code}):")
    print(json.dumps(r.json(), indent=2))
    raise SystemExit

print("APPROVED — quota is now active.\n")
for acc in r.json().get("accounts", []):
    acc_id = acc["name"].split("/")[-1]
    print(f"Account: {acc.get('accountName')}")
    r2 = requests.get(
        f"https://mybusinessbusinessinformation.googleapis.com/v1/accounts/{acc_id}/locations",
        params={"readMask": "name,title,storefrontAddress"},
        headers=headers, timeout=15,
    )
    for loc in r2.json().get("locations", []):
        print(f"\n  Business: {loc.get('title')}")
        print(f"\n  >>> Copy this into the GBP_LOCATION_NAME GitHub secret:")
        print(f"      accounts/{acc_id}/{loc['name']}")
        print(f"\n  Then trigger a workflow run to populate GBP in the dashboard.")
