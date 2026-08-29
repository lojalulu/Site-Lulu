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

from conteudo import gerar_post
from imagem_story import gerar_imagem_story

HISTORICO_PATH = "instagram/historico_postagens.json"
SAIDA_DIR = "instagram/_saida"
SAIDA_POST = f"{SAIDA_DIR}/post.json"
SAIDA_STORY_IMG = f"{SAIDA_DIR}/story.jpg"

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


def main():
    os.makedirs(SAIDA_DIR, exist_ok=True)
    historico, precisa_migrar = carregar_historico()

    # a migração (se necessária) estabelece a base conhecida pras DUAS
    # lojas de uma vez, não só a que vai postar agora
    if precisa_migrar:
        for loja_m in LOJAS:
            atualizar_lancamentos(historico, loja_m, carregar_catalogo(loja_m), precisa_migrar=True)

    loja = historico["proxima_loja"]
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

    post = gerar_post(produto, loja, historico["ultimos_pilares"], eh_lancamento=eh_lancamento)

    imagem_bytes = gerar_imagem_story(produto["imagens"][0], post["texto_story"])
    with open(SAIDA_STORY_IMG, "wb") as f:
        f.write(imagem_bytes)

    saida = {
        "loja": loja,
        "produto_id": produto["id"],
        "produto_nome": produto["nome"],
        "foto_feed_url": produto["imagens"][0],
        "legenda_feed": post["legenda_feed"],
        "pilar": post["pilar"],
        "eh_lancamento": eh_lancamento,
    }
    with open(SAIDA_POST, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    # atualiza o histórico (marca como postado, gira pra próxima loja,
    # guarda o pilar usado pra não repetir no próximo)
    historico["postados"][loja].append(produto["id"])
    historico["ultimos_pilares"] = (historico["ultimos_pilares"] + [post["pilar"]])[-5:]
    historico["proxima_loja"] = "avulso" if loja == "kits" else "kits"
    salvar_historico(historico)

    tag = " [LANÇAMENTO]" if eh_lancamento else ""
    print(f"Produto escolhido: [{loja}]{tag} {produto['nome']} (pilar: {post['pilar']})")
    print(f"Legenda:\n{post['legenda_feed']}")
    print(f"\nTexto do Story:\n{post['texto_story']}")


if __name__ == "__main__":
    main()
