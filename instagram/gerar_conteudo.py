"""
Passo 1 do robô do Instagram: escolhe o próximo produto (alternando
entre as duas lojas, sem repetir até esgotar o catálogo), gera a
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
    if os.path.exists(HISTORICO_PATH):
        with open(HISTORICO_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {
        "proxima_loja": "kits",
        "postados": {"kits": [], "avulso": []},
        "ultimos_pilares": [],
    }


def salvar_historico(historico):
    os.makedirs(os.path.dirname(HISTORICO_PATH), exist_ok=True)
    with open(HISTORICO_PATH, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)


def escolher_produto(loja: str, historico: dict) -> dict:
    with open(LOJAS[loja], encoding="utf-8") as f:
        produtos = json.load(f)

    postados = set(historico["postados"][loja])
    candidatos = [p for p in produtos if p["id"] not in postados]

    if not candidatos:
        # já postou todo mundo dessa loja — recomeça o ciclo
        historico["postados"][loja] = []
        candidatos = produtos

    return random.choice(candidatos)


def main():
    os.makedirs(SAIDA_DIR, exist_ok=True)
    historico = carregar_historico()

    loja = historico["proxima_loja"]
    produto = escolher_produto(loja, historico)

    post = gerar_post(produto, loja, historico["ultimos_pilares"])

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
    }
    with open(SAIDA_POST, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    # atualiza o histórico (marca como postado, gira pra próxima loja,
    # guarda o pilar usado pra não repetir no próximo)
    historico["postados"][loja].append(produto["id"])
    historico["ultimos_pilares"] = (historico["ultimos_pilares"] + [post["pilar"]])[-5:]
    historico["proxima_loja"] = "avulso" if loja == "kits" else "kits"
    salvar_historico(historico)

    print(f"Produto escolhido: [{loja}] {produto['nome']} (pilar: {post['pilar']})")
    print(f"Legenda:\n{post['legenda_feed']}")


if __name__ == "__main__":
    main()
