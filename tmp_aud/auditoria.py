import os, json, urllib.request, urllib.parse, collections, statistics, datetime
TOK = os.environ["INSTAGRAM_ACCESS_TOKEN"]; ID = os.environ.get("INSTAGRAM_BUSINESS_ID") or "17841401562118752"
G = "https://graph.instagram.com/v23.0"
def get(path, **p):
    url = path if path.startswith("http") else f"{G}/{path}?" + urllib.parse.urlencode(p)
    try:
        r = urllib.request.Request(url, headers={"Authorization": "Bearer " + TOK})
        return json.load(urllib.request.urlopen(r, timeout=40))
    except Exception as e:
        try: msg = json.load(e).get("error", {}).get("message", "")[:120]
        except Exception: msg = str(e)[:80]
        return {"_erro": msg}
posts = []; r = get(f"{ID}/media", fields="id,media_type,media_product_type,timestamp,like_count,comments_count", limit=50)
while r.get("data") and len(posts) < 90:
    posts += r["data"]
    nxt = r.get("paging", {}).get("cursors", {}).get("after")
    if not nxt or len(posts) >= 90: break
    r = get(f"{ID}/media", fields="id,media_type,media_product_type,timestamp,like_count,comments_count", limit=50, after=nxt)
posts = posts[:90]
rows = []
for p in posts:
    tipo = "REEL" if p.get("media_product_type") == "REELS" else ("STORY" if p.get("media_product_type") == "STORY" else p["media_type"])
    ins = get(f"{p['id']}/insights", metric="reach,saved,shares,views,total_interactions")
    m = {d["name"]: (d.get("values") or [{}])[0].get("value", 0) for d in ins.get("data", [])}
    t = datetime.datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00")) - datetime.timedelta(hours=3)
    rows.append(dict(tipo=tipo, hora=t.hour, dia=t.date().isoformat(), reach=m.get("reach", 0), views=m.get("views", 0), saved=m.get("saved", 0), shares=m.get("shares", 0), inter=m.get("total_interactions", 0), likes=p.get("like_count", 0), com=p.get("comments_count", 0)))
print("POSTS lidos:", len(rows), "| de", rows[-1]["dia"] if rows else "-", "a", rows[0]["dia"] if rows else "-")
def resumo(titulo, grupos):
    print("\n==", titulo)
    for k, v in sorted(grupos.items(), key=lambda kv: str(kv[0])):
        rc = [x["reach"] for x in v]
        print(f"{str(k):10} n={len(v):3} alcance_med={statistics.mean(rc):7.0f} mediana={statistics.median(rc):6.0f} max={max(rc):5} salvos={sum(x['saved'] for x in v):3} compart={sum(x['shares'] for x in v):3} curtidas={sum(x['likes'] for x in v):3} coment={sum(x['com'] for x in v):3}")
g = collections.defaultdict(list)
for x in rows: g[x["tipo"]].append(x)
resumo("POR TIPO", g)
g = collections.defaultdict(list)
for x in rows: g[f"{x['hora']:02d}h"].append(x)
resumo("POR HORA (Salvador)", g)
g = collections.defaultdict(list)
for x in rows: g[x["dia"]].append(x)
print("\n== posts por dia (média):", round(statistics.mean(len(v) for v in g.values()), 1), "| dias:", len(g))
print("\n== DEMOGRAFIA dos seguidores")
for bd in ("city", "age", "gender", "country"):
    d = get(f"{ID}/insights", metric="follower_demographics", period="lifetime", metric_type="total_value", breakdown=bd)
    if "_erro" in d: print(bd, "erro:", d["_erro"]); continue
    try:
        res = d["data"][0]["total_value"]["breakdowns"][0]["results"]
        res = sorted(res, key=lambda r: -r["value"])[:8]
        tot = sum(r["value"] for r in d["data"][0]["total_value"]["breakdowns"][0]["results"]) or 1
        print(bd, [(",".join(r["dimension_values"]), f"{100*r['value']/tot:.0f}%") for r in res])
    except Exception as e: print(bd, "sem dados", str(e)[:60])
print("\n== ATIVIDADE por hora dos seguidores")
d = get(f"{ID}/insights", metric="online_followers", period="lifetime")
print(json.dumps(d)[:400])
