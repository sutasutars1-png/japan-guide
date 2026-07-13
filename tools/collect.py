# -*- coding: utf-8 -*-
"""collect.py — 無料API(キー不要)から観光地情報を収集するモジュール。
使用API: Wikipedia REST / Wikivoyage / (画像は Wikimedia Commons のURL参照)
すべて無料・APIキー不要・商用利用可のオープンデータです。
"""
import json, re
from urllib.request import Request, urlopen
from urllib.parse import quote

UA = {"User-Agent": "TABIJI-site-builder/1.0 (personal travel site; contact via repo)"}

def _get_json(url, timeout=15):
    req = Request(url, headers=UA)
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def wiki_summary(title, lang="en"):
    """Wikipedia要約・座標・代表画像を取得。見つからなければ None。"""
    try:
        j = _get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title)}")
    except Exception:
        return None
    if j.get("type") == "https://mediawiki.org/wiki/HyperSwitch/errors/not_found":
        return None
    img = (j.get("originalimage") or j.get("thumbnail") or {}).get("source")
    coords = j.get("coordinates") or {}
    return {
        "title": j.get("title"),
        "extract": j.get("extract", ""),
        "lat": coords.get("lat"), "lon": coords.get("lon"),
        "image": img,
        "image_credit": "Photo: Wikimedia Commons (CC — 画像ページでライセンス要確認)" if img else None,
        "page_url": (j.get("content_urls") or {}).get("desktop", {}).get("page"),
    }

def wikivoyage_extract(title, chars=4500):
    """Wikivoyage(旅行ガイド版Wikipedia)の本文冒頭を取得。実用情報が豊富。"""
    url = ("https://en.wikivoyage.org/w/api.php?action=query&prop=extracts"
           f"&explaintext=1&redirects=1&format=json&titles={quote(title)}")
    try:
        j = _get_json(url)
        pages = j["query"]["pages"]
        page = next(iter(pages.values()))
        text = page.get("extract", "")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:chars]
    except Exception:
        return ""

def fetch_context(name):
    """新ページ作成用のソース素材をまとめて収集。"""
    print(f"  Wikipedia(en) を検索中: {name} ...")
    s = wiki_summary(name, "en") or {}
    print(f"  Wikivoyage を検索中: {name} ...")
    v = wikivoyage_extract(name)
    ctx = {
        "name": name,
        "wikipedia_summary": s.get("extract", "(not found)"),
        "wikivoyage_text": v or "(not found)",
        "lat": s.get("lat"), "lon": s.get("lon"),
        "image": s.get("image"), "image_credit": s.get("image_credit"),
        "source_url": s.get("page_url"),
    }
    return ctx

if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else input("Destination name (English): ")
    print(json.dumps(fetch_context(name), ensure_ascii=False, indent=2))
