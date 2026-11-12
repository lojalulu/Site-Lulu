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

GRAPH_API_VERSION = "v23.0"  # conferir em developers.facebook.com/docs/instagram-platform/changelog
# Seu app usa "Instagram Business Login" (não Facebook Login) — por isso o
# host certo é graph.instagram.com, não graph.facebook.com.
GRAPH_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"

ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
IG_USER_ID = os.environ.get("INSTAGRAM_BUSINESS_ID")
REPO = os.environ.get("GITHUB_REPOSITORY")  # ex: "lojalulu/Site-Lulu", já vem pronto no GitHub Actions

SAIDA_POST = "instagram/_saida/post.json"
STORY_IMG_REPO_PATH = "instagram/_saida/story.jpg"


def url_bruta_da_imagem_no_github(caminho: str = STORY_IMG_REPO_PATH) -> str:
    if not REPO:
        raise RuntimeError("GITHUB_REPOSITORY não definido — rode isso dentro do GitHub Actions.")
    # ?v= evita a Meta pegar a imagem antiga do cache (mesmo nome de arquivo toda vez)
    return f"https://raw.githubusercontent.com/{REPO}/main/{caminho}?v={int(time.time())}"


def _checar_erro(resp: requests.Response, contexto: str):
    if resp.status_code >= 300:
        raise RuntimeError(f"Erro em {contexto}: {resp.status_code} — {resp.text}")


def criar_container(image_url: str = None, media_type: str = None, caption: str = None, **extra) -> str:
    params = {"access_token": ACCESS_TOKEN}
    if image_url:
        params["image_url"] = image_url
    if media_type:
        params["media_type"] = media_type
    if caption:
        params["caption"] = caption
    params.update({k: v for k, v in extra.items() if v is not None})
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
    # A Meta às vezes diz "FINISHED" e ainda recusa a publicação por alguns
    # segundos ("Media ID is not available", código 9007/2207027). Tenta de novo.
    for tentativa in range(1, 9):
        resp = requests.post(
            f"{GRAPH_BASE}/{IG_USER_ID}/media_publish",
            data={"creation_id": creation_id, "access_token": ACCESS_TOKEN},
            timeout=30,
        )
        if resp.status_code < 300:
            return resp.json()["id"]
        if "2207027" in resp.text or '"code":9007' in resp.text:
            print(f"  mídia ainda não pronta (tentativa {tentativa}/8), esperando 8s...")
            time.sleep(8)
            continue
        _checar_erro(resp, "publicar")
    _checar_erro(resp, "publicar")


def publicar_carrossel(caminhos, legenda) -> str:
    """Carrossel (2 a 10 lâminas JPEG 4:5 hospedadas no repositório)."""
    filhos = []
    for c in caminhos[:10]:
        cid = criar_container(url_bruta_da_imagem_no_github(c), is_carousel_item="true")
        filhos.append(cid)
    for cid in filhos:
        esperar_pronto(cid)
    pai = criar_container(media_type="CAROUSEL", caption=legenda, children=",".join(filhos))
    esperar_pronto(pai, tentativas=20)
    return publicar(pai)


def main():
    if not ACCESS_TOKEN or not IG_USER_ID:
        print("ERRO: faltam os segredos INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID.")
        sys.exit(1)

    with open(SAIDA_POST, encoding="utf-8") as f:
        post = json.load(f)

    print(f"Publicando: [{post['loja']}] {post['produto_nome']}")

    falhas = []

    # ----- 1) Feed: foto do produto (JPEG convertido) + legenda -----
    # (só nas rodadas pares: 3 posts no feed por dia; story sai sempre)
    if post.get("publicar_feed", True) is False:
        print(f"Rodada {post.get('rodada_do_dia')} do dia: só Story (feed fica para a próxima rodada).")
    else:
        try:
            print("Criando post do feed...")
            if post.get("carrossel"):
                try:
                    id_feed = publicar_carrossel(post["carrossel"], post["legenda_feed"])
                    print(f"Carrossel publicado ({post.get('formato_feed')}, {len(post['carrossel'])} lâminas): {id_feed}")
                    post["_feito"] = True
                except Exception as e:  # noqa: BLE001
                    print(f"CARROSSEL FALHOU ({e}); publicando a foto única do kit no lugar.")
            if post.get("_feito"):
                pass
            elif post.get("feed_img_repo_path"):
                url_feed = url_bruta_da_imagem_no_github(post["feed_img_repo_path"])
            else:
                url_feed = post["foto_feed_url"]
            if not post.get("_feito"):
                legenda = post["legenda_feed"] if not post.get("carrossel") else post.get("legenda_reserva", post["legenda_feed"])
                container_feed = criar_container(url_feed, caption=legenda)
                esperar_pronto(container_feed)
                id_feed = publicar(container_feed)
                print(f"Feed publicado: {id_feed}")
        except Exception as e:
            print(f"FEED FALHOU: {e}")
            falhas.append(f"feed: {e}")

    # ----- 2) Story: sai mesmo se o feed falhar -----
    try:
        print("Criando Story...")
        url_story = url_bruta_da_imagem_no_github()
        container_story = criar_container(url_story, media_type="STORIES")
        esperar_pronto(container_story)
        id_story = publicar(container_story)
        print(f"Story publicado: {id_story}")
    except Exception as e:
        print(f"STORY FALHOU: {e}")
        falhas.append(f"story: {e}")

    if falhas:
        raise RuntimeError(" | ".join(falhas))
    print("\nTudo certo — feed e story publicados com sucesso.")


if __name__ == "__main__":
    ERRO = "instagram/ultimo_erro_post.txt"
    try:
        main()
        if os.path.exists(ERRO):
            os.remove(ERRO)
    except BaseException:
        import traceback
        with open(ERRO, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()) + "\n" + traceback.format_exc()[-3000:])
        raise
