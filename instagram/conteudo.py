"""
Sistema de geração de conteúdo para o Instagram da Lulu.
==========================================================
Gera legenda de feed + texto do Story combinando blocos de copy por
"pilar" de venda, sem precisar chamar nenhuma IA a cada postagem
(zero custo recorrente de token).
"""

import random
import re

# ===== Pilares de venda (a "personalidade" da marca) =====================
# Cada pilar tem várias variações. O produto real (nome, preço, loja de
# origem) é encaixado dentro do texto na hora.

PILARES = {
    "qualidade": [],  # tratado à parte por loja — ver QUALIDADE_POR_LOJA (kits usa suplex vip/zero
                       # transparência, avulso usa malha premium — são tecidos e propostas diferentes)
    "renda_extra": [
        "Quem revende sabe: peça boa e barata é lucro certo no fim do mês.",
        "Se você revende moda fitness, essa é a peça que sai rápido.",
        "Dá pra começar pequeno e ir crescendo — peça que gira bem ajuda muito.",
        "Muita revendedora começou com um kit só e hoje compra todo mês.",
        "Renda extra de verdade começa com produto que a cliente quer comprar.",
        "Pra quem vende no WhatsApp ou no Instagram, essa peça ajuda a fechar pedido.",
        "Peça que você posta no status e já aparece gente perguntando o preço.",
        "Quer começar a revender? Esse é o tipo de peça que facilita.",
        "Revender moda fitness é bom porque a cliente sempre volta pra comprar mais.",
        "Se o objetivo é aumentar a renda, começa pelo que vende fácil.",
        "Essa entra no pedido e sai do seu estoque rapidinho.",
        "Boa pra quem vende pra academia, vizinhança ou grupo de amigas.",
    ],
    "cliente_ama": [
        "Sua cliente vai amar essa modelagem — e voltar pra pedir mais.",
        "Esse é daqueles produtos que a cliente manda foto usando, de tão satisfeita.",
        "Peça que vira queridinha na primeira leva — cliente ama e indica pra amiga.",
        "Veste bem em corpos diferentes, por isso quase não tem troca.",
        "A cliente experimenta e já pergunta se tem em outra cor.",
        "É o tipo de peça que a cliente compra uma e depois volta pra levar mais duas.",
        "Quem comprou elogiou o caimento — e caimento bom é venda garantida.",
        "Peça que valoriza o corpo sem apertar. Cliente satisfeita volta.",
        "Esse modelo costuma ter muita recompra.",
        "As revendedoras contam que esse modelo quase não volta pra troca.",
        "Cliente gosta de peça que dá pra usar muito — essa é assim.",
        "Aposta segura: modelo que agrada quase todo mundo.",
    ],
    "lucratividade": [
        "Preço de fábrica pra você vender com uma margem boa de verdade.",
        "Compra no kit, sai mais em conta por peça, revende com lucro tranquilo.",
        "É difícil achar peça com esse preço e essa qualidade pra revender.",
        "Faz a conta: o valor por peça no kit deixa espaço pra um bom lucro.",
        "Comprando direto da fábrica, sobra mais no seu bolso em cada venda.",
        "Preço de atacado de verdade, sem intermediário no meio.",
        "Você define seu preço de venda — a margem fica com você.",
        "Custo baixo por peça é o que faz a revenda valer a pena.",
        "Peça que você revende pelo dobro e a cliente ainda acha justo.",
        "Quanto menor o custo, mais fácil fica competir e ainda lucrar.",
        "Atacado com preço pensado pra quem revende.",
        "Lucro bom começa na hora da compra — e esse preço ajuda.",
    ],
    "conforto": [
        "Malha que acompanha o corpo sem apertar — conforto o dia inteiro.",
        "Elástico que não marca, tecido que respira. Conforto de verdade.",
        "Feita pra treinar, trabalhar ou só ficar em casa — confortável do mesmo jeito.",
        "Cós que não enrola e não aperta a barriga.",
        "Dá pra agachar, correr e alongar sem ficar ajeitando a roupa.",
        "Tecido macio, que não pinica nem esquenta demais.",
        "Veste bem do treino da manhã até o fim do dia.",
        "Conforto é o que faz a cliente usar toda semana — e indicar.",
        "Peça leve, que não pesa nem nos dias mais quentes.",
        "Firme sem ser apertada. É isso que a cliente procura.",
        "Costura bem feita, que não incomoda na pele.",
        "Modelagem que dá liberdade pra se mexer.",
    ],
    "estilo": [
        "Modelagem atual, cores que estão em alta — moda fitness que também é moda de rua.",
        "Sai da academia e já segue o dia sem trocar de roupa.",
        "Aquele visual que a cliente vê no feed e já quer pro guarda-roupa.",
        "Combina com tênis, sandália ou papete — serve pra tudo.",
        "Bonita no treino e bonita na rua também.",
        "Cores que chamam atenção na vitrine e no seu status.",
        "Peça que fica linda na foto — ajuda muito na hora de divulgar.",
        "Moda fitness que dá pra usar no mercado, no passeio e na academia.",
        "Detalhes que fazem diferença e deixam o conjunto mais bonito.",
        "Visual arrumado sem esforço nenhum.",
        "Modelo que não sai de moda de uma estação pra outra.",
        "Tem cara de peça cara, mas com preço de atacado.",
    ],
    "disponibilidade": [
        "Últimas unidades desse lote — reposição não tem data certa.",
        "Poucas peças disponíveis por enquanto.",
        "Enquanto durar o estoque desse lote, o preço continua esse.",
        "Esse modelo costuma acabar rápido — melhor não deixar pra depois.",
        "Estoque limitado nessa leva.",
        "Quando acaba, a próxima leva pode demorar.",
        "Ainda tem, mas não sabemos até quando.",
        "Garante o seu antes que o lote acabe.",
        "Esse aqui já está saindo bastante essa semana.",
        "Quem viu primeiro já garantiu. Ainda dá tempo.",
    ],
    "lancamento": [
        "Acabou de chegar no catálogo — poucas peças por enquanto.",
        "Lançamento novinho, direto da fábrica.",
        "Você está entre as primeiras a ver essa peça.",
        "Novidade no catálogo, chegou agora.",
        "Modelo novo na área — sua cliente ainda não viu em lugar nenhum.",
        "Chegou lançamento! Primeira leva disponível.",
        "Peça nova no catálogo, quentinha da produção.",
        "Lançamento da semana — sai na frente e oferece antes de todo mundo.",
        "Modelo inédito no catálogo. Vale a pena conferir.",
        "Novidade que acabou de entrar — primeira remessa.",
    ],
}

# ===== Qualidade — texto MUITO diferente por loja, porque os produtos
# são diferentes de verdade: kits são suplex vip/zero transparência,
# vendidos em pacote fechado de 5; avulso é malha premium, vendida peça
# por peça, com proposta de qualidade superior/atacado. =================
QUALIDADE_POR_LOJA = {
    "kits": [
        "Suplex vip, zero transparência — testado antes de entrar no catálogo.",
        "Tecido suplex vip, grosso e sem transparência nem agachando.",
        "Zero transparência de verdade — o padrão do suplex vip da Lulu.",
        "Suplex encorpado, que não fica transparente no agachamento.",
        "Tecido firme, que não perde a forma depois de lavar.",
        "Qualidade de confecção própria, em kit fechado.",
        "Suplex vip que segura bem e não deixa marquinha.",
        "Não desbota fácil e não faz bolinha — qualidade que dura.",
        "Todas as peças do kit no mesmo padrão de qualidade.",
        "Pode fazer o teste do agachamento: zero transparência.",
    ],
    "avulso": [
        "Malha premium, qualidade superior — você sente a diferença assim que veste.",
        "Peça avulsa com malha premium: acabamento caprichado, preço de atacado.",
        "Qualidade superior peça por peça, sem precisar levar kit fechado.",
        "Malha premium com toque macio e caimento bonito.",
        "Acabamento caprichado, costura reforçada, peça que dura.",
        "Você escolhe a peça certa pra sua cliente — sem sortimento fechado.",
        "Malha de qualidade superior, que não perde a forma.",
        "Peça selecionada uma a uma, com padrão premium.",
        "Toque macio, tecido encorpado, acabamento de loja boa.",
        "Qualidade que a cliente percebe logo no primeiro uso.",
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
    "{nome_curto}: {preco}.",
    "Hoje, {nome_curto} sai por {preco}.",
    "{preco} — e você revende no seu preço.",
    "Valor: {preco}.",
    "Tudo isso por {preco}.",
    "Preço de atacado: {preco}.",
]

# Só pra loja de KITS, quando o título tem quantidade reconhecível (ex:
# "Pacote com 5 Conjuntos..." -> "5 Conjuntos"). Toda vez que o preço
# aparecer numa postagem de kits com quantidade disponível, usa essas
# linhas em vez das de cima — assim quem vê já entende quantas peças
# vêm por aquele preço (ex: "5 Conjuntos - só R$ 259,90").
LINHAS_PRECO_KITS_COM_QTD = [
    "{quantidade} - só {preco}.",
    "{quantidade}: {preco}.",
    "Hoje, {quantidade} saem por {preco}.",
    "{quantidade} por {preco} — já pode revender no seu preço.",
    "São {quantidade} por {preco}. Faz a conta de quanto sai cada peça.",
    "Kit com {quantidade} por {preco}.",
    "{preco} no kit com {quantidade}.",
]

# ===== Frete (aparece só em parte dos posts) ===============================
# Atenção: as regras de frete são DIFERENTES entre as duas lojas —
# nunca usar a mesma linha pras duas.
LINHAS_FRETE = {
    "kits": [
        "E tem mais: frete grátis pra Salvador e o Brasil inteiro em pedidos a partir de 6 kits 🚚",
        "Frete grátis pra Salvador e qualquer canto do Brasil, a partir de 6 kits no pedido 📦",
        "E o frete? Sai grátis pra Salvador e o Brasil inteiro fechando 6 kits ou mais 🚛",
        "Fechando 6 kits, o frete sai grátis pra todo o Brasil 🚚",
        "A partir de 6 kits você não paga frete, pra Salvador e pro Brasil todo 📦",
    ],
    "avulso": [
        "Aproveite a opção de frete grátis (Vip) pra Salvador e o Brasil 🚚",
        "Tem opção de frete grátis (Vip), de 4 a 7 dias úteis 📦",
        "Dá pra aproveitar o frete grátis (Vip) nesse pedido 🚛",
        "Frete grátis (Vip) pra Salvador e todo o Brasil 🚚",
        "Pedido de peça avulsa com frete grátis (Vip) 📦",
    ],
}

# ===== Chamada pra ação (quase sempre "link na bio", com variação) ========
# Usada na legenda do FEED. Aqui o dedo apontando (👆) faz sentido — é uma
# referência visual comum a "olha lá em cima, no perfil".
CTA_BIO = [
    "Link na bio 🔗", "Catálogo completo — link na bio ✨",
    "Catálogo inteiro tá no link da bio 👆", "Dá uma espiada no link da bio 💗",
    "Link da bio te leva direto pro catálogo 📲",
    "Os outros modelos estão no link da bio 👆",
    "Pedido pelo site, link na bio 🛍️",
    "Vê as cores e monta seu pedido pelo link da bio 🔗",
]

# Usada só no STORY. Sem dedo apontando (☝️/👆) — no Story não tem nada
# na tela pra esse gesto apontar, então fica sem sentido/confuso.
CTA_STORY = [
    "Link na bio 🔗", "Catálogo completo — link na bio ✨",
    "Catálogo inteiro tá no link da bio 🛍️", "Dá uma espiada no link da bio 💗",
    "Link da bio te leva direto pro catálogo 📲",
]

CTA_ALTERNATIVA = [
    "Chama no direct pra garantir o seu 💬",
    "Manda mensagem que a gente te ajuda a montar o pedido 💬",
    "Ficou com dúvida? Chama no direct 💬",
    "Me chama no direct que te passo os detalhes 💬",
]

# ===== Hashtags do feed (Stories não suportam legenda/hashtag via API,
# então isso só entra na legenda do feed). Sorteia 3-4 por post, pra não
# repetir sempre o mesmo conjunto. =========================================
HASHTAGS = ["#modafitness", "#salvador", "#modafitnesssalvador", "#modafitnessevangelica", "#rendaextra"]


def sortear_hashtags() -> str:
    qtd = random.randint(3, len(HASHTAGS))
    return " ".join(random.sample(HASHTAGS, qtd))

TAG_LOJA = {
    "kits": [
        "É kit fechado com 5 peças, em suplex vip.",
        "Vem em kit fechado de 5, tecido suplex vip.",
        "Kit fechado, 5 peças, suplex vip.",
        "Vendido em kit fechado, cores sortidas.",
        "Kit com cores variadas.",
        "Kit fechado — ótimo pra começar a revender.",
    ],
    "avulso": [
        "É peça avulsa, na malha premium.",
        "Vendida avulsa, sem precisar levar kit fechado.",
        "Peça avulsa, malha premium.",
        "Você escolhe peça por peça (mínimo de 10 no pedido).",
        "Atacado de peça avulsa, a partir de 10 peças.",
        "Peça avulsa premium — você monta o pedido do seu jeito.",
    ],
}

EMOJIS_ABERTURA = ["✨", "🔥", "💗", "🛍️", "👗", "💫", "🏋️‍♀️", "💪", "🌸", "⭐"]

# ===== Frases curtas pro Story (destaque + CTA, duas linhas na imagem) =====
# Pool comum: preço, disponibilidade, características genéricas — usado
# pelas duas lojas. Cada loja soma seu pool extra específico de tecido.
# Separado em "com preço" / "sem preço" porque a loja de kits usa sorteio
# em duas etapas (ver PROB_PRECO_STORY_KITS) pra controlar a frequência
# do preço aparecer — a avulso continua com sorteio uniforme simples.
STORY_DESTAQUES_COMUM_COM_PRECO = [
    "{preco}",
    "Só {preco} 💸",
    "{nome_curto} por {preco}",
]

# Só pra loja de KITS, quando o título tem quantidade reconhecível.
# Usado no lugar do pool acima sempre que o Story de kits sorteia
# "mostrar preço" e a quantidade foi identificada no título (ex:
# "5 Conjuntos - só R$ 259,90 💸"). Se não achar quantidade no título,
# cai de volta no pool comum acima.
STORY_DESTAQUES_COMUM_COM_PRECO_KITS_QTD = [
    "{quantidade} - só {preco} 💸",
    "{quantidade} por {preco}",
    "{quantidade}: {preco}",
]
STORY_DESTAQUES_COMUM_SEM_PRECO = [
    "Conforto o dia inteiro",
    "Direto da fábrica pra você",
    "Poucas peças desse lote",
    "Chegou fresquinho no catálogo",
    "Cores variadas disponíveis",
    "Ótimo pra revenda 💰",
]
STORY_DESTAQUES_COMUM = STORY_DESTAQUES_COMUM_COM_PRECO + STORY_DESTAQUES_COMUM_SEM_PRECO

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

# Mesma lista, só que a linha de preço vem com a quantidade junto.
# Usada só pra loja de KITS quando dá pra reconhecer a quantidade no
# título — a regra de "preço sempre com quantidade" vale mesmo em
# lançamento.
STORY_DESTAQUES_LANCAMENTO_KITS_QTD = [
    "🚀 Lançamento disponível!",
    "Lançamento: {nome_curto}",
    "Lançamento: {quantidade} por {preco}",
    "Chegou agora — lançamento!",
    "Primeira leva, poucas peças",
    "Novidade no catálogo hoje",
]

# Chance do Story da loja de KITS (luluextra.com) mostrar preço.
# Antes, com sorteio uniforme entre as 12 frases do pool, a chance "saía"
# em ~25% (3 frases com preço em 12). A pedido do Lucas, agora o sorteio
# é em duas etapas só pra essa loja: primeiro decide se mostra preço
# (com essa probabilidade), depois sorteia a frase dentro do grupo certo.
# A loja avulso continua igual (sorteio uniforme simples, ~25%).
PROB_PRECO_STORY_KITS = 0.5


# ===== Anti-repetição de frases =========================================
# Guarda, por "categoria" (pilar, preço, frete, CTA...), as últimas frases
# usadas — e nunca repete uma delas até que a maior parte do pool já
# tenha sido usada. O histórico vem de historico_postagens.json
# ("ultimas_frases"), então vale entre execuções diferentes do robô.
_frases_recentes = {}


def _escolher(categoria: str, pool: list) -> str:
    recentes = _frases_recentes.setdefault(categoria, [])
    memoria = max(1, int(len(pool) * 0.7))
    candidatos = [f for f in pool if f not in recentes[-memoria:]] or pool
    escolhida = random.choice(candidatos)
    recentes.append(escolhida)
    del recentes[:-max(memoria, 1)]
    return escolhida


def extrair_quantidade(nome: str):
    """Extrai a parte de quantidade do título (ex: 'Pacote com 5
    Conjuntos de Calça...' -> '5 Conjuntos'), pra usar junto do preço
    nas postagens de kits. É a mesma lógica usada no site (index.html)
    pra deixar a quantidade em negrito no título — mantém as duas em
    sincronia. Retorna None quando o título não indica nenhuma
    quantidade (não tenta adivinhar — e nunca confunde "Ref 71" com
    quantidade)."""
    m = re.search(r"(\d+)(\s+)([A-Za-zÀ-ÿ]+)", nome)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"

    m2 = re.search(r"([A-Za-zÀ-ÿ.]+)?\s*(\d+)\s*$", nome)
    if m2:
        palavra_antes = (m2.group(1) or "").replace(".", "").lower()
        if palavra_antes == "ref":
            return None  # código de referência, não quantidade
        return m2.group(2)

    return None


def gerar_texto_story(nome_curto: str, preco: str, loja: str, eh_lancamento: bool, quantidade=None) -> str:
    """Monta o texto do Story em 2 linhas: um destaque curto (preço,
    característica do tecido certo pra essa loja, ou aviso de
    lançamento) + uma chamada pra bio, puxando do mesmo pool de CTAs
    usado no feed pra variar ainda mais."""
    if eh_lancamento:
        pool = STORY_DESTAQUES_LANCAMENTO_KITS_QTD if (loja == "kits" and quantidade) else STORY_DESTAQUES_LANCAMENTO
        destaque = random.choice(pool).format(nome_curto=nome_curto, preco=preco, quantidade=quantidade or "")
    elif loja == "kits":
        pool_sem_preco = STORY_DESTAQUES_COMUM_SEM_PRECO + STORY_DESTAQUES_KITS_EXTRA
        mostrar_preco = random.random() < PROB_PRECO_STORY_KITS
        if mostrar_preco and quantidade:
            pool_preco = STORY_DESTAQUES_COMUM_COM_PRECO_KITS_QTD
            destaque = random.choice(pool_preco).format(quantidade=quantidade, preco=preco)
        elif mostrar_preco:
            destaque = random.choice(STORY_DESTAQUES_COMUM_COM_PRECO).format(nome_curto=nome_curto, preco=preco)
        else:
            destaque = random.choice(pool_sem_preco).format(nome_curto=nome_curto, preco=preco)
    else:
        pool = STORY_DESTAQUES_COMUM + STORY_DESTAQUES_AVULSO_EXTRA
        destaque = random.choice(pool).format(nome_curto=nome_curto, preco=preco)
    cta = random.choice(CTA_STORY)
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


def gerar_post(produto: dict, loja: str, historico_pilares=None, eh_lancamento: bool = False, frases_recentes=None):
    """
    produto: {"nome": ..., "preco_final": ...}
    loja: "kits" ou "avulso"
    historico_pilares: lista dos últimos pilares usados (pra variar)
    eh_lancamento: True se o produto acabou de aparecer no catálogo —
        força o pilar e o destaque do Story pro modo "lançamento"
    Retorna dict com "legenda_feed" e "texto_story".
    """
    historico_pilares = historico_pilares or []
    global _frases_recentes
    _frases_recentes = frases_recentes if frases_recentes is not None else {}
    pilar = "lancamento" if eh_lancamento else _sortear_pilar(historico_pilares)
    if pilar == "qualidade":
        corpo = _escolher(f"qualidade_{loja}", QUALIDADE_POR_LOJA[loja])
    else:
        corpo = _escolher(pilar, PILARES[pilar])
    nome_curto = _nome_curto(produto["nome"])
    preco = f"R$ {produto['preco_final']:.2f}".replace(".", ",")
    quantidade = extrair_quantidade(produto["nome"]) if loja == "kits" else None

    linhas = [random.choice(EMOJIS_ABERTURA) + " " + corpo]

    # preço aparece em ~40% dos posts
    if random.random() < 0.4:
        if loja == "kits" and quantidade:
            linhas.append(_escolher("preco_kits", LINHAS_PRECO_KITS_COM_QTD).format(quantidade=quantidade, preco=preco))
        else:
            linhas.append(_escolher("preco", LINHAS_PRECO).format(nome_curto=nome_curto, preco=preco))

    # frete aparece em ~30% dos posts (linha certa pra cada loja)
    if random.random() < 0.3:
        linhas.append(_escolher(f"frete_{loja}", LINHAS_FRETE[loja]))

    linhas.append(_escolher(f"tag_{loja}", TAG_LOJA[loja]))

    # CTA: 85% link na bio, 15% alternativa
    linhas.append(_escolher("cta_bio", CTA_BIO) if random.random() < 0.85 else _escolher("cta_alt", CTA_ALTERNATIVA))

    linhas.append(sortear_hashtags())

    legenda_feed = "\n\n".join(linhas)
    texto_story = gerar_texto_story(nome_curto, preco, loja, eh_lancamento, quantidade)

    return {"pilar": pilar, "legenda_feed": legenda_feed, "texto_story": texto_story}
