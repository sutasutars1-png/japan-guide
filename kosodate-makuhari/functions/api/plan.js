// Cloudflare Pages Function : AI旅程生成（Gemini API・無料枠を利用）
// 事前に: wrangler pages secret put GEMINI_API_KEY   （キーは https://aistudio.google.com で取得）
const SYSTEM = `あなたは子連れの「楽しいおでかけ」プランナー。渡された候補地リストのみを使い、リスト外の場所・事実を一切追加しない。
楽しさ（遊び・体験・発見）を主役に、各stopの why には「何が楽しいか・どんな子におすすめか」を書く。
設備・料金・営業などの固有情報は断定しない（候補データに無い情報は述べない）。
昼寝(0〜2歳は12-14時)・食事・休憩は「配慮」として caveats に添える。
食事に触れる stop には caveats に「アレルギー等は店舗へご確認ください」を必ず入れる。
訪問は最大3〜4か所。候補が薄ければ data_gaps に正直に書く。
出力は指定JSONのみ。前置き・説明・思考は書かず、JSONオブジェクトだけを返す。`;

const json = (o) => new Response(JSON.stringify(o), { headers: { "content-type": "application/json" } });

export async function onRequestPost(context){
  const { request, env } = context;

  if (!env.GEMINI_API_KEY) {
    return json({ summary: "提案を生成できませんでした", stops: [], data_gaps: [
      "サーバに GEMINI_API_KEY が設定されていません。Pagesプロジェクトの環境変数に設定して再デプロイしてください。" ] });
  }

  const { age, allergy, candidates, span, rain, categories, amenities, center } = await request.json();
  const parts = [`子供:${age}歳帯`, `所要:${span || "半日"}`, `移動:徒歩圏`];
  if (center && center.name) parts.push(`起点:${center.name}（最初のstopは必ずここにし、以降はこの近くで構成する）`);
  if (rain) parts.push(`天候:雨（屋内中心にする）`);
  if (Array.isArray(categories) && categories.length) parts.push(`希望ジャンル:${categories.join("・")}`);
  if (Array.isArray(amenities) && amenities.length) parts.push(`重視設備:${amenities.join("・")}（候補データにその設備がある場所を優先）`);
  parts.push(`安全:${allergy ? "アレルギー配慮あり" : "指定なし"}`);
  const conditions = parts.join(" / ");
  const prompt = `候補地(JSON・各要素は{id,name,cat,amenities}): ${JSON.stringify(candidates)}
条件: ${conditions}
このリストのみを使い、リスト外の場所・事実は加えない。地域名や施設固有の事実は推測しない。
次のJSON形式だけで出力: {"summary":str,"stops":[{"time":str,"name":str,"why":str,"caveats":[str]}],"data_gaps":[str]}`;

  // 既定は常に最新のFlashを指すエイリアス。RPDを増やしたい場合は環境変数 GEMINI_MODEL=gemini-flash-lite-latest
  const model = env.GEMINI_MODEL || "gemini-flash-latest";

  let res, data;
  try {
    res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-goog-api-key": env.GEMINI_API_KEY },
      body: JSON.stringify({
        system_instruction: { parts: [{ text: SYSTEM }] },
        contents: [{ role: "user", parts: [{ text: prompt }] }],
        // 思考(thinking)モデルでも本文JSONを出し切れるよう上限を大きめに確保
        generationConfig: { maxOutputTokens: 8192, temperature: 0.4, responseMimeType: "application/json" }
      })
    });
    data = await res.json();
  } catch (e) {
    return json({ summary: "提案を生成できませんでした", stops: [], data_gaps: [
      `Geminiへの接続に失敗しました: ${String(e)}` ] });
  }

  if (!res.ok) {
    const msg = data?.error?.message || JSON.stringify(data).slice(0, 300);
    return json({ summary: "提案を生成できませんでした", stops: [], data_gaps: [
      `Gemini APIエラー (model=${model}): HTTP ${res.status} ${msg}` ] });
  }

  // 思考パート(thought:true)は除外し、本文パートのみを連結
  const text = (data?.candidates?.[0]?.content?.parts || [])
    .filter(p => !p.thought)
    .map(p => p.text || "").join("");
  let plan;
  try { const a = text.indexOf("{"), b = text.lastIndexOf("}"); plan = JSON.parse(text.slice(a, b + 1)); }
  catch(e) { plan = { summary: "提案を生成できませんでした", stops: [], data_gaps: [
    `応答を解析できませんでした（finishReason=${data?.candidates?.[0]?.finishReason || "不明"}）: ${text.slice(0, 200)}` ] }; }
  return json(plan);
}
