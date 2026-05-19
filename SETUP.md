# Blue Moon Dashboard — Setup Guide

One-time setup. After this, the dashboard refreshes automatically every morning.

---

## Step 1 — Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project → name it "Blue Moon Dashboard"
3. Enable these APIs (search each in the API Library):
   - **Google Analytics Data API**
   - **Google Search Console API**
   - **Business Profile Performance API**
   - **My Business Business Information API**
4. Go to **APIs & Services → OAuth consent screen**
   - User type: External
   - App name: Blue Moon Dashboard
   - Add your email as a test user
5. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
   - Application type: Desktop app
   - Download the JSON file → save as `client_secret.json` in this folder

---

## Step 2 — Get your Google refresh token (run once locally)

```bash
pip install -r requirements.txt
python setup_google_auth.py
```

A browser window opens → sign in with your Google account → approve access.
Copy the three values printed in the terminal.

---

## Step 3 — Find your Google property IDs

**GA4 Property ID:**
- Go to [analytics.google.com](https://analytics.google.com) → Admin → Property Settings
- Copy the numeric ID and format it as `properties/XXXXXXXXX`

**Search Console site URL:**
- Go to [search.google.com/search-console](https://search.google.com/search-console)
- Copy the exact URL shown for your property (include trailing slash)

**Google Business Profile location name:**
- Call this URL in your browser (replace with your access token):
  `https://mybusinessbusinessinformation.googleapis.com/v1/accounts`
- Then:
  `https://mybusinessbusinessinformation.googleapis.com/v1/accounts/ACCOUNT_ID/locations`
- Format: `accounts/XXXXXXXXXX/locations/XXXXXXXXXX`

---

## Step 4 — Facebook & Instagram IDs

You already have a Facebook Developer App. You need:

**FB_PAGE_ID** — go to your Facebook Page → About → Page ID

**FB_PAGE_ACCESS_TOKEN** — long-lived Page Access Token:
1. Go to [developers.facebook.com/tools/explorer](https://developers.facebook.com/tools/explorer)
2. Select your app → generate User Token with permissions:
   - `pages_read_engagement`
   - `pages_show_list`
   - `read_insights`
   - `instagram_basic`
   - `instagram_manage_insights`
3. Exchange for a long-lived token:
   `GET https://graph.facebook.com/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_TOKEN`
4. Then get your Page Access Token (never expires):
   `GET https://graph.facebook.com/me/accounts?access_token=LONG_LIVED_USER_TOKEN`

**IG_USER_ID** — Instagram Business Account ID:
`GET https://graph.facebook.com/PAGE_ID?fields=instagram_business_account&access_token=PAGE_TOKEN`

---

## Step 5 — GitHub setup

1. Create a new **private** GitHub repo (e.g. `blue-moon-dashboard`)
2. Push this folder to it:
   ```bash
   git init
   git add .
   git commit -m "Initial dashboard setup"
   git remote add origin https://github.com/YOUR_USERNAME/blue-moon-dashboard.git
   git push -u origin main
   ```
3. Go to repo **Settings → Secrets and variables → Actions → New repository secret**
   Add all 9 secrets (values from steps 2–4):
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REFRESH_TOKEN`
   - `GA4_PROPERTY_ID`
   - `GSC_SITE_URL`
   - `GBP_LOCATION_NAME`
   - `FB_PAGE_ID`
   - `FB_PAGE_ACCESS_TOKEN`
   - `IG_USER_ID`

4. Go to **Settings → Pages → Source** → set to `gh-pages` branch

---

## Step 6 — Run it

Go to **Actions tab → Refresh dashboard → Run workflow**.

In ~30 seconds your dashboard is live at:
`https://YOUR_USERNAME.github.io/blue-moon-dashboard/`

After that it refreshes automatically at 6am every morning.

---

## Refreshing Facebook tokens

The long-lived Page Access Token for a Facebook Page **never expires** as long as your app stays active.
If it ever stops working, repeat Step 4 to get a new one and update the GitHub secret.
