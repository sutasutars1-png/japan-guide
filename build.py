# -*- coding: utf-8 -*-
"""build.py — generate the whole static site into docs/. Run: python build.py"""
import json, os, shutil, datetime, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
from site_lib import (LANGS, LANG_DIR, HREFLANG, UI, esc, shell,
                      dest_card, guide_card, cta_block, season_tabs, gallery)

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "docs")
TODAY = datetime.date.today().isoformat()

def load(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return json.load(f)

cfg = load("config.json")
dests = load("data/destinations.json")["destinations"]
guides = load("data/guides.json")["guides"]
base = cfg["base_url"].rstrip("/")

def write(path, content):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)

# ---------------- home pages ----------------
def build_home(lang):
    t = UI[lang]
    depth = 0 if lang == "en" else 1
    root = "../" * depth
    cards = "\n".join(dest_card(d, lang, root) for d in dests)
    gcards = "\n".join(guide_card(g, lang, root) for g in guides)
    tag = cfg["site_tagline"][lang]
    hero_kanji = "".join(f'<span>{k}</span>' for k in "旅路")
    body = f"""<main>
<section class="hero">
  <div class="hero-text">
    <p class="kicker">{t["hero_kicker"]} · 2026</p>
    <h1>{esc(tag)}</h1>
    <p class="lede">{esc(t["footer_about"])}</p>
    <a class="cta primary" href="#destinations">{t["explore"]} ↓</a>
  </div>
  <div class="hero-kanji" aria-hidden="true">{hero_kanji}</div>
</section>
<section id="destinations" class="wrap">
  <h2 class="sec">{t["explore"]}</h2>
  <div class="grid">{cards}</div>
</section>
<section id="guides" class="wrap">
  <h2 class="sec">{t["all_guides"]}</h2>
  <div class="ggrid">{gcards}</div>
</section>
</main>"""
    path = f'{LANG_DIR[lang]}index.html'
    alts = {l: f'{LANG_DIR[l]}index.html' for l in LANGS}
    jsonld = {"@context": "https://schema.org", "@type": "WebSite",
              "name": cfg["site_name"], "url": f"{base}/{path}",
              "inLanguage": HREFLANG[lang], "description": tag}
    write(path, shell(cfg, lang, depth, cfg["site_name"] + " — " + tag,
                      tag, body, path, alts, jsonld))

# ---------------- destination pages ----------------
def build_dest(d, lang):
    t = UI[lang]
    depth = 1 if lang == "en" else 2
    root = "../" * depth
    name = d["name"][lang]
    paras = "".join(f"<p>{esc(p)}</p>" for p in d["intro"][lang].split("\n\n"))
    hl = "".join(f'<li><span class="dot"></span>{esc(h[lang])}</li>' for h in d["highlights"])
    img = ""
    if d.get("image"):
        credit = f'<figcaption>{esc(d.get("image_credit") or "")}</figcaption>' if d.get("image_credit") else ""
        img = f'<figure class="photo"><img src="{esc(d["image"])}" alt="{esc(name)}" loading="lazy">{credit}</figure>'
    others = [x for x in dests if x["id"] != d["id"]][:3]
    rel = "\n".join(dest_card(x, lang, root) for x in others)
    body = f"""<main class="wrap article">
<p class="crumbs"><a href="{root}{LANG_DIR[lang]}index.html">{t["home"]}</a> / <a href="{root}{LANG_DIR[lang]}index.html#destinations">{t["destinations"]}</a> / {esc(name)}</p>
<header class="d-head">
  <div class="tile big"><span class="k">{esc(d["kanji"])}</span><span class="stamp">{esc(d["region"])}</span></div>
  <div>
    <h1>{esc(name)}</h1>
    <p class="lede">{esc(d["tagline"][lang])}</p>
    <p class="meta">{t["season"]}: <strong>{esc(d["best_season"][lang])}</strong>
      <span class="wx" data-lat="{d["lat"]}" data-lon="{d["lon"]}" data-label="{t["weather_now"]}"></span></p>
  </div>
</header>
{img}
<div class="prose">{paras}</div>
{season_tabs(d, lang, datetime.date.today().month)}
{gallery(d, lang)}
<h2>{t["highlights"]}</h2>
<ul class="hl">{hl}</ul>
<h2>{t["access"]}</h2>
<p class="access">{esc(d["access"][lang])}</p>
{cta_block(cfg, lang, d["name"]["en"])}
<p class="fx" data-label="{t["yen_now"]}"></p>
<h2>{t["related"]}</h2>
<div class="grid">{rel}</div>
<p><a href="{root}{LANG_DIR[lang]}index.html#destinations">← {t["back"]}</a></p>
</main>"""
    path = f'{LANG_DIR[lang]}destinations/{d["id"]}.html'
    alts = {l: f'{LANG_DIR[l]}destinations/{d["id"]}.html' for l in LANGS}
    jsonld = {"@context": "https://schema.org", "@type": "TouristDestination",
              "name": name, "description": d["tagline"][lang],
              "url": f"{base}/{path}", "inLanguage": HREFLANG[lang],
              "geo": {"@type": "GeoCoordinates", "latitude": d["lat"], "longitude": d["lon"]},
              "touristType": ["Sightseeing", "Culinary"]}
    title = f'{name} — {d["tagline"][lang]}'
    write(path, shell(cfg, lang, depth, title, d["tagline"][lang], body,
                      path, alts, jsonld, og_type="article"))

# ---------------- guide pages ----------------
def build_guide(g, lang):
    t = UI[lang]
    depth = 1 if lang == "en" else 2
    root = "../" * depth
    secs = ""
    for s in g["sections"]:
        paras = "".join(f"<p>{esc(p)}</p>" for p in s["body"][lang])
        secs += f'<h2>{esc(s["h"][lang])}</h2><div class="prose">{paras}</div>'
    faq_html, faq_ld = "", []
    for f_ in g.get("faq", []):
        faq_html += (f'<details><summary>{esc(f_["q"][lang])}</summary>'
                     f'<p>{esc(f_["a"][lang])}</p></details>')
        faq_ld.append({"@type": "Question", "name": f_["q"][lang],
                       "acceptedAnswer": {"@type": "Answer", "text": f_["a"][lang]}})
    if faq_html:
        faq_html = f'<h2>{t["faq"]}</h2><div class="faq">{faq_html}</div>'
    body = f"""<main class="wrap article">
<p class="crumbs"><a href="{root}{LANG_DIR[lang]}index.html">{t["home"]}</a> / <a href="{root}{LANG_DIR[lang]}index.html#guides">{t["guides"]}</a></p>
<header class="g-head">
  <p class="kicker">{t["hero_kicker"]} · {t["updated"]} {TODAY}</p>
  <h1>{esc(g["title"][lang])}</h1>
  <p class="lede">{esc(g["description"][lang])}</p>
</header>
{secs}
{faq_html}
{cta_block(cfg, lang, "Japan")}
</main>"""
    path = f'{LANG_DIR[lang]}guides/{g["id"]}.html'
    alts = {l: f'{LANG_DIR[l]}guides/{g["id"]}.html' for l in LANGS}
    jsonld = [{"@context": "https://schema.org", "@type": "Article",
               "headline": g["title"][lang], "description": g["description"][lang],
               "inLanguage": HREFLANG[lang], "dateModified": TODAY,
               "author": {"@type": "Organization", "name": cfg["author"]},
               "mainEntityOfPage": f"{base}/{path}"}]
    if faq_ld:
        jsonld.append({"@context": "https://schema.org", "@type": "FAQPage",
                       "mainEntity": faq_ld})
    write(path, shell(cfg, lang, depth, g["title"][lang], g["description"][lang],
                      body, path, alts, jsonld, og_type="article"))

# ---------------- feeds / seo files ----------------
def build_meta_files(all_paths):
    urls = "\n".join(
        f"  <url><loc>{base}/{p}</loc><lastmod>{TODAY}</lastmod></url>" for p in all_paths)
    write("sitemap.xml",
          '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          f"{urls}\n</urlset>\n")
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
    items = ""
    for g in guides:
        items += (f"<item><title>{esc(g['title']['en'])}</title>"
                  f"<link>{base}/guides/{g['id']}.html</link>"
                  f"<description>{esc(g['description']['en'])}</description></item>\n")
    for d in dests:
        items += (f"<item><title>{esc(d['name']['en'])}</title>"
                  f"<link>{base}/destinations/{d['id']}.html</link>"
                  f"<description>{esc(d['tagline']['en'])}</description></item>\n")
    write("feed.xml",
          '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
          f"<title>{esc(cfg['site_name'])}</title><link>{base}/</link>"
          f"<description>{esc(cfg['site_tagline']['en'])}</description>\n{items}"
          "</channel></rss>\n")
    lines = [f"# {cfg['site_name']}", "", f"> {cfg['site_tagline']['en']}", "",
             "Independent multilingual (EN/KO/ZH-Hant) travel guides for visitors to Japan.",
             "", "## Destinations"]
    lines += [f"- [{d['name']['en']}]({base}/destinations/{d['id']}.html): {d['tagline']['en']}" for d in dests]
    lines += ["", "## Guides"]
    lines += [f"- [{g['title']['en']}]({base}/guides/{g['id']}.html): {g['description']['en']}" for g in guides]
    write("llms.txt", "\n".join(lines) + "\n")
    write(".nojekyll", "")

def main():
    os.makedirs(OUT, exist_ok=True)
    # copy static assets
    src_assets = os.path.join(ROOT, "assets")
    dst_assets = os.path.join(OUT, "assets")
    if os.path.isdir(dst_assets):
        shutil.rmtree(dst_assets)
    shutil.copytree(src_assets, dst_assets)

    all_paths = []
    for lang in LANGS:
        build_home(lang)
        all_paths.append(f"{LANG_DIR[lang]}index.html")
        for d in dests:
            build_dest(d, lang)
            all_paths.append(f"{LANG_DIR[lang]}destinations/{d['id']}.html")
        for g in guides:
            build_guide(g, lang)
            all_paths.append(f"{LANG_DIR[lang]}guides/{g['id']}.html")
    build_meta_files(all_paths)
    print(f"OK: {len(all_paths)} pages -> docs/  ({len(dests)} destinations x {len(LANGS)} langs + guides)")
    if "YOUR-USERNAME" in base:
        print("NOTE: config.json の base_url をあなたのURLに変更してください。")

if __name__ == "__main__":
    main()
