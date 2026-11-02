"""
Relatório MENSAL do Projeto Lulu (roda no dia 1 de cada mês).
Mês anterior: pedidos iniciados no site (total, por loja, por origem),
top 10 produtos pedidos, Instagram do mês (views, cliques na bio,
interações, 5 melhores publicações), evolução semanal e checklist do mês
(preços/fretes, o que pausar, plano de conteúdo).
Mesmas regras de segurança do semanal: nada de resposta bruta da API.
"""
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import relatorio_semanal as S  # noqa: E402

HIST_M = f"{S.PASTA}/historico_mensal.json"
MESES = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]


def mes_anterior(hoje):
    fim = hoje.replace(day=1) - timedelta(days=1)
    return fim.replace(day=1), fim


def nomes_produtos():
    nomes = {}
    for loja, arq in (("kits", "produtos.json"), ("avulso", "kitavulso/produtos.json")):
        try:
            for p in json.load(open(arq, encoding="utf-8")):
                nomes[(loja, str(p["id"]))] = (p.get("nome") or "").strip()
        except Exception:
            pass
    return nomes


def instagram_mes(ini, fim):
    """Views, cliques e interações somados por quinzena (a API limita 30 dias)."""
    tot = {"views": 0, "cliques_links": 0, "interacoes": 0}
    ok = False
    a = ini
    while a <= fim:
        b = min(fim, a + timedelta(days=14))
        d = S.dados_instagram(a, b)
        for k in tot:
            if d.get(k) is not None:
                tot[k] += d[k]
                ok = True
        if a == ini:
            seguidores = d.get("seguidores")
        tot.setdefault("posts", []).extend(d["posts"])
        a = b + timedelta(days=1)
    tot["seguidores"] = seguidores
    unicos = {}
    for p in tot.get("posts", []):
        unicos[p["link"] or id(p)] = p
    tot["posts"] = list(unicos.values())
    if not ok:
        for k in ("views", "cliques_links", "interacoes"):
            tot[k] = None
    return tot


def montar(ini, fim, ig, site, hist_sem, nomes, anterior):
    a = anterior or {}
    mes = f"{MESES[ini.month]} de {ini.year}"
    L = [f"# Relatório mensal Lulu — {mes}", ""]
    L += ["## 🛒 Vendas pelo site (pedidos iniciados)"]
    if site is None:
        L += ["- Dados do site indisponíveis.", ""]
    else:
        conv = (site["total_pedidos"] / site["total_visitantes"] * 100) if site["total_visitantes"] else 0
        L += [f"- Pedidos iniciados: **{site['total_pedidos']}**{S.variacao(site['total_pedidos'], a.get('pedidos'))} "
              f"(LU {site['pedidos'].get('kits', 0)} · AV {site['pedidos'].get('avulso', 0)})",
              f"- Valor: **{S.reais(site['total_valor'])}**{S.variacao(site['total_valor'], a.get('valor'))}"
              + (f" · ticket médio {S.reais(site['total_valor'] / site['total_pedidos'])}" if site["total_pedidos"] else ""),
              f"- Visitantes: **{S.num(site['total_visitantes'])}** · conversão **{str(round(conv, 1)).replace('.', ',')}%**",
              ""]
        if site["origem_ped"]:
            L += ["| Origem | Pedidos | Valor |", "|---|---:|---:|"]
            for o, n in site["origem_ped"].most_common():
                L.append(f"| {S.NOMES_ORIGEM.get(o, o)} | {n} | {S.reais(site['valor_origem'][o])} |")
            L.append("")
        L.append("## 🏆 Top 10 produtos pedidos")
        if site["produtos"]:
            for i, ((loja, pid), q) in enumerate(site["produtos"].most_common(10), 1):
                nome = nomes.get((loja, pid)) or f"produto {pid} (saiu do catálogo)"
                un = "kits" if loja == "kits" else "peças"
                L.append(f"{i}. {nome} — {q} {un} ({'Kits' if loja == 'kits' else 'Avulsas'})")
        else:
            L.append("- Ainda sem pedidos com produtos registrados neste mês.")
        L.append("")
    L += ["## 📸 Instagram no mês",
          f"- Seguidores: **{S.num(ig['seguidores'])}**",
          f"- Visualizações: **{S.num(ig['views'])}** · Cliques na bio: **{S.num(ig['cliques_links'])}** · Interações: {S.num(ig['interacoes'])}",
          f"- Publicações: {len(ig['posts'])} ({sum(1 for p in ig['posts'] if p['tipo'] == 'Reel')} Reels)", ""]
    melhores = sorted(ig["posts"], key=lambda p: p["alcance"], reverse=True)[:5]
    if melhores:
        L.append("**5 melhores publicações (alcance):**")
        for p in melhores:
            L.append(f"- {p['tipo']} {p['dia'][8:10]}/{p['dia'][5:7]} — alcance {S.num(p['alcance'])}, {p['salvos']} salvos — [{p['legenda'][:40]}…]({p['link']})")
        L.append("")
    semanas = sorted((k, v) for k, v in hist_sem.get("semanas", {}).items() if str(ini - timedelta(days=6)) <= k <= str(fim))
    if semanas:
        L += ["## 📈 Semana a semana", "", "| Semana | Alcance | Cliques bio | Visitantes | Pedidos | Valor |", "|---|---:|---:|---:|---:|---:|"]
        for k, v in semanas:
            L.append(f"| {k[8:10]}/{k[5:7]} | {S.num(v.get('alcance'))} | {S.num(v.get('cliques_links'))} | {S.num(v.get('visitantes'))} | "
                     f"{S.num(v.get('pedidos'))} | {S.reais(v['valor']) if v.get('valor') is not None else '—'} |")
        L.append("")
    L += ["## ✅ Checklist do mês",
          "1. **Preços e fretes**: conferir se os preços do site batem com o fornecedor (o robô atualiza seg/qua) e se Econômico R$ 39,90 / Vip R$ 90 ainda cobrem o custo real do envio.",
          ]
    top3 = []
    if site and site["produtos"]:
        top3 = [nomes[k] for k, _ in site["produtos"].most_common() if nomes.get(k)][:3]
    if top3:
        L.append(f"2. **Conteúdo do mês**: 1 Reel com vídeo real por semana dos mais pedidos: {', '.join(top3)}.")
    else:
        L.append("2. **Conteúdo do mês**: 1 Reel com vídeo real por semana (provador, tecido, embalagem), começando pelos lançamentos.")
    if melhores:
        L.append(f"3. **Repetir o formato campeão**: a publicação de maior alcance foi um {melhores[0]['tipo']} — fazer mais 2 no mesmo estilo.")
    L.append("4. **Clientes do mês**: mandar mensagem de recompra pra quem comprou há ~30 dias (roteiro de atendimento, mensagem de recompra).")
    L += ["", f"_Gerado automaticamente em {datetime.now(S.SALVADOR):%d/%m/%Y %H:%M} (Salvador)._"]
    return "\n".join(L) + "\n"


def main():
    hoje = datetime.now(S.SALVADOR).date()
    if os.environ.get("DATA_REF"):
        hoje = datetime.strptime(os.environ["DATA_REF"], "%Y-%m-%d").date()
    ini, fim = mes_anterior(hoje)
    chave = f"{ini:%Y-%m}"
    print(f"Mês: {chave}")
    hist = json.load(open(HIST_M)) if os.path.exists(HIST_M) else {"meses": {}}
    if chave in hist["meses"] and os.environ.get("AUTO") == "true":
        print("Relatório deste mês já feito.")
        open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a").write("feito=nao\n")
        return
    ant = sorted(k for k in hist["meses"] if k < chave)
    anterior = hist["meses"][ant[-1]] if ant else None
    ig = instagram_mes(ini, fim)
    site = S.dados_site(ini, fim)
    hist_sem = json.load(open(S.HIST)) if os.path.exists(S.HIST) else {}
    md = montar(ini, fim, ig, site, hist_sem, nomes_produtos(), anterior)
    if re.search(r"IGAA|access_token|eyJ[A-Za-z0-9_-]{20,}", md):
        sys.exit("ERRO: o relatório contém algo parecido com token — não vou salvar.")
    arq = f"{S.PASTA}/mensal-{chave}.md"
    open(arq, "w", encoding="utf-8").write(md)
    hist["meses"][chave] = {"pedidos": site["total_pedidos"] if site else None,
                            "valor": round(site["total_valor"], 2) if site else None,
                            "views": ig["views"], "cliques_links": ig["cliques_links"]}
    json.dump(hist, open(HIST_M, "w"), ensure_ascii=False, indent=2)
    print(md)
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
        f.write(f"feito=sim\narquivo={arq}\ntitulo=🗓️ Relatório mensal Lulu — {MESES[ini.month]} de {ini.year}\n")


if __name__ == "__main__":
    main()
