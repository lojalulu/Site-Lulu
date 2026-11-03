"""
Laboratório de Reels — gera o "briefing" criativo de cada Reel:
gancho, frases dos quadros, chamada final, legenda e hashtags.

Usa a API do DeepSeek (segredo DEEPSEEK_API_KEY) com a metodologia de
estrategista de Reels (demanda real, gancho por mecanismo, retenção,
conteúdo útil, nada de clickbait). Se a chave faltar, a API falhar ou a
resposta vier fora das regras, cai num banco de briefings prontos —
o Reel nunca deixa de sair por causa disso.
"""

import datetime
import json
import os
import random
import re

import requests

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODELO = "deepseek-chat"

# ÂNGULOS de venda (desde 03/11/2026): giram em rodízio, sem repetir os últimos 4.
# O Reel fala SÓ dos kits de luluextra.com. {PRECO} = preço real de um kit do vídeo,
# inserido pelo código no formato "5 Conjuntos por R$ 199,90" (a IA nunca escreve valores).
ANGULOS = {
    "salvador": ("Mora em Salvador", "Fala direto com quem mora em Salvador e revende ou quer revender: a Lulu nasceu em Salvador; a partir de 6 kits o frete Vip é grátis e chega em 4 dias úteis.",
                 ["Mora em *Salvador* e revende moda fitness?", "*Salvador*, chegou kit novo no catálogo"]),
    "nordeste": ("Revendedora do Nordeste", "Fala com revendedoras do Nordeste: fábrica própria nordestina (Recife) desde 2013, marca nascida em Salvador, frete grátis a partir de 6 kits.",
                 ["Revende no *Nordeste*? Olha isso", "Fábrica *nordestina* de moda fitness desde 2013"]),
    "frete": ("Frete que não pesa", "Contraste com o problema de frete caro em compra de atacado (sem citar nenhuma loja): aqui, a partir de 6 kits, o frete Vip é grátis pro Brasil todo.",
              ["Cansada de *frete caro* no atacado fitness?", "O frete *não precisa* comer seu lucro"]),
    "preco": ("Preço do kit", "Mostra o preço real de um kit, sempre no formato {PRECO}, e o que vem nele (5 peças, cores variadas). Direto e sem exagero.",
              ["{PRECO}. *Sim*, no atacado", "Quanto custa um *kit* da Lulu?"]),
    "pix": ("Desconto no Pix", "Pagamento facilitado: 10% de desconto nas peças pagando no Pix, ou cartão em até 3x sem juros.",
            ["*10% off* no Pix em todo kit", "Pagando no *Pix* o kit sai mais barato"]),
    "cores": ("Vitrine cheia", "Cada kit vem com cores variadas: a revendedora monta uma vitrine cheia e colorida com um pedido só.",
              ["Uma vitrine *colorida* com um pedido só", "5 peças, *cores variadas*, um kit só"]),
    "tecido": ("Tecido que segura", "Qualidade do tecido: suplex e poliamida, zero transparência no agachamento — o que a cliente final mais pergunta.",
               ["O teste do *agachamento* que sua cliente faz", "Suplex que *não fica transparente*"]),
    "comecar": ("Começar a revender", "Pra quem quer começar: pedido mínimo de 4 kits, kits prontos, catálogo atualizado toda semana em luluextra.com.",
                ["Começar a revender com *4 kits*", "Seu *primeiro pedido* de revenda, sem complicação"]),
    "plus": ("Plus size", "Kits com modelos plus size (o tamanho vem no nome do produto), um público que muita revendedora ainda não atende.",
             ["Sua cliente *plus size* também treina", "Tem *plus size* no catálogo, sim"]),
    "novidade": ("Catálogo novo", "O catálogo de luluextra.com é atualizado toda semana com modelos novos; convite pra ver as novidades.",
                 ["Modelos *novos* toda semana", "Olha o que *entrou* no catálogo"]),
}

MECANISMOS = ["curiosidade", "contraste", "problema específico", "pergunta direta",
              "chamada regional", "número concreto", "objeção respondida", "antes e depois"]

FATOS = """FATOS PERMITIDOS (use só estes; não invente nada além):
- Lulu Extra Fitness: moda fitness feminina no ATACADO em luluextra.com. Kits prontos de 5 peças (alguns pacotes de 10 blusas), em suplex e poliamida, cores variadas, zero transparência.
- Marca nascida em Salvador (BA), com fábrica própria no Nordeste (Recife) desde 2013. A maioria das clientes é de Salvador e do Nordeste, mas enviamos pra todo o Brasil.
- Pedido mínimo: 4 kits. A partir de 6 kits, frete Vip GRÁTIS pra Salvador e todo o Brasil (Vip: 4 dias úteis). Abaixo disso: Econômico R$ 39,90 (9 dias úteis) ou Vip R$ 90.
- Pix com 10% de desconto nas peças. Cartão em até 3x sem juros.
- Catálogo atualizado toda semana em luluextra.com (link da bio).
- Preço: só use o marcador {PRECO} (o sistema troca pelo preço real, ex.: "5 Conjuntos por R$ 199,90"). Nunca escreva valores."""

PROIBIDO = """PROIBIDO: promessa de ganho ou lucro garantido, escrever valores em reais (use {PRECO}), números ou estatísticas inventados,
"sem estoque", "de graça", dizer que envia "pro mundo"/exterior (só enviamos pro Brasil), urgência falsa ("últimas unidades"), citar ou criticar concorrentes pelo nome, clickbait que o vídeo não entrega,
pedir "curta/compartilhe/salve", emojis nos textos do vídeo, prometer data exata de entrega,
falar de peças avulsas ou da mini franquia (este Reel é SÓ dos kits de luluextra.com),
afirmar que dá pra montar kit peça por peça (os kits já vêm prontos), criticar qualquer forma de comprar,
dizer que a pessoa terá "marca própria", frases como "perder tempo" ou "está errado", jargões ("white label", "ecossistema", "funil")."""

COERENCIA = """REGRAS DE COERÊNCIA (obrigatórias):
1. O gancho fala com UMA pessoa (revendedora ou quem quer revender, de preferência de Salvador/Nordeste quando o ângulo pedir) e promete algo que os quadros entregam.
2. Sequência: gancho -> quadro 1 entrega -> quadro 2 complementa -> chamada leva a luluextra.com / link da bio.
3. Frases completas, simples, concretas, com cara de conversa baiana/nordestina sem forçar sotaque.
4. NUNCA comece o gancho com "Quer revender" nem repita o começo (2 primeiras palavras) dos ganchos recentes.
5. Teste: lido sem som, em 10 segundos dá pra entender a oferta e o que fazer?"""


def _sem_emoji(txt: str) -> str:
    return re.sub(r"[^\w\s\.,;:!\?\-–—'\"“”‘’%/\*\(\)\{\}·&@ÀÁÂÃÇÉÊÍÓÔÕÚàáâãçéêíóôõú]", "", txt).strip()


def _n_palavras(txt: str) -> int:
    return len(re.findall(r"\S+", txt))


RUIM = re.compile(r"perder tempo|marca pr[óo]pria|errad[oa]|white label|garanti|lucro de|ganhe r\$|r\$\s?\d|sem estoque|de gra[çc]a|últimas unidades|ultimas unidades|curta|compartilhe|salve este", re.I)


def _comeco(txt):
    return " ".join(re.findall(r"[a-zà-ú]+", txt.lower().replace("*", ""))[:2])


def _validar(b: dict) -> dict:
    gancho = _sem_emoji(str(b.get("gancho", "")))
    quadros = [_sem_emoji(str(q)) for q in (b.get("quadros") or []) if str(q).strip()][:2]
    cta = _sem_emoji(str(b.get("cta", "")))
    selo = _sem_emoji(str(b.get("selo", ""))).upper() or "LULUEXTRA.COM"
    legenda = str(b.get("legenda", "")).strip()
    hashtags = [h if h.startswith("#") else "#" + h for h in (b.get("hashtags") or []) if isinstance(h, str)]
    hashtags = [re.sub(r"[^#\wÀ-ú]", "", h) for h in hashtags][:9]
    if not (2 <= _n_palavras(gancho) <= 10):
        raise ValueError("gancho fora do tamanho")
    if not quadros or any(not (3 <= _n_palavras(q) <= 18) for q in quadros):
        raise ValueError("quadros fora do tamanho")
    if not (2 <= _n_palavras(cta) <= 12):
        raise ValueError("cta fora do tamanho")
    if len(legenda) < 40 or len(legenda) > 900:
        raise ValueError("legenda fora do tamanho")
    for t in [gancho, cta, legenda] + quadros:
        if RUIM.search(t):
            raise ValueError(f"texto proibido: {t[:40]}")
    if len(selo) > 34:
        selo = "LINK NA BIO"
    if re.match(r"\s*\*?quer\s+\*?revender", gancho, re.I):
        raise ValueError("gancho começa com 'Quer revender' (proibido: repetitivo)")
    for t in [gancho, cta, legenda] + quadros:
        if re.search(r"avuls|mini franquia|franquia", t, re.I):
            raise ValueError("Reel é só dos kits")
        if "{" in t.replace("{PRECO}", ""):
            raise ValueError("marcador inválido")
    return {"pilar": b.get("pilar", ""), "angulo": b.get("angulo", ""), "mecanismo": b.get("mecanismo", ""), "gancho": gancho,
            "quadros": quadros, "cta": cta, "selo": selo, "legenda": legenda,
            "hashtags": hashtags or ["#modafitness", "#revendedora", "#atacado", "#lulumodafitness"]}


def _chamar_deepseek(pilar, instrucao, mecanismo, recentes, exemplos=()):
    chave = os.environ.get("DEEPSEEK_API_KEY")
    if not chave:
        raise RuntimeError("DEEPSEEK_API_KEY ausente")
    sistema = (
        "Você é um estrategista sênior de Reels e diretor de marketing de uma marca de moda fitness brasileira. "
        "Escreve em português do Brasil, como gente fala, sem texto de robô. Cada Reel tem demanda real de público, "
        "um gancho forte nos 3 primeiros segundos que o vídeo realmente entrega, ritmo sem enrolação e valor logo cedo. "
        "O Reel é feito só de fotos de produtos com texto na tela, então as frases precisam funcionar lidas, em silêncio. "
        "O público principal são revendedoras de Salvador e do Nordeste. O objetivo é levar a pessoa a luluextra.com (link da bio).\n\n"
        + FATOS + "\n\n" + PROIBIDO + "\n\n" + COERENCIA
    )
    usuario = f"""Crie o briefing do Reel de hoje.
Ângulo de venda: {pilar}. Direção: {instrucao}
Mecanismo do gancho: {mecanismo}.
Exemplos de gancho deste ângulo (inspiração, NÃO copie): {json.dumps(list(exemplos), ensure_ascii=False)}
Pode usar o marcador {{PRECO}} em no máximo UMA frase (gancho ou quadro).
Ganchos já usados recentemente (NÃO repita nem parafraseie): {json.dumps(recentes[-15:], ensure_ascii=False)}

Responda SÓ com JSON neste formato:
{{
 "pilar": "{pilar}",
 "mecanismo": "{mecanismo}",
 "gancho": "abertura de 4 a 9 palavras; marque 1 ou 2 palavras-chave com *asteriscos*",
 "quadros": ["frase de valor de 6 a 14 palavras", "(opcional) segunda frase de 6 a 14 palavras"],
 "cta": "chamada final de 4 a 9 palavras, natural, mandando pra luluextra.com ou pro link da bio",
 "selo": "LINK NA BIO",
 "legenda": "legenda de 2 a 4 frases, tom próximo, terminando com convite pra acessar o link da bio",
 "hashtags": ["#...", "#...", "#...", "#...", "#...", "#...", "#..."]
}}"""
    r = requests.post(DEEPSEEK_URL, headers={"Authorization": f"Bearer {chave}"}, timeout=90, json={
        "model": MODELO, "temperature": 1.15, "max_tokens": 900,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]})
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def _revisar(b: dict) -> dict:
    """Segunda leitura (editor): confere coerência, clareza e fatos; devolve versão corrigida."""
    chave = os.environ.get("DEEPSEEK_API_KEY")
    sistema = ("Você é o editor-chefe de conteúdo de uma marca de moda fitness. Revise o briefing de um Reel. "
               "Verifique: (1) o gancho promete algo claro e os quadros entregam; (2) a sequência faz sentido; "
               "(3) nenhuma contradição nem exagero frente aos FATOS; (4) frases simples e completas. "
               "Se algo estiver confuso, vago ou contraditório, REESCREVA mantendo o mesmo pilar.\n\n"
               + FATOS + "\n\n" + PROIBIDO + "\n\n" + COERENCIA)
    usuario = ("Briefing atual:\n" + json.dumps(b, ensure_ascii=False) +
               "\n\nResponda SÓ com JSON: {\"aprovado\": true/false, \"motivo\": \"...\", "
               "\"briefing\": {mesmo formato do briefing, já corrigido se necessário}}")
    r = requests.post(DEEPSEEK_URL, headers={"Authorization": f"Bearer {chave}"}, timeout=90, json={
        "model": MODELO, "temperature": 0.4, "max_tokens": 900,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]})
    r.raise_for_status()
    res = json.loads(r.json()["choices"][0]["message"]["content"])
    print(f"  revisão: aprovado={res.get('aprovado')} | {str(res.get('motivo', ''))[:140]}")
    return _validar(res.get("briefing") or b)


# ------------------------------------------------------------ banco de reserva
RESERVA = {
    "salvador": [{"gancho": "Mora em *Salvador* e revende moda fitness?", "quadros": ["A Lulu nasceu aqui, e a partir de 6 kits o frete Vip é grátis.", "{PRECO}, com cores variadas em cada kit."], "cta": "Veja os kits em luluextra.com"}],
    "nordeste": [{"gancho": "Fábrica *nordestina* de moda fitness desde 2013", "quadros": ["Kits prontos de 5 peças em suplex e poliamida, direto da fábrica.", "A partir de 6 kits o frete Vip é grátis."], "cta": "Catálogo completo no link da bio"}],
    "frete": [{"gancho": "Cansada de *frete caro* no atacado?", "quadros": ["Aqui, a partir de 6 kits, o frete Vip é grátis pro Brasil todo.", "Chega em 4 dias úteis, pronto pra revender."], "cta": "Monte seu pedido em luluextra.com"}],
    "preco": [{"gancho": "{PRECO}. *Sim*, no atacado", "quadros": ["Kit pronto com 5 peças e cores variadas.", "Pedido mínimo de 4 kits e 10% de desconto no Pix."], "cta": "Veja todos os preços no link da bio"}],
    "pix": [{"gancho": "*10% off* pagando no Pix", "quadros": ["O desconto vale nas peças de todos os kits.", "Prefere cartão? Em até 3x sem juros."], "cta": "Escolha seus kits em luluextra.com"}],
    "cores": [{"gancho": "Uma vitrine *colorida* com um pedido só", "quadros": ["Cada kit vem com 5 peças em cores variadas.", "Sua cliente sempre acha a cor que procura."], "cta": "Veja os kits no link da bio"}],
    "tecido": [{"gancho": "Suplex que *não fica transparente*", "quadros": ["Pode agachar: zero transparência, do jeito que a cliente pede.", "Suplex e poliamida em kits prontos de 5 peças."], "cta": "Confira em luluextra.com"}],
    "comecar": [{"gancho": "Começar a revender com *4 kits*", "quadros": ["Os kits já vêm prontos, com 5 peças e cores variadas.", "Você escolhe no site e fecha o pedido pelo WhatsApp."], "cta": "Comece pelo link da bio"}],
    "plus": [{"gancho": "Sua cliente *plus size* também treina", "quadros": ["Tem kit plus size no catálogo, é só olhar o nome do produto.", "Mais clientes atendidas com o mesmo pedido."], "cta": "Veja os modelos em luluextra.com"}],
    "novidade": [{"gancho": "Modelos *novos* toda semana", "quadros": ["O catálogo de luluextra.com é atualizado toda semana.", "{PRECO}, pronto pra sua vitrine."], "cta": "Veja as novidades no link da bio"}],
}


def _reserva(angulo):
    b = dict(random.choice(RESERVA[angulo]))
    b["pilar"] = ANGULOS[angulo][0]
    b["angulo"] = angulo
    b.setdefault("selo", "LULUEXTRA.COM")
    b["mecanismo"] = "reserva"
    b["legenda"] = (b["quadros"][0] + " " + (b["quadros"][1] if len(b["quadros"]) > 1 else "") +
                    " Catálogo completo e preços atualizados em luluextra.com, no link da bio.")
    b["hashtags"] = ["#modafitness", "#atacadofitness", "#revendedora", "#modafitnesssalvador", "#lulumodafitness", "#roupafitness", "#nordeste"]
    return _validar(b)


def escolher_angulo(recentes_angulos):
    livres = [a for a in ANGULOS if a not in list(recentes_angulos)[-4:]]
    return random.choice(livres or list(ANGULOS))


def gerar_briefing(recentes, recentes_angulos=()):
    angulo = escolher_angulo(recentes_angulos)
    pilar, instrucao, exemplos = ANGULOS[angulo]
    mecanismo = random.choice(MECANISMOS)
    comecos = {_comeco(g) for g in recentes[-10:]}
    for tentativa in (1, 2):
        try:
            b = _chamar_deepseek(pilar, instrucao, mecanismo, recentes, exemplos)
            b["angulo"] = angulo
            b = _validar(b)
            try:
                b = _revisar(b)
                b["angulo"] = angulo
            except Exception as e:
                print(f"  revisão indisponível, seguindo sem ela: {str(e)[:100]}")
            if b["gancho"] in recentes or _comeco(b["gancho"]) in comecos:
                raise ValueError("gancho repetido (ou começa igual a um recente)")
            print(f"Laboratório (DeepSeek, {pilar} / {mecanismo}): {b['gancho']}")
            return b
        except Exception as e:
            print(f"  laboratório tentativa {tentativa} falhou: {str(e)[:120]}")
    b = _reserva(angulo)
    print(f"Laboratório (banco reserva, {pilar}): {b['gancho']}")
    return b
