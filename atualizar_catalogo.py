"""
Lulu — Atualizador de catálogo (kits + peças avulsas)
========================================================

Isso é o "motor de dados" dos dois sites:
- index.html            -> Lulu Extra Fitness (kits, fonte: facilzap.com.br/extrafitness)
- kitavulso/index.html  -> Lulu Peças Avulsas (fonte: usefga.com.br)

Rode este script sempre que quiser que os sites reflitam o estoque
atual das lojas originais.

O que ele faz, pra CADA loja configurada em LOJAS (lá embaixo):
1. Lê o catálogo completo da loja original
2. Para cada produto, verifica se está disponível ou indisponível
3. Ignora os esgotados — só produtos disponíveis entram no site
4. Aplica a fórmula de preço configurada pra aquela loja: preço
   original x markup, arredondado pra fechar em ",90"
5. Atualiza o bloco de dados embutido no index.html daquela loja, e
   salva uma cópia de referência em produtos.json + um log em CSV

IMPORTANTE — sobre erros de rede:
Se uma consulta falhar (timeout, bloqueio temporário, instabilidade),
o script tenta de novo até 3 vezes antes de desistir daquele produto.
Se mesmo assim falhar, ele NÃO finge que o produto está esgotado — ele
entra numa contagem separada de "erros" e aparece bem destacado no
resumo final, junto com a lista de quais produtos falharam, salva em
erros.csv (ou kitavulso/erros.csv). Se o número de erros for alto,
isso quase sempre significa que a loja bloqueou/limitou as consultas
temporariamente, e não que os produtos estejam mesmo fora de estoque
— nesse caso, rodar de novo mais tarde costuma resolver.

Como usar:
    pip install requests
    python atualizar_catalogo.py

Isso já atualiza as DUAS lojas de uma vez, na ordem em que aparecem
na lista LOJAS. Depois é só subir os arquivos de novo pro GitHub (ou
deixar o robô do GitHub Actions fazer isso sozinho toda semana).
"""

import csv
import json
import math
import os
import re
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ------------------- CONFIGURAÇÃO DAS LOJAS -------------------
LOJAS = [
    {
        "nome": "Lulu Extra Fitness (kits)",
        "base_url": "https://facilzap.com.br/extrafitness",
        "site_html": "index.html",
        "output_json": "produtos.json",
        "log_csv": "ultima_verificacao.csv",
        "erros_csv": "erros.csv",
        "markup": 1.6,
        "cores_variadas": True,   # kits com sortimento de cores
    },
    {
        "nome": "Lulu Peças Avulsas",
        "base_url": "https://usefga.com.br",
        "site_html": "kitavulso/index.html",
        "output_json": "kitavulso/produtos.json",
        "log_csv": "kitavulso/ultima_verificacao.csv",
        "erros_csv": "kitavulso/erros.csv",
        "markup": 1.6,   # mesma margem por enquanto; ajuste aqui se quiser diferente
        "cores_variadas": False,  # peça avulsa, não é kit sortido
    },
]

DELAY_SECONDS = 1.0   # pausa entre produtos — mais conservador que antes, de propósito
TENTATIVAS_POR_PRODUTO = 3
TIMEOUT_SEGUNDOS = 30

# Cabeçalhos parecidos com um navegador de verdade. O nome antigo
# ("CatalogoUpdater/1.0") deixava óbvio pra loja que era um robô, e
# lojas com proteção antibot costumam bloquear/limitar esse tipo de
# identificação depois de poucas consultas — o que explica quedas
# bruscas na quantidade de produtos encontrados numa execução real.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/markdown,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


def criar_sessao() -> requests.Session:
    """Sessão HTTP com novas tentativas automáticas para erros passageiros
    (timeout, erro 5xx, conexão recusada) — evita que uma falha momentânea
    já derrube o produto da lista."""
    sessao = requests.Session()
    sessao.headers.update(HEADERS)
    retry = Retry(
        total=TENTATIVAS_POR_PRODUTO,
        backoff_factor=2,  # espera 2s, depois 4s, depois 8s entre tentativas
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    sessao.mount("https://", adapter)
    sessao.mount("http://", adapter)
    return sessao


def preco_final(preco_original: float, markup: float) -> float:
    """Aplica o markup e arredonda para terminar em ',90'."""
    marcado = round(preco_original * markup, 2)
    base = math.floor(marcado)
    return round(base + 0.90, 2)


def get_lista_produtos(sessao: requests.Session, base_url: str):
    """Lê catalogo.md e retorna [(id, nome, preco_original, url_md), ...]."""
    resp = sessao.get(f"{base_url}/catalogo.md", timeout=TIMEOUT_SEGUNDOS)
    resp.raise_for_status()
    pattern = re.compile(
        r"\[([^\]]+)\]\((https?://[^\)]+?/produto/(\d+)\.md)\):\s*R\$\s*([\d\.]+,\d{2})"
    )
    vistos = set()
    produtos = []
    for nome, url_md, pid, preco_str in pattern.findall(resp.text):
        if pid in vistos:
            continue
        vistos.add(pid)
        preco = float(preco_str.replace(".", "").replace(",", "."))
        produtos.append((pid, nome.strip(), preco, url_md))
    return produtos


def checar_produto(sessao: requests.Session, url_md: str):
    """Retorna (status, lista_de_imagens) para um produto."""
    resp = sessao.get(url_md, timeout=TIMEOUT_SEGUNDOS)
    resp.raise_for_status()
    texto = resp.text

    disp_m = re.search(r"\*\*Disponibilidade:\*\*\s*(.+)", texto)
    disp_texto = disp_m.group(1).strip() if disp_m else ""
    disp_lower = disp_texto.lower()

    if "indispon" in disp_lower or "esgotad" in disp_lower:
        status = "esgotado"
    elif "em estoque" in disp_lower or "dispon" in disp_lower:
        status = "disponivel"
    else:
        status = "desconhecido"

    imagens = re.findall(r"^-\s*(https?://\S+)", texto, re.MULTILINE)
    return status, imagens


def atualizar_loja(config: dict):
    nome = config["nome"]
    print(f"\n========== {nome} ==========")
    sessao = criar_sessao()

    print("Lendo catálogo completo da loja...")
    produtos_catalogo = get_lista_produtos(sessao, config["base_url"])
    print(f"{len(produtos_catalogo)} referências encontradas. Verificando estoque de cada uma...\n")

    resultado = []
    log_linhas = []
    erros_linhas = []
    disponiveis = 0
    esgotados = 0

    for i, (pid, nome_produto, preco_original, url_md) in enumerate(produtos_catalogo, start=1):
        try:
            status, imagens = checar_produto(sessao, url_md)
        except Exception as e:
            print(f"[{i}/{len(produtos_catalogo)}] ERRO em {nome_produto[:40]}: {e}")
            erros_linhas.append({"id": pid, "nome": nome_produto, "erro": str(e)})
            time.sleep(DELAY_SECONDS)
            continue

        print(f"[{i}/{len(produtos_catalogo)}] {nome_produto[:55]:55s} -> {status}")
        log_linhas.append({"id": pid, "nome": nome_produto, "status": status, "preco_original": preco_original})

        if status == "disponivel" and imagens:
            resultado.append({
                "id": pid,
                "nome": nome_produto,
                "preco_original": preco_original,
                "preco_final": preco_final(preco_original, config["markup"]),
                "imagens": imagens,
                "cores_variadas": config["cores_variadas"],
            })
            disponiveis += 1
        elif status == "esgotado":
            esgotados += 1

        time.sleep(DELAY_SECONDS)

    # garante que a pasta de destino existe (ex.: "kitavulso/")
    pasta = os.path.dirname(config["output_json"])
    if pasta:
        os.makedirs(pasta, exist_ok=True)

    with open(config["output_json"], "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    # o site é um arquivo único (index.html) — atualiza o bloco de dados embutido nele
    with open(config["site_html"], encoding="utf-8") as f:
        html = f.read()

    novo_bloco = (
        '<!-- PRODUTOS:START -->\n'
        '<script id="produtos-data" type="application/json">\n'
        + json.dumps(resultado, ensure_ascii=False, indent=2) +
        '\n</script>\n'
        '<!-- PRODUTOS:END -->'
    )
    html_novo, n = re.subn(
        r'<!-- PRODUTOS:START -->.*?<!-- PRODUTOS:END -->',
        lambda _: novo_bloco,
        html,
        flags=re.S,
    )
    if n == 0:
        print(f"AVISO: não encontrei os marcadores PRODUTOS:START/END em "
              f"{config['site_html']} — o arquivo não foi alterado.")
    else:
        with open(config["site_html"], "w", encoding="utf-8") as f:
            f.write(html_novo)

    with open(config["log_csv"], "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "nome", "status", "preco_original"])
        writer.writeheader()
        writer.writerows(log_linhas)

    with open(config["erros_csv"], "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "nome", "erro"])
        writer.writeheader()
        writer.writerows(erros_linhas)

    print(f"\n----- Resumo: {nome} -----")
    print(f"Disponíveis (foram para o site): {disponiveis}")
    print(f"Esgotados (ficaram de fora):     {esgotados}")
    print(f"Erros de consulta (NÃO contam como esgotado): {len(erros_linhas)}")

    taxa_erro = len(erros_linhas) / len(produtos_catalogo) if produtos_catalogo else 0
    if taxa_erro > 0.10:
        print("\n" + "!" * 70)
        print(f"AVISO IMPORTANTE: {len(erros_linhas)} de {len(produtos_catalogo)} produtos "
              f"({taxa_erro:.0%}) falharam por erro de rede, não porque estão esgotados.")
        print("Isso costuma acontecer quando a loja bloqueia/limita consultas em sequência.")
        print(f"Detalhes em {config['erros_csv']}. Recomendo rodar de novo mais tarde.")
        print("!" * 70)

    print(f"\n{config['output_json']} e {config['site_html']} atualizados.")

    return disponiveis, esgotados, len(erros_linhas)


def main():
    totais = []
    for config in LOJAS:
        totais.append((config["nome"], *atualizar_loja(config)))

    print("\n===== RESUMO GERAL =====")
    for nome, disponiveis, esgotados, erros in totais:
        extra = f" — ATENÇÃO: {erros} erros de rede" if erros else ""
        print(f"{nome}: {disponiveis} disponíveis, {esgotados} esgotados{extra}")


if __name__ == "__main__":
    main()
