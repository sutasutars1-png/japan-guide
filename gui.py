# -*- coding: utf-8 -*-
"""gui.py — TABIJI 管理ツール(GUI)。ダブルクリック用: TABIJI管理ツール.bat
Pythonに標準搭載のtkinterのみ使用。追加インストール不要。

できること:
  ・サイト生成 / ブラウザでプレビュー / ネットに公開(git push)
  ・新ページ作成(AI): 地名を入れてボタン → プロンプト自動生成&コピー&claude.aiを開く
  ・AI返答を取込: チャットの返答をコピーした状態でボタン → 検証・ページ化・再生成
  ・写真を自動取得: Wikimedia(無料)から各地の写真を取得して反映
  ・config.json / データ / 受信箱フォルダを開く
"""
import os, subprocess, sys, threading, webbrowser
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# ---------------- helpers ----------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("TABIJI 管理ツール")
        root.geometry("720x560")
        root.minsize(600, 480)

        main = ttk.Frame(root, padding=12)
        main.pack(fill="both", expand=True)

        # --- サイト運用 ---
        row1 = ttk.LabelFrame(main, text=" サイト運用 ", padding=10)
        row1.pack(fill="x", pady=(0, 8))
        self.btn(row1, "① サイトを生成", self.build, 0)
        self.btn(row1, "② ブラウザでプレビュー", self.preview, 1)
        self.btn(row1, "③ ネットに公開 (git push)", self.publish, 2)
        self.btn(row1, "📷 写真を自動取得", self.photos, 3)

        # --- AI 記事作成 ---
        row2 = ttk.LabelFrame(main, text=" AIで新ページ作成(無料チャット利用) ", padding=10)
        row2.pack(fill="x", pady=(0, 8))
        ttk.Label(row2, text="観光地名(英語):").grid(row=0, column=0, padx=(0, 6))
        self.place = ttk.Entry(row2, width=24)
        self.place.grid(row=0, column=1, padx=(0, 10))
        ttk.Button(row2, text="A. プロンプト作成 → AIを開く",
                   command=self.new_page).grid(row=0, column=2, padx=4)
        ttk.Button(row2, text="B. AI返答を取込(コピーしてから押す)",
                   command=self.import_ai).grid(row=0, column=3, padx=4)
        ttk.Label(row2, foreground="#666",
                  text="使い方: 地名入力→A→開いたAIに貼り付け→返答を全てコピー→B"
                  ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # --- 設定・フォルダ ---
        row3 = ttk.LabelFrame(main, text=" 設定・フォルダ ", padding=10)
        row3.pack(fill="x", pady=(0, 8))
        self.btn(row3, "config.json を編集", lambda: self.open_path("config.json"), 0)
        self.btn(row3, "記事データを開く", lambda: self.open_path("data"), 1)
        self.btn(row3, "受信箱(inbox)を開く", lambda: self.open_path("inbox"), 2)
        self.btn(row3, "サイトフォルダ(docs)", lambda: self.open_path("docs"), 3)

        # --- ログ ---
        ttk.Label(main, text="ログ:").pack(anchor="w")
        self.log = scrolledtext.ScrolledText(main, height=14, state="disabled",
                                             font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)
        self.write("ようこそ。まず「① サイトを生成」→「② プレビュー」を試してください。\n")

    def btn(self, parent, text, cmd, col):
        b = ttk.Button(parent, text=text, command=cmd)
        b.grid(row=0, column=col, padx=4, sticky="w")
        return b

    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def run_script(self, args, done_msg=None):
        """別スレッドでコマンドを実行し、出力をログに流す(画面が固まらない)。"""
        def worker():
            self.write(f"\n$ {' '.join(args)}\n")
            try:
                env = dict(os.environ, PYTHONIOENCODING="utf-8")
                p = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, env=env)
                for line in iter(p.stdout.readline, b""):
                    self.root.after(0, self.write, line.decode("utf-8", "replace"))
                p.wait()
                if done_msg and p.returncode == 0:
                    self.root.after(0, self.write, done_msg + "\n")
                if p.returncode != 0:
                    self.root.after(0, self.write,
                                    f"※ エラー終了 (code {p.returncode})\n")
            except Exception as e:
                self.root.after(0, self.write, f"実行エラー: {e}\n")
        threading.Thread(target=worker, daemon=True).start()

    # ---------------- actions ----------------
    def build(self):
        self.run_script([PY, "build.py"], "✔ 生成完了。②でプレビューできます。")

    def preview(self):
        idx = os.path.join(ROOT, "docs", "index.html")
        if not os.path.exists(idx):
            messagebox.showinfo("TABIJI", "先に「① サイトを生成」を実行してください。")
            return
        webbrowser.open("file:///" + idx.replace("\\", "/"))
        self.write("ブラウザでプレビューを開きました。\n")

    def publish(self):
        if not os.path.isdir(os.path.join(ROOT, ".git")):
            messagebox.showinfo("TABIJI", "まだgitが初期化されていません。\nREADMEのセットアップ手順③をご覧ください。")
            return
        self.run_script(["git", "add", "-A"])
        self.run_script(["git", "commit", "-m", "update site"])
        self.run_script(["git", "push"], "✔ 公開しました(反映まで1〜2分)。")

    def photos(self):
        self.run_script([PY, os.path.join("tools", "fetch_images.py")],
                        "✔ 写真を取得しました。「① サイトを生成」で反映されます。")

    def new_page(self):
        name = self.place.get().strip()
        if not name:
            messagebox.showinfo("TABIJI", "観光地名を英語で入力してください(例: Nikko)")
            return
        self.run_script([PY, "ai_new_page.py", name])

    def import_ai(self):
        self.run_script([PY, "ai_import.py"], "✔ 取込&再生成が完了しました。")

    def open_path(self, rel):
        path = os.path.join(ROOT, rel)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("TABIJI", f"開けませんでした: {e}")

def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
