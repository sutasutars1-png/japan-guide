// Cloudflare Pages Function : AI旅程生成（Gemini API・無料枠を利用）
// 事前に: wrangler pages secret put GEMINI_API_KEY   （キーは https://aistudio.google.com で取得）
const SYSTEM = `あなたは子連れ旅程プランナー。渡された候補地リストのみを使い、リスト外の場所・事実を一切追加しない。
各stopは候補地の名称に基づき、候補データに無い設備は述べない（必要なら caveats に「要確認」）。
個別アレルゲンの対応可否は断定せず、食事の stop には caveats に「アレルギー詳細は店舗へご確認ください」を必ず入れる。
1歳帯の昼寝帯(12-14時)は屋外の軽移動か休憩に。訪問は最大3か所。候補が薄ければ data_gaps に正直に書く。
出力は指定JSONのみ。`;

const json = (o) => new Response(JSON.stringify(o), { headers: { "content-type": "application/json" } });

export async function onRequestPost(context){
  const { request, env } = context;

  if (!env.GEMINI_API_KEY) {
    return json({ summary: "提案を生成できませんでした", stops: [], data_gaps: [
      "サーバに GEMINI_API_KEY が設定されていません。Pagesプロジェクトの環境変数に設定して再デプロイしてください。" ] });
  }

  const { age, allergy, candidates } = await request.json();
  const conditions = `子供:${age}歳帯 / 拠点:海浜幕張 / 移動:徒歩 / 安全:${allergy?"アレルギー配慮あり":"なし"}`;
  const prompt = `候補地(JSON): ${JSON.stringify(candidates)}
条件: ${conditions}
次のJSON形式だけで出力: {"summary":str,"stops":[{"time":str,"name":str,"why":str,"caveats":[str]}],"data_gaps":[str]}`;

  const model = env.GEMINI_MODEL || "gemini-2.5-flash";

  let res, data;
  try {
    res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-goog-api-key": env.GEMINI_API_KEY },
      body: JSON.stringify({
        system_instruction: { parts: [{ text: SYSTEM }] },
        contents: [{ role: "user", parts: [{ text: prompt }] }],
        generationConfig: { maxOutputTokens: 1024, temperature: 0.4, responseMimeType: "application/json" }
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

  const text = (data?.candidates?.[0]?.content?.parts || []).map(p => p.text || "").join("");
  let plan;
  try { const a = text.indexOf("{"), b = text.lastIndexOf("}"); plan = JSON.parse(text.slice(a, b + 1)); }
  catch(e) { plan = { summary: "提案を生成できませんでした", stops: [], data_gaps: [
    `応答を解析できませんでした（finishReason=${data?.candidates?.[0]?.finishReason || "不明"}）: ${text.slice(0, 200)}` ] }; }
  return json(plan);
}
