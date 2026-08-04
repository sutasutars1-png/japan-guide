"""
Phase2 実データ統合取込 : 千葉市OD(CC BY 4.0) + OpenStreetMap/Overpass(ODbL) を海浜幕張圏で
いずれも無料・鍵不要・構造化(LLM不使用)。地図API有料は非採用(地域拡大で無料枠が破綻するため)。
権威=自治体は検証済 / OSMはopendata扱い単独→報告 / 複数一致→検証済 / 矛盾→quarantine。
"""
import urllib.request, urllib.parse, csv, io, json, math, difflib, collections

BBOX = (35.630, 140.020, 35.665, 140.055)  # S,W,N,E
CHIBA = {"name": "千葉市 公共施設位置情報OD", "type": "municipal", "updated": "2025-06-27", "license": "CC BY 4.0", "by": "千葉市"}
OSM = {"name": "OpenStreetMap", "type": "opendata", "updated": "2026-08", "license": "ODbL", "by": "© OpenStreetMap contributors"}
SOURCE_TIER = {"municipal": 1.0, "opendata": 0.8}
AUTH = {"municipal", "official_site", "field_check"}

def inbox(la, ln): return BBOX[0] <= la <= BBOX[2] and BBOX[1] <= ln <= BBOX[3]

def collect_chiba():
    text = urllib.request.urlopen(CHIBA_URL, timeout=60).read().decode("cp932", errors="replace")
    G = {"赤ちゃんの駅": ("施設", ["nursing_room", "diaper_changing"]), "公園": ("公園", []), "観光施設": ("観光", []),
         "図書館": ("文化施設", []), "公民館": ("文化施設", []), "コミュニティセンター": ("文化施設", []), "スポーツ施設": ("スポーツ", [])}
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        g = r.get("施設ジャンル") or ""
        if g not in G: continue
        try: la, ln = float(r["緯度"]), float(r["経度"])
        except: continue
        if not inbox(la, ln): continue
        cat, bb = G[g]
        out.append({"name": r["ページタイトル"], "cat": cat, "lat": la, "lng": ln,
                    "obs": [{"key": k, "value": True, "source": CHIBA} for k in bb]})
    return out
CHIBA_URL = "https://www.city.chiba.jp/sogoseisaku/shichokoshitsu/kohokocho/documents/export_r7.csv"

def collect_osm():
    q = f'''[out:json][timeout:25];(
      nwr["amenity"~"^(restaurant|cafe)$"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
      nwr["leisure"="park"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
    );out center tags 300;'''
    body = urllib.parse.urlencode({"data": q}).encode()
    els = None
    import time
    for url in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
                "https://maps.mail.ru/osm/tools/overpass/api/interpreter"):
        for _ in range(2):
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": "kosodate-mvp/0.1 (research)"})
                els = json.load(urllib.request.urlopen(req, timeout=120)).get("elements", []); break
            except Exception as e:
                print(f"  osm retry ({url.split('/')[2]}): {e}"); time.sleep(3)
        if els is not None: break
    if els is None:
        print("  ! OSM取得失敗。自治体ODのみで継続"); return []
    out = []
    for e in els:
        t = e.get("tags", {}); name = t.get("name")
        la = e.get("lat") or e.get("center", {}).get("lat"); ln = e.get("lon") or e.get("center", {}).get("lon")
        if not (name and la and ln and inbox(la, ln)): continue
        cat = "飲食" if t.get("amenity") in ("restaurant", "cafe") else "公園"
        obs = []
        if t.get("wheelchair") in ("yes", "limited"):
            obs.append({"key": "step_free_entrance", "value": True, "source": OSM})
        out.append({"name": name, "cat": cat, "lat": la, "lng": ln, "obs": obs})
    return out

# 名寄せ(公園などソース跨ぎを突合)
def dm(a, b): return math.hypot((a[0]-b[0])*111000, (a[1]-b[1])*90000)
def resolve(cands):
    places = []
    for c in cands:
        m = None
        for p in places:
            if dm((c["lat"], c["lng"]), (p["lat"], p["lng"])) < 120 and \
               difflib.SequenceMatcher(None, c["name"].replace(" ",""), p["name"].replace(" ","")).ratio() > 0.7:
                m = p; break
        if m: m["obs"] += c["obs"]
        else: places.append({**c})
    return places

def validate(places):
    db, quarantine = [], []
    for p in places:
        by = collections.defaultdict(list)
        for o in p["obs"]: by[o["key"]].append(o)
        for k, obs in by.items():
            if len(set(o["value"] for o in obs)) > 1:
                quarantine.append((p["name"], k)); continue
            types = [o["source"]["type"] for o in obs]
            conf = round(max(SOURCE_TIER[t] for t in types) * (1.0 if len(obs) >= 2 else 0.9), 2)
            status = "verified" if (any(t in AUTH for t in types) or len(obs) >= 2) else "reported"
            db.append({"place": p["name"], "cat": p["cat"], "key": k, "value": obs[0]["value"],
                       "confidence": conf, "status": status,
                       "cite": ",".join(f"{o['source']['type']}({o['source']['updated']})" for o in obs)})
    return db, quarantine

cands = collect_chiba() + collect_osm()
places = resolve(cands)
attrs, quarantine = validate(places)
bycat = collections.Counter(p["cat"] for p in places)
print(f"海浜幕張圏 実データ統合: 総スポット {len(places)}  (自治体OD＋OSM・無料ソースのみ)")
print("カテゴリ別:", dict(bycat))
print(f"place_attribute: {len(attrs)}  / quarantine: {len(quarantine)}")
print(f"公開ゲートL2(20件以上・飲食5件以上): "
      f"{'✅達成' if len(places)>=20 and bycat['飲食']>=5 else '未達'}  (総{len(places)}件/飲食{bycat['飲食']}件)")
print("\n検証済み属性の例(授乳室/おむつ替え=自治体):")
for a in [x for x in attrs if x['status']=='verified'][:3]:
    print(f"  {a['place']} | {a['key']}={a['value']} | {a['status']} | {a['cite']}")
json.dump({"sources": [CHIBA, OSM], "places": [{k:p[k] for k in ('name','cat','lat','lng')} for p in places],
           "place_attribute": attrs}, open("/mnt/user-data/outputs/phase2_real_output.json","w"), ensure_ascii=False, indent=2)
print("\n出典: 千葉市(CC BY 4.0) / © OpenStreetMap contributors(ODbL)  -> phase2_real_output.json")
