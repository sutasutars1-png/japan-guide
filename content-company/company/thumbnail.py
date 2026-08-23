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


def _wrap(title: str, per_line: int = 11, max_lines: int = 3) -> list[str]:
    """全角想定でタイトルを機械的に折り返す（SVG は自動改行しないため）。"""
    title = " ".join(title.split())
    lines: list[str] = []
    cur = ""
    for ch in title:
        cur += ch
        if len(cur) >= per_line:
            lines.append(cur)
            cur = ""
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if not lines:
        lines = ["(無題)"]
    # 収まり切らない場合は末尾に … を付ける
    if len(lines) == max_lines and len("".join(lines)) < len(title):
        lines[-1] = lines[-1][:per_line - 1] + "…"
    return lines


def svg(product: dict, width: int = 1280, height: int = 670) -> str:
    cat = str(product.get("category", ""))
    c1, c2, accent = _PALETTE.get(cat, _DEFAULT)
    title = str(product.get("title", "無題"))
    theme = str(product.get("theme", ""))
    price = product.get("price_jpy")
    badge = f"{('カテゴリ ' + cat + ' ・ ') if cat else ''}{theme}".strip(" ・")

    lines = _wrap(title)
    # タイトルを縦中央に配置
    font_size = 74 if max(len(x) for x in lines) <= 9 else 62
    line_h = font_size + 22
    block_h = line_h * len(lines)
    start_y = (height - block_h) // 2 + font_size
    tspans = "".join(
        f'<tspan x="80" y="{start_y + i * line_h}">{_esc(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    price_tag = ""
    if isinstance(price, (int, float)) and price:
        price_tag = (
            f'<g><rect x="{width - 250}" y="{height - 110}" rx="16" '
            f'width="170" height="60" fill="{accent}" opacity="0.95"/>'
            f'<text x="{width - 165}" y="{height - 68}" text-anchor="middle" '
            f'font-size="34" font-weight="700" fill="{c2}">¥{int(price)}</text></g>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui,\'Segoe UI\','
        f"'Hiragino Kaku Gothic ProN','Yu Gothic',Meiryo,sans-serif\">"
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
        f"</linearGradient></defs>"
        f'<rect width="{width}" height="{height}" fill="url(#g)"/>'
        # 左の縦アクセントバー
        f'<rect x="0" y="0" width="16" height="{height}" fill="{accent}" opacity="0.9"/>'
        # カテゴリ/テーマのバッジ
        f'<rect x="80" y="70" rx="22" width="{min(len(badge) * 26 + 60, width - 160)}" '
        f'height="52" fill="{accent}" opacity="0.9"/>'
        f'<text x="110" y="106" font-size="30" font-weight="700" fill="{c2}">'
        f"{_esc(badge)}</text>"
        # タイトル
        f'<text font-size="{font_size}" font-weight="800" fill="#ffffff" '
        f'style="paint-order:stroke">{tspans}</text>'
        # フッター（媒体名っぽい装飾）
        f'<text x="80" y="{height - 68}" font-size="30" fill="#ffffff" '
        f'opacity="0.85">note で公開</text>'
        f"{price_tag}"
        f"</svg>"
    )
