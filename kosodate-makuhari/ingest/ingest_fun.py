"""
楽しさ版 データ取込（公園フィルタ・マージ対応版）
OSM(tourism/leisure)＋千葉市OD →「楽しい施設」を分類し data/spots.json 生成。
公園は「行き先になる規模/著名/名称」に絞り、同一公園の断片を統合（1公園=1件）。
無料・鍵不要・LLM不使用（紹介文はカテゴリ別テンプレ）。
"""
import urllib.request, urllib.parse, csv, io, json, re, math, collections
BBOX=(35.55,140.02,35.73,140.22)  # 千葉市周辺。拡張時はここを変える
CHIBA_CSV="https://www.city.chiba.jp/sogoseisaku/shichokoshitsu/kohokocho/documents/export_r7.csv"
INTRO={
 "あそび場・体験":"天候を気にせず遊べる室内あそび場・体験施設。小さな子でも一日楽しめます。",
 "動物とふれあう":"動物を間近に見られるスポット。ふれあいや観察で、こどもの好奇心が育ちます。",
 "水族館":"水の生き物を楽しく観察できるスポット。雨の日のお出かけにも。",
 "学ぶ・科学館":"見て・触れて学べる展示が楽しめるスポット。雨の日のお出かけにもぴったり。",
 "公園でのびのび":"広場や遊具でのびのび遊べる公園。ベビーカー散歩やピクニックにも。",
 "水あそび":"水遊びが楽しめるスポット。夏のおでかけや水遊びデビューに。",
 "美術・文化":"アートや文化にふれられるスポット。親子で静かに楽しめます。",
 "観光・名所":"地域の見どころスポット。おさんぽやおでかけの目的地に。",
}
DEST=re.compile(r"総合|運動|海浜|自然|森|フラワー|りんかい|中央公園|スポーツ|プール|こども|子ども|ふるさと|里山")
def contact(t):
    web=t.get("website") or t.get("contact:website") or ""
    tel=t.get("phone") or t.get("contact:phone") or ""
    img=t.get("wikimedia_commons") or ""
    img=img if img.startswith("File:") else ""
    return web, tel, img
def inbox(la,ln): return BBOX[0]<=la<=BBOX[2] and BBOX[1]<=ln<=BBOX[3]
def overpass(q):
    body=urllib.parse.urlencode({"data":q}).encode()
    for url in ("https://overpass-api.de/api/interpreter","https://overpass.kumi.systems/api/interpreter","https://maps.mail.ru/osm/tools/overpass/api/interpreter"):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(url,data=body,headers={"User-Agent":"kosodate/0.1"}),timeout=180)).get("elements",[])
        except Exception as e: print("osm retry",str(e)[:40])
    return []
def area_m2(g):
    if not g or len(g)<3: return 0
    lat0=sum(p["lat"] for p in g)/len(g); mlat=111320; mlon=111320*math.cos(math.radians(lat0))
    pts=[(p["lon"]*mlon,p["lat"]*mlat) for p in g]; s=0
    for i in range(len(pts)):
        x1,y1=pts[i];x2,y2=pts[(i+1)%len(pts)];s+=x1*y2-x2*y1
    return abs(s)/2
def norm(n): return re.sub(r"[（(].*?[）)]|ブロック|地区|Ｄ・Ｅ・Ｆ|\s","",n)

spots=[]; seen=set()
# --- 楽しい施設(点/面) ---
q1=f'''[out:json][timeout:60];(
 nwr["tourism"~"^(theme_park|zoo|aquarium|museum)$"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
 nwr["leisure"="water_park"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);out center tags;'''
def classify(t):
    tour=t.get("tourism"); n=t.get("name","")
    if tour=="theme_park": return "あそび場・体験"
    if tour=="zoo": return "動物とふれあう"
    if tour=="aquarium": return "水族館"
    if tour=="museum": return "美術・文化" if "美術" in n else "学ぶ・科学館"
    if t.get("leisure")=="water_park": return "水あそび"
    return None
for e in overpass(q1):
    t=e.get("tags",{}); c=classify(t); n=t.get("name")
    la=e.get("lat") or e.get("center",{}).get("lat"); ln=e.get("lon") or e.get("center",{}).get("lon")
    if not(c and n and la and ln and inbox(la,ln)) or n in seen: continue
    seen.add(n)
    amen=[k for tag,k in [("changing_table","おむつ替え"),("wheelchair","段差なし")] if t.get(tag) in ("yes","limited")]
    web,tel,img=contact(t)
    spots.append({"name":n,"cat":c,"lat":la,"lng":ln,"amenities":amen,"website":web,"phone":tel,"image_commons":img,"has_image":bool(img),"intro":INTRO.get(c,"")})

# --- 公園（面積で geom 取得 → 行き先フィルタ → 同名近接マージ） ---
q2=f'''[out:json][timeout:90];way["leisure"="park"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});out geom;'''
cand=[]
for e in overpass(q2):
    t=e.get("tags",{}); n=t.get("name"); g=e.get("geometry")
    if not(n and g): continue
    a=area_m2(g); cx=sum(p["lon"] for p in g)/len(g); cy=sum(p["lat"] for p in g)/len(g)
    notable=any(k in t for k in ("wikipedia","wikidata","wikimedia_commons"))
    if a>=10000 or notable or DEST.search(n):
        web,tel,img=contact(t)
        cand.append({"n":n,"a":a,"cx":cx,"cy":cy,"img":img,"web":web})
def dm(a,b): return math.hypot((a[0]-b[0])*111320*math.cos(math.radians(35.6)),(a[1]-b[1])*111320)
byn=collections.defaultdict(list)
for i,p in enumerate(cand): byn[norm(p["n"])].append(i)
for key,idxs in byn.items():
    groups=[]
    for i in idxs:
        for gr in groups:
            if dm((cand[i]["cx"],cand[i]["cy"]),(cand[gr[0]]["cx"],cand[gr[0]]["cy"]))<600: gr.append(i);break
        else: groups.append([i])
    for gr in groups:
        b=max(gr,key=lambda i:cand[i]["a"]); p=cand[b]
        nm=re.sub(r"\s*[（(].*?[）)]\s*","",p["n"]).strip() or p["n"]
        if nm in seen: continue
        seen.add(nm)
        spots.append({"name":nm,"cat":"公園でのびのび","lat":p["cy"],"lng":p["cx"],"amenities":[],"website":p.get("web",""),"phone":"","image_commons":p.get("img",""),"has_image":bool(p.get("img")),"intro":INTRO["公園でのびのび"]})

# --- 千葉市OD 観光/文化 ---
try:
    txt=urllib.request.urlopen(CHIBA_CSV,timeout=60).read().decode("cp932",errors="replace")
    G={"観光施設":"観光・名所","図書館":"学ぶ・科学館"}
    for r in csv.DictReader(io.StringIO(txt)):
        g=r.get("施設ジャンル"); n=r.get("ページタイトル")
        if g in G and n and n not in seen:
            try: la,ln=float(r["緯度"]),float(r["経度"])
            except: continue
            if not inbox(la,ln): continue
            seen.add(n); c=G[g]; spots.append({"name":n,"cat":c,"lat":la,"lng":ln,"amenities":[],"website":"","phone":"","image_commons":"","has_image":False,"intro":INTRO.get(c,"")})
except Exception as e: print("chiba OD skip:",e)

for i,s in enumerate(spots,1): s["id"]=f"s{i:04d}"
import os; os.makedirs("data",exist_ok=True)
json.dump(spots,open("data/spots.json","w"),ensure_ascii=False,indent=1)
by=collections.Counter(s["cat"] for s in spots)
print("data/spots.json 生成:",len(spots),"件 /",dict(by))
