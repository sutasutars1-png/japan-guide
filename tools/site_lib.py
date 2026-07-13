# -*- coding: utf-8 -*-
"""site_lib.py — TABIJI static site templates & helpers. Python 3.8+, stdlib only."""
import json, html
from urllib.parse import quote

LANGS = ["en", "ko", "zh"]          # zh = Traditional Chinese (Taiwan/HK)
HREFLANG = {"en": "en", "ko": "ko", "zh": "zh-Hant"}
LANG_NAME = {"en": "English", "ko": "한국어", "zh": "繁體中文"}
LANG_DIR = {"en": "", "ko": "ko/", "zh": "zh/"}
KLOOK_LOCALE = {"en": "en-US", "ko": "ko", "zh": "zh-TW"}

UI = {
    "en": {
        "destinations": "Destinations", "guides": "Travel guides", "home": "Home",
        "highlights": "Don't miss", "access": "Getting there", "season": "Best time to visit",
        "plan": "Plan your trip", "book_exp": "Tours & tickets", "hotels_agoda": "Hotels on Agoda",
        "hotels_booking": "Hotels on Booking.com", "book_gyg": "Activities on GetYourGuide",
        "esim": "Japan eSIM (stay online)", "related": "Where next", "read": "Read the guide",
        "weather_now": "Right now in", "faq": "Questions travelers ask",
        "disclosure": "Some links on this site are affiliate links. If you book through them we may earn a commission at no extra cost to you — it keeps these guides free.",
        "footer_about": "Independent Japan travel guides, updated for real trips.",
        "explore": "Explore Japan", "all_guides": "Guides for a smoother trip",
        "hero_kicker": "Japan travel guide", "region": "Region", "updated": "Updated",
        "yen_now": "¥1,000 is about", "back": "All destinations",
        "seasons_h": "Through the seasons",
        "s_spring": "🌸 Spring", "s_summer": "🌻 Summer", "s_autumn": "🍁 Autumn", "s_winter": "❄️ Winter",
        "photos_h": "In pictures",
    },
    "ko": {
        "destinations": "여행지", "guides": "여행 가이드", "home": "홈",
        "highlights": "놓치지 마세요", "access": "가는 방법", "season": "추천 시기",
        "plan": "여행 준비하기", "book_exp": "투어·입장권 (Klook)", "hotels_agoda": "아고다 호텔 검색",
        "hotels_booking": "부킹닷컴 호텔 검색", "book_gyg": "GetYourGuide 액티비티",
        "esim": "일본 eSIM (데이터 준비)", "related": "다음 여행지", "read": "가이드 읽기",
        "weather_now": "지금 날씨:", "faq": "여행자들이 자주 묻는 질문",
        "disclosure": "이 사이트의 일부 링크는 제휴 링크입니다. 링크를 통해 예약하시면 추가 비용 없이 소정의 수수료를 받으며, 가이드를 무료로 운영하는 데 사용됩니다.",
        "footer_about": "진짜 여행을 위해 업데이트되는 독립 일본 여행 가이드.",
        "explore": "일본 여행지 탐색", "all_guides": "더 편한 여행을 위한 가이드",
        "hero_kicker": "일본 여행 가이드", "region": "지역", "updated": "업데이트",
        "yen_now": "1,000엔은 약", "back": "여행지 전체 보기",
        "seasons_h": "사계절 즐기기",
        "s_spring": "🌸 봄", "s_summer": "🌻 여름", "s_autumn": "🍁 가을", "s_winter": "❄️ 겨울",
        "photos_h": "사진으로 보기",
    },
    "zh": {
        "destinations": "目的地", "guides": "旅遊攻略", "home": "首頁",
        "highlights": "不可錯過", "access": "交通方式", "season": "最佳造訪時間",
        "plan": "開始規劃行程", "book_exp": "行程·門票 (Klook)", "hotels_agoda": "Agoda 訂房",
        "hotels_booking": "Booking.com 訂房", "book_gyg": "GetYourGuide 體驗",
        "esim": "日本 eSIM（上網必備）", "related": "下一站", "read": "閱讀攻略",
        "weather_now": "現在天氣：", "faq": "旅人常見問題",
        "disclosure": "本站部分連結為聯盟連結。透過連結預訂不會增加您的費用，我們可能獲得少量佣金，用於維持指南免費營運。",
        "footer_about": "為真實旅程持續更新的獨立日本旅遊指南。",
        "explore": "探索日本目的地", "all_guides": "讓旅程更順的攻略",
        "hero_kicker": "日本旅遊指南", "region": "地區", "updated": "更新",
        "yen_now": "¥1,000 約為", "back": "所有目的地",
        "seasons_h": "四季玩法",
        "s_spring": "🌸 春", "s_summer": "🌻 夏", "s_autumn": "🍁 秋", "s_winter": "❄️ 冬",
        "photos_h": "影像巡禮",
    },
}

def esc(s): return html.escape(str(s), quote=True)

# ---------- affiliate links ----------
def aff_links(cfg, lang, query):
    a = cfg.get("affiliates", {})
    q = quote(query)
    klook = f"https://www.klook.com/{KLOOK_LOCALE[lang]}/search/result/?query={q}"
    if a.get("klook_aid"): klook += f"&aid={a['klook_aid']}"
    gyg = f"https://www.getyourguide.com/s/?q={quote(query + ' Japan')}"
    if a.get("gyg_partner_id"): gyg += f"&partner_id={a['gyg_partner_id']}"
    agoda = f"https://www.agoda.com/search?searchText={q}"
    if a.get("agoda_cid"): agoda += f"&cid={a['agoda_cid']}"
    booking = f"https://www.booking.com/searchresults.html?ss={quote(query + ', Japan')}"
    if a.get("booking_aid"): booking += f"&aid={a['booking_aid']}"
    esim = a.get("airalo_url") or "https://www.airalo.com/japan-esim"
    return {"klook": klook, "gyg": gyg, "agoda": agoda, "booking": booking, "esim": esim}

# ---------- page shell ----------
def shell(cfg, lang, depth, title, description, body, canonical_path, alt_paths,
          jsonld=None, og_type="website"):
    t = UI[lang]
    root = "../" * depth
    base = cfg["base_url"].rstrip("/")
    canonical = f"{base}/{canonical_path}"
    hreflangs = "\n".join(
        f'  <link rel="alternate" hreflang="{HREFLANG[l]}" href="{base}/{alt_paths[l]}">'
        for l in LANGS) + f'\n  <link rel="alternate" hreflang="x-default" href="{base}/{alt_paths["en"]}">'
    switcher = " ".join(
        f'<a class="lang{" on" if l == lang else ""}" href="{root}{alt_paths[l]}">{LANG_NAME[l]}</a>'
        for l in LANGS)
    ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>' if jsonld else ""
    gc = cfg.get("analytics", {}).get("goatcounter_code", "")
    analytics = (f'<script data-goatcounter="https://{gc}.goatcounter.com/count" '
                 f'async src="//gc.zgo.at/count.js"></script>') if gc else ""
    site = esc(cfg["site_name"])
    return f"""<!DOCTYPE html>
<html lang="{HREFLANG[lang]}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)} | {site}</title>
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{canonical}">
{hreflangs}
  <meta property="og:site_name" content="{site}">
  <meta property="og:type" content="{og_type}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{canonical}">
  <meta name="twitter:card" content="summary">
  <link rel="alternate" type="application/rss+xml" title="{site}" href="{base}/feed.xml">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ccircle cx='50' cy='50' r='46' fill='%23D9381E'/%3E%3Ctext x='50' y='68' font-size='52' text-anchor='middle' fill='%23FAFAF7' font-family='serif'%3E旅%3C/text%3E%3C/svg%3E">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,300..800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{root}assets/style.css">
  {ld}
  {analytics}
</head>
<body>
<header class="top">
  <a class="brand" href="{root}{LANG_DIR[lang]}index.html"><span class="seal">旅</span>{site}</a>
  <nav>
    <a href="{root}{LANG_DIR[lang]}index.html#destinations">{t["destinations"]}</a>
    <a href="{root}{LANG_DIR[lang]}index.html#guides">{t["guides"]}</a>
  </nav>
  <div class="langs">{switcher}</div>
</header>
{body}
<footer>
  <p class="f-about"><span class="seal small">旅</span> {site} — {t["footer_about"]}</p>
  <p class="f-disc">{t["disclosure"]}</p>
  <div class="langs">{switcher}</div>
</footer>
<script src="{root}assets/app.js" defer></script>
</body>
</html>"""

# ---------- components ----------
def kanji_tile(kanji, size="", href=None, label=""):
    inner = f'<span class="k">{esc(kanji)}</span>'
    tile = f'<div class="tile {size}" aria-hidden="true">{inner}</div>'
    if href:
        return f'<a class="tile-link" href="{href}">{tile}{label}</a>'
    return tile

def dest_card(d, lang, root):
    t = UI[lang]
    href = f'{root}{LANG_DIR[lang]}destinations/{d["id"]}.html'
    photos = d.get("photos") or []
    if photos:
        visual = (f'<div class="tile photo-tile" style="background-image:url(\'{esc(photos[0]["url"])}\')">'
                  f'<span class="k corner">{esc(d["kanji"])}</span>'
                  f'<span class="stamp">{esc(d["region"])}</span></div>')
    else:
        visual = (f'<div class="tile"><span class="k">{esc(d["kanji"])}</span>'
                  f'<span class="stamp">{esc(d["region"])}</span></div>')
    return f"""<a class="card" href="{href}">
  {visual}
  <div class="card-body">
    <h3>{esc(d["name"][lang])}</h3>
    <p>{esc(d["tagline"][lang])}</p>
    <p class="meta">{t["season"]}: {esc(d["best_season"][lang])}</p>
  </div>
</a>"""

def guide_card(g, lang, root):
    t = UI[lang]
    href = f'{root}{LANG_DIR[lang]}guides/{g["id"]}.html'
    return f"""<a class="gcard" href="{href}">
  <span class="g-emoji" aria-hidden="true">{g.get("emoji","📖")}</span>
  <div><h3>{esc(g["title"][lang])}</h3><p>{esc(g["description"][lang])}</p>
  <span class="readmore">{t["read"]} →</span></div>
</a>"""

def cta_block(cfg, lang, city_query):
    t = UI[lang]
    links = aff_links(cfg, lang, city_query)
    def btn(url, label, cls=""):
        return (f'<a class="cta {cls}" href="{url}" target="_blank" '
                f'rel="sponsored nofollow noopener">{esc(label)}</a>')
    return f"""<aside class="plan">
  <h2>{t["plan"]}</h2>
  <div class="ctas">
    {btn(links["klook"], t["book_exp"], "primary")}
    {btn(links["gyg"], t["book_gyg"])}
    {btn(links["agoda"], t["hotels_agoda"])}
    {btn(links["booking"], t["hotels_booking"])}
    {btn(links["esim"], t["esim"])}
  </div>
</aside>"""


SEASON_KEYS = ["spring", "summer", "autumn", "winter"]

def season_tabs(d, lang, today_month):
    """CSSのみで動く四季タブ。today_monthの季節を初期選択にする。"""
    t = UI[lang]
    seasons = d.get("seasons") or {}
    if not all(k in seasons for k in SEASON_KEYS):
        return ""
    cur = {12:"winter",1:"winter",2:"winter",3:"spring",4:"spring",5:"spring",
           6:"summer",7:"summer",8:"summer",9:"autumn",10:"autumn",11:"autumn"}[today_month]
    uid = d["id"]
    inputs, labels, panels = "", "", ""
    for k in SEASON_KEYS:
        checked = " checked" if k == cur else ""
        inputs += f'<input type="radio" name="ssn-{uid}" id="ssn-{uid}-{k}" class="ssn-i ssn-{k}"{checked}>'
        labels += f'<label for="ssn-{uid}-{k}">{t["s_" + k]}</label>'
        panels += f'<div class="s-panel s-{k}"><p>{esc(seasons[k][lang])}</p></div>'
    return (f'<h2>{t["seasons_h"]}</h2><div class="seasons">'
            f'{inputs}<div class="s-tabs">{labels}</div>{panels}</div>')

def gallery(d, lang):
    photos = d.get("photos") or []
    if not photos:
        return ""
    t = UI[lang]
    figs = ""
    for p in photos:
        page = p.get("file_page") or p["url"]
        figs += (f'<figure><img src="{esc(p["url"])}" alt="{esc(d["name"][lang])}" loading="lazy">'
                 f'<figcaption><a href="{esc(page)}" rel="noopener" target="_blank">'
                 f'{esc(p.get("credit","Photo: Wikimedia Commons"))}</a></figcaption></figure>')
    return f'<h2>{t["photos_h"]}</h2><div class="gallery">{figs}</div>'
