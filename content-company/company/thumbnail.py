"""note サムネイル画像（SVG）の自動生成 (付録A #2 の成果物拡張)。

外部通信・画像ライブラリを使わず、標準ライブラリのみで **SVG** を組み立てる。
note は PNG/JPG をアップロードするため、GUI 側で SVG を canvas 経由 PNG に
変換してダウンロードする（ブラウザ内処理・外部送信なし）。

推奨サイズは 1280x670（note のヘッダ画像比率に近い 1.91:1 相当）。
"""

from __future__ import annotations

from html import escape as _esc

# カテゴリー → 背景グラデーション（上→下）とアクセント色。
_PALETTE: dict[str, tuple[str, str, str]] = {
    "A": ("#f59e0b", "#b45309", "#fff7ed"),  # 副業・お金
    "B": ("#6366f1", "#1e3a8a", "#eef2ff"),  # AI活用・効率化
    "C": ("#10b981", "#065f46", "#ecfdf5"),  # 学習・スキル
    "D": ("#f43f5e", "#9f1239", "#fff1f2"),  # 健康・習慣
    "E": ("#a855f7", "#6b21a8", "#faf5ff"),  # 人間関係・メンタル
}
_DEFAULT = ("#334155", "#0f172a", "#f1f5f9")


# 区切り候補（この文字の直後で改行してよい）。単語途中の分断を避ける。
_BREAK_AFTER = "｜|・/／、，。&＆:：〜～ 　-—"


def _wrap(title: str, max_lines: int = 4) -> tuple[list[str], int]:
    """タイトルを区切り優先で折り返す。全文を表示し、途中で切らない。

    返り値は (行リスト, 1行あたりの目安文字数)。行数が max_lines に収まるよう
    1行の文字数を決め、区切り記号の直後で改行する。長すぎる語のみ強制分割。
    """
    title = " ".join(title.split()) or "(無題)"
    n = len(title)
    # max_lines 行に収まる 1行文字数（8〜16 でクランプ）
    per_line = max(8, min(16, -(-n // max_lines)))
    # 区切りごとにトークン化（区切り文字は直前トークンに含める）
    tokens: list[str] = []
    cur = ""
    for ch in title:
        cur += ch
        if ch in _BREAK_AFTER:
            tokens.append(cur)
            cur = ""
    if cur:
        tokens.append(cur)
    # 貪欲に詰める。少しの余裕(slack)で末尾1〜2字の孤立や単語途中分割を避ける。
    limit = per_line + 2
    lines: list[str] = []
    line = ""
    for tok in tokens:
        while len(tok) > limit:
            if line:
                lines.append(line)
                line = ""
            lines.append(tok[:per_line])
            tok = tok[per_line:]
        if line and len(line) + len(tok) > limit:
            lines.append(line)
            line = tok
        else:
            line += tok
    if line:
        lines.append(line)
    return [ln.rstrip() for ln in lines], per_line


def svg(product: dict, width: int = 1280, height: int = 670) -> str:
    cat = str(product.get("category", ""))
    c1, c2, accent = _PALETTE.get(cat, _DEFAULT)
    title = str(product.get("title", "無題"))

    lines, per_line = _wrap(title)
    pad = 80
    # 幅に収まるフォントサイズ（1行の文字数から算出、40〜72 でクランプ）。
    font_size = max(40, min(72, int((width - pad * 2) / max(per_line, 1))))
    line_h = int(font_size * 1.34)
    block_h = line_h * len(lines)
    start_y = (height - block_h) // 2 + font_size
    tspans = "".join(
        f'<tspan x="{pad}" y="{start_y + i * line_h}">{_esc(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui,\'Segoe UI\','
        f"'Hiragino Kaku Gothic ProN','Yu Gothic',Meiryo,sans-serif\">"
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
        f"</linearGradient></defs>"
        f'<rect width="{width}" height="{height}" fill="url(#g)"/>'
        # 左の縦アクセントバー（装飾のみ）
        f'<rect x="0" y="0" width="16" height="{height}" fill="{accent}" opacity="0.9"/>'
        # タイトル（縦中央）
        f'<text font-size="{font_size}" font-weight="800" fill="#ffffff">{tspans}</text>'
        f"</svg>"
    )
