# -*- coding: utf-8 -*-
"""ai_new_page.py — 新しい観光地ページを「ワンクリック+AIチャット貼り付け」で作る。

手順(費用ゼロ):
  1) python ai_new_page.py  →  地名を入力(英語名。例: Takayama)
  2) 無料APIから素材を自動収集し、AI用プロンプトを生成してクリップボードへコピー
  3) claude.ai か chatgpt.com(無料版でOK)を開いて貼り付け → 送信
  4) AIの返答(JSON)を全部コピー
  5) python ai_import.py  →  クリップボードから自動取り込み・サイト再生成
"""
import json, os, re, subprocess, sys, webbrowser
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
from collect import fetch_context

ROOT = os.path.dirname(os.path.abspath(__file__))

PROMPT_TEMPLATE = """You are helping me add a page to my multilingual Japan travel site.
Using ONLY the source material below (plus general knowledge to fill small gaps),
write the page content in three languages: English, Korean, Traditional Chinese.

Respond with ONE valid JSON object and NOTHING else — no markdown fences, no commentary.
Use exactly this schema (all fields required):

{{
  "id": "<lowercase-slug>",
  "kanji": "<ONE evocative kanji character for this place>",
  "region": "<region name in English, e.g. Tohoku>",
  "lat": {lat}, "lon": {lon},
  "name": {{"en": "...", "ko": "...", "zh": "..."}},
  "tagline": {{"en": "<punchy, max 12 words>", "ko": "...", "zh": "..."}},
  "best_season": {{"en": "...", "ko": "...", "zh": "..."}},
  "intro": {{"en": "<two paragraphs, 100-150 words total, separated by \\n\\n, vivid and practical, no clichés like hidden gem>",
            "ko": "<one paragraph, natural Korean>", "zh": "<one paragraph, natural Traditional Chinese (Taiwan style)>"}},
  "highlights": [ five items, each {{"en": "...", "ko": "...", "zh": "..."}} ],
  "access": {{"en": "<how to get there from the nearest hub, with times>", "ko": "...", "zh": "..."}},
  "seasons": {{
    "spring": {{"en": "<1-2 sentences: what makes spring special here, with specifics>", "ko": "...", "zh": "..."}},
    "summer": {{"en": "...", "ko": "...", "zh": "..."}},
    "autumn": {{"en": "...", "ko": "...", "zh": "..."}},
    "winter": {{"en": "...", "ko": "...", "zh": "..."}}
  }},
  "image": {image_json},
  "image_credit": {credit_json}
}}

Write like an experienced travel editor: specific, honest, useful. Korean and Chinese
must read as native writing, not translationese.

=== SOURCE: Wikipedia summary ===
{wiki}

=== SOURCE: Wikivoyage (practical travel info) ===
{voyage}
"""

def to_clipboard(text):
    try:
        if sys.platform.startswith("win"):
            subprocess.run("clip", input=text.encode("utf-16-le"), check=True, shell=True)
        elif sys.platform == "darwin":
            subprocess.run("pbcopy", input=text.encode(), check=True)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
        return True
    except Exception:
        return False

def main():
    name = sys.argv[1] if len(sys.argv) > 1 else input("追加したい観光地の英語名 (例: Takayama): ").strip()
    if not name:
        print("地名が入力されませんでした。"); return
    print(f"[1/3] 無料APIから素材を収集中...")
    ctx = fetch_context(name)
    prompt = PROMPT_TEMPLATE.format(
        lat=ctx["lat"] if ctx["lat"] is not None else '"FILL_IN"',
        lon=ctx["lon"] if ctx["lon"] is not None else '"FILL_IN"',
        image_json=json.dumps(ctx["image"]),
        credit_json=json.dumps(ctx["image_credit"], ensure_ascii=False),
        wiki=ctx["wikipedia_summary"],
        voyage=ctx["wikivoyage_text"],
    )
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    out_dir = os.path.join(ROOT, "prompt_out"); os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{slug}_prompt.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(prompt)
    copied = to_clipboard(prompt)
    print(f"[2/3] プロンプトを生成しました → {path}")
    print("      クリップボードにコピー済み ✔" if copied else "      ↑このファイルの中身を全選択してコピーしてください")
    print("[3/3] ブラウザでAIチャットを開きます。貼り付けて送信してください。")
    webbrowser.open("https://claude.ai/new")
    print("\n次の手順: AIの返答(JSON)を全部コピーしてから  python ai_import.py  を実行")

if __name__ == "__main__":
    main()
