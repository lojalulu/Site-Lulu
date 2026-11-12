"""
Passo 1 do robô do Instagram: escolhe o próximo produto (priorizando
lançamentos — produtos que apareceram no catálogo desde a última vez
que o robô rodou — e, quando não há lançamento pendente, alternando
entre as duas lojas sem repetir até esgotar o catálogo), gera a
legenda do feed e a imagem do Story, e salva tudo em disco pronto pra
publicar no próximo passo.
"""

import json
import os
import random
from datetime import datetime, timedelta, timezone

import glob
import re

import carrossel as car
from conteudo import gerar_post, rotulo_kit, sortear_hashtags
from imagem_story import gerar_imagem_feed, gerar_imagem_story

HISTORICO_PATH = "instagram/historico_postagens.json"
SAIDA_DIR = "instagram/_saida"
SAIDA_POST = f"{SAIDA_DIR}/post.json"
SAIDA_STORY_IMG = f"{SAIDA_DIR}/story.jpg"
SAIDA_FEED_IMG = f"{SAIDA_DIR}/feed.jpg"

LOJAS = {
    "kits": "produtos.json",
    "avulso": "kitavulso/produtos.json",
}


def carregar_historico():
    """Retorna (historico, precisa_migrar). precisa_migrar é True só na
    primeira vez que essa versão do robô roda num histórico antigo —
    nesse caso o catálogo atual inteiro vira a "base conhecida" sem
    marcar nada como lançamento (senão tudo que já existe seria
    anunciado como novidade de uma vez)."""
    if os.path.exists(HISTORICO_PATH):
        with open(HISTORICO_PATH, encoding="utf-8") as f:
            hist = json.load(f)
    else:
        hist = {}

    precisa_migrar = "conhecidos" not in hist

    hist.setdefault("proxima_loja", "kits")
    hist.setdefault("postados", {"kits": [], "avulso": []})
    hist.setdefault("ultimos_pilares", [])
    hist.setdefault("conhecidos", {"kits": [], "avulso": []})
    hist.setdefault("lancamentos_pendentes", {"kits": [], "avulso": []})
    return hist, precisa_migrar


def salvar_historico(historico):
    os.makedirs(os.path.dirname(HISTORICO_PATH), exist_ok=True)
    with open(HISTORICO_PATH, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)


def carregar_catalogo(loja: str) -> list:
    with open(LOJAS[loja], encoding="utf-8") as f:
        return json.load(f)


def atualizar_lancamentos(historico, loja, produtos_loja, precisa_migrar):
    """Compara o catálogo atual com o que já era conhecido e devolve a
    fila de IDs pendentes de anúncio de lançamento pra essa loja."""
    ids_atuais = {p["id"] for p in produtos_loja}

    if precisa_migrar:
        # primeira execução dessa versão — só estabelece a base, não
        # anuncia o catálogo inteiro como lançamento
        historico["conhecidos"][loja] = sorted(ids_atuais)
        return []

    conhecidos_antes = set(historico["conhecidos"][loja])
    novos = ids_atuais - conhecidos_antes
    historico["conhecidos"][loja] = sorted(conhecidos_antes | ids_atuais)

    if novos:
        pendentes_atuais = set(historico["lancamentos_pendentes"][loja]) | novos
        historico["lancamentos_pendentes"][loja] = sorted(pendentes_atuais)

    # remove da fila qualquer id que não exista mais no catálogo (produto saiu)
    historico["lancamentos_pendentes"][loja] = [
        pid for pid in historico["lancamentos_pendentes"][loja] if pid in ids_atuais
    ]
    return historico["lancamentos_pendentes"][loja]


def escolher_produto_normal(loja: str, historico: dict, produtos: list) -> dict:
    postados = set(historico["postados"][loja])
    candidatos = [p for p in produtos if p["id"] not in postados]

    if not candidatos:
        # já postou todo mundo dessa loja — recomeça o ciclo
        historico["postados"][loja] = []
        candidatos = produtos

    return random.choice(candidatos)


# ====================================================================== FEED (12/11/2026)
# Pedido do Lucas: o FEED fala SÓ de luluextra.com (kits). Formatos em rodízio:
#   produto           -> foto única do kit (o estilo de sempre)
#   carrossel_produto -> 3 a 5 fotos do MESMO kit (todos os ângulos) + preço
#   vitrine           -> capa + 5 kits diferentes com etiqueta de preço + lâmina final
#   novidades         -> igual à vitrine, só com lançamentos recentes (prioridade quando há 3+)
#   info              -> capa + 3 lâminas de assunto útil (como comprar, frete, tamanhos...) + final
# Stories seguem alternando kits e peças avulsas.
FORMATOS_FEED = {"produto": 3, "carrossel_produto": 2, "vitrine": 2, "info": 2}
DIAS_NOVIDADE = 14
SAIDA_CARROSSEL = f"{SAIDA_DIR}/carrossel_{{}}.jpg"


def _hoje():
    return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


def lancamentos_recentes():
    try:
        with open("lancamentos_datas.json", encoding="utf-8") as f:
            datas = json.load(f)
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for pid, d in datas.items():
        try:
            if (_hoje() - datetime.fromisoformat(d).date()).days <= DIAS_NOVIDADE:
                out[str(pid)] = d
        except ValueError:
            pass
    return out


def escolher_formato_feed(hist, novidades_livres):
    recentes = hist.setdefault("formatos_feed", [])
    forcado = os.environ.get("FORMATO_FEED")
    if forcado in list(FORMATOS_FEED) + ["novidades"]:
        return forcado
    if len(novidades_livres) >= 3 and "novidades" not in recentes[-4:]:
        return "novidades"
    livres = [f for f in FORMATOS_FEED if f not in recentes[-1:]]
    return random.choices(livres, weights=[FORMATOS_FEED[f] for f in livres], k=1)[0]


def kits_para_vitrine(hist, produtos, n=5, prioridade=()):
    """Kits diferentes, primeiro os que ainda não apareceram no feed neste ciclo (rodízio)."""
    postados = set(hist["postados"]["kits"])
    pri = [p for p in produtos if p["id"] in set(prioridade)][:n]
    resto = [p for p in produtos if p not in pri and p.get("imagens")]
    random.shuffle(resto)
    resto.sort(key=lambda p: p["id"] in postados)
    return (pri + resto)[:n]


def _curto(nome, lim=44):
    nome = re.sub(r"^\s*(pacote|kit)\s+com\s+\d+\s+", "", nome, flags=re.I)  # "Pacote com 5 Conjuntos de X" -> "Conjuntos de X"
    nome = re.sub(r"\s*[-–—]\s*pacote com \d+.*$|\s*~\s*|\s+", " ", nome, flags=re.I).strip(" -–—")
    nome = re.sub(r"^(\w+)\s+[–-]\s+", r"\1 de ", nome)  # "Conjuntos – Short" -> "Conjuntos de Short"
    if nome.isupper():
        nome = nome.title()
    nome = nome[:1].upper() + nome[1:]
    return nome if len(nome) <= lim else nome[:lim].rsplit(" ", 1)[0] + "…"


def _preco(p):
    return f"R$ {p['preco_final']:.2f}".replace(".", ",")


COMPARTILHAR_FEED = ["Manda esse post pra quem vai revender com você 💌",
                     "Marca aquela amiga que quer começar a revender 💌",
                     "Envia pra sua sócia de revenda ver também 💌"]
CTA_FEED = ["Catálogo completo no link da bio 🔗", "Monte seu pedido em luluextra.com (link na bio) 🛍️",
            "Vê todos os modelos e cores no link da bio 👆"]


def _fechar(linhas):
    if random.random() < 0.45:
        linhas.append(random.choice(COMPARTILHAR_FEED))
    linhas.append(random.choice(CTA_FEED))
    tags = sortear_hashtags()
    if tags:
        linhas.append(tags)
    return "\n\n".join(linhas)


def montar_feed(formato, produto, hist, produtos_kits, novidades_livres, lancs):
    """Gera as lâminas (JPEG) e a legenda do post do feed. Devolve (caminhos, legenda, ids_usados)."""
    for velho in glob.glob(SAIDA_CARROSSEL.format("*")):
        os.remove(velho)
    caminhos, ids = [], []

    def grava(img):
        c = SAIDA_CARROSSEL.format(len(caminhos) + 1)
        car.salvar(img, c)
        caminhos.append(c)

    if formato == "carrossel_produto":
        fotos = []
        for u in produto["imagens"][:5]:
            try:
                fotos.append(car.baixar(u))
            except Exception as e:  # noqa: BLE001
                print(f"  foto ignorada: {e}")
        if len(fotos) < 2:
            return None
        rot = rotulo_kit(produto["nome"])
        grava(car.slide_produto(fotos[0], f"{rot} por", produto["preco_final"], _curto(produto["nome"], 40),
                                "NOVIDADE" if produto["id"] in lancs else None))
        for f in fotos[1:]:
            grava(car.foto_4x5(f))
        ids = [produto["id"]]
        legenda = _fechar([random.choice(["Arrasta pra ver esse kit de todos os ângulos 👉", "Olha esse kit por todos os lados 👉",
                                          "Mais fotos desse kit, pra você ver o caimento 👉"]),
                           f"{_curto(produto['nome'], 60)}",
                           f"{rot} por {_preco(produto)}. Cores variadas em cada kit.",
                           random.choice(["Pix com 10% de desconto nas peças.", "A partir de 6 kits, o frete Vip é grátis.",
                                          "Pedido mínimo de 4 kits."])])
        return caminhos, legenda, ids

    if formato in ("vitrine", "novidades"):
        if formato == "novidades":
            kits = [p for p in produtos_kits if p["id"] in novidades_livres][:5]
            titulo, sub = random.choice([("Chegou *novidade* no catálogo", "Lançamentos da semana na Lulu"),
                                         ("Modelos *novos* na Lulu", "Acabaram de entrar no catálogo")])
        else:
            kits = kits_para_vitrine(hist, produtos_kits, 5, prioridade=list(novidades_livres)[:1])
            titulo, sub = random.choice([("Vitrine da *semana*", "5 kits pra sua revenda"),
                                         ("Kits que vão *encher* sua vitrine", "Preço de atacado, direto da fábrica"),
                                         ("Escolhidos da *semana*", "Kits prontos de 5 peças")])
        fotos, usados = [], []
        for p in kits:
            try:
                fotos.append(car.baixar(p["imagens"][0]))
                usados.append(p)
            except Exception as e:  # noqa: BLE001
                print(f"  foto ignorada: {e}")
        if len(usados) < 3:
            return None
        grava(car.slide_capa(fotos[0], titulo, sub))
        for p, f in zip(usados, fotos):
            grava(car.slide_produto(f, f"{rotulo_kit(p['nome'])} por", p["preco_final"], _curto(p["nome"], 40),
                                    "NOVIDADE" if p["id"] in lancs else None))
        grava(car.slide_final(fotos[1:4]))
        ids = [p["id"] for p in usados]
        lista = "\n".join(f"• {rotulo_kit(p['nome'])} por {_preco(p)} — {_curto(p['nome'])}" for p in usados)
        abertura = ("Chegou novidade no catálogo ✨" if formato == "novidades"
                    else random.choice(["Vitrine da semana na Lulu 👇", "Separei 5 kits pra você conferir 👇", "Qual desses entra no seu pedido? 👇"]))
        legenda = _fechar([abertura, lista, "Pedido mínimo de 4 kits • frete Vip grátis a partir de 6 • Pix com 10% de desconto nas peças."])
        return caminhos, legenda, ids

    if formato == "info":
        feitos = hist.setdefault("temas_info", [])
        livres = [t for t in car.TEMAS_INFO if t not in feitos[-4:]]
        tema = random.choice(livres or list(car.TEMAS_INFO))
        feitos.append(tema)
        hist["temas_info"] = feitos[-12:]
        info = car.TEMAS_INFO[tema]
        kits = kits_para_vitrine(hist, produtos_kits, 4)
        fotos = []
        for p in kits:
            try:
                fotos.append(car.baixar(p["imagens"][0]))
            except Exception as e:  # noqa: BLE001
                print(f"  foto ignorada: {e}")
        if not fotos:
            return None
        grava(car.slide_capa(fotos[0], *info["capa"]))
        for k, (tit, txt) in enumerate(info["passos"], 1):
            grava(car.slide_info(k, tit, txt, fotos[k % len(fotos)]))
        grava(car.slide_final(fotos[1:4] or fotos))
        ids = [p["id"] for p in kits[:len(fotos)]]
        legenda = _fechar(list(info["legenda"]))
        print(f"Tema informativo: {tema}")
        return caminhos, legenda, ids
    return None


def main():
    os.makedirs(SAIDA_DIR, exist_ok=True)
    historico, precisa_migrar = carregar_historico()
    # rodada do dia (Salvador): decide se esta rodada também posta no FEED
    hoje = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d")
    cont = historico.get("contagem_dia") or {}
    rodada = (cont.get("n", 0) if cont.get("data") == hoje else 0) + 1
    publicar_feed = os.environ.get("FORCAR_FEED") == "1" or rodada in (2, 6)  # desde 04/11: 2 no feed/dia (≈10h e 21h)

    # a migração (se necessária) estabelece a base conhecida pras DUAS
    # lojas de uma vez, não só a que vai postar agora
    if precisa_migrar:
        for loja_m in LOJAS:
            atualizar_lancamentos(historico, loja_m, carregar_catalogo(loja_m), precisa_migrar=True)

    loja = historico["proxima_loja"]
    if publicar_feed:
        loja = "kits"  # 12/11/2026: o feed é SÓ da luluextra.com (o Story desta rodada usa o mesmo kit)
    produtos_loja = carregar_catalogo(loja)

    if precisa_migrar:
        # a base dessa loja já foi estabelecida no bloco acima — nesta
        # primeira execução não há lançamento pendente ainda
        pendentes = []
    else:
        pendentes = atualizar_lancamentos(historico, loja, produtos_loja, precisa_migrar=False)

    eh_lancamento = False
    if pendentes:
        produto_id = random.choice(pendentes)
        produto = next(p for p in produtos_loja if p["id"] == produto_id)
        eh_lancamento = True
        historico["lancamentos_pendentes"][loja] = [
            pid for pid in historico["lancamentos_pendentes"][loja] if pid != produto_id
        ]
    else:
        produto = escolher_produto_normal(loja, historico, produtos_loja)

    post = gerar_post(
        produto, loja, historico["ultimos_pilares"], eh_lancamento=eh_lancamento,
        frases_recentes=historico.setdefault("ultimas_frases", {}),
    )

    imagem_bytes = gerar_imagem_story(produto["imagens"][0], post["texto_story"])
    with open(SAIDA_STORY_IMG, "wb") as f:
        f.write(imagem_bytes)

    # foto do feed sempre convertida pra JPEG em proporção aceita pelo Instagram
    with open(SAIDA_FEED_IMG, "wb") as f:
        f.write(gerar_imagem_feed(produto["imagens"][0]))

    # Story em TODAS as rodadas (6/dia); FEED só nas rodadas 2 e 6 (≈10h e 21h) — ver topo do main().
    formato_feed, carrossel_paths, legenda_feed = None, None, post["legenda_feed"]
    if publicar_feed:
        lancs = lancamentos_recentes()
        mostradas = set(historico.setdefault("novidades_feed", []))
        kits_cat = [p for p in carregar_catalogo("kits") if p.get("imagens")]
        novidades_livres = [p["id"] for p in kits_cat if p["id"] in lancs and p["id"] not in mostradas]
        formato_feed = escolher_formato_feed(historico, novidades_livres)
        if formato_feed != "produto":
            try:
                r = montar_feed(formato_feed, produto, historico, kits_cat, novidades_livres, lancs)
            except Exception as e:  # noqa: BLE001  (carrossel nunca impede o post: cai na foto única)
                print(f"Carrossel falhou ({type(e).__name__}: {e}); volta pra foto única.")
                r = None
            if r:
                carrossel_paths, legenda_feed, ids_usados = r
                for pid in ids_usados:
                    if pid != produto["id"] and pid not in historico["postados"]["kits"]:
                        historico["postados"]["kits"].append(pid)
                if formato_feed in ("novidades", "vitrine"):
                    historico["novidades_feed"] = (historico["novidades_feed"] + [i for i in ids_usados if i in lancs])[-80:]
            else:
                formato_feed = "produto"
        historico["formatos_feed"] = (historico.get("formatos_feed", []) + [formato_feed])[-20:]
        print(f"FEED: formato {formato_feed}" + (f" ({len(carrossel_paths)} lâminas)" if carrossel_paths else ""))

    saida = {
        "loja": loja,
        "produto_id": produto["id"],
        "produto_nome": produto["nome"],
        "foto_feed_url": produto["imagens"][0],  # original (referência)
        "feed_img_repo_path": SAIDA_FEED_IMG,
        "legenda_feed": legenda_feed,
        "formato_feed": formato_feed,
        "carrossel": carrossel_paths,
        "legenda_reserva": post["legenda_feed"],  # se o carrossel falhar, a foto única sai com esta legenda
        "pilar": post["pilar"],
        "eh_lancamento": eh_lancamento,
        "publicar_feed": publicar_feed,
        "rodada_do_dia": rodada,
    }
    with open(SAIDA_POST, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    # atualiza o histórico (marca como postado, gira pra próxima loja,
    # guarda o pilar usado pra não repetir no próximo)
    historico["postados"][loja].append(produto["id"])
    historico["ultimos_pilares"] = (historico["ultimos_pilares"] + [post["pilar"]])[-5:]
    historico["proxima_loja"] = "avulso" if loja == "kits" else "kits"
    historico["contagem_dia"] = {"data": hoje, "n": rodada}
    salvar_historico(historico)

    tag = " [LANÇAMENTO]" if eh_lancamento else ""
    print(f"Produto escolhido: [{loja}]{tag} {produto['nome']} (pilar: {post['pilar']})")
    print(f"Legenda:\n{post['legenda_feed']}")
    print(f"\nTexto do Story:\n{post['texto_story']}")


if __name__ == "__main__":
    main()
