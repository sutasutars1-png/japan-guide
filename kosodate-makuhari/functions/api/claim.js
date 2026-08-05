// Cloudflare Pages Function : 店舗自己申告(owner_claim)の受付。突合後に昇格(単独昇格しない)。
export async function onRequestPost(context){
  const { request, env } = context;
  const claim = await request.json(); // {place_id, attributes:[{key,value}], contact}
  claim.status = "reviewed_false"; claim.received_at = new Date().toISOString();
  // KVをバインドしていれば保存(未バインドなら受領のみ)。一般ユーザー投稿は受け付けない前提。
  if (env.CLAIMS) await env.CLAIMS.put(`claim:${Date.now()}`, JSON.stringify(claim));
  return new Response(JSON.stringify({ ok:true, note:"受領しました。他ソースと突合後に反映します。" }),
    { headers:{ "content-type":"application/json" }});
}
