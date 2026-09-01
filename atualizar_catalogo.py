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
        "rastrear_novidades": True,  # ativa o campo "lancamento" (seção
                                      # "ACABARAM DE CHEGAR" no site)
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
        "extrair_tamanhos": True,  # só essa loja mostra seletor de tamanho no site
    },
]

# Se True, salva o texto bruto (.md) dos primeiros produtos de cada loja
# com extrair_tamanhos=True em debug_tamanhos.txt (ou kitavulso/debug_tamanhos.txt).
# Serve só pra conferir/ajustar o formato real de como a loja original escreve
# os tamanhos — depois que confirmar que está extraindo certo, pode deixar False.
DEBUG_TAMANHOS = False
DEBUG_TAMANHOS_QTD_AMOSTRAS = 5

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


def extrair_tamanhos_do_texto(texto: str):
    """Tenta reconhecer a lista de tamanhos disponíveis de um produto a
    partir do texto (.md) da página. Isso é 'melhor esforço': o robô ainda
    não teve a chance de rodar contra o formato real da loja usefga.com.br,
    então os padrões abaixo cobrem os jeitos mais comuns que o FácilZap
    costuma usar — mas pode precisar de ajuste depois da primeira execução
    real (ative DEBUG_TAMANHOS=True lá em cima pra investigar).

    Sempre retorna uma lista (vazia se não encontrar nada reconhecível) —
    nunca quebra o robô por causa disso."""

    TAMANHOS_VALIDOS = {"PP", "P", "M", "G", "GG", "XG", "XGG", "U", "ÚNICO", "UNICO",
                         "36", "38", "40", "42", "44", "46", "48", "50"}

    def limpar_lista(bruto):
        # separa por vírgula, barra ou "e", remove parênteses tipo "M (2 un.)"
        pedacos = re.split(r"[,/]| e ", bruto)
        tamanhos = []
        for p in pedacos:
            p = re.sub(r"\(.*?\)", "", p).strip().upper()
            if p and p not in tamanhos:
                tamanhos.append(p)
        return tamanhos

    # Padrão 1: uma linha tipo "**Tamanhos:** P, M, G, GG" ou "**Tamanho:** ..."
    m = re.search(r"\*\*Tamanhos?(?:\s+dispon[íi]veis)?:\*\*\s*(.+)", texto, re.IGNORECASE)
    if m:
        tamanhos = limpar_lista(m.group(1))
        if tamanhos:
            return tamanhos

    # Padrão 2: uma linha tipo "**Variações:** P, M, G" ou "**Opções:** ..."
    m = re.search(r"\*\*(?:Varia[çc][õo]es|Op[çc][õo]es):\*\*\s*(.+)", texto, re.IGNORECASE)
    if m:
        tamanhos = limpar_lista(m.group(1))
        if tamanhos:
            return tamanhos

    # Padrão 3: lista em itens de markdown, ex.:
    #   - P (disponível)
    #   - M
    #   - G (esgotado)
    # Só considera "disponível"/sem menção de esgotado como tamanho válido.
    itens = re.findall(r"^-\s*([A-Za-zÀ-ú0-9]{1,4})\s*(\(.*?\))?\s*$", texto, re.MULTILINE)
    if itens:
        candidatos = []
        for tam, obs in itens:
            tam_upper = tam.strip().upper()
            if tam_upper in TAMANHOS_VALIDOS:
                if obs and re.search(r"esgotad|indispon", obs, re.IGNORECASE):
                    continue
                if tam_upper not in candidatos:
                    candidatos.append(tam_upper)
        if candidatos:
            return candidatos

    return []


def checar_produto(sessao: requests.Session, url_md: str, extrair_tamanhos: bool = False):
    """Retorna (status, lista_de_imagens, lista_de_tamanhos) para um produto.
    lista_de_tamanhos vem vazia quando extrair_tamanhos=False, ou quando o
    produto não tem opção de tamanho / o robô não conseguiu reconhecer o
    formato da página."""
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

    tamanhos = []
    if extrair_tamanhos:
        tamanhos = extrair_tamanhos_do_texto(texto)

    return status, imagens, tamanhos, texto


def atualizar_loja(config: dict):
    nome = config["nome"]
    extrair_tamanhos = config.get("extrair_tamanhos", False)
    rastrear_novidades = config.get("rastrear_novidades", False)
    print(f"\n========== {nome} ==========")
    sessao = criar_sessao()

    print("Lendo catálogo completo da loja...")
    produtos_catalogo = get_lista_produtos(sessao, config["base_url"])
    print(f"{len(produtos_catalogo)} referências encontradas. Verificando estoque de cada uma...\n")

    # ----- detecção de lançamento (produtos novos desde a última execução) -----
    pasta_saida = os.path.dirname(config["output_json"])
    caminho_conhecidos = os.path.join(pasta_saida, "produtos_conhecidos.json") if pasta_saida else "produtos_conhecidos.json"
    primeira_execucao = not os.path.exists(caminho_conhecidos)
    if rastrear_novidades and not primeira_execucao:
        with open(caminho_conhecidos, encoding="utf-8") as f:
            ids_conhecidos = set(json.load(f))
    else:
        ids_conhecidos = set()
    # na primeira execução com essa opção ligada, ninguém é "lançamento"
    # (senão o catálogo inteiro apareceria como novidade de uma vez só)

    resultado = []
    log_linhas = []
    erros_linhas = []
    sem_imagem_linhas = []
    status_desconhecido_linhas = []
    disponiveis = 0
    esgotados = 0
    amostras_debug = []
    ids_disponiveis_agora = set()

    for i, (pid, nome_produto, preco_original, url_md) in enumerate(produtos_catalogo, start=1):
        try:
            status, imagens, tamanhos, texto_bruto = checar_produto(sessao, url_md, extrair_tamanhos)
        except Exception as e:
            print(f"[{i}/{len(produtos_catalogo)}] ERRO em {nome_produto[:40]}: {e}")
            erros_linhas.append({"id": pid, "nome": nome_produto, "erro": str(e)})
            time.sleep(DELAY_SECONDS)
            continue

        tag_tam = f" [tamanhos: {', '.join(tamanhos)}]" if tamanhos else (" [sem tamanho reconhecido]" if extrair_tamanhos else "")
        print(f"[{i}/{len(produtos_catalogo)}] {nome_produto[:55]:55s} -> {status}{tag_tam}")
        log_linhas.append({"id": pid, "nome": nome_produto, "status": status, "preco_original": preco_original})

        if DEBUG_TAMANHOS and extrair_tamanhos and len(amostras_debug) < DEBUG_TAMANHOS_QTD_AMOSTRAS:
            amostras_debug.append(f"===== {pid} — {nome_produto} =====\n{texto_bruto}\n")

        if status == "disponivel" and imagens:
            ids_disponiveis_agora.add(pid)
            item = {
                "id": pid,
                "nome": nome_produto,
                "preco_original": preco_original,
                "preco_final": preco_final(preco_original, config["markup"]),
                "imagens": imagens,
                "cores_variadas": config["cores_variadas"],
            }
            if extrair_tamanhos:
                item["tamanhos"] = tamanhos  # lista vazia = produto sem seletor de tamanho no site
            if rastrear_novidades:
                item["lancamento"] = (not primeira_execucao) and (pid not in ids_conhecidos)
            resultado.append(item)
            disponiveis += 1
        elif status == "esgotado":
            esgotados += 1
        elif status == "disponivel" and not imagens:
            # AUDITORIA: produto está disponível na loja original, mas o robô
            # não conseguiu extrair nenhuma foto — sem foto, não dá pra
            # mostrar no site, então fica de fora. Antes isso desaparecia em
            # silêncio; agora fica registrado aqui pra você conferir.
            sem_imagem_linhas.append({"id": pid, "nome": nome_produto, "erro": "disponível mas sem nenhuma imagem reconhecida"})
        else:
            # AUDITORIA: status não reconhecido (nem "disponível" nem
            # "esgotado" — o texto de disponibilidade da loja não bateu com
            # nenhum padrão esperado). Também ficava de fora em silêncio.
            status_desconhecido_linhas.append({"id": pid, "nome": nome_produto, "erro": f"status não reconhecido: '{status}'"})

        time.sleep(DELAY_SECONDS)

    if rastrear_novidades:
        with open(caminho_conhecidos, "w", encoding="utf-8") as f:
            json.dump(sorted(ids_conhecidos | ids_disponiveis_agora), f)

    if DEBUG_TAMANHOS and amostras_debug:
        pasta_debug = os.path.dirname(config["output_json"])
        caminho_debug = os.path.join(pasta_debug, "debug_tamanhos.txt") if pasta_debug else "debug_tamanhos.txt"
        with open(caminho_debug, "w", encoding="utf-8") as f:
            f.write("\n\n".join(amostras_debug))
        print(f"\n[DEBUG_TAMANHOS] Amostras brutas salvas em {caminho_debug} — "
              f"envie esse arquivo pra ajustar a extração de tamanhos, se necessário.")

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

    caminho_sem_imagem = os.path.join(pasta_saida, "produtos_sem_imagem.csv") if pasta_saida else "produtos_sem_imagem.csv"
    with open(caminho_sem_imagem, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "nome", "erro"])
        writer.writeheader()
        writer.writerows(sem_imagem_linhas + status_desconhecido_linhas)

    print(f"\n----- Resumo: {nome} -----")
    print(f"Disponíveis (foram para o site): {disponiveis}")
    print(f"Esgotados (ficaram de fora):     {esgotados}")
    print(f"Erros de consulta (NÃO contam como esgotado): {len(erros_linhas)}")
    if sem_imagem_linhas:
        print(f"AVISO: {len(sem_imagem_linhas)} produto(s) disponível(is) mas SEM imagem "
              f"reconhecida — ficaram de fora do site. Detalhes em {caminho_sem_imagem}.")
    if status_desconhecido_linhas:
        print(f"AVISO: {len(status_desconhecido_linhas)} produto(s) com status de disponibilidade "
              f"não reconhecido pelo robô — ficaram de fora do site. Detalhes em {caminho_sem_imagem}.")

    # AUDITORIA GERAL: toda referência do catálogo tem que cair em uma
    # dessas 5 categorias. Se a soma não bater com o total lido, alguma
    # referência está desaparecendo em algum lugar do código sem ser
    # contabilizada — isso é o alerta que confirma (ou descarta) que o
    # robô está deixando produtos de fora sem avisar.
    total_contabilizado = disponiveis + esgotados + len(erros_linhas) + len(sem_imagem_linhas) + len(status_desconhecido_linhas)
    if total_contabilizado != len(produtos_catalogo):
        diferenca = len(produtos_catalogo) - total_contabilizado
        print(f"\n⚠️  ALERTA DE AUDITORIA: o catálogo tinha {len(produtos_catalogo)} referências, mas "
              f"só {total_contabilizado} foram contabilizadas (diferença de {diferenca}). "
              f"Isso não deveria acontecer — avise o desenvolvedor.")
    else:
        print(f"\n✅ Auditoria: as {len(produtos_catalogo)} referências do catálogo foram todas "
              f"contabilizadas (disponíveis + esgotados + erros + sem imagem + status desconhecido).")

    if rastrear_novidades:
        n_lancamentos = sum(1 for item in resultado if item.get("lancamento"))
        if primeira_execucao:
            print("Detecção de lançamentos: primeira execução com essa opção ligada — "
                  "nenhum produto foi marcado como novidade dessa vez (a partir da "
                  "próxima execução, os realmente novos vão aparecer).")
        else:
            print(f"Lançamentos detectados nessa execução: {n_lancamentos}")

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
