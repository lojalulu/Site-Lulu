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
   (lojas diferentes usam textos diferentes pra dizer "disponível" —
   esse script já entende os formatos mais comuns: "Em estoque (N
   unidades)" e "Disponivel")
3. Ignora os esgotados — só produtos disponíveis entram no site
4. Aplica a fórmula de preço configurada pra aquela loja: preço
   original x markup, arredondado pra fechar em ",90"
   (ex.: preço original R$100,00, markup 1.6 -> R$160,00 -> vira
   R$160,90 — sempre pega a parte inteira e termina em ",90")
5. Atualiza o bloco de dados embutido no index.html daquela loja, e
   salva uma cópia de referência em produtos.json + um log em CSV

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

# ------------------- CONFIGURAÇÃO DAS LOJAS -------------------
LOJAS = [
    {
        "nome": "Lulu Extra Fitness (kits)",
        "base_url": "https://facilzap.com.br/extrafitness",
        "site_html": "index.html",
        "output_json": "produtos.json",
        "log_csv": "ultima_verificacao.csv",
        "markup": 1.6,
        "cores_variadas": True,   # kits com sortimento de cores
    },
    {
        "nome": "Lulu Peças Avulsas",
        "base_url": "https://usefga.com.br",
        "site_html": "kitavulso/index.html",
        "output_json": "kitavulso/produtos.json",
        "log_csv": "kitavulso/ultima_verificacao.csv",
        "markup": 1.6,   # mesma margem por enquanto; ajuste aqui se quiser diferente
        "cores_variadas": False,  # peça avulsa, não é kit sortido
    },
]

DELAY_SECONDS = 0.4
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CatalogoUpdater/1.0)"}
# ------------------------------------------------------


def preco_final(preco_original: float, markup: float) -> float:
    """Aplica o markup e arredonda para terminar em ',90'."""
    marcado = round(preco_original * markup, 2)
    base = math.floor(marcado)
    return round(base + 0.90, 2)


def get_lista_produtos(base_url: str):
    """Lê catalogo.md e retorna [(id, nome, preco_original, url_md), ...].

    Funciona com qualquer loja FácilZap, seja no formato
    facilzap.com.br/<loja> ou num domínio próprio como usefga.com.br,
    porque captura a URL do produto direto do link, sem presumir o
    formato do domínio.
    """
    resp = requests.get(f"{base_url}/catalogo.md", headers=HEADERS, timeout=30)
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


def checar_produto(url_md: str):
    """Retorna (status, lista_de_imagens) para um produto.

    Aceita os formatos de disponibilidade usados pelas lojas FácilZap:
    - "Em estoque (N unidades)"   -> disponível
    - "Disponivel" / "Disponível" -> disponível
    - "Indisponivel..." / "Esgotado..." -> esgotado
    (a checagem de indisponível vem primeiro de propósito, porque a
    palavra "disponivel" aparece DENTRO de "indisponivel" também)
    """
    resp = requests.get(url_md, headers=HEADERS, timeout=30)
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
    print("Lendo catálogo completo da loja...")
    produtos_catalogo = get_lista_produtos(config["base_url"])
    print(f"{len(produtos_catalogo)} referências encontradas. Verificando estoque de cada uma...\n")

    resultado = []
    log_linhas = []
    disponiveis = 0
    esgotados = 0

    for i, (pid, nome_produto, preco_original, url_md) in enumerate(produtos_catalogo, start=1):
        try:
            status, imagens = checar_produto(url_md)
        except Exception as e:
            print(f"[{i}/{len(produtos_catalogo)}] ERRO em {nome_produto[:40]}: {e}")
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

    print(f"\n----- Resumo: {nome} -----")
    print(f"Disponíveis (foram para o site): {disponiveis}")
    print(f"Esgotados (ficaram de fora):     {esgotados}")
    print(f"{config['output_json']} e {config['site_html']} atualizados.")

    return disponiveis, esgotados


def main():
    totais = []
    for config in LOJAS:
        totais.append((config["nome"], *atualizar_loja(config)))

    print("\n===== RESUMO GERAL =====")
    for nome, disponiveis, esgotados in totais:
        print(f"{nome}: {disponiveis} disponíveis, {esgotados} esgotados")


if __name__ == "__main__":
    main()
