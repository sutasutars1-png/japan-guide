# -*- coding: utf-8 -*-
"""ai_import.py — AIチャットの返答(JSON)を取り込み、検証してサイトを再生成する。

読み込み順: ① クリップボード → ② inbox/ フォルダ内の .json / .txt ファイル
成功すると data/destinations.json に追記(同idは上書き)し、build.py を自動実行します。
"""
import json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
REQUIRED = ["id", "kanji", "region", "lat", "lon", "name", "tagline",
            "best_season", "intro", "highlights", "access"]
LANGS = ["en", "ko", "zh"]

def from_clipboard():
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                                 capture_output=True, check=True)
            return out.stdout.decode("utf-8", errors="replace")
        elif sys.platform == "darwin":
            return subprocess.run("pbpaste", capture_output=True, check=True).stdout.decode()
        else:
            return subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                                  capture_output=True, check=True).stdout.decode()
    except Exception:
        return ""

def extract_json(text):
    """マークダウンの ```json フェンスや前後の文章を取り除いてJSONを抽出。"""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"  JSONの解析に失敗: {e}")
        return None

def validate(d):
    missing = [k for k in REQUIRED if k not in d]
    if missing:
        return f"必須フィールドが不足: {missing}"
    for field in ["name", "tagline", "best_season", "intro", "access"]:
        for l in LANGS:
            if not d[field].get(l):
                return f"{field}.{l} が空です"
    if not isinstance(d["highlights"], list) or len(d["highlights"]) < 3:
        return "highlights は3件以上必要です"
    for h in d["highlights"]:
        for l in LANGS:
            if not h.get(l):
                return f"highlights 内の {l} が空です"
    return None

def merge(dest):
    path = os.path.join(ROOT, "data", "destinations.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    dest.setdefault("image", None)
    dest.setdefault("image_credit", None)
    dest.setdefault("seasons", None)   # 無くても取り込める(タブが出ないだけ)
    dest.setdefault("photos", None)
    existing = [d["id"] for d in data["destinations"]]
    if dest["id"] in existing:
        data["destinations"] = [dest if d["id"] == dest["id"] else d
                                for d in data["destinations"]]
        print(f"  既存ページを更新: {dest['id']}")
    else:
        data["destinations"].append(dest)
        print(f"  新規ページを追加: {dest['id']}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    candidates = []
    clip = from_clipboard()
    if clip.strip():
        candidates.append(("クリップボード", clip))
    inbox = os.path.join(ROOT, "inbox")
    if os.path.isdir(inbox):
        for fn in sorted(os.listdir(inbox)):
            if fn.endswith((".json", ".txt")):
                with open(os.path.join(inbox, fn), encoding="utf-8") as f:
                    candidates.append((f"inbox/{fn}", f.read()))
    imported = 0
    for src, text in candidates:
        d = extract_json(text)
        if not d:
            continue
        err = validate(d)
        if err:
            print(f"[{src}] スキップ: {err}")
            continue
        print(f"[{src}] 取り込み中...")
        merge(d)
        imported += 1
        break  # クリップボード優先で1件処理(inboxを一括処理したい場合はこの行を削除)
    if not imported:
        print("取り込めるJSONが見つかりませんでした。")
        print("AIの返答を全てコピーしてから再実行するか、inbox/ に .json として保存してください。")
        return
    print("サイトを再生成します...")
    subprocess.run([sys.executable, os.path.join(ROOT, "build.py")], check=True)
    print("完了! docs/ フォルダが更新されました。git push すれば公開されます。")

if __name__ == "__main__":
    main()
