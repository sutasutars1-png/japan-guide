"""
楽しさ版 データ取込 : OSM(tourism/leisure)＋千葉市OD で「楽しい施設」を分類し data/spots.json を生成。
無料・鍵不要・LLM不使用（紹介文はカテゴリ別テンプレ。AIエンリッチは任意=後段）。
"""
import urllib.request, urllib.parse, csv, io, json, re, collections
BBOX=(35.55,140.02,35.73,140.22)  # 千葉市周辺。拡張時はここを変える
OSM_SRC={"type":"opendata","by":"© OpenStreetMap contributors","lic":"ODbL"}
CHIBA_CSV="https://www.city.chiba.jp/sogoseisaku/shichokoshitsu/kohokocho/documents/export_r7.csv"
INTRO={
 "あそび場・体験":"天候を気にせず遊べる室内あそび場・体験施設。小さな子でも一日楽しめます。",
 "動物とふれあう":"動物を間近に見られるスポット。ふれあいや観察で、こどもの好奇心が育ちます。",
 "学ぶ・科学館":"見て・触れて学べる展示が楽しめるスポット。雨の日のお出かけにもぴったり。",
 "公園でのびのび":"広場や遊具でのびのび遊べる公園。ベビーカー散歩やピクニックにも。",
 "水あそび":"水遊びが楽しめるスポット。夏のおでかけや水遊びデビューに。",
 "美術・文化":"アートや文化にふれられるスポット。親子で静かに楽しめます。",
 "観光・名所":"地域の見どころスポット。おさんぽやおでかけの目的地に。",
}
def inbox(la,ln): return BBOX[0]<=la<=BBOX[2] and BBOX[1]<=ln<=BBOX[3]
def overpass():
    q=f'''[out:json][timeout:40];(
      nwr["tourism"~"^(theme_park|zoo|aquarium|museum)$"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
      nwr["leisure"~"^(water_park|park)$"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
    );out center tags 600;'''
    body=urllib.parse.urlencode({"data":q}).encode()
    for url in ("https://overpass-api.de/api/interpreter","https://overpass.kumi.systems/api/interpreter"):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(url,data=body,headers={"User-Agent":"kosodate/0.1"}),timeout=120)).get("elements",[])
        except Exception as e: print("osm retry",e)
    return []
def classify(t):
    tour=t.get("tourism"); leis=t.get("leisure"); n=t.get("name","")
    if tour=="theme_park": return "あそび場・体験"
    if tour=="zoo": return "動物とふれあう"
    if tour=="aquarium": return "水族館"
    if tour=="museum": return "美術・文化" if "美術" in n else "学ぶ・科学館"
    if leis=="water_park": return "水あそび"
    if leis=="park": return "公園でのびのび"
    return None
def slug(i): return f"s{i:04d}"
spots=[]; seen=set()
for e in overpass():
    t=e.get("tags",{}); c=classify(t); n=t.get("name")
    la=e.get("lat") or e.get("center",{}).get("lat"); ln=e.get("lon") or e.get("center",{}).get("lng") or e.get("center",{}).get("lon")
    if not(c and n and la and ln and inbox(la,ln)) or n in seen: continue
    seen.add(n)
    amen=[]
    if t.get("changing_table") in ("yes","limited"): amen.append("おむつ替え")
    if t.get("wheelchair") in ("yes","limited"): amen.append("段差なし")
    img = t.get("wikimedia_commons") or ""
    spots.append({"name":n,"cat":c or "観光・名所","lat":la,"lng":ln,"amenities":amen,
                  "has_image":bool(img),"intro":INTRO.get(c,"")})
# 千葉市OD 観光/文化 も追加
try:
    txt=urllib.request.urlopen(CHIBA_CSV,timeout=60).read().decode("cp932",errors="replace")
    G={"観光施設":"観光・名所","図書館":"学ぶ・科学館","公民館":"美術・文化"}
    for r in csv.DictReader(io.StringIO(txt)):
        g=r.get("施設ジャンル"); n=r.get("ページタイトル")
        if g in G and n and n not in seen:
            try: la,ln=float(r["緯度"]),float(r["経度"])
            except: continue
            if not inbox(la,ln): continue
            seen.add(n); c=G[g]
            spots.append({"name":n,"cat":c,"lat":la,"lng":ln,"amenities":[],"has_image":False,"intro":INTRO.get(c,"")})
except Exception as e: print("chiba OD skip:",e)
for i,s in enumerate(spots,1): s["id"]=slug(i)
json.dump(spots,open("data/spots.json","w"),ensure_ascii=False,indent=1)
by=collections.Counter(s["cat"] for s in spots)
print("data/spots.json 生成:",len(spots),"件 /",dict(by))
