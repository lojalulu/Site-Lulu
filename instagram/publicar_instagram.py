"""
Passo 2 do robô do Instagram: pega o que o gerar_conteudo.py preparou
e publica de verdade — 1 post no feed + 1 Story — via API oficial da
Meta (Instagram Graph API).

Pré-requisitos (ver GUIA-INSTAGRAM.md):
- Conta Instagram Business/Creator ligada a uma Página do Facebook
- Um Meta App com você como "Instagram Tester" (ou Administrador)
- Um token de acesso e o ID da conta comercial, guardados como
  segredos do repositório: INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ID
"""

import json
import os
import sys
import time

import requests

GRAPH_API_VERSION = "v26.0"  # conferir em developers.facebook.com/docs/graph-api/changelog
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
IG_USER_ID = os.environ.get("INSTAGRAM_BUSINESS_ID")
REPO = os.environ.get("GITHUB_REPOSITORY")  # ex: "lojalulu/Site-Lulu", já vem pronto no GitHub Actions

SAIDA_POST = "instagram/_saida/post.json"
STORY_IMG_REPO_PATH = "instagram/_saida/story.jpg"


def url_bruta_da_imagem_no_github() -> str:
    if not REPO:
        raise RuntimeError("GITHUB_REPOSITORY não definido — rode isso dentro do GitHub Actions.")
    return f"https://raw.githubusercontent.com/{REPO}/main/{STORY_IMG_REPO_PATH}"


def _checar_erro(resp: requests.Response, contexto: str):
    if resp.status_code >= 300:
        raise RuntimeError(f"Erro em {contexto}: {resp.status_code} — {resp.text}")


def criar_container(image_url: str, media_type: str = None, caption: str = None) -> str:
    params = {"image_url": image_url, "access_token": ACCESS_TOKEN}
    if media_type:
        params["media_type"] = media_type
    if caption:
        params["caption"] = caption
    resp = requests.post(f"{GRAPH_BASE}/{IG_USER_ID}/media", data=params, timeout=30)
    _checar_erro(resp, "criar container")
    return resp.json()["id"]


def esperar_pronto(creation_id: str, tentativas: int = 10, espera_segundos: int = 3):
    for _ in range(tentativas):
        resp = requests.get(
            f"{GRAPH_BASE}/{creation_id}",
            params={"fields": "status_code", "access_token": ACCESS_TOKEN},
            timeout=30,
        )
        _checar_erro(resp, "checar status do container")
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Container {creation_id} falhou no processamento da Meta.")
        time.sleep(espera_segundos)
    raise RuntimeError(f"Container {creation_id} não ficou pronto a tempo.")


def publicar(creation_id: str) -> str:
    resp = requests.post(
        f"{GRAPH_BASE}/{IG_USER_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": ACCESS_TOKEN},
        timeout=30,
    )
    _checar_erro(resp, "publicar")
    return resp.json()["id"]


def main():
    if not ACCESS_TOKEN or not IG_USER_ID:
        print("ERRO: faltam os segredos INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID.")
        sys.exit(1)

    with open(SAIDA_POST, encoding="utf-8") as f:
        post = json.load(f)

    print(f"Publicando: [{post['loja']}] {post['produto_nome']}")

    # ----- 1) Feed: foto real do produto + legenda -----
    print("Criando post do feed...")
    container_feed = criar_container(post["foto_feed_url"], caption=post["legenda_feed"])
    esperar_pronto(container_feed)
    id_feed = publicar(container_feed)
    print(f"Feed publicado: {id_feed}")

    # ----- 2) Story: imagem composta (Link na bio), já publicada no GitHub -----
    print("Criando Story...")
    url_story = url_bruta_da_imagem_no_github()
    container_story = criar_container(url_story, media_type="STORIES")
    esperar_pronto(container_story)
    id_story = publicar(container_story)
    print(f"Story publicado: {id_story}")

    print("\nTudo certo — feed e story publicados com sucesso.")


if __name__ == "__main__":
    main()
