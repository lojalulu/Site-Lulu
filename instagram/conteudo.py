"""
Sistema de geração de conteúdo para o Instagram da Lulu.
==========================================================
Gera legenda de feed + texto do Story combinando blocos de copy por
"pilar" de venda, sem precisar chamar nenhuma IA a cada postagem
(zero custo recorrente de token).
"""

import random

# ===== Pilares de venda (a "personalidade" da marca) =====================
# Cada pilar tem várias variações. O produto real (nome, preço, loja de
# origem) é encaixado dentro do texto na hora.

PILARES = {
    "qualidade": [],  # tratado à parte por loja — ver QUALIDADE_POR_LOJA (kits usa suplex vip/zero
                       # transparência, avulso usa malha premium — são tecidos e propostas diferentes)
    "renda_extra": [
        "Enquanto você dorme, seu Instagram pode estar vendendo por você. Ideal pra quem já revende ou quer começar uma renda extra hoje.",
        "Quem revende sabe: peça boa e barata é sinônimo de lucro certo no fim do mês.",
        "Se você revende moda fitness, essa é a peça que fecha carrinho rápido.",
    ],
    "cliente_ama": [
        "Sua cliente vai amar essa modelagem — e voltar pra pedir mais.",
        "Esse é daqueles produtos que a cliente manda foto usando, de tão satisfeita.",
        "Peça que vira queridinha na primeira leva — cliente ama e indica pra amiga.",
    ],
    "lucratividade": [
        "Preço de fábrica pra você vender com uma margem excelente.",
        "Compra em kit, economiza no preço unitário, revende com lucro tranquilo.",
        "Poucas peças no mercado entregam essa relação custo-benefício pra revenda.",
    ],
    "conforto": [
        "Malha que acompanha o corpo sem apertar — conforto o dia inteiro.",
        "Elástico que não marca, tecido que respira. Conforto de verdade, não só na etiqueta.",
        "Feita pra treinar, trabalhar ou só ficar em casa — conforto que não sacrifica o estilo.",
    ],
    "estilo": [
        "Modelagem atual, cores que estão em alta — moda fitness que também é moda de rua.",
        "Do treino pro dia a dia sem trocar de roupa — estilo que multiplica o uso da peça.",
        "Aquele visual que a cliente vê no feed e já quer pro guarda-roupa.",
    ],
    "disponibilidade": [
        "Últimas unidades desse lote — reposição não tem data certa.",
        "Chegou fresquinho no catálogo — poucas peças por enquanto.",
        "Enquanto durar o estoque desse lote, o preço continua esse.",
    ],
    "lancamento": [
        "Acabou de chegar no catálogo — poucas peças, ninguém mais tem ainda.",
        "Lançamento fresquinho, direto da fábrica pro seu feed.",
        "Você está entre os primeiros a ver essa peça — lançamento disponível agora.",
        "Novidade quentinha no catálogo, chegou hoje.",
    ],
}

# ===== Qualidade — texto MUITO diferente por loja, porque os produtos
# são diferentes de verdade: kits são suplex vip/zero transparência,
# vendidos em pacote fechado de 5; avulso é malha premium, vendida peça
# por peça, com proposta de qualidade superior/atacado. =================
QUALIDADE_POR_LOJA = {
    "kits": [
        "Suplex vip, zero transparência — testado antes de entrar no catálogo. Kit fechado com 5 peças que não decepciona.",
        "Tecido suplex vip, grosso e sem transparência nem agachando. Qualidade comprovada em cada kit de 5.",
        "Zero transparência de verdade — o padrão que só o suplex vip da Lulu entrega, no kit fechado com 5 peças.",
    ],
    "avulso": [
        "Malha premium, qualidade superior — você sente a diferença assim que veste.",
        "Peça avulsa com malha premium: acabamento de grife, preço de atacado.",
        "Qualidade superior peça por peça — malha selecionada uma a uma, sem precisar levar kit fechado.",
    ],
}

PESOS_PILARES = {
    "qualidade": 1.2,
    "renda_extra": 1.0,
    "cliente_ama": 1.0,
    "lucratividade": 1.0,
    "conforto": 1.0,
    "estilo": 1.0,
    "disponibilidade": 0.8,
    "lancamento": 0,  # nunca sorteado à toa — só é usado quando forçado (eh_lancamento=True)
}

# ===== Preço (aparece em ~40% dos posts) ===================================
LINHAS_PRECO = [
    "{nome_curto} sai por {preco}.",
    "{nome_curto}: {preco}. Simples assim.",
    "Hoje, {nome_curto} sai por {preco}.",
    "{preco} — e já pode revender no seu preço.",
]

# ===== Frete (aparece só em parte dos posts) ===============================
# Atenção: as regras de frete são DIFERENTES entre as duas lojas —
# nunca usar a mesma linha pras duas.
LINHAS_FRETE = {
    "kits": [
        "E tem mais: frete grátis pra Salvador e o Brasil inteiro em pedidos a partir de 6 kits 🚚",
        "Frete grátis pra Salvador e pra qualquer canto do Brasil, a partir de 6 kits no pedido 📦",
        "Ah, e o frete? Sai grátis pra Salvador e o Brasil inteiro fechando 6 kits ou mais 🚛",
    ],
    "avulso": [
        "Aproveite a opção de frete grátis (Vip) pra Salvador e o Brasil 🚚",
        "Tem opção de frete grátis (Vip), de 4 a 7 dias úteis 📦",
        "Dá pra aproveitar o frete grátis (Vip) nesse pedido, direto pra sua casa 🚛",
    ],
}

# ===== Chamada pra ação (quase sempre "link na bio", com variação) ========
CTA_BIO = [
    "Link na bio 🔗", "Catálogo completo — link na bio ✨",
    "Catálogo inteiro tá no link da bio 👆", "Dá uma espiada no link da bio 💗",
    "Link da bio te leva direto pro catálogo 📲",
]
CTA_ALTERNATIVA = [
    "Chama no direct pra garantir o seu 💬",
    "Manda mensagem que a gente te ajuda a montar o pedido 💬",
]

TAG_LOJA = {
    "kits": "kit fechado com 5 peças, suplex vip, zero transparência",
    "avulso": "peça avulsa, malha premium, qualidade superior",
}

EMOJIS_ABERTURA = ["✨", "🔥", "💗", "🛍️", "👗", "💫"]

# ===== Frases curtas pro Story (destaque + CTA, duas linhas na imagem) =====
# Pool comum: preço, disponibilidade, características genéricas — usado
# pelas duas lojas. Cada loja soma seu pool extra específico de tecido.
STORY_DESTAQUES_COMUM = [
    "{preco}",
    "Só {preco} 💸",
    "{nome_curto} por {preco}",
    "Conforto o dia inteiro",
    "Direto da fábrica pra você",
    "Poucas peças desse lote",
    "Chegou fresquinho no catálogo",
    "Cores variadas disponíveis",
    "Ótimo pra revenda 💰",
]

STORY_DESTAQUES_KITS_EXTRA = [
    "Suplex vip ✨",
    "Zero transparência ✨",
    "Kit fechado com 5 peças",
]

STORY_DESTAQUES_AVULSO_EXTRA = [
    "Malha premium ✨",
    "Qualidade superior",
    "Peça selecionada a dedo",
]

# Pool exclusivo pra produtos recém-chegados ao catálogo (lançamento).
STORY_DESTAQUES_LANCAMENTO = [
    "🚀 Lançamento disponível!",
    "Lançamento: {nome_curto}",
    "Lançamento por {preco}",
    "Chegou agora — lançamento!",
    "Primeira leva, poucas peças",
    "Novidade no catálogo hoje",
]


def gerar_texto_story(nome_curto: str, preco: str, loja: str, eh_lancamento: bool) -> str:
    """Monta o texto do Story em 2 linhas: um destaque curto (preço,
    característica do tecido certo pra essa loja, ou aviso de
    lançamento) + uma chamada pra bio, puxando do mesmo pool de CTAs
    usado no feed pra variar ainda mais."""
    if eh_lancamento:
        pool = STORY_DESTAQUES_LANCAMENTO
    else:
        extra = STORY_DESTAQUES_KITS_EXTRA if loja == "kits" else STORY_DESTAQUES_AVULSO_EXTRA
        pool = STORY_DESTAQUES_COMUM + extra
    destaque = random.choice(pool).format(nome_curto=nome_curto, preco=preco)
    cta = random.choice(CTA_BIO)
    return f"{destaque}\n{cta}"


def _nome_curto(nome: str, limite: int = 45) -> str:
    nome = nome.strip()
    return nome if len(nome) <= limite else nome[:limite].rsplit(" ", 1)[0] + "…"


def _sortear_pilar(historico_pilares, n_evitar=2):
    """Evita repetir os últimos N pilares usados, pra não enjoar."""
    recentes = set(historico_pilares[-n_evitar:]) if historico_pilares else set()
    candidatos = [p for p in PILARES if p not in recentes] or list(PILARES)
    pesos = [PESOS_PILARES[p] for p in candidatos]
    return random.choices(candidatos, weights=pesos, k=1)[0]


def gerar_post(produto: dict, loja: str, historico_pilares=None, eh_lancamento: bool = False):
    """
    produto: {"nome": ..., "preco_final": ...}
    loja: "kits" ou "avulso"
    historico_pilares: lista dos últimos pilares usados (pra variar)
    eh_lancamento: True se o produto acabou de aparecer no catálogo —
        força o pilar e o destaque do Story pro modo "lançamento"
    Retorna dict com "legenda_feed" e "texto_story".
    """
    historico_pilares = historico_pilares or []
    pilar = "lancamento" if eh_lancamento else _sortear_pilar(historico_pilares)
    corpo = random.choice(QUALIDADE_POR_LOJA[loja]) if pilar == "qualidade" else random.choice(PILARES[pilar])
    nome_curto = _nome_curto(produto["nome"])
    preco = f"R$ {produto['preco_final']:.2f}".replace(".", ",")

    linhas = [random.choice(EMOJIS_ABERTURA) + " " + corpo]

    # preço aparece em ~40% dos posts
    if random.random() < 0.4:
        linhas.append(random.choice(LINHAS_PRECO).format(nome_curto=nome_curto, preco=preco))

    # frete aparece em ~30% dos posts (linha certa pra cada loja)
    if random.random() < 0.3:
        linhas.append(random.choice(LINHAS_FRETE[loja]))

    linhas.append(f"({TAG_LOJA[loja]})")

    # CTA: 85% link na bio, 15% alternativa
    linhas.append(random.choice(CTA_BIO) if random.random() < 0.85 else random.choice(CTA_ALTERNATIVA))

    legenda_feed = "\n\n".join(linhas)
    texto_story = gerar_texto_story(nome_curto, preco, loja, eh_lancamento)

    return {"pilar": pilar, "legenda_feed": legenda_feed, "texto_story": texto_story}
