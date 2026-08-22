"""note チャネル連携 (§22, §30-31, 付録A #2)。

note は「公式に提供されている機能・連携方法を優先。非公式なブラウザ自動操作は
最後の手段」(§22)。また売上/PV の公式 API は限定的で、データは**管理画面からの
CSV エクスポート**で取り込むのが現実的 (付録A #2)。この方針に忠実に:

* **NoteExporter** — 承認済み記事を「貼り付けるだけ」の公開用 Markdown に書き出す。
  自動投稿はしない（人間が note エディタに貼る）。有料エリアの境界も明示する。
* **NoteImporter** — note の売上/アクセス CSV を取り込み、商品の実績を更新する。
  列名は日本語/英語のゆらぎを吸収し、URL→タイトル完全一致→部分一致で商品に紐付ける。

どちらも外部ネットワークにアクセスしない（ローカルファイルのみ, §36）。
"""

from __future__ import annotations

import csv
import html as _html
import io
import pathlib
import re
from typing import Any

from . import ids


# ---- エクスポート（公開補助, §22） ---------------------------------------

_PAID_MARK_SRC = "―― ここから有料 ――"


def _inline_md(text: str) -> str:
    """行内 Markdown（太字/斜体/コード/リンク）を HTML に変換。"""
    t = _html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"__(.+?)__", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    t = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', t)
    return t


def _is_ol(s: str) -> bool:
    return re.match(r"^\s*\d+[.)]\s+", s) is not None


def renumber_ordered_lists(md: str) -> str:
    """順序付きリスト（1. 2. …）の番号を出現順に振り直す。

    LLM が番号を誤る/重複させることがあるため、連続ブロック内で 1..N に正規化。
    項目間に空行が1つ入っていても同一リストとして扱う（番号を継続）。
    """
    lines = md.split("\n")
    # 番号項目に挟まれた空行を除去して、リストを連続させる。
    merged: list[str] = []
    for i, ln in enumerate(lines):
        if ln.strip() == "" and merged and _is_ol(merged[-1]):
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and _is_ol(lines[j]):
                continue
        merged.append(ln)
    # 連続ブロックごとに 1..N へ振り直す。
    result: list[str] = []
    n = 0
    for ln in merged:
        if _is_ol(ln):
            n += 1
            num = n
            ln = re.sub(r"^(\s*)\d+([.)])(\s+)",
                        lambda m: m.group(1) + str(num) + m.group(2) + m.group(3),
                        ln, count=1)
        elif ln.strip() != "":
            n = 0
        result.append(ln)
    return "\n".join(result)


def md_to_html(md: str) -> str:
    """最小限の Markdown → HTML 変換（見出し/箇条書き/段落/引用/罫線）。

    note エディタは Markdown 記号を解釈しないため、書式付きで貼り付けられるよう
    整形済み HTML を用意する。標準ライブラリのみ。
    """
    md = renumber_ordered_lists(md)
    out: list[str] = []
    para: list[str] = []
    state = {"ul": False, "ol": False}

    def flush_para() -> None:
        if para:
            text = " ".join(para).strip()
            if text:
                out.append("<p>" + _inline_md(text) + "</p>")
            para.clear()

    def close_lists() -> None:
        if state["ul"]:
            out.append("</ul>")
            state["ul"] = False
        if state["ol"]:
            out.append("</ol>")
            state["ol"] = False

    for raw in md.split("\n"):
        s = raw.strip()
        if not s:
            flush_para()
            close_lists()
            continue
        if "ここから有料" in s or "有料エリア" in s:
            flush_para()
            close_lists()
            out.append('<hr><p class="paid">👇 ここから下を note の有料エリアに設定</p>')
            continue
        if re.match(r"^([-*_])\1{2,}$", s):
            flush_para()
            close_lists()
            out.append("<hr>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush_para()
            close_lists()
            level = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (level, _inline_md(m.group(2)), level))
            continue
        m = re.match(r"^\d+[.)]\s+(.*)$", s)
        if m:
            flush_para()
            if not state["ol"]:
                close_lists()
                out.append("<ol>")
                state["ol"] = True
            out.append("<li>" + _inline_md(m.group(1)) + "</li>")
            continue
        m = re.match(r"^[-*・]\s+(.*)$", s)
        if m:
            flush_para()
            if not state["ul"]:
                close_lists()
                out.append("<ul>")
                state["ul"] = True
            out.append("<li>" + _inline_md(m.group(1)) + "</li>")
            continue
        m = re.match(r"^>\s?(.*)$", s)
        if m:
            flush_para()
            close_lists()
            out.append("<blockquote>" + _inline_md(m.group(1)) + "</blockquote>")
            continue
        para.append(s)

    flush_para()
    close_lists()
    return "\n".join(out)


class NoteExporter:
    def __init__(self, company):
        self.c = company

    def _hashtags(self, product: dict) -> list[str]:
        tags = ["note", "有料note"]
        theme = product.get("theme") or ""
        for w in re.split(r"[・/、\s]+", theme):
            if len(w) >= 2:
                tags.append(w)
        return tags[:6]

    def export(self, product_id: str) -> dict[str, Any]:
        product = self.c.storage.get("products", product_id)
        if product is None:
            raise KeyError(product_id)
        arts = self.c.storage.find("articles", product_id=product_id)
        if not arts:
            raise ValueError(f"記事が見つかりません: {product_id}")
        article = arts[-1]
        body = renumber_ordered_lists(article.get("body_markdown", ""))
        # 有料エリア境界を note 用コメントに置換して明示。
        body_marked = body.replace(
            _PAID_MARK_SRC, "<!-- 👇 ここから下を note の有料エリアに設定 -->")
        hashtags = self._hashtags(product)
        header = (
            f"<!-- note 公開用（人間が note エディタに貼り付け, §22）\n"
            f"タイトル: {product.get('title')}\n"
            f"価格: {product.get('price_jpy')}円\n"
            f"カテゴリー: {product.get('category')}  テーマ: {product.get('theme')}\n"
            f"ハッシュタグ: {' '.join('#'+t for t in hashtags)}\n"
            f"商品ID: {product_id}\n-->\n\n"
        )
        # 本文が既に H1 で始まる場合は見出しを重複させない。
        title_h1 = "" if body_marked.lstrip().startswith("# ") else f"# {product.get('title')}\n\n"
        content = header + title_h1 + body_marked + "\n"

        out_dir = pathlib.Path(self.c.config.data_dir) / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{product_id}.md"
        path.write_text(content, encoding="utf-8")

        self.c.memory.add("note", f"note公開用エクスポート: {product.get('title')}",
                          str(path), related=[product_id])
        return {
            "product_id": product_id, "title": product.get("title"),
            "price_jpy": product.get("price_jpy"), "hashtags": hashtags,
            "path": str(path), "markdown": content,
        }

    def render_html(self, product_id: str) -> dict[str, Any]:
        """note 貼り付け用に、記事本文を整形済み HTML にして返す。

        note エディタは Markdown を解釈しないので、見出し・太字・箇条書きを
        保ったまま「書式ごとコピー」できるよう HTML を用意する（自動投稿はしない）。
        """
        product = self.c.storage.get("products", product_id)
        if product is None:
            raise KeyError(product_id)
        arts = self.c.storage.find("articles", product_id=product_id)
        if not arts:
            raise ValueError(f"記事が見つかりません: {product_id}")
        body = arts[-1].get("body_markdown", "")
        title = product.get("title") or ""
        # 本文が H1 で始まらなければタイトルを先頭に補う。
        md = body if body.lstrip().startswith("# ") else f"# {title}\n\n{body}"
        return {
            "product_id": product_id, "title": title,
            "price_jpy": product.get("price_jpy"),
            "hashtags": self._hashtags(product),
            "html": md_to_html(md),
        }


# ---- インポート（売上/PV 取り込み, 付録A #2） ----------------------------

# 列名のゆらぎ → 内部キー。小文字化・空白除去して照合する。
_COLUMN_ALIASES: dict[str, list[str]] = {
    "title": ["タイトル", "記事タイトル", "コンテンツ名", "コンテンツ", "title", "記事"],
    "url": ["url", "記事url", "リンク", "ノートurl", "コンテンツurl"],
    "pv": ["ビュー", "ビュー数", "閲覧数", "pv", "アクセス数", "views", "全体ビュー"],
    "purchases": ["購入数", "販売数", "売上件数", "購入", "sales", "販売件数"],
    "revenue": ["売上金額", "売上", "金額", "revenue", "販売金額", "売上高"],
    "likes": ["スキ", "スキ数", "いいね", "likes", "like"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).strip().lower()


def _to_int(v: Any) -> int:
    if v is None:
        return 0
    digits = re.sub(r"[^0-9\-]", "", str(v))
    try:
        return int(digits) if digits not in ("", "-") else 0
    except ValueError:
        return 0


class NoteImporter:
    def __init__(self, company):
        self.c = company

    def _resolve_columns(self, fieldnames: list[str]) -> dict[str, str]:
        """CSV の実列名 → 内部キー の対応を作る。"""
        mapping: dict[str, str] = {}
        norm_fields = {_norm(f): f for f in fieldnames}
        for key, aliases in _COLUMN_ALIASES.items():
            for a in aliases:
                na = _norm(a)
                # 完全一致優先、無ければ部分一致
                if na in norm_fields:
                    mapping[key] = norm_fields[na]
                    break
            else:
                for nf, orig in norm_fields.items():
                    if any(_norm(a) in nf for a in aliases):
                        mapping[key] = orig
                        break
        return mapping

    def _find_product(self, *, url: str, title: str) -> dict | None:
        products = self.c.storage.all("products")
        if url:
            for p in products:
                if p.get("url") and _norm(p["url"]) == _norm(url):
                    return p
        if title:
            nt = _norm(title)
            for p in products:  # 完全一致
                if _norm(p.get("title", "")) == nt:
                    return p
            for p in products:  # 部分一致
                if nt and (nt in _norm(p.get("title", "")) or _norm(p.get("title", "")) in nt):
                    return p
        return None

    def import_csv(self, source: str, *, dry_run: bool = False) -> dict[str, Any]:
        """CSV（ファイルパス or 生テキスト）を取り込む。

        note の売上/アクセス CSV を想定。タブ区切りも自動判定する。
        """
        text = self._read(source)
        # 区切り文字を推定
        sample = text[:2000]
        delim = "\t" if sample.count("\t") > sample.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        if not reader.fieldnames:
            return {"error": "ヘッダー行が読めません", "matched": 0, "unmatched": []}
        cols = self._resolve_columns(list(reader.fieldnames))
        if "title" not in cols and "url" not in cols:
            return {"error": "タイトル列も URL 列も見つかりません",
                    "columns_seen": reader.fieldnames, "matched": 0, "unmatched": []}

        matched, updated, unmatched = 0, [], []
        for row in reader:
            title = row.get(cols.get("title", ""), "") if "title" in cols else ""
            url = row.get(cols.get("url", ""), "") if "url" in cols else ""
            if not (title or url):
                continue
            product = self._find_product(url=url, title=title)
            if product is None:
                unmatched.append(title or url)
                continue
            matched += 1
            pv = _to_int(row.get(cols["pv"])) if "pv" in cols else product.get("pv", 0)
            purchases = _to_int(row.get(cols["purchases"])) if "purchases" in cols else product.get("purchases", 0)
            revenue = _to_int(row.get(cols["revenue"])) if "revenue" in cols else product.get("revenue_jpy", 0)
            likes = _to_int(row.get(cols["likes"])) if "likes" in cols else product.get("likes", 0)
            if not dry_run:
                self.c.record_metrics(product["id"], pv=pv, purchases=purchases,
                                      revenue_jpy=revenue, likes=likes)
            updated.append({"product_id": product["id"], "title": product.get("title"),
                            "pv": pv, "purchases": purchases, "revenue_jpy": revenue})
        if matched and not dry_run:
            self.c.memory.add("customer", "note実績をCSV取り込み",
                              f"{matched}件更新", tags=["note"])
        return {"columns": cols, "matched": matched, "updated": updated,
                "unmatched": unmatched, "dry_run": dry_run}

    @staticmethod
    def _read(source: str) -> str:
        p = pathlib.Path(source)
        try:
            if len(source) < 4096 and p.exists():
                return p.read_text(encoding="utf-8-sig")
        except (OSError, ValueError):
            pass
        return source  # 生テキストとして扱う

    @staticmethod
    def template_csv() -> str:
        return "タイトル,URL,ビュー,購入数,売上金額,スキ\n見出しの例,https://note.com/xxx/n/xxxx,1200,30,3000,45\n"
