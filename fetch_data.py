"""Blue Moon Wellness Spa — Dashboard Data Fetcher
Pulls GA4, Search Console, Google Business Profile, Facebook, and
Instagram data for the last 30 days and writes index.html.
"""

import json
import os
import sys
from datetime import datetime, timedelta

import certifi
os.environ.setdefault("SSL_CERT_FILE",                  certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE",             certifi.where())
os.environ.setdefault("GRPC_DEFAULT_SSL_ROOTS_FILE_PATH", certifi.where())

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, OrderBy, RunReportRequest,
)

# ── Config ────────────────────────────────────────────────────────────────────

GA4_PROPERTY_ID    = os.environ["GA4_PROPERTY_ID"]       # e.g. "properties/123456789"
GSC_SITE_URL       = os.environ["GSC_SITE_URL"]          # e.g. "https://www.bluemoonwellnessspa.com.au/"
GBP_LOCATION_NAME  = os.environ.get("GBP_LOCATION_NAME", "")  # optional, leave blank if quota not approved
GOOGLE_CLIENT_ID     = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REFRESH_TOKEN = os.environ["GOOGLE_REFRESH_TOKEN"]
FB_PAGE_ID           = os.environ["FB_PAGE_ID"]
FB_PAGE_ACCESS_TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
IG_USER_ID           = os.environ["IG_USER_ID"]

TODAY      = datetime.utcnow()
START_DT   = TODAY - timedelta(days=30)
START_DATE = START_DT.strftime("%Y-%m-%d")
END_DATE   = TODAY.strftime("%Y-%m-%d")

def fmt_day(dt: datetime) -> str:
    return f"{dt.strftime('%b')} {dt.day}"

DISPLAY_DATE = fmt_day(TODAY)

# ── Google auth ───────────────────────────────────────────────────────────────

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/business.manage",
]

def get_google_creds() -> Credentials:
    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=GOOGLE_SCOPES,
    )
    creds.refresh(Request())
    return creds

# ── GA4 ───────────────────────────────────────────────────────────────────────

def fetch_ga4(creds: Credentials):
    client = BetaAnalyticsDataClient(credentials=creds, transport="rest")

    # Traffic by source/medium
    resp = client.run_report(RunReportRequest(
        property=GA4_PROPERTY_ID,
        date_ranges=[DateRange(start_date=START_DATE, end_date=END_DATE)],
        dimensions=[Dimension(name="sessionSource"), Dimension(name="sessionMedium")],
        metrics=[Metric(name="sessions")],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=20,
    ))

    raw: dict[str, int] = {}
    for row in resp.rows:
        src = row.dimension_values[0].value
        med = row.dimension_values[1].value
        n   = int(row.metric_values[0].value)
        key = f"{src} / {med}"
        raw[key] = raw.get(key, 0) + n

    total = sum(raw.values())
    top7  = sorted(raw.items(), key=lambda x: -x[1])[:7]
    traffic = [{"s": k, "n": v} for k, v in top7]

    # Bookings / conversion events
    resp2 = client.run_report(RunReportRequest(
        property=GA4_PROPERTY_ID,
        date_ranges=[DateRange(start_date=START_DATE, end_date=END_DATE)],
        dimensions=[Dimension(name="eventName")],
        metrics=[Metric(name="eventCount")],
    ))
    bookings = 0
    for row in resp2.rows:
        ev = row.dimension_values[0].value.lower()
        if any(k in ev for k in ("purchase", "booking_complete", "checkout_success", "conversion")):
            bookings += int(row.metric_values[0].value)

    return traffic, total, bookings

# ── Search Console ────────────────────────────────────────────────────────────

def fetch_search_console(creds: Credentials):
    svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    resp = svc.searchanalytics().query(
        siteUrl=GSC_SITE_URL,
        body={
            "startDate": START_DATE,
            "endDate": END_DATE,
            "dimensions": ["query"],
            "rowLimit": 50,
            "dataState": "final",
        },
    ).execute()

    with_clicks, opps = [], []
    for row in resp.get("rows", []):
        q   = row["keys"][0]
        imp = round(row.get("impressions", 0))
        cl  = round(row.get("clicks", 0))
        pos = round(row.get("position", 0), 2)

        if cl > 0:
            with_clicks.append({"q": q, "imp": imp, "cl": cl, "pos": pos})
        elif imp >= 5:
            label = "Almost page 1 — push with content" if pos <= 15 else "Build more content for this term"
            opps.append({"q": q, "imp": imp, "pos": pos, "label": label})

    with_clicks.sort(key=lambda r: -r["cl"])
    opps.sort(key=lambda r: -r["imp"])
    return with_clicks[:20], opps[:10]

# ── Google Business Profile ───────────────────────────────────────────────────

GBP_METRICS = [
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
    "WEBSITE_CLICKS",
    "BUSINESS_DIRECTION_REQUESTS",
]

def fetch_gbp(creds: Credentials):
    if not GBP_LOCATION_NAME:
        empty = [{"d": fmt_day(TODAY - timedelta(days=i)), "i": 0, "wc": 0, "dr": 0}
                 for i in range(30, -1, -1)]
        return empty, 0, 0, 0, "—"

    headers = {"Authorization": f"Bearer {creds.token}"}
    base_url = (
        f"https://businessprofileperformance.googleapis.com/v1"
        f"/{GBP_LOCATION_NAME}:getDailyMetricsTimeSeries"
    )

    daily: dict[str, dict] = {}

    for metric in GBP_METRICS:
        params = {
            "dailyMetric": metric,
            "dailyRange.startDate.year":  START_DT.year,
            "dailyRange.startDate.month": START_DT.month,
            "dailyRange.startDate.day":   START_DT.day,
            "dailyRange.endDate.year":    TODAY.year,
            "dailyRange.endDate.month":   TODAY.month,
            "dailyRange.endDate.day":     TODAY.day,
        }
        r = requests.get(base_url, headers=headers, params=params, timeout=15)
        if r.status_code != 200:
            print(f"  GBP warning: {metric} → {r.status_code}", file=sys.stderr)
            continue

        for pt in r.json().get("timeSeries", {}).get("datedValues", []):
            d   = pt.get("date", {})
            key = f"{d.get('year',0)}-{d.get('month',1):02d}-{d.get('day',1):02d}"
            val = int(pt.get("value") or 0)
            if key not in daily:
                daily[key] = {"i": 0, "wc": 0, "dr": 0}
            if "IMPRESSIONS" in metric:
                daily[key]["i"] += val
            elif metric == "WEBSITE_CLICKS":
                daily[key]["wc"] += val
            elif metric == "BUSINESS_DIRECTION_REQUESTS":
                daily[key]["dr"] += val

    gmb_list = []
    for offset in range(30, -1, -1):
        day = TODAY - timedelta(days=offset)
        key = day.strftime("%Y-%m-%d")
        vals = daily.get(key, {"i": 0, "wc": 0, "dr": 0})
        gmb_list.append({"d": fmt_day(day), **vals})

    total_imp = sum(r["i"]  for r in gmb_list)
    total_wc  = sum(r["wc"] for r in gmb_list)
    total_dr  = sum(r["dr"] for r in gmb_list)
    best      = max(gmb_list, key=lambda r: r["i"], default={"d": "—", "i": 0})

    return gmb_list, total_imp, total_wc, total_dr, best["d"]

# ── Facebook ──────────────────────────────────────────────────────────────────

FB_BASE = "https://graph.facebook.com/v19.0"

def fetch_facebook():
    tok = FB_PAGE_ACCESS_TOKEN

    # Posts with per-post unique impressions (page-level aggregate metrics were
    # deprecated by Meta in 2024 — we sum per-post values to get daily totals)
    r = requests.get(f"{FB_BASE}/{FB_PAGE_ID}/posts", params={
        "fields": (
            "message,created_time,permalink_url,"
            "insights.metric(post_impressions_unique){values},"
            "reactions.summary(total_count),"
            "shares"
        ),
        "since": (TODAY - timedelta(days=29)).strftime("%Y-%m-%d"),
        "access_token": tok,
        "limit": 50,
    }, timeout=15)

    posts = []
    daily_imps: dict[str, int] = {}

    if r.status_code == 200:
        for post in r.json().get("data", []):
            created = post.get("created_time", "")[:10]
            imp = 0
            for ins in post.get("insights", {}).get("data", []):
                for v in ins.get("values", []):
                    imp = max(imp, int(v.get("value", 0)))

            if created:
                daily_imps[created] = daily_imps.get(created, 0) + imp

            react  = post.get("reactions", {}).get("summary", {}).get("total_count", 0)
            shares = post.get("shares", {}).get("count", 0)
            permalink = post.get("permalink_url", "")
            post_type = "video" if "/reel/" in permalink or "/videos/" in permalink else "photo"

            posts.append({
                "date":    fmt_day(datetime.strptime(created, "%Y-%m-%d")) if created else "",
                "type":    post_type,
                "imp":     imp,
                "react":   react,
                "shares":  shares,
                "caption": (post.get("message") or "")[:220],
                "url":     permalink,
            })

    posts.sort(key=lambda p: -p["imp"])

    fb_daily = []
    for offset in range(30, -1, -1):
        day = TODAY - timedelta(days=offset)
        key = day.strftime("%Y-%m-%d")
        fb_daily.append({"d": fmt_day(day), "v": daily_imps.get(key, 0)})

    total_imp = sum(d["v"] for d in fb_daily)
    return fb_daily, posts[:7], total_imp

# ── Instagram ─────────────────────────────────────────────────────────────────

def fetch_instagram():
    tok = FB_PAGE_ACCESS_TOKEN

    # Follower count
    r = requests.get(f"{FB_BASE}/{IG_USER_ID}", params={
        "fields": "followers_count",
        "access_token": tok,
    }, timeout=15)
    followers = r.json().get("followers_count", 0) if r.status_code == 200 else 0

    # Daily reach
    r = requests.get(f"{FB_BASE}/{IG_USER_ID}/insights", params={
        "metric": "reach",
        "period": "day",
        "since": (TODAY - timedelta(days=29)).strftime("%Y-%m-%d"),
        "until": TODAY.strftime("%Y-%m-%d"),
        "access_token": tok,
    }, timeout=15)

    daily_reach: dict[str, int] = {}
    if r.status_code == 200:
        for entry in r.json().get("data", []):
            if entry.get("name") == "reach":
                for v in entry.get("values", []):
                    daily_reach[v["end_time"][:10]] = v.get("value", 0)

    ig_daily = []
    for offset in range(30, -1, -1):
        day = TODAY - timedelta(days=offset)
        key = day.strftime("%Y-%m-%d")
        ig_daily.append({"d": fmt_day(day), "r": daily_reach.get(key, 0)})

    total_reach = sum(d["r"] for d in ig_daily)
    best = max(ig_daily, key=lambda r: r["r"], default={"d": "—", "r": 0})

    # Media (posts/reels)
    r = requests.get(f"{FB_BASE}/{IG_USER_ID}/media", params={
        "fields": "caption,like_count,comments_count,timestamp,media_type,permalink",
        "since": (TODAY - timedelta(days=29)).strftime("%Y-%m-%d"),
        "access_token": tok,
        "limit": 20,
    }, timeout=15)

    ig_posts = []
    total_likes = 0
    if r.status_code == 200:
        for post in r.json().get("data", []):
            ts      = post.get("timestamp", "")[:10]
            likes   = post.get("like_count", 0)
            comments= post.get("comments_count", 0)
            total_likes += likes
            media_type = post.get("media_type", "IMAGE")
            if media_type == "VIDEO":
                media_type = "REEL"
            ig_posts.append({
                "date":     fmt_day(datetime.strptime(ts, "%Y-%m-%d")) if ts else "",
                "type":     media_type,
                "likes":    likes,
                "comments": comments,
                "caption":  (post.get("caption") or "")[:220],
                "url":      post.get("permalink", ""),
            })

    ig_posts.sort(key=lambda p: -(p["likes"] + p["comments"] * 2))
    return followers, ig_daily, ig_posts[:6], total_reach, total_likes, best

# ── HTML generation ───────────────────────────────────────────────────────────

def generate_html(d: dict) -> str:
    ga4_js     = json.dumps(d["ga4_traffic"])
    ig_dly_js  = json.dumps(d["ig_daily"])
    ig_post_js = json.dumps(d["ig_posts"])
    fb_dly_js  = json.dumps(d["fb_daily"])
    fb_post_js = json.dumps(d["fb_posts"])
    gmb_js     = json.dumps(d["gmb_daily"])
    seo_c_js   = json.dumps(d["seo_clicks"])
    seo_o_js   = json.dumps(d["seo_opps"])

    best_ig = d["ig_best_day"]
    top_fb  = d["fb_posts"][0] if d["fb_posts"] else {}
    top_fb_label = (top_fb.get("caption") or "—")[:22] + "…"
    top_fb_imp   = top_fb.get("imp", 0)
    top_fb_date  = top_fb.get("date", "—")

    milestone_sub = ("🌙 Milestone reached!" if d["ig_followers"] >= 1000
                     else f"{1000 - d['ig_followers']} from 1,000 🌙")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Blue Moon Wellness Spa — Marketing Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
:root{{--moon:#C8B8A2;--deep:#1A1714;--card:#272320;--border:rgba(200,184,162,0.13);--text:#EDE8E2;--muted:rgba(237,232,226,0.45);--green:#7FAF8A;--amber:#C4924A;--rose:#C47A7A;--blue:#7A9DC4;--purple:#9B8FC4;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:var(--deep);color:var(--text);font-family:'DM Sans',sans-serif;font-weight:300;padding:2rem;}}
header{{display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:2rem;padding-bottom:1.5rem;border-bottom:.5px solid var(--border);}}
.brand h1{{font-family:'Cormorant Garamond',serif;font-weight:300;font-size:1.9rem;letter-spacing:.04em;color:var(--moon);}}
.brand p{{font-size:11px;color:var(--muted);margin-top:4px;letter-spacing:.08em;text-transform:uppercase;}}
.updated{{font-size:11px;color:var(--muted);text-align:right;line-height:1.6;}}
.updated strong{{color:var(--moon);display:block;font-size:13px;font-weight:500;}}
.tabs{{display:flex;gap:4px;margin-bottom:1.5rem;flex-wrap:wrap;}}
.tab{{background:none;border:.5px solid var(--border);color:var(--muted);font-family:'DM Sans',sans-serif;font-size:11px;padding:6px 14px;border-radius:20px;cursor:pointer;transition:all .2s;}}
.tab.active{{background:var(--moon);border-color:var(--moon);color:var(--deep);font-weight:500;}}
.panel{{display:none;}}.panel.active{{display:block;}}
.section-label{{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:.75rem;margin-top:1.75rem;}}
.section-label:first-child{{margin-top:0;}}
.metrics-row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;}}
.metric-card{{background:var(--card);border:.5px solid var(--border);border-radius:10px;padding:1rem 1.1rem;}}
.lbl{{font-size:10px;color:var(--muted);letter-spacing:.05em;text-transform:uppercase;margin-bottom:6px;}}
.val{{font-family:'Cormorant Garamond',serif;font-size:2rem;font-weight:300;color:var(--moon);line-height:1;}}
.sub{{font-size:10px;color:var(--muted);margin-top:5px;}}
.delta{{font-size:10px;padding:2px 6px;border-radius:4px;margin-left:6px;font-weight:500;vertical-align:middle;}}
.up{{background:rgba(127,175,138,0.15);color:var(--green);}}
.dn{{background:rgba(196,122,122,0.15);color:var(--rose);}}
.charts-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:.75rem;}}
@media(max-width:680px){{.charts-grid{{grid-template-columns:1fr;}}}}
.chart-card{{background:var(--card);border:.5px solid var(--border);border-radius:10px;padding:1.1rem;}}
.chart-card.wide{{grid-column:1/-1;}}
.chart-title{{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin-bottom:.9rem;}}
.chart-wrap{{position:relative;width:100%;height:190px;}}
.chart-wrap.tall{{height:230px;}}
.legend{{display:flex;flex-wrap:wrap;gap:10px;margin-top:8px;font-size:11px;color:var(--muted);}}
.legend span{{display:flex;align-items:center;gap:5px;}}
.swatch{{width:9px;height:9px;border-radius:2px;flex-shrink:0;}}
.seo-wrap{{background:var(--card);border:.5px solid var(--border);border-radius:10px;overflow:hidden;margin-top:.75rem;}}
table{{width:100%;border-collapse:collapse;font-size:12px;}}
thead th{{text-align:left;color:var(--muted);font-weight:400;font-size:10px;letter-spacing:.06em;text-transform:uppercase;padding:8px 12px;border-bottom:.5px solid var(--border);}}
tbody td{{padding:8px 12px;border-bottom:.5px solid rgba(200,184,162,0.05);}}
tbody tr:last-child td{{border-bottom:none;}}
tbody tr:hover td{{background:rgba(200,184,162,0.03);}}
.tag{{display:inline-block;font-size:9px;padding:2px 7px;border-radius:20px;font-weight:500;}}
.tag-green{{background:rgba(127,175,138,0.15);color:var(--green);border:.5px solid rgba(127,175,138,0.3);}}
.tag-amber{{background:rgba(196,146,74,0.15);color:var(--amber);border:.5px solid rgba(196,146,74,0.3);}}
.tag-rose{{background:rgba(196,122,122,0.15);color:var(--rose);border:.5px solid rgba(196,122,122,0.3);}}
.tag-blue{{background:rgba(122,157,196,0.15);color:var(--blue);border:.5px solid rgba(122,157,196,0.3);}}
.posts-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-top:.75rem;}}
.post-card{{background:var(--card);border:.5px solid var(--border);border-radius:10px;padding:.9rem 1.1rem;display:flex;flex-direction:column;gap:6px;}}
.post-meta{{display:flex;align-items:center;justify-content:space-between;}}
.post-caption{{font-size:11px;color:var(--muted);line-height:1.5;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;}}
.post-stats{{display:flex;gap:12px;font-size:11px;color:var(--muted);}}
.post-stats strong{{color:var(--text);}}
.post-card a{{font-size:10px;color:var(--moon);text-decoration:none;}}
footer{{margin-top:2.5rem;padding-top:1.2rem;border-top:.5px solid var(--border);display:flex;justify-content:space-between;font-size:10px;color:var(--muted);}}
</style>
</head>
<body>
<header>
  <div class="brand"><h1>Blue Moon Wellness Spa</h1><p>Marketing performance dashboard · Camden NSW</p></div>
  <div class="updated"><strong>Last 30 days</strong>Refreshed {d["display_date"]}</div>
</header>
<div class="tabs">
  <button class="tab active" onclick="showTab('overview',this)">Overview</button>
  <button class="tab" onclick="showTab('website',this)">Website</button>
  <button class="tab" onclick="showTab('instagram',this)">Instagram</button>
  <button class="tab" onclick="showTab('facebook',this)">Facebook</button>
  <button class="tab" onclick="showTab('google',this)">Google</button>
  <button class="tab" onclick="showTab('seo',this)">Search rankings</button>
</div>

<div class="panel active" id="panel-overview">
  <div class="section-label">All channels at a glance</div>
  <div class="metrics-row">
    <div class="metric-card"><div class="lbl">Website sessions</div><div class="val">{d["total_sessions"]:,}</div><div class="sub">All sources · 30 days</div></div>
    <div class="metric-card"><div class="lbl">Bookings completed</div><div class="val">{d["bookings"]}</div><div class="sub">Checkout successes</div></div>
    <div class="metric-card"><div class="lbl">IG total reach</div><div class="val">{d["ig_reach"]:,}</div><div class="sub">30 days</div></div>
    <div class="metric-card"><div class="lbl">IG followers</div><div class="val">{d["ig_followers"]:,}</div><div class="sub">{milestone_sub}</div></div>
    <div class="metric-card"><div class="lbl">GBP impressions</div><div class="val">{d["gmb_impressions"]:,}</div><div class="sub">Google Search &amp; Maps</div></div>
    <div class="metric-card"><div class="lbl">GBP direction requests</div><div class="val">{d["gmb_directions"]}</div><div class="sub">People navigating to you</div></div>
  </div>
</div>

<div class="panel" id="panel-website">
  <div class="section-label">Traffic</div>
  <div class="metrics-row">
    <div class="metric-card"><div class="lbl">Total sessions</div><div class="val">{d["total_sessions"]:,}</div><div class="sub">All sources</div></div>
    <div class="metric-card"><div class="lbl">Bookings completed</div><div class="val">{d["bookings"]}</div><div class="sub">Check-out success</div></div>
  </div>
  <div class="charts-grid">
    <div class="chart-card wide"><div class="chart-title">Sessions by source</div><div class="chart-wrap"><canvas id="trafficChart"></canvas></div><div class="legend" id="trafficLegend"></div></div>
  </div>
</div>

<div class="panel" id="panel-instagram">
  <div class="section-label">Profile</div>
  <div class="metrics-row">
    <div class="metric-card"><div class="lbl">Followers</div><div class="val">{d["ig_followers"]:,}</div><div class="sub">{milestone_sub}</div></div>
    <div class="metric-card"><div class="lbl">Total reach</div><div class="val">{d["ig_reach"]:,}</div><div class="sub">30 days</div></div>
    <div class="metric-card"><div class="lbl">Total likes</div><div class="val">{d["ig_likes"]:,}</div></div>
    <div class="metric-card"><div class="lbl">Best day</div><div class="val" style="font-size:1.1rem;padding-top:5px">{best_ig["d"]}</div><div class="sub">{best_ig["r"]:,} reach</div></div>
  </div>
  <div class="charts-grid"><div class="chart-card wide"><div class="chart-title">Daily reach</div><div class="chart-wrap"><canvas id="igReachChart"></canvas></div></div></div>
  <div class="section-label">Top posts by engagement</div>
  <div class="posts-grid" id="igPostsGrid"></div>
</div>

<div class="panel" id="panel-facebook">
  <div class="section-label">Page performance</div>
  <div class="metrics-row">
    <div class="metric-card"><div class="lbl">Total impressions</div><div class="val">{d["fb_impressions"]:,}</div><div class="sub">30 days</div></div>
    <div class="metric-card"><div class="lbl">Total reactions</div><div class="val" id="fb-react"></div></div>
    <div class="metric-card"><div class="lbl">Total shares</div><div class="val" id="fb-shares"></div></div>
    <div class="metric-card"><div class="lbl">Top post</div><div class="val" style="font-size:1rem;padding-top:5px">{top_fb_label}</div><div class="sub">{top_fb_imp:,} impressions · {top_fb_date}</div></div>
  </div>
  <div class="charts-grid"><div class="chart-card wide"><div class="chart-title">Daily organic impressions</div><div class="chart-wrap tall"><canvas id="fbChart"></canvas></div></div></div>
  <div class="section-label">Top posts by impressions</div>
  <div class="posts-grid" id="fbPostsGrid"></div>
</div>

<div class="panel" id="panel-google">
  <div class="section-label">Google My Business</div>
  <div class="metrics-row">
    <div class="metric-card"><div class="lbl">Total impressions</div><div class="val">{d["gmb_impressions"]:,}</div><div class="sub">Search &amp; Maps</div></div>
    <div class="metric-card"><div class="lbl">Website clicks</div><div class="val">{d["gmb_clicks"]:,}</div></div>
    <div class="metric-card"><div class="lbl">Direction requests</div><div class="val">{d["gmb_directions"]}</div></div>
    <div class="metric-card"><div class="lbl">Best day</div><div class="val" style="font-size:1.1rem;padding-top:5px">{d["gmb_best_day"]}</div></div>
  </div>
  <div class="charts-grid">
    <div class="chart-card"><div class="chart-title">GBP impressions — daily</div><div class="chart-wrap"><canvas id="gmbChart"></canvas></div></div>
    <div class="chart-card"><div class="chart-title">Website clicks &amp; directions</div><div class="chart-wrap"><canvas id="gmbActionsChart"></canvas></div></div>
  </div>
</div>

<div class="panel" id="panel-seo">
  <div class="section-label">Search rankings — terms with clicks</div>
  <div class="seo-wrap"><table><thead><tr><th>Search term</th><th style="text-align:right">Impr.</th><th style="text-align:right">Clicks</th><th style="text-align:right">Position</th><th>Status</th></tr></thead><tbody id="seoBody"></tbody></table></div>
  <div class="section-label">Opportunity terms — 0 clicks</div>
  <div class="seo-wrap"><table><thead><tr><th>Search term</th><th style="text-align:right">Impr.</th><th style="text-align:right">Position</th><th>Action</th></tr></thead><tbody id="oppBody"></tbody></table></div>
</div>

<footer><span>Blue Moon Wellness Spa · Camden NSW</span><span>Refreshed {d["display_date"]}</span></footer>

<script>
function showTab(id,el){{document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));document.getElementById('panel-'+id).classList.add('active');el.classList.add('active');setTimeout(()=>window.dispatchEvent(new Event('resize')),50);}}
const C={{moon:'#C8B8A2',green:'#7FAF8A',amber:'#C4924A',rose:'#C47A7A',blue:'#7A9DC4',grid:'rgba(200,184,162,0.07)',txt:'rgba(237,232,226,0.38)'}};
const bs={{x:{{ticks:{{color:C.txt,font:{{size:10}},maxTicksLimit:8}},grid:{{display:false}}}},y:{{ticks:{{color:C.txt,font:{{size:10}}}},grid:{{color:C.grid}}}}}};
const GA4={ga4_js};
const IG={ig_dly_js};
const IG_POSTS={ig_post_js};
const FB_POSTS={fb_post_js};
const FB_DAILY={fb_dly_js};
const GMB={gmb_js};
const SEO_C={seo_c_js};
const SEO_O={seo_o_js};
const pal=[C.green,C.moon,C.blue,'rgba(122,157,196,0.5)',C.amber,C.rose,'rgba(200,184,162,0.35)'];
new Chart(document.getElementById('trafficChart'),{{type:'bar',data:{{labels:GA4.map(r=>r.s),datasets:[{{data:GA4.map(r=>r.n),backgroundColor:pal,borderRadius:4}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{...bs,x:{{...bs.x,ticks:{{...bs.x.ticks,maxRotation:20,font:{{size:9}}}}}}}}}}}});
document.getElementById('trafficLegend').innerHTML=GA4.map((r,i)=>`<span><span class="swatch" style="background:${{pal[i]}}"></span>${{r.s}}</span>`).join('');
new Chart(document.getElementById('igReachChart'),{{type:'line',data:{{labels:IG.map(d=>d.d),datasets:[{{data:IG.map(d=>d.r),borderColor:C.rose,backgroundColor:'rgba(196,122,122,0.1)',fill:true,tension:0.35,pointRadius:2}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:bs}}}});
const igT={{REEL:'tag-rose',IMAGE:'tag-blue',CAROUSEL:'tag-amber'}};
document.getElementById('igPostsGrid').innerHTML=IG_POSTS.map(p=>`<div class="post-card"><div class="post-meta"><span style="font-size:11px;color:var(--muted)">${{p.date}}</span><span class="tag ${{igT[p.type]||'tag-blue'}}">${{p.type}}</span></div><div class="post-caption">${{p.caption}}</div><div class="post-stats"><span>❤ <strong>${{p.likes}}</strong></span><span>💬 <strong>${{p.comments}}</strong></span></div><a href="${{p.url}}" target="_blank">View on Instagram →</a></div>`).join('');
document.getElementById('fb-react').textContent=FB_POSTS.reduce((s,r)=>s+r.react,0);
document.getElementById('fb-shares').textContent=FB_POSTS.reduce((s,r)=>s+r.shares,0);
new Chart(document.getElementById('fbChart'),{{type:'bar',data:{{labels:FB_DAILY.map(d=>d.d),datasets:[{{data:FB_DAILY.map(d=>d.v),backgroundColor:C.blue,borderRadius:3}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{...bs,y:{{...bs.y,ticks:{{...bs.y.ticks,callback:v=>v>=1000?(v/1000).toFixed(1)+'k':v}}}}}}}}}});
const fbT={{photo:'tag-blue',video:'tag-rose',album:'tag-amber'}};
document.getElementById('fbPostsGrid').innerHTML=FB_POSTS.map(p=>`<div class="post-card"><div class="post-meta"><span style="font-size:11px;color:var(--muted)">${{p.date}}</span><span class="tag ${{fbT[p.type]||'tag-blue'}}">${{p.type}}</span></div><div class="post-caption">${{p.caption}}</div><div class="post-stats"><span>👁 <strong>${{p.imp.toLocaleString()}}</strong></span><span>❤ <strong>${{p.react}}</strong></span><span>↗ <strong>${{p.shares}}</strong></span></div><a href="${{p.url}}" target="_blank">View on Facebook →</a></div>`).join('');
new Chart(document.getElementById('gmbChart'),{{type:'line',data:{{labels:GMB.map(d=>d.d),datasets:[{{data:GMB.map(d=>d.i),borderColor:C.moon,backgroundColor:'rgba(200,184,162,0.08)',fill:true,tension:0.3,pointRadius:2}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:bs}}}});
new Chart(document.getElementById('gmbActionsChart'),{{type:'bar',data:{{labels:GMB.map(d=>d.d),datasets:[{{label:'Website clicks',data:GMB.map(d=>d.wc),backgroundColor:C.blue,borderRadius:2}},{{label:'Directions',data:GMB.map(d=>d.dr),backgroundColor:C.amber,borderRadius:2}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:true,labels:{{color:C.txt,font:{{size:10}},boxWidth:10,padding:12}}}}}},scales:bs}}}});
document.getElementById('seoBody').innerHTML=SEO_C.map(r=>{{const[cls,lbl]=r.pos<=3?['green','top 3']:r.pos<=7?['amber','close']:['rose','needs work'];return`<tr><td style="color:var(--text)">${{r.q}}</td><td style="text-align:right;color:var(--muted)">${{r.imp}}</td><td style="text-align:right;font-weight:500;color:${{r.cl>0?C.green:'var(--muted)'}} ">${{r.cl}}</td><td style="text-align:right;color:var(--muted)">${{r.pos.toFixed(1)}}</td><td><span class="tag tag-${{cls}}">${{lbl}}</span></td></tr>`;}}).join('');
document.getElementById('oppBody').innerHTML=SEO_O.map(r=>{{const cls=r.pos<=7?'amber':'rose';return`<tr><td style="color:var(--text)">${{r.q}}</td><td style="text-align:right;color:var(--muted)">${{r.imp}}</td><td style="text-align:right;color:var(--muted)">${{r.pos.toFixed(1)}}</td><td><span class="tag tag-${{cls}}">${{r.label}}</span></td></tr>`;}}).join('');
</script>
</body>
</html>"""

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Authenticating with Google...")
    creds = get_google_creds()

    print("Fetching GA4...")
    ga4_traffic, total_sessions, bookings = fetch_ga4(creds)

    print("Fetching Search Console...")
    seo_clicks, seo_opps = fetch_search_console(creds)

    print("Fetching Google Business Profile...")
    gmb_daily, gmb_imp, gmb_clicks, gmb_dir, gmb_best = fetch_gbp(creds)

    print("Fetching Facebook...")
    fb_daily, fb_posts, fb_imp = fetch_facebook()

    print("Fetching Instagram...")
    ig_followers, ig_daily, ig_posts, ig_reach, ig_likes, ig_best = fetch_instagram()

    data = {
        "display_date":   DISPLAY_DATE,
        "total_sessions": total_sessions,
        "bookings":       bookings,
        "ga4_traffic":    ga4_traffic,
        "seo_clicks":     seo_clicks,
        "seo_opps":       seo_opps,
        "gmb_daily":      gmb_daily,
        "gmb_impressions":gmb_imp,
        "gmb_clicks":     gmb_clicks,
        "gmb_directions": gmb_dir,
        "gmb_best_day":   gmb_best,
        "fb_daily":       fb_daily,
        "fb_posts":       fb_posts,
        "fb_impressions": fb_imp,
        "ig_followers":   ig_followers,
        "ig_daily":       ig_daily,
        "ig_posts":       ig_posts,
        "ig_reach":       ig_reach,
        "ig_likes":       ig_likes,
        "ig_best_day":    ig_best,
    }

    print("Generating HTML...")
    html = generate_html(data)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Done — index.html written ({len(html):,} bytes)")

if __name__ == "__main__":
    main()
