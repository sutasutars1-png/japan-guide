# -*- coding: utf-8 -*-
"""fetch_images.py — 各観光地の写真をWikimedia(無料・要クレジット)から自動取得して
data/destinations.json に反映する。実行: py tools/fetch_images.py
- Wikipedia代表画像 + ページ内画像から横長の写真を最大3枚選ぶ
- 画像URLが実際に生きているか(HTTP 200)を確認してから保存する
"""
import json, os, re, sys, urllib.parse
from urllib.request import Request, urlopen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "TABIJI-site-builder/1.0 (personal travel site)"}
SKIP = re.compile(r"(logo|icon|map|locator|flag|seal|emblem|montage|banner|arms|\.svg|\.gif)", re.I)

def get_json(url):
    with urlopen(Request(url, headers=UA), timeout=20) as r:
        return json.loads(r.read().decode())

def head_ok(url):
    try:
        req = Request(url, headers=UA, method="HEAD")
        with urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception:
        return False

def thumb(commons_title, width=1200):
    t = urllib.parse.quote(commons_title.replace(" ", "_"))
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{t}?width={width}"

def page_images(wiki_title, limit=3):
    """Wikipedia(en)記事の画像一覧から写真らしいものを選ぶ。"""
    url = ("https://en.wikipedia.org/w/api.php?action=query&format=json&redirects=1"
           "&prop=images&imlimit=50&titles=" + urllib.parse.quote(wiki_title))
    try:
        pages = get_json(url)["query"]["pages"]
        page = next(iter(pages.values()))
        names = [i["title"].replace("File:", "") for i in page.get("images", [])]
    except Exception:
        return []
    picked = []
    for n in names:
        if SKIP.search(n):
            continue
        if not n.lower().endswith((".jpg", ".jpeg")):
            continue
        picked.append(n)
        if len(picked) >= limit * 2:
            break
    out = []
    for n in picked:
        u = thumb(n)
        if head_ok(u):
            out.append({"url": u,
                        "credit": f"Photo: Wikimedia Commons — {n}",
                        "file_page": "https://commons.wikimedia.org/wiki/File:" + urllib.parse.quote(n.replace(' ', '_'))})
        if len(out) >= limit:
            break
    return out

def lead_image(wiki_title):
    try:
        j = get_json("https://en.wikipedia.org/api/rest_v1/page/summary/" +
                     urllib.parse.quote(wiki_title))
        src = (j.get("originalimage") or {}).get("source")
        if src and head_ok(src):
            return {"url": src, "credit": "Photo: Wikimedia Commons",
                    "file_page": (j.get("content_urls") or {}).get("desktop", {}).get("page", "")}
    except Exception:
        pass
    return None

# 記事タイトルの対応表(観光地ID → Wikipedia英語記事名)
WIKI_TITLE = {
    "tokyo": "Tokyo", "kyoto": "Kyoto", "osaka": "Osaka", "nara": "Nara (city)",
    "hakone-fuji": "Hakone", "hiroshima": "Hiroshima", "kanazawa": "Kanazawa",
    "sapporo-hokkaido": "Sapporo", "fukuoka": "Fukuoka", "okinawa": "Okinawa Island",
}

def main(only_missing=True):
    path = os.path.join(ROOT, "data", "destinations.json")
    data = json.load(open(path, encoding="utf-8"))
    for d in data["destinations"]:
        if only_missing and d.get("photos"):
            print(f"skip (has photos): {d['id']}")
            continue
        title = WIKI_TITLE.get(d["id"]) or d["name"]["en"]
        print(f"fetching: {d['id']}  ({title})")
        photos = []
        lead = lead_image(title)
        if lead:
            photos.append(lead)
        for p in page_images(title, limit=3):
            if all(p["url"] != q["url"] for q in photos):
                photos.append(p)
        d["photos"] = photos[:3]
        print(f"  -> {len(d['photos'])} photos")
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("saved data/destinations.json")

if __name__ == "__main__":
    main(only_missing="--force" not in sys.argv)
