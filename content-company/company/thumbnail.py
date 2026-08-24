"""note サムネイル画像（SVG）の自動生成 (付録A #2 の成果物拡張)。

外部通信・画像ライブラリを使わず、標準ライブラリのみで **SVG** を組み立てる。
note は PNG/JPG をアップロードするため、GUI 側で SVG を canvas 経由 PNG に
変換してダウンロードする（ブラウザ内処理・外部送信なし）。

推奨サイズは 1280x670（note のヘッダ画像比率に近い 1.91:1 相当）。
"""

from __future__ import annotations

from html import escape as _esc

# テーマ別アクセント。背景は共通の上質なダーク基調にして、アクセントで差別化。
# (accent, accent2) — accent2 は装飾グラデ用の第2色。
_PALETTE: dict[str, tuple[str, str]] = {
    "A": ("#fbbf24", "#f97316"),  # 副業・お金（ゴールド→オレンジ）
    "B": ("#38bdf8", "#6366f1"),  # AI活用・効率化（シアン→インディゴ）
    "C": ("#34d399", "#14b8a6"),  # 学習・スキル（グリーン→ティール）
    "D": ("#fb7185", "#f43f5e"),  # 健康・習慣（ローズ）
    "E": ("#c084fc", "#a855f7"),  # 人間関係・メンタル（パープル）
}
_DEFAULT = ("#818cf8", "#38bdf8")
_BG1 = "#0b1220"   # 上（やや明るいダークネイビー）
_BG2 = "#05070d"   # 下（ほぼ黒）


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
    a1, a2 = _PALETTE.get(cat, _DEFAULT)
    title = str(product.get("title", "無題"))

    lines, per_line = _wrap(title)
    pad = 96
    # 幅に収まるフォントサイズ（1行の文字数から算出、42〜78 でクランプ）。
    font_size = max(42, min(78, int((width - pad * 2) / max(per_line, 1))))
    line_h = int(font_size * 1.32)
    block_h = line_h * len(lines)
    # ヘッダの帯（上）を避けて、やや上寄りの中央に配置。
    start_y = (height - block_h) // 2 + font_size - 6
    tspans = "".join(
        f'<tspan x="{pad}" y="{start_y + i * line_h}">{_esc(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    # タイトル1行目の下に引くアクセント下線の位置
    underline_y = start_y - font_size + int(font_size * 1.28)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui,\'Segoe UI\','
        f"'Hiragino Kaku Gothic ProN','Yu Gothic',Meiryo,sans-serif\">"
        f"<defs>"
        f'<linearGradient id="bg" x1="0" y1="0" x2="0.4" y2="1">'
        f'<stop offset="0" stop-color="{_BG1}"/><stop offset="1" stop-color="{_BG2}"/>'
        f"</linearGradient>"
        f'<linearGradient id="acc" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{a1}"/><stop offset="1" stop-color="{a2}"/>'
        f"</linearGradient>"
        f'<radialGradient id="glow" cx="0.85" cy="0.12" r="0.6">'
        f'<stop offset="0" stop-color="{a1}" stop-opacity="0.30"/>'
        f'<stop offset="1" stop-color="{a1}" stop-opacity="0"/>'
        f"</radialGradient>"
        f"</defs>"
        f'<rect width="{width}" height="{height}" fill="url(#bg)"/>'
        # 右上のソフトなグロー（奥行き）
        f'<rect width="{width}" height="{height}" fill="url(#glow)"/>'
        # 右上に大きな半透明リング（装飾）
        f'<circle cx="{width - 120}" cy="90" r="240" fill="none" '
        f'stroke="{a1}" stroke-opacity="0.10" stroke-width="60"/>'
        # 左上のブランドマーク（小さな四角＋ライン）
        f'<rect x="{pad}" y="70" width="34" height="34" rx="9" fill="url(#acc)"/>'
        f'<rect x="{pad + 48}" y="85" width="150" height="6" rx="3" '
        f'fill="#ffffff" opacity="0.28"/>'
        # タイトル1行目の下のアクセント下線
        f'<rect x="{pad}" y="{underline_y}" width="132" height="10" rx="5" '
        f'fill="url(#acc)"/>'
        # タイトル（白・太字・自動改行）
        f'<text font-size="{font_size}" font-weight="800" fill="#f8fafc" '
        f'letter-spacing="0.5">{tspans}</text>'
        # 下部のヘアライン
        f'<rect x="{pad}" y="{height - 74}" width="{width - pad * 2}" height="2" '
        f'fill="#ffffff" opacity="0.10"/>'
        f"</svg>"
    )
