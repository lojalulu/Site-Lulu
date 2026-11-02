"""
Relatório semanal do Projeto Lulu (roda toda segunda de manhã).

Junta, da semana anterior (seg–dom, horário de Salvador):
- Instagram (API oficial, mesmo token dos robôs): seguidores, alcance, views,
  cliques nos links do perfil, interações, melhores posts e Reel.
- Site (função do Netlify, acesso pela assinatura OIDC do GitHub): visitantes,
  cliques no WhatsApp, pedidos iniciados LU/AV, valor e de onde vieram.
Gera relatorios/AAAA-MM-DD.md, atualiza relatorios/historico.json e abre um
aviso (issue) no GitHub com o resumo + 3 ações da semana.

SEGURANÇA: nunca grava resposta bruta da API (a Meta põe o token dentro dos
links de paginação). Só números e textos escolhidos a dedo.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

GRAPH = "https://graph.instagram.com/v23.0"
SITE = os.environ.get("SITE_URL", "https://luluextra.com")
PASTA = "relatorios"
HIST = f"{PASTA}/historico.json"
SALVADOR = timezone(timedelta(hours=-3))
NOMES_ORIGEM = {
    "bio": "Link da bio", "instagram": "Instagram", "reel": "Reel", "story": "Story",
    "grupo": "Grupos de WhatsApp", "whatsapp": "WhatsApp", "facebook": "Facebook",
    "google": "Google", "direto": "Direto / sem origem", "ig": "Instagram",
}


# ---------------------------------------------------------------- utilidades
def http_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"erro": str(e)[:200]}


def ig(path, **params):
    params["access_token"] = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    st, d = http_json(f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}")
    if st != 200:
        msg = (d.get("error") or {}).get("message", "") if isinstance(d, dict) else ""
        print(f"  [aviso] Instagram {path}: {st} {msg[:120]}")
        return None
    return d


def reais(v):
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def num(v):
    return "—" if v is None else f"{int(v):,}".replace(",", ".")


def variacao(atual, anterior):
    if atual is None or anterior in (None, 0):
        return ""
    p = (atual - anterior) / anterior * 100
    seta = "▲" if p > 0 else ("▼" if p < 0 else "=")
    return f" ({seta} {abs(p):.0f}%)"


def periodo(hoje_salvador):
    """Semana anterior completa: segunda a domingo."""
    seg_atual = hoje_salvador - timedelta(days=hoje_salvador.weekday())
    ini = seg_atual - timedelta(days=7)
    fim = seg_atual - timedelta(days=1)
    return ini, fim


# ---------------------------------------------------------------- Instagram
def dados_instagram(ini, fim):
    out = {"seguidores": None, "alcance": None, "views": None, "cliques_links": None,
           "engajadas": None, "interacoes": None, "novos_seguidores": None, "posts": []}
    me = ig("me", fields="followers_count,media_count")
    if me:
        out["seguidores"] = me.get("followers_count")
    since = int(datetime.combine(ini, datetime.min.time(), SALVADOR).timestamp())
    until = int(datetime.combine(fim + timedelta(days=1), datetime.min.time(), SALVADOR).timestamp())
    d = ig("me/insights", metric="reach,views,profile_links_taps,accounts_engaged,total_interactions",
           period="day", metric_type="total_value", since=since, until=until)
    mapa = {"reach": "alcance", "views": "views", "profile_links_taps": "cliques_links",
            "accounts_engaged": "engajadas", "total_interactions": "interacoes"}
    for m in (d or {}).get("data", []):
        if m.get("name") in mapa:
            out[mapa[m["name"]]] = (m.get("total_value") or {}).get("value")
    f = ig("me/insights", metric="follower_count", period="day", since=since, until=until)
    for m in (f or {}).get("data", []):
        vals = [v.get("value", 0) for v in m.get("values", [])]
        if vals:
            out["novos_seguidores"] = sum(vals)

    # posts da semana
    midias, url_params = [], dict(fields="id,caption,media_product_type,media_type,timestamp,like_count,comments_count,permalink", limit=50)
    pagina = ig("me/media", **url_params)
    for p in (pagina or {}).get("data", []):
        ts = datetime.strptime(p["timestamp"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).astimezone(SALVADOR).date()
        if ini <= ts <= fim:
            midias.append((p, ts))
    for p, ts in midias:
        reel = p.get("media_product_type") == "REELS"
        met = "reach,saved,shares,views" if reel else "reach,saved,shares"
        ins = ig(f"{p['id']}/insights", metric=met) or {}
        valores = {m["name"]: (m.get("values") or [{}])[0].get("value", 0) for m in ins.get("data", [])}
        legenda = re.sub(r"\s+", " ", (p.get("caption") or "")).strip()
        out["posts"].append({
            "tipo": "Reel" if reel else "Post", "dia": ts.isoformat(),
            "alcance": valores.get("reach", 0), "views": valores.get("views"),
            "salvos": valores.get("saved", 0), "compart": valores.get("shares", 0),
            "curtidas": p.get("like_count", 0), "coment": p.get("comments_count", 0),
            "link": p.get("permalink", ""), "legenda": legenda[:70],
        })
    return out


# ---------------------------------------------------------------- Site
def token_oidc():
    url, req_tok = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"), os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not url or not req_tok:
        return None
    st, d = http_json(url + "&audience=lulu-relatorio", {"Authorization": f"bearer {req_tok}"})
    return d.get("value") if st == 200 else None


def dados_site(ini, fim):
    tok = token_oidc()
    if not tok:
        print("  [aviso] sem token OIDC — dados do site indisponíveis")
        return None
    st, d = http_json(f"{SITE}/.netlify/functions/dados?de={ini}&ate={fim}", {"Authorization": f"Bearer {tok}"})
    if st != 200:
        print(f"  [aviso] dados do site: HTTP {st}")
        return None
    return resumir_site(d.get("eventos", []))


def resumir_site(eventos):
    r = {"visitantes": {}, "whats": 0, "pedidos": {}, "valor": {}, "itens": {},
         "origem_visit": Counter(), "origem_ped": Counter(), "valor_origem": defaultdict(float),
         "pag": Counter(), "por_dia": Counter()}
    vis = defaultdict(set)
    pedidos = {}  # nº do pedido -> último evento (Pix e cartão do mesmo pedido contam 1 vez)
    for e in sorted(eventos, key=lambda x: x.get("ts", 0)):
        loja = e.get("loja", "")
        if e["t"] == "visita":
            vis[loja].add(e.get("v") or str(e.get("ts")))
            r["origem_visit"][e.get("origem") or "direto"] += 1
        elif e["t"] == "whats":
            r["whats"] += 1
        elif e["t"] == "pedido":
            chave = (e.get("pedido") or "").upper() or f"sem-{e.get('v')}-{e.get('ts')}"
            pedidos[chave] = e
    for k, e in pedidos.items():
        loja = e.get("loja", "")
        r["pedidos"][loja] = r["pedidos"].get(loja, 0) + 1
        r["valor"][loja] = r["valor"].get(loja, 0) + e.get("valor", 0)
        r["itens"][loja] = r["itens"].get(loja, 0) + e.get("itens", 0)
        o = e.get("origem") or "direto"
        r["origem_ped"][o] += 1
        r["valor_origem"][o] += e.get("valor", 0)
        r["pag"][e.get("pag") or "?"] += 1
        r["por_dia"][e.get("dia", "")] += 1
    r["visitantes"] = {k: len(v) for k, v in vis.items()}
    r["total_visitantes"] = sum(r["visitantes"].values())
    r["total_pedidos"] = len(pedidos)
    r["total_valor"] = sum(r["valor"].values())
    return r


# ---------------------------------------------------------------- Ações
def tres_acoes(igd, site, anterior):
    acoes = []
    posts = sorted(igd["posts"], key=lambda p: p["alcance"], reverse=True)
    reels = [p for p in posts if p["tipo"] == "Reel"]
    if reels:
        r = reels[0]
        acoes.append(f"**Impulsionar o Reel campeão** ({r['dia'][8:10]}/{r['dia'][5:7]}, alcance {num(r['alcance'])}) "
                     f"com R$ 10–20/dia por 3 dias, público mulheres 25–45 interessadas em moda fitness/revenda. {r['link']}")
    if site and site["total_pedidos"]:
        acoes.append(f"**Follow-up no WhatsApp**: {site['total_pedidos']} pedido(s) iniciado(s) no site. "
                     "Responder em até 1h; quem não pagou recebe mensagem em 24h e de novo em 72h (roteiro de atendimento).")
    if site and site["origem_ped"]:
        top, n = site["origem_ped"].most_common(1)[0]
        acoes.append(f"**Reforçar a origem que mais vende**: {NOMES_ORIGEM.get(top, top)} trouxe {n} pedido(s). "
                     "Repetir o tipo de conteúdo/chamada que levou a cliente até lá.")
    elif site and site["total_visitantes"] and not site["total_pedidos"]:
        acoes.append(f"**Converter as visitas**: {num(site['total_visitantes'])} visitantes e nenhum pedido iniciado. "
                     "Revisar a primeira tela do site (depoimentos, frete grátis, pedido mínimo bem explicado).")
    if igd["cliques_links"] is not None and igd["alcance"]:
        taxa = igd["cliques_links"] / igd["alcance"] * 100
        if taxa < 1:
            acoes.append(f"**Mais cliques na bio**: só {str(round(taxa, 1)).replace('.', ',')}% de quem viu clicou no link. "
                         "Colocar chamada clara no 1º e no último quadro dos Reels (\"Catálogo completo no link da bio\").")
    if posts:
        salvos = max(posts, key=lambda p: p["salvos"] + p["compart"])
        if salvos["salvos"] + salvos["compart"] > 0:
            acoes.append(f"**Repostar no Story** o post mais salvo/compartilhado da semana ({salvos['tipo']} de "
                         f"{salvos['dia'][8:10]}/{salvos['dia'][5:7]}) com enquete \"Quer o catálogo?\". {salvos['link']}")
    acoes.append("**Gravar 1 vídeo real** (provador, tecido esticando, embalagem) — Reels com vídeo real alcançam mais que montagem de fotos.")
    return acoes[:3]


# ---------------------------------------------------------------- Montagem
def montar(ini, fim, igd, site, anterior):
    a = anterior or {}
    L = [f"# Relatório semanal Lulu — {ini:%d/%m} a {fim:%d/%m/%Y}", ""]
    L += ["## 📸 Instagram",
          f"- Seguidores: **{num(igd['seguidores'])}**" + (f" (novos na semana: {num(igd['novos_seguidores'])})" if igd["novos_seguidores"] is not None else ""),
          f"- Contas alcançadas: **{num(igd['alcance'])}**{variacao(igd['alcance'], a.get('alcance'))}",
          f"- Visualizações: **{num(igd['views'])}**{variacao(igd['views'], a.get('views'))}",
          f"- Cliques nos links do perfil (bio): **{num(igd['cliques_links'])}**{variacao(igd['cliques_links'], a.get('cliques_links'))}",
          f"- Contas que interagiram: **{num(igd['engajadas'])}** · Interações: {num(igd['interacoes'])}",
          ""]
    posts = sorted(igd["posts"], key=lambda p: p["alcance"], reverse=True)
    if posts:
        n_reels = sum(1 for p in posts if p["tipo"] == "Reel")
        L.append(f"**Top 3 da semana** ({len(posts)} publicações, {n_reels} Reels):")
        for p in posts[:3]:
            extra = f", {num(p['views'])} views" if p["views"] is not None else ""
            L.append(f"1. {p['tipo']} {p['dia'][8:10]}/{p['dia'][5:7]} — alcance {num(p['alcance'])}{extra}, "
                     f"{p['curtidas']} curtidas, {p['salvos']} salvos, {p['compart']} compart. — [{p['legenda'][:45]}…]({p['link']})")
        L.append("")
    L.append("## 🛒 Site (luluextra.com)")
    if site is None:
        L += ["- Dados do site indisponíveis nesta semana.", ""]
    else:
        v = site["visitantes"]
        conv = (site["total_pedidos"] / site["total_visitantes"] * 100) if site["total_visitantes"] else 0
        L += [f"- Visitantes: **{num(site['total_visitantes'])}**{variacao(site['total_visitantes'], a.get('visitantes'))} "
              f"(kits {num(v.get('kits', 0))} · avulsas {num(v.get('avulso', 0))})",
              f"- Pedidos iniciados (enviados ao WhatsApp): **{site['total_pedidos']}**{variacao(site['total_pedidos'], a.get('pedidos'))} "
              f"— LU {site['pedidos'].get('kits', 0)} · AV {site['pedidos'].get('avulso', 0)}",
              f"- Valor dos pedidos iniciados: **{reais(site['total_valor'])}**"
              + (f" · ticket médio {reais(site['total_valor'] / site['total_pedidos'])}" if site["total_pedidos"] else ""),
              f"- Taxa de conversão (pedidos ÷ visitantes): **{conv:.1f}%**".replace(".", ",") + f"",
              f"- Outros cliques no WhatsApp do site: {site['whats']}",
              f"- Forma de pagamento escolhida: Pix {site['pag'].get('pix', 0)} · Cartão {site['pag'].get('cartao', 0)}",
              ""]
        if site["origem_visit"] or site["origem_ped"]:
            L += ["**De onde vieram** (visitas → pedidos):", ""]
            L += ["| Origem | Visitas | Pedidos | Valor |", "|---|---:|---:|---:|"]
            origens = set(site["origem_visit"]) | set(site["origem_ped"])
            for o in sorted(origens, key=lambda x: (-site["origem_ped"][x], -site["origem_visit"][x])):
                L.append(f"| {NOMES_ORIGEM.get(o, o)} | {site['origem_visit'][o]} | {site['origem_ped'][o]} | {reais(site['valor_origem'][o])} |")
            L.append("")
        L.append("_Pedido iniciado = cliente clicou em pagar e foi pro WhatsApp. Confirme no WhatsApp quantos pagaram._")
        L.append("")
    L += ["## ✅ 3 ações desta semana"]
    L += [f"{i}. {t}" for i, t in enumerate(tres_acoes(igd, site, anterior), 1)]
    L += ["", f"_Gerado automaticamente em {datetime.now(SALVADOR):%d/%m/%Y %H:%M} (Salvador)._"]
    return "\n".join(L) + "\n"


def main():
    hoje = datetime.now(SALVADOR).date()
    if os.environ.get("DATA_REF"):
        hoje = datetime.strptime(os.environ["DATA_REF"], "%Y-%m-%d").date()
    ini, fim = periodo(hoje)
    if os.environ.get("ULTIMOS_7"):
        ini, fim = hoje - timedelta(days=7), hoje - timedelta(days=1)
    print(f"Período: {ini} a {fim}")
    hist = json.load(open(HIST)) if os.path.exists(HIST) else {"semanas": {}}
    if str(ini) in hist["semanas"] and os.environ.get("AUTO") == "true":
        print("Relatório desta semana já feito — nada a fazer.")
        open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a").write("feito=nao\n")
        return
    anteriores = sorted(k for k in hist["semanas"] if k < str(ini))
    anterior = hist["semanas"][anteriores[-1]] if anteriores else None

    igd = dados_instagram(ini, fim)
    site = dados_site(ini, fim)
    md = montar(ini, fim, igd, site, anterior)

    if re.search(r"IGAA|access_token|eyJ[A-Za-z0-9_-]{20,}", md):
        sys.exit("ERRO: o relatório contém algo parecido com token — não vou salvar.")
    os.makedirs(PASTA, exist_ok=True)
    arq = f"{PASTA}/{ini}.md"
    open(arq, "w", encoding="utf-8").write(md)
    hist["semanas"][str(ini)] = {
        "alcance": igd["alcance"], "views": igd["views"], "cliques_links": igd["cliques_links"],
        "seguidores": igd["seguidores"],
        "visitantes": site["total_visitantes"] if site else None,
        "pedidos": site["total_pedidos"] if site else None,
        "valor": round(site["total_valor"], 2) if site else None,
    }
    json.dump(hist, open(HIST, "w"), ensure_ascii=False, indent=2)
    print(md)
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
        f.write(f"feito=sim\narquivo={arq}\ntitulo=📊 Relatório semanal Lulu — {ini:%d/%m} a {fim:%d/%m}\n")


if __name__ == "__main__":
    main()
