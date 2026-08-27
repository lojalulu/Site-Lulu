"""
Extra Fitness Atacado — Atualizador de catálogo
=================================================

Isso é o "motor de dados" do site. Rode este script sempre que quiser
que o site reflita o estoque atual da loja original (facilzap.com.br).

O que ele faz:
1. Lê o catálogo completo da loja original (todas as ~325 referências)
2. Para cada produto, verifica se está "Em estoque" ou "Indisponível"
3. Ignora os esgotados — só produtos disponíveis entram no site
4. Aplica a fórmula de preço: preço original x 1,6, e o resultado é
   arredondado para fechar em ",90"
   (ex.: preço original R$100,00 → x1,6 = R$160,00 → vira R$160,90.
   Se o valor calculado cair em algo como R$51,40, o site fecha em
   R$51,90 — sempre pega a parte inteira e termina em ",90")
5. Salva tudo em produtos.json, no formato que o site (index.html /
   app.js) já sabe ler

Como usar:
    pip install requests
    python atualizar_catalogo.py

Isso substitui o arquivo produtos.json desta mesma pasta. Depois é só
subir a pasta de novo pro Netlify (ou usar o deploy automático, se a
pasta já estiver conectada a um repositório/site).

Para usar em outra loja FácilZap, troque STORE_SLUG abaixo.
"""

import csv
import json
import math
import os
import re
import time
import requests

# ------------------- CONFIGURAÇÃO -------------------
STORE_SLUG = "extrafitness"
BASE_URL = f"https://facilzap.com.br/{STORE_SLUG}"
SITE_HTML = "index.html"       # o site inteiro (site + dados) mora aqui
OUTPUT_JSON = "produtos.json"  # cópia de referência, só pra você conferir os dados
LOG_CSV = "ultima_verificacao.csv"
DELAY_SECONDS = 0.4
MARKUP = 1.6
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CatalogoUpdater/1.0)"}
# ------------------------------------------------------


def preco_final(preco_original: float) -> float:
    """Aplica o markup e arredonda para terminar em ',90'."""
    marcado = round(preco_original * MARKUP, 2)
    base = math.floor(marcado)
    return round(base + 0.90, 2)


def get_lista_produtos():
    """Lê catalogo.md e retorna [(id, nome, preco_original, url_md), ...]."""
    resp = requests.get(f"{BASE_URL}/catalogo.md", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    pattern = re.compile(
        r"\[([^\]]+)\]\(https://facilzap\.com\.br/" + re.escape(STORE_SLUG) +
        r"/produto/(\d+)\.md\):\s*R\$\s*([\d\.]+,\d{2})"
    )
    vistos = set()
    produtos = []
    for nome, pid, preco_str in pattern.findall(resp.text):
        if pid in vistos:
            continue
        vistos.add(pid)
        preco = float(preco_str.replace(".", "").replace(",", "."))
        produtos.append((pid, nome.strip(), preco, f"{BASE_URL}/produto/{pid}.md"))
    return produtos


def checar_produto(url_md: str):
    """Retorna (status, lista_de_imagens) para um produto."""
    resp = requests.get(url_md, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    texto = resp.text

    disp_m = re.search(r"\*\*Disponibilidade:\*\*\s*(.+)", texto)
    disp_texto = disp_m.group(1).strip() if disp_m else ""
    if "em estoque" in disp_texto.lower():
        status = "disponivel"
    elif "indispon" in disp_texto.lower() or "esgotad" in disp_texto.lower():
        status = "esgotado"
    else:
        status = "desconhecido"

    imagens = re.findall(r"^-\s*(https?://\S+)", texto, re.MULTILINE)
    return status, imagens


def main():
    print("Lendo catálogo completo da loja...")
    produtos_catalogo = get_lista_produtos()
    print(f"{len(produtos_catalogo)} referências encontradas. Verificando estoque de cada uma...\n")

    resultado = []
    log_linhas = []
    disponiveis = 0
    esgotados = 0

    for i, (pid, nome, preco_original, url_md) in enumerate(produtos_catalogo, start=1):
        try:
            status, imagens = checar_produto(url_md)
        except Exception as e:
            print(f"[{i}/{len(produtos_catalogo)}] ERRO em {nome[:40]}: {e}")
            continue

        print(f"[{i}/{len(produtos_catalogo)}] {nome[:55]:55s} -> {status}")
        log_linhas.append({"id": pid, "nome": nome, "status": status, "preco_original": preco_original})

        if status == "disponivel" and imagens:
            resultado.append({
                "id": pid,
                "nome": nome,
                "preco_original": preco_original,
                "preco_final": preco_final(preco_original),
                "imagens": imagens,
                "cores_variadas": True,
            })
            disponiveis += 1
        elif status == "esgotado":
            esgotados += 1

        time.sleep(DELAY_SECONDS)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    # o site é um arquivo único (index.html) — atualiza o bloco de dados embutido nele
    with open(SITE_HTML, encoding="utf-8") as f:
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
        print("AVISO: não encontrei os marcadores PRODUTOS:START/END em "
              f"{SITE_HTML} — o arquivo não foi alterado. Copie o bloco "
              "manualmente ou me avise pra eu gerar o index.html de novo.")
    else:
        with open(SITE_HTML, "w", encoding="utf-8") as f:
            f.write(html_novo)

    with open(LOG_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "nome", "status", "preco_original"])
        writer.writeheader()
        writer.writerows(log_linhas)

    print("\n===== RESUMO =====")
    print(f"Disponíveis (foram para o site): {disponiveis}")
    print(f"Esgotados (ficaram de fora):     {esgotados}")
    print(f"\n{OUTPUT_JSON} atualizado com sucesso.")
    print(f"Log completo em {LOG_CSV}.")


if __name__ == "__main__":
    main()
