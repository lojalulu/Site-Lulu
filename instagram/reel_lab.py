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

# ÂNGULOS de CONTEÚDO (Reel do meio do dia): dicas e assuntos variados de moda fitness e da loja, SEM pedir "QUERO".
ANGULOS_CONTEUDO = {
    "dica_vitrine": ("Dica de vitrine", "Dica prática pra revendedora montar uma vitrine ou feed que vende mais moda fitness (organização por cor, foto com luz natural, conjunto montado). Só dica, sem vender.",
                     ["Foto de *conjunto fitness* que vende mais", "Como arrumar sua *vitrine* fitness"]),
    "dica_tecido": ("Cuidado com a peça", "Dica de cuidado com roupa fitness (lavar do avesso, evitar amaciante, secar à sombra) pra durar mais e a cliente voltar a comprar.",
                    ["Roupa fitness *durando mais* com 3 cuidados", "O erro na hora de *lavar* a legging"]),
    "tendencia": ("Tendência fitness", "Conversa leve sobre o que as clientes de moda fitness pedem hoje: conjuntos coordenados, cintura alta, cores do verão. Sem inventar dados nem estatísticas.",
                  ["O que a cliente fitness *mais pede* hoje", "Conjunto *coordenado* nunca sai de moda"]),
    "atendimento": ("Atender melhor", "Dica de atendimento no WhatsApp pra revendedora: responder rápido, mandar foto da peça no corpo, tirar dúvida de tamanho com medidas.",
                    ["Cliente sumiu? *Faça isso* no WhatsApp", "Dúvida de *tamanho* sem perder a venda"]),
    "bastidores": ("Bastidores da Lulu", "Bastidor leve da marca: nascida em Salvador, fábrica própria em Recife desde 2013, catálogo renovado toda semana. Conta a história sem vender.",
                   ["De *Salvador* pro Brasil: a história da Lulu", "Fábrica própria em *Recife* desde 2013"]),
    "mito": ("Dúvida comum", "Responde uma dúvida comum de quem quer revender moda fitness: precisa de muito dinheiro pra começar? Os kits já vêm prontos, pedido mínimo de 4 kits. Sem prometer lucro.",
             ["Dá pra *começar pequena* na revenda?", "O que *ninguém conta* sobre revender fitness"]),
    "treino": ("Moda e treino", "Assunto leve que conecta roupa e treino: a roupa certa dá confiança pra treinar, e a cliente fitness percebe tecido e caimento. Sem promessas de saúde ou resultado.",
               ["Roupa boa *muda o treino*", "Por que a cliente *volta* na mesma loja"]),
}

# ÂNGULOS de FRANQUIA (raro: no máximo 1 Reel em cada 8 a 10). A pessoa comenta FRANQUIA e recebe o link no Direct.
ANGULOS_FRANQUIA = {
    "fq_loja": ("Loja online pronta", "Apresenta a Franquia Online Lulu: uma loja virtual pronta, igual à luluextra.com, com o catálogo que se atualiza sozinho. Sem falar de preço.",
                ["Sua *loja online* pronta, igual à da Lulu", "Catálogo que se *atualiza sozinho*"]),
    "fq_margem": ("Você define a margem", "Na franquia online, quem decide quanto cobrar das clientes é a dona da loja; os pedidos chegam direto no WhatsApp dela. Sem prometer lucro nem valor.",
                  ["Quem *define o preço* é você", "Pedido da sua loja chega no *seu WhatsApp*"]),
    "fq_comeco": ("Começar sem CNPJ", "Para quem nunca teve loja: não precisa de CNPJ pra começar na franquia online e o curso de como vender vem incluso. Sem prometer resultado.",
                  ["Loja online *sem CNPJ*? Dá pra começar", "Curso *incluso* pra quem nunca vendeu online"]),
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

FATOS_FRANQUIA = """FATOS PERMITIDOS (use só estes; não invente nada além):
- Franquia Online Lulu: loja virtual pronta, com a mesma estrutura da luluextra.com, em nome da própria dona da loja.
- O catálogo de produtos se atualiza sozinho, a partir da fábrica da Lulu (Nordeste).
- A dona da loja decide quanto cobrar das clientes (a margem é dela).
- Os pedidos chegam direto no WhatsApp da dona da loja.
- Curso de como vender online incluso. Não precisa de CNPJ pra começar.
- Brasil apenas. Quem quer saber mais comenta FRANQUIA e recebe o link no Direct.
- Valores, vagas, promoções e prazos: NÃO mencione nenhum."""

FATOS_CONTEUDO = """FATOS PERMITIDOS (use só estes; não invente nada além; este Reel é conteúdo, não venda direta):
- Lulu Extra Fitness: moda fitness feminina no atacado (luluextra.com), kits prontos de 5 peças, suplex e poliamida, zero transparência.
- Marca nascida em Salvador (BA), fábrica própria no Nordeste (Recife) desde 2013. Envio pra todo o Brasil.
- Pedido mínimo 4 kits; a partir de 6 kits o frete Vip é grátis. Pix com 10% de desconto nas peças.
- Dicas gerais de venda, vitrine, atendimento e cuidado com roupa fitness são bem-vindas, desde que sem dados inventados.
- NÃO escreva valores nem use o marcador {PRECO}. NÃO peça comentário nem "QUERO"; a chamada final é leve (seguir o perfil / conhecer o catálogo no link da bio)."""


def _fatos(modo):
    return {"franquia": FATOS_FRANQUIA, "conteudo": FATOS_CONTEUDO}.get(modo, FATOS)


def _proibido(modo):
    if modo == "franquia":
        return PROIBIDO.replace("falar de peças avulsas ou da mini franquia (este Reel é SÓ dos kits de luluextra.com)",
                                "falar de peças avulsas, de preço, vagas, promoção ou prazo da franquia").replace(
            "dizer que a pessoa terá \"marca própria\"", "dizer que a pessoa terá \"marca própria\" (a loja é dela, mas os produtos são da Lulu)")
    if modo == "conteudo":
        return PROIBIDO.replace("falar de peças avulsas ou da mini franquia (este Reel é SÓ dos kits de luluextra.com)",
                                "falar de peças avulsas ou de franquia")
    return PROIBIDO


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


def _validar(b: dict, modo: str = "venda") -> dict:
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
        if re.search(r"avuls|mini franquia", t, re.I) or (modo != "franquia" and re.search(r"franquia", t, re.I)):
            raise ValueError("assunto fora do modo do Reel")
        if "{PRECO}" in t and re.search(r"\b\d+\s*(pe[çc]as|kits?|conjuntos|regatas|blusas)", t, re.I):
            raise ValueError("número de peças junto do {PRECO} (o preço já diz a quantidade)")
        if modo == "conteudo" and re.search(r"\bquero\b|\{PRECO\}", t, re.I):
            raise ValueError("Reel de conteúdo não pede QUERO nem usa preço")
        if "{" in t.replace("{PRECO}", ""):
            raise ValueError("marcador inválido")
    return {"pilar": b.get("pilar", ""), "angulo": b.get("angulo", ""), "mecanismo": b.get("mecanismo", ""), "gancho": gancho,
            "quadros": quadros, "cta": cta, "selo": selo, "legenda": legenda,
            "hashtags": hashtags or ["#modafitness", "#revendedora", "#atacado", "#lulumodafitness"]}


def _chamar_deepseek(pilar, instrucao, mecanismo, recentes, exemplos=(), modo="venda"):
    chave = os.environ.get("DEEPSEEK_API_KEY")
    if not chave:
        raise RuntimeError("DEEPSEEK_API_KEY ausente")
    sistema = (
        "Você é um estrategista sênior de Reels e diretor de marketing de uma marca de moda fitness brasileira. "
        "Escreve em português do Brasil, como gente fala, sem texto de robô. Cada Reel tem demanda real de público, "
        "um gancho forte nos 3 primeiros segundos que o vídeo realmente entrega, ritmo sem enrolação e valor logo cedo. "
        "O Reel é feito só de fotos de produtos com texto na tela, então as frases precisam funcionar lidas, em silêncio. "
        "O público principal são revendedoras de Salvador e do Nordeste. O objetivo é levar a pessoa a luluextra.com (link da bio).\n\n"
        + _fatos(modo) + "\n\n" + _proibido(modo) + "\n\n" + COERENCIA
    )
    usuario = f"""Crie o briefing do Reel de hoje.
Tipo de Reel: {modo.upper()} (VENDA = vende kits; CONTEUDO = dica/assunto sem vender; FRANQUIA = apresenta a franquia online). Ângulo: {pilar}. Direção: {instrucao}
Mecanismo do gancho: {mecanismo}.
{ {"conteudo": "Chamada final leve: convida a seguir o perfil ou conhecer o catálogo no link da bio. NÃO peça comentário.", "franquia": "Chamada final: diz que quem quiser saber mais é só comentar a palavra FRANQUIA aqui embaixo."}.get(modo, "") }
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


def _revisar(b: dict, modo: str = "venda") -> dict:
    """Segunda leitura (editor): confere coerência, clareza e fatos; devolve versão corrigida."""
    chave = os.environ.get("DEEPSEEK_API_KEY")
    sistema = ("Você é o editor-chefe de conteúdo de uma marca de moda fitness. Revise o briefing de um Reel. "
               "Verifique: (1) o gancho promete algo claro e os quadros entregam; (2) a sequência faz sentido; "
               "(3) nenhuma contradição nem exagero frente aos FATOS; (4) frases simples e completas. "
               "Se algo estiver confuso, vago ou contraditório, REESCREVA mantendo o mesmo pilar.\n\n"
               + _fatos(modo) + "\n\n" + _proibido(modo) + "\n\n" + COERENCIA)
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
    return _validar(res.get("briefing") or b, modo)


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

RESERVA_CONTEUDO = {
    "dica_vitrine": [{"gancho": "Foto de *conjunto fitness* que vende mais", "quadros": ["Mostre o conjunto montado, com luz natural e fundo limpo.", "Cliente enxerga o look completo e decide mais rápido."], "cta": "Segue a Lulu pra mais dicas", "selo": "DICA LULU"}],
    "dica_tecido": [{"gancho": "O erro na hora de *lavar* a legging", "quadros": ["Lave do avesso, sem amaciante e seque à sombra.", "O tecido segura a forma e a cor por muito mais tempo."], "cta": "Segue a Lulu pra mais dicas", "selo": "DICA LULU"}],
    "atendimento": [{"gancho": "Dúvida de *tamanho* sem perder a venda", "quadros": ["Peça a medida da cliente e compare com a tabela da peça.", "Mande uma foto da peça no corpo pra ela se imaginar usando."], "cta": "Segue a Lulu pra mais dicas", "selo": "DICA LULU"}],
    "bastidores": [{"gancho": "Fábrica própria em *Recife* desde 2013", "quadros": ["A Lulu nasceu em Salvador e cresceu com fábrica no Nordeste.", "O catálogo é renovado toda semana com modelos novos."], "cta": "Conheça o catálogo no link da bio", "selo": "BASTIDORES"}],
    "mito": [{"gancho": "Dá pra *começar pequena* na revenda?", "quadros": ["Os kits já vêm prontos, com 5 peças cada.", "O pedido mínimo é de 4 kits, sem montar nada peça por peça."], "cta": "Conheça o catálogo no link da bio", "selo": "REVENDA"}],
    "tendencia": [{"gancho": "Conjunto *coordenado* nunca sai de moda", "quadros": ["Top e legging combinando é o que a cliente fitness mais procura.", "Vale ter variedade de cores na vitrine."], "cta": "Segue a Lulu pra mais dicas", "selo": "TENDÊNCIA"}],
    "treino": [{"gancho": "Roupa boa *muda o treino*", "quadros": ["Tecido que não transparenta dá confiança pra agachar sem medo.", "A cliente percebe o caimento e volta na mesma loja."], "cta": "Segue a Lulu pra mais dicas", "selo": "MODA FITNESS"}],
}
RESERVA_FRANQUIA = {
    "fq_loja": [{"gancho": "Sua *loja online* pronta, igual à da Lulu", "quadros": ["Catálogo que se atualiza sozinho, sem você digitar produto.", "Os pedidos chegam direto no seu WhatsApp."], "cta": "Comenta FRANQUIA aqui embaixo", "selo": "FRANQUIA ONLINE"}],
    "fq_margem": [{"gancho": "Quem *define o preço* é você", "quadros": ["Na sua loja, você escolhe quanto cobrar das clientes.", "Os pedidos chegam direto no seu WhatsApp."], "cta": "Comenta FRANQUIA aqui embaixo", "selo": "FRANQUIA ONLINE"}],
    "fq_comeco": [{"gancho": "Loja online *sem CNPJ*? Dá pra começar", "quadros": ["Você não precisa de CNPJ pra começar na franquia online.", "O curso de como vender online vem incluso."], "cta": "Comenta FRANQUIA aqui embaixo", "selo": "FRANQUIA ONLINE"}],
}


def _reserva(angulo, modo="venda"):
    banco = {"conteudo": RESERVA_CONTEUDO, "franquia": RESERVA_FRANQUIA}.get(modo, RESERVA)
    b = dict(random.choice(banco[angulo]))
    b["pilar"] = _angulos(modo)[angulo][0]
    b["angulo"] = angulo
    b.setdefault("selo", "LULUEXTRA.COM")
    b["mecanismo"] = "reserva"
    corpo = b["quadros"][0] + " " + (b["quadros"][1] if len(b["quadros"]) > 1 else "")
    if modo == "conteudo":
        b["legenda"] = corpo + " Segue a Lulu pra mais dicas de moda fitness e revenda. O catálogo está no link da bio."
    elif modo == "franquia":
        b["legenda"] = corpo + " Quer saber mais sobre a Franquia Online Lulu? Comenta FRANQUIA aqui embaixo."
    else:
        b["legenda"] = corpo + " Catálogo completo e preços atualizados em luluextra.com, no link da bio."
    b["hashtags"] = ["#modafitness", "#atacadofitness", "#revendedora", "#modafitnesssalvador", "#lulumodafitness", "#roupafitness", "#nordeste"]
    return _validar(b, modo)


def _angulos(modo="venda"):
    return {"conteudo": ANGULOS_CONTEUDO, "franquia": ANGULOS_FRANQUIA}.get(modo, ANGULOS)


def escolher_angulo(recentes_angulos, modo="venda"):
    todos = _angulos(modo)
    livres = [a for a in todos if a not in list(recentes_angulos)[-3:]]
    return random.choice(livres or list(todos))


def gerar_briefing(recentes, recentes_angulos=(), modo="venda"):
    angulo = escolher_angulo(recentes_angulos, modo)
    pilar, instrucao, exemplos = _angulos(modo)[angulo]
    mecanismo = random.choice(MECANISMOS)
    comecos = {_comeco(g) for g in recentes[-10:]}
    for tentativa in (1, 2):
        try:
            b = _chamar_deepseek(pilar, instrucao, mecanismo, recentes, exemplos, modo)
            b["angulo"] = angulo
            b = _validar(b, modo)
            try:
                b = _revisar(b, modo)
                b["angulo"] = angulo
            except Exception as e:
                print(f"  revisão indisponível, seguindo sem ela: {str(e)[:100]}")
            if b["gancho"] in recentes or _comeco(b["gancho"]) in comecos:
                raise ValueError("gancho repetido (ou começa igual a um recente)")
            print(f"Laboratório (DeepSeek, {modo}, {pilar} / {mecanismo}): {b['gancho']}")
            return b
        except Exception as e:
            print(f"  laboratório tentativa {tentativa} falhou: {str(e)[:120]}")
    b = _reserva(angulo, modo)
    print(f"Laboratório (banco reserva, {modo}, {pilar}): {b['gancho']}")
    return b
