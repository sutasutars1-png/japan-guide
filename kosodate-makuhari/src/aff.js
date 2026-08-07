// アフィリエイト・スロット設定（環境変数ゲート。未設定・OFFなら一切表示しない）
// 有効化：Cloudflare Pages のビルド環境変数に以下を設定して再デプロイ
//   PUBLIC_AFF_ENABLED=true
//   PUBLIC_AFF_TICKET_URL=<体験チケットの提携リンク>
//   PUBLIC_AFF_HOTEL_URL=<宿の提携リンク>
export const AFF = {
  enabled: import.meta.env.PUBLIC_AFF_ENABLED === 'true',
  ticket: import.meta.env.PUBLIC_AFF_TICKET_URL || '',
  hotel: import.meta.env.PUBLIC_AFF_HOTEL_URL || '',
};

// チケット枠は体験系カテゴリのみ。宿枠は全カテゴリ（近くの宿）。1ページ最大2枠。
const TICKET_CATS = new Set(["あそび場・体験", "動物とふれあう", "水あそび", "学ぶ・科学館"]);

export function affSlots(cat){
  if (!AFF.enabled) return [];
  const slots = [];
  if (AFF.ticket && TICKET_CATS.has(cat)) slots.push({ label: "チケット予約（提携サイト）", url: AFF.ticket });
  if (AFF.hotel) slots.push({ label: "近くの宿をさがす（提携サイト）", url: AFF.hotel });
  return slots.slice(0, 2);
}
