"""ローカル Web GUI（標準ライブラリ http.server のみ）。

`python3 -m company gui` で起動し、ブラウザから会社 OS を操作する。npm も外部
パッケージも不要（§36）。人間の役割＝経営判断・承認（§3.3, §21）に集中できる
よう、**承認待ち**と**次アクション**を中心に据えたコックピット。

エンドポイント（すべて 127.0.0.1 既定）:
  GET  /                     コックピット HTML
  GET  /dashboard            §25 ダッシュボード（iframe 埋め込み用）
  GET  /api/state            KPI・進捗・承認待ち・商品・スキル をまとめて返す
  POST /api/plan             {n, llm}   企画パイプライン実行
  POST /api/approve|reject   {approval_id}
  POST /api/publish          {product_id, url, approval_id}
  POST /api/metrics          {product_id, pv, purchases, revenue, likes, rating}
  POST /api/evaluate         {}
  POST /api/demo             {}
  GET  /api/report?period=
  GET  /api/memory?query=&kind=
  POST /api/skill/propose|evaluate|request-adoption|adopt
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import dashboard
from .approval import PermissionError_
from .company import Company


def _state(c: Company) -> dict:
    products = c.storage.all("products")
    pending = c.approvals.pending()
    # product_id → 未処理の publish 承認 id
    pub_apr = {a["payload"].get("product_id"): a["id"]
               for a in pending if a.get("kind") == "publish"}
    prod_rows = [{
        "id": p["id"], "title": p.get("title"), "category": p.get("category"),
        "status": p.get("status"), "pv": p.get("pv", 0),
        "purchases": p.get("purchases", 0), "revenue_jpy": p.get("revenue_jpy", 0),
        "conversion_rate": p.get("conversion_rate", 0), "outcome": p.get("outcome"),
        "url": p.get("url"), "approval_id": pub_apr.get(p["id"]),
    } for p in products]
    prod_rows.sort(key=lambda r: (r["status"] != "awaiting_approval", r["id"]))
    return {
        "summary": c.kpi.summary(),
        "progress": c.experiments.progress(),
        "pending": pending,
        "products": prod_rows,
        "skills": c.skills_lab.all_current(),
        "tasks_today": c.cost.tasks_today(),
        "max_tasks_per_day": c.config.max_tasks_per_day,
        "runner": type(c.tasks.runner).__name__,
    }


class _Handler(BaseHTTPRequestHandler):
    company: Company = None  # type: ignore[assignment]
    server_version = "CompanyGUI/0.1"

    def log_message(self, *a):  # 静かに
        pass

    # ---- helpers ----------------------------------------------------------

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    # ---- GET --------------------------------------------------------------

    def do_GET(self):
        u = urlparse(self.path)
        c = self.company
        try:
            if u.path == "/":
                self._send(200, _INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif u.path == "/dashboard":
                self._send(200, dashboard.render(c).encode("utf-8"),
                           "text/html; charset=utf-8")
            elif u.path == "/api/state":
                self._json(_state(c))
            elif u.path == "/api/report":
                q = parse_qs(u.query)
                self._json(c.report((q.get("period") or [None])[0]))
            elif u.path == "/api/memory":
                q = parse_qs(u.query)
                text = (q.get("query") or [None])[0]
                kind = (q.get("kind") or [None])[0]
                self._json(c.memory.query(text=text, kind=kind) if (text or kind)
                           else c.memory.recent(30))
            elif u.path == "/api/skill/versions":
                q = parse_qs(u.query)
                self._json(c.skills_lab.versions((q.get("key") or [""])[0]))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, 500)

    # ---- POST -------------------------------------------------------------

    def do_POST(self):
        u = urlparse(self.path)
        c = self.company
        b = self._body()
        try:
            if u.path == "/api/plan":
                if b.get("llm"):
                    enabled = c.enable_llm()
                    if not enabled:
                        return self._json({"error": "claude CLI 未検出。雛形で継続してください。"}, 400)
                res = c.plan_products(int(b.get("n", 5)))
                self._json({"planned": res})
            elif u.path == "/api/approve":
                self._json(c.approvals.approve(b["approval_id"]).to_dict())
            elif u.path == "/api/reject":
                self._json(c.approvals.reject(b["approval_id"], note=b.get("note", "")).to_dict())
            elif u.path == "/api/publish":
                p = c.publish(b["product_id"], b["url"], b["approval_id"])
                self._json(p.to_dict())
            elif u.path == "/api/metrics":
                p = c.record_metrics(
                    b["product_id"], pv=int(b.get("pv", 0)),
                    purchases=int(b.get("purchases", 0)),
                    revenue_jpy=int(b.get("revenue", 0)), likes=int(b.get("likes", 0)),
                    rating=b.get("rating"))
                self._json(p.to_dict())
            elif u.path == "/api/evaluate":
                self._json(c.evaluate())
            elif u.path == "/api/demo":
                from .seed import seed_demo, DemoRunner
                c.tasks.runner = DemoRunner()
                self._json(seed_demo(c)["summary"])
            elif u.path == "/api/skill/propose":
                self._json(c.skills_lab.propose(
                    b["key"], purpose=b.get("purpose"), success=b.get("success"),
                    guidance=b.get("guidance"),
                    forbidden=b.get("forbidden") or None))
            elif u.path == "/api/skill/evaluate":
                self._json(c.skills_lab.evaluate(b["key"], int(b["version"])))
            elif u.path == "/api/skill/request-adoption":
                self._json(c.skills_lab.request_adoption(b["key"], int(b["version"])))
            elif u.path == "/api/skill/adopt":
                self._json(c.skills_lab.adopt(b["key"], int(b["version"]), b["approval_id"]))
            elif u.path == "/api/note/export":
                self._json(c.note_export.export(b["product_id"]))
            elif u.path == "/api/note/import":
                self._json(c.note_import.import_csv(b.get("csv", ""),
                                                    dry_run=bool(b.get("dry_run"))))
            else:
                self._json({"error": "not found"}, 404)
        except PermissionError_ as exc:
            self._json({"error": str(exc)}, 403)
        except KeyError as exc:
            self._json({"error": f"missing/invalid: {exc}"}, 400)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, 500)


def serve(company: Company, *, host: str = "127.0.0.1", port: int = 8787,
          llm: bool = False) -> None:
    if llm:
        ok = company.enable_llm()
        print("実 LLM:", "有効 (Claude Code CLI)" if ok else "無効 (claude 未検出) → 雛形")
    _Handler.company = company
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"AI会社 GUI 起動: http://{host}:{port}/  (Ctrl+C で停止)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました。")
    finally:
        httpd.server_close()


# --- 単一ページ・コックピット（外部依存なし） ---------------------------
_INDEX_HTML = r"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI会社 コックピット</title>
<style>
:root{color-scheme:light dark;--bg:#0b0e14;--panel:#151b2b;--line:#232838;--fg:#e6e9ef;
--muted:#8b97b0;--accent:#4f8cff;--good:#3fbf7f;--warn:#e0b341;--bad:#e06666}
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
margin:0;background:var(--bg);color:var(--fg);line-height:1.55}
header{padding:16px 22px;border-bottom:1px solid var(--line);background:#111624;
display:flex;align-items:center;gap:14px;flex-wrap:wrap}
h1{font-size:17px;margin:0} h2{font-size:14px;color:#9fb4d8;margin:22px 0 8px}
main{padding:16px 22px 60px;max-width:1080px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.card .k{font-size:12px;color:var(--muted)} .card .v{font-size:20px;font-weight:650;margin-top:4px}
button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:7px 12px;
font-size:13px;cursor:pointer} button.ghost{background:#1e2a44;color:#cfe0ff}
button.good{background:var(--good)} button.bad{background:var(--bad)} button:disabled{opacity:.5;cursor:wait}
input,select{background:#0f1422;color:var(--fg);border:1px solid var(--line);border-radius:7px;
padding:6px 8px;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px;background:var(--panel);
border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:middle}
th{background:#1a2133;color:#9fb4d8} .pill{padding:1px 8px;border-radius:999px;font-size:11px;background:#1e2a44}
.pill.await{background:#3a2f10;color:var(--warn)} .pill.pub{background:#123524;color:var(--good)}
.muted{color:var(--muted)} .overflow{overflow-x:auto}
#toast{position:fixed;right:16px;bottom:16px;background:#1a2133;border:1px solid var(--line);
padding:10px 14px;border-radius:8px;max-width:380px;display:none;font-size:13px;white-space:pre-wrap}
details{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-top:8px}
summary{cursor:pointer;color:#9fb4d8}
iframe{width:100%;height:520px;border:1px solid var(--line);border-radius:10px;background:#fff}
</style></head><body>
<header>
  <h1>🏢 AI会社 コックピット</h1>
  <span class="muted" id="runner"></span>
  <span class="row" style="margin-left:auto">
    <label class="muted"><input type="checkbox" id="useLlm"> 実LLM生成</label>
    <input id="planN" type="number" value="5" min="1" max="20" style="width:60px">
    <button id="btnPlan">商品を企画</button>
    <button class="ghost" id="btnDemo">デモ投入</button>
    <button class="ghost" id="btnEval">評価</button>
    <button class="ghost" id="btnRefresh">更新</button>
  </span>
</header>
<main>
  <h2>経営 KPI</h2>
  <div class="grid" id="kpi"></div>

  <h2>⏳ 承認待ち（人間の判断ポイント · §21）</h2>
  <div class="overflow"><table id="pending"><thead><tr>
    <th>種別</th><th>内容</th><th>操作</th></tr></thead><tbody></tbody></table></div>

  <h2>📦 商品</h2>
  <div class="overflow"><table id="products"><thead><tr>
    <th>タイトル</th><th>カテゴリ</th><th>状態</th><th>PV</th><th>購入</th>
    <th>売上</th><th>評価</th><th>操作</th></tr></thead><tbody></tbody></table></div>

  <details><summary>🧠 Skill 自己改善（§20）</summary>
    <div id="skills" style="margin-top:8px"></div>
  </details>

  <details><summary>📤 note 連携（公開用エクスポート / 実績CSV取込 · §22, 付録A#2）</summary>
    <p class="muted" style="margin:8px 0">公開は note エディタに貼り付け（自動投稿はしない, §22）。
      売上/PV は note 管理画面の CSV をここに貼って取り込む。</p>
    <textarea id="noteCsv" placeholder="note の売上/アクセス CSV を貼り付け（タイトル,URL,ビュー,購入数,売上金額,スキ …）"
      style="width:100%;height:90px;background:#0f1422;color:var(--fg);border:1px solid var(--line);border-radius:7px;padding:8px"></textarea>
    <div class="row" style="margin-top:6px">
      <button class="ghost" id="btnImportDry">取り込み（下書き確認）</button>
      <button id="btnImport">取り込み実行</button>
    </div>
  </details>

  <details><summary>🔎 レポート / メモリ</summary>
    <div class="row" style="margin-top:8px">
      <button class="ghost" id="btnReport">先月レポート</button>
      <input id="memq" placeholder="メモリ検索（例: 副業）">
      <button class="ghost" id="btnMem">検索</button>
    </div>
    <pre id="out" class="muted" style="white-space:pre-wrap;margin-top:8px"></pre>
  </details>

  <details><summary>📊 ダッシュボード（§25）</summary>
    <iframe src="/dashboard" id="dash"></iframe>
  </details>
</main>
<div id="toast"></div>
<script>
const $=s=>document.querySelector(s), tbody=s=>$(s).querySelector('tbody');
function toast(m){const t=$('#toast');t.textContent=m;t.style.display='block';
  clearTimeout(window._t);window._t=setTimeout(()=>t.style.display='none',4000);}
async function api(path,method='GET',body){
  const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},
    body:body?JSON.stringify(body):undefined});
  const j=await r.json(); if(!r.ok) throw new Error(j.error||('HTTP '+r.status)); return j;}
const yen=n=>'¥'+(n||0).toLocaleString();
function esc(s){return String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

async function refresh(){
  const s=await api('/api/state');
  $('#runner').textContent='ランナー: '+s.runner+' · 本日タスク '+s.tasks_today+'/'+s.max_tasks_per_day
    +' · 実験 '+s.progress.created+'/'+s.progress.target_products;
  const k=s.summary;
  $('#kpi').innerHTML=[
    ['総売上',yen(k.total_revenue_jpy)],['今月売上',yen(k.month_revenue_jpy)],
    ['商品数',k.product_count],['公開',k.published_count],['購入',k.purchases],
    ['PV',(k.pv||0).toLocaleString()],['購入率',(k.conversion_rate*100).toFixed(1)+'%'],
    ['AIコスト',k.ai_cost_units],['1商品コスト',k.ai_cost_per_product]
  ].map(([a,b])=>`<div class="card"><div class="k">${a}</div><div class="v">${b}</div></div>`).join('');

  tbody('#pending').innerHTML=s.pending.length? s.pending.map(a=>`<tr>
    <td><span class="pill await">${esc(a.kind)}</span></td><td>${esc(a.summary)}</td>
    <td class="row">
      <button class="good" onclick="approve('${a.id}')">承認</button>
      <button class="bad" onclick="reject('${a.id}')">却下</button>
    </td></tr>`).join('') : '<tr><td colspan=3 class="muted">なし</td></tr>';

  tbody('#products').innerHTML=s.products.length? s.products.map(p=>{
    const st = p.status==='awaiting_approval'?'<span class="pill await">公開待ち</span>'
      : p.status==='published'?'<span class="pill pub">公開</span>':`<span class="pill">${esc(p.status)}</span>`;
    let act='';
    if(p.status==='awaiting_approval'&&p.approval_id)
      act=`<button class="good" onclick="approve('${p.approval_id}')">承認</button>`;
    else if(p.status==='awaiting_approval')
      act='<span class="muted">承認申請へ</span>';
    else if(p.status==='published')
      act=`<button class="ghost" onclick="metrics('${p.id}')">実績入力</button>`;
    if(p.status==='published'||p.status==='awaiting_approval')
      act+=` <button class="ghost" onclick="noteExport('${p.id}')">note出力</button>`;
    return `<tr><td>${esc(p.title)}</td><td>${esc(p.category)}</td><td>${st}</td>
      <td>${p.pv}</td><td>${p.purchases}</td><td>${yen(p.revenue_jpy)}</td>
      <td>${p.outcome?esc(p.outcome):'-'}</td><td class="row">${act}</td></tr>`;
  }).join('') : '<tr><td colspan=8 class="muted">まだ商品がありません。「商品を企画」から。</td></tr>';

  $('#skills').innerHTML='<div class="overflow"><table><thead><tr><th>Skill</th><th>現行版</th>'
    +'<th>改善案</th><th>操作</th></tr></thead><tbody>'
    + s.skills.map(sk=>`<tr><td>${esc(sk.key)}</td><td>v${sk.version}</td>
        <td>${sk.candidates}</td><td class="row">
        <button class="ghost" onclick="propose('${sk.key}')">改善案</button>
        <button class="ghost" onclick="showVersions('${sk.key}')">履歴</button></td></tr>`).join('')
    +'</tbody></table></div>';
  $('#dash').src='/dashboard?'+Date.now();
}
async function approve(id){try{await api('/api/approve','POST',{approval_id:id});
  const url=prompt('公開する場合は note の URL を入力（キャンセルで承認のみ）:');
  if(url){const pid=await findProductFor(id); if(pid) await api('/api/publish','POST',{product_id:pid,url,approval_id:id});}
  toast('承認しました');refresh();}catch(e){toast('エラー: '+e.message);}}
async function findProductFor(aid){const s=await api('/api/state');
  const p=s.products.find(x=>x.approval_id===aid);return p?p.id:null;}
async function reject(id){const note=prompt('却下理由（任意）')||'';
  try{await api('/api/reject','POST',{approval_id:id,note});toast('却下しました');refresh();}
  catch(e){toast('エラー: '+e.message);}}
async function metrics(pid){const pv=+prompt('PV',0),pu=+prompt('購入数',0),rev=+prompt('売上(円)',0);
  try{await api('/api/metrics','POST',{product_id:pid,pv,purchases:pu,revenue:rev});
  toast('実績を記録しました');refresh();}catch(e){toast('エラー: '+e.message);}}
async function propose(key){const guidance=prompt('改善したい手順・ガイダンス（v+1 として保存されます）');
  if(guidance==null)return; try{const v=await api('/api/skill/propose','POST',{key,guidance});
  await api('/api/skill/evaluate','POST',{key,version:v.version});
  const apr=await api('/api/skill/request-adoption','POST',{key,version:v.version});
  toast('改善案 v'+v.version+' を提案。承認待ちに追加（Skill採用）。');refresh();}
  catch(e){toast('エラー: '+e.message);}}
async function showVersions(key){const vs=await api('/api/skill/versions?key='+encodeURIComponent(key));
  $('#out').textContent=JSON.stringify(vs,null,2);toast('履歴を下部に表示');}
async function noteExport(pid){try{const r=await api('/api/note/export','POST',{product_id:pid});
  $('#out').textContent=r.markdown;
  try{await navigator.clipboard.writeText(r.markdown);toast('note本文をコピー＋書き出し: '+r.path);}
  catch(e){toast('note公開用を書き出し: '+r.path+'（下部に本文表示）');}
  }catch(e){toast('エラー: '+e.message);}}
async function noteImport(dry){try{const csv=$('#noteCsv').value;
  const r=await api('/api/note/import','POST',{csv,dry_run:dry});
  $('#out').textContent=JSON.stringify(r,null,2);
  toast((dry?'下書き: ':'取込: ')+'一致 '+r.matched+' 件 / 未一致 '+(r.unmatched||[]).length+' 件');
  if(!dry) refresh();}catch(e){toast('エラー: '+e.message);}}

$('#btnPlan').onclick=async()=>{const b=$('#btnPlan');b.disabled=true;b.textContent='実行中…';
  try{await api('/api/plan','POST',{n:+$('#planN').value,llm:$('#useLlm').checked});
  toast('企画を実行しました');refresh();}catch(e){toast('エラー: '+e.message);}
  finally{b.disabled=false;b.textContent='商品を企画';}};
$('#btnDemo').onclick=async()=>{if(!confirm('架空デモデータを投入します。よろしいですか？'))return;
  try{await api('/api/demo','POST',{});toast('デモ投入完了');refresh();}catch(e){toast(e.message);}};
$('#btnEval').onclick=async()=>{try{const r=await api('/api/evaluate','POST',{});
  $('#out').textContent=JSON.stringify(r.actions,null,2);toast('評価しました');refresh();}catch(e){toast(e.message);}};
$('#btnRefresh').onclick=refresh;
$('#btnImport').onclick=()=>noteImport(false);
$('#btnImportDry').onclick=()=>noteImport(true);
$('#btnReport').onclick=async()=>{const r=await api('/api/report');$('#out').textContent=JSON.stringify(r,null,2);};
$('#btnMem').onclick=async()=>{const r=await api('/api/memory?query='+encodeURIComponent($('#memq').value));
  $('#out').textContent=JSON.stringify(r,null,2);};
refresh();
</script></body></html>"""
