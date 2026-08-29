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
    "qualidade": [
        "Malha com ZERO transparência — testada antes de entrar no catálogo. É o tipo de detalhe que sua cliente sente na primeira vestida.",
        "Tecido grosso, costura reforçada, zero transparência. A diferença que faz ela voltar pra comprar de novo.",
        "Não é só bonito na foto — é grosso, não marca e não fica transparente nem agachando. Qualidade que vende sozinha.",
    ],
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
}

PESOS_PILARES = {
    "qualidade": 1.2,
    "renda_extra": 1.0,
    "cliente_ama": 1.0,
    "lucratividade": 1.0,
    "conforto": 1.0,
    "estilo": 1.0,
    "disponibilidade": 0.8,
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
        "Frete grátis (Vip) em todo pedido — não importa a quantidade 🚚",
        "Aqui o frete já sai grátis sempre, sem pegadinha 📦",
        "Frete Vip grátis, de 4 a 7 dias úteis, direto pra sua casa 🚛",
    ],
}

# ===== Chamada pra ação (quase sempre "link na bio", com variação) ========
CTA_BIO = [
    "Link na bio 🔗", "Catálogo completo — link na bio ✨",
    "Todo o mix está no link da bio 👆", "Dá uma espiada no link da bio 💗",
    "Link da bio te leva direto pro catálogo 📲",
]
CTA_ALTERNATIVA = [
    "Chama no direct pra garantir o seu 💬",
    "Manda mensagem que a gente te ajuda a montar o pedido 💬",
]

TAG_LOJA = {
    "kits": "kit fechado, cores variadas",
    "avulso": "peça avulsa, sem comprar kit fechado",
}

EMOJIS_ABERTURA = ["✨", "🔥", "💗", "🛍️", "👗", "💫"]


def _nome_curto(nome: str, limite: int = 45) -> str:
    nome = nome.strip()
    return nome if len(nome) <= limite else nome[:limite].rsplit(" ", 1)[0] + "…"


def _sortear_pilar(historico_pilares, n_evitar=2):
    """Evita repetir os últimos N pilares usados, pra não enjoar."""
    recentes = set(historico_pilares[-n_evitar:]) if historico_pilares else set()
    candidatos = [p for p in PILARES if p not in recentes] or list(PILARES)
    pesos = [PESOS_PILARES[p] for p in candidatos]
    return random.choices(candidatos, weights=pesos, k=1)[0]


def gerar_post(produto: dict, loja: str, historico_pilares=None):
    """
    produto: {"nome": ..., "preco_final": ...}
    loja: "kits" ou "avulso"
    historico_pilares: lista dos últimos pilares usados (pra variar)
    Retorna dict com "legenda_feed" e "texto_story".
    """
    historico_pilares = historico_pilares or []
    pilar = _sortear_pilar(historico_pilares)
    corpo = random.choice(PILARES[pilar])
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
    texto_story = "Link na bio ✨"  # o texto desenhado na imagem do Story é sempre direto e curto

    return {"pilar": pilar, "legenda_feed": legenda_feed, "texto_story": texto_story}
