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

# Pilar do dia (varia por dia da semana: 0 = segunda)
PILARES = {
    0: ("Dica de revenda", "Uma dica prática e útil pra quem revende moda fitness (como escolher mix, girar estoque, precificar, atender). Conteúdo que a pessoa queira salvar."),
    1: ("Kits em destaque", "Mostrar o valor dos kits prontos de 5 peças da Lulu pra quem revende: praticidade, variedade de cores e modelos, preço de atacado."),
    2: ("Mini franquia", "Apresentar a mini franquia Lulu: loja online própria de moda fitness, já pronta, com catálogo atualizado automaticamente. Convite pra conhecer pelo link da bio."),
    3: ("Erro comum da revendedora", "Um erro comum de quem revende roupa (comprar sem planejamento, não ter variedade, não divulgar...) e como evitar. Tom de ajuda, nunca de bronca."),
    4: ("Condições do atacado", "Condições reais do atacado Lulu: pedido mínimo de 4 kits, frete grátis a partir de 6 kits, 10% de desconto no Pix. Foco em facilitar a decisão."),
    5: ("Moda fitness em alta", "Moda fitness que vende: peças que as clientes procuram (conjuntos, macacões, leggings, modelos plus size), por que giram bem."),
    6: ("Bastidores da Lulu", "Bastidores e confiança: marca de moda fitness que atende revendedoras de todo o Brasil, com produção própria e anos de estrada. Tom humano e próximo."),
}

MECANISMOS = ["curiosidade", "contraste", "problema específico", "erro comum",
              "transformação", "opinião contundente", "tensão", "promessa útil"]

FATOS = """FATOS PERMITIDOS (use só estes; não invente nada além):
- Lulu Extra Fitness: moda fitness feminina no atacado, kits prontos de 5 peças (também há pacotes de 10 blusas), em suplex e poliamida, cores variadas.
- Pedido mínimo: 4 kits. Frete grátis a partir de 6 kits (Salvador e Brasil). Pix com 10% de desconto. Cartão em até 3x.
- Catálogo completo no link da bio (luluextra.com).
- Mini franquia: loja online própria de moda fitness, pronta, com catálogo atualizado automaticamente (informações no link da bio).
- Público: revendedoras e donas de loja de moda fitness, e mulheres que querem começar a revender."""

PROIBIDO = """PROIBIDO: promessa de ganho ou lucro garantido, valores em reais, números ou estatísticas inventados,
"sem estoque", "de graça", urgência falsa ("últimas unidades"), críticas a concorrentes, clickbait que o vídeo não entrega,
pedir "curta/compartilhe/salve", emojis nos textos do vídeo."""


def _sem_emoji(txt: str) -> str:
    return re.sub(r"[^\w\s\.,;:!\?\-–—'\"“”‘’%/\*\(\)·&@ÀÁÂÃÇÉÊÍÓÔÕÚàáâãçéêíóôõú]", "", txt).strip()


def _n_palavras(txt: str) -> int:
    return len(re.findall(r"\S+", txt))


RUIM = re.compile(r"garanti|lucro de|ganhe r\$|r\$\s?\d|sem estoque|de gra[çc]a|últimas unidades|ultimas unidades|curta|compartilhe|salve este", re.I)


def _validar(b: dict) -> dict:
    gancho = _sem_emoji(str(b.get("gancho", "")))
    quadros = [_sem_emoji(str(q)) for q in (b.get("quadros") or []) if str(q).strip()][:2]
    cta = _sem_emoji(str(b.get("cta", "")))
    selo = _sem_emoji(str(b.get("selo", ""))).upper() or "LINK NA BIO"
    legenda = str(b.get("legenda", "")).strip()
    hashtags = [h if h.startswith("#") else "#" + h for h in (b.get("hashtags") or []) if isinstance(h, str)]
    hashtags = [re.sub(r"[^#\wÀ-ú]", "", h) for h in hashtags][:9]
    if not (2 <= _n_palavras(gancho) <= 12):
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
    return {"pilar": b.get("pilar", ""), "mecanismo": b.get("mecanismo", ""), "gancho": gancho,
            "quadros": quadros, "cta": cta, "selo": selo, "legenda": legenda,
            "hashtags": hashtags or ["#modafitness", "#revendedora", "#atacado", "#lulumodafitness"]}


def _chamar_deepseek(pilar, instrucao, mecanismo, recentes):
    chave = os.environ.get("DEEPSEEK_API_KEY")
    if not chave:
        raise RuntimeError("DEEPSEEK_API_KEY ausente")
    sistema = (
        "Você é um estrategista sênior de Reels e diretor de marketing de uma marca de moda fitness brasileira. "
        "Escreve em português do Brasil, como gente fala, sem texto de robô. Cada Reel tem demanda real de público, "
        "um gancho forte nos 3 primeiros segundos que o vídeo realmente entrega, ritmo sem enrolação e valor logo cedo. "
        "O Reel é feito só de fotos de produtos com texto na tela, então as frases precisam funcionar lidas, em silêncio.\n\n"
        + FATOS + "\n\n" + PROIBIDO
    )
    usuario = f"""Crie o briefing do Reel de hoje.
Pilar: {pilar}. Direção: {instrucao}
Mecanismo do gancho: {mecanismo}.
Ganchos já usados recentemente (NÃO repita nem parafraseie): {json.dumps(recentes[-15:], ensure_ascii=False)}

Responda SÓ com JSON neste formato:
{{
 "pilar": "{pilar}",
 "mecanismo": "{mecanismo}",
 "gancho": "abertura de 4 a 9 palavras; marque 1 ou 2 palavras-chave com *asteriscos*",
 "quadros": ["frase de valor de 6 a 14 palavras", "(opcional) segunda frase de 6 a 14 palavras"],
 "cta": "chamada final de 4 a 9 palavras, natural, mandando pro link da bio",
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


# ------------------------------------------------------------ banco de reserva
RESERVA = [
    {"pilar": 0, "gancho": "Quem revende *moda fitness* não pode errar isso", "quadros": ["Misture modelos e cores no mesmo pedido: sua cliente sempre acha algo pra levar.", "Variedade faz a cliente voltar na próxima coleção."], "cta": "Monte o seu pedido no link da bio", "legenda": "Variedade é o que faz a cliente voltar. Nos kits da Lulu você já recebe modelos e cores misturados pra montar a vitrine. Veja o catálogo completo no link da bio."},
    {"pilar": 0, "gancho": "O jeito *mais simples* de girar o estoque", "quadros": ["Peça que combina com outra vende junto: conjunto, top e legging na mesma foto.", "Mostre o look completo, não só a peça."], "cta": "Veja os kits no link da bio", "legenda": "Cliente que vê o look completo leva mais de uma peça. Monte combinações com os kits da Lulu e divulgue como conjunto. Catálogo no link da bio."},
    {"pilar": 1, "gancho": "Kit pronto de *5 peças*, direto pra sua vitrine", "quadros": ["Você escolhe o kit, a gente envia as peças com cores variadas.", "Pedido mínimo de 4 kits e frete grátis a partir de 6."], "cta": "Escolha o seu no link da bio", "legenda": "Kits prontos de 5 peças com cores variadas, direto pra sua revenda. Pedido mínimo de 4 kits e frete grátis a partir de 6. Veja tudo no link da bio."},
    {"pilar": 1, "gancho": "Seu *próximo kit* já está aqui", "quadros": ["Suplex e poliamida, conjuntos, macacões e linha plus size.", "Tudo no atacado, pronto pra revender."], "cta": "Catálogo completo no link da bio", "legenda": "Conjuntos, macacões e linha plus size em suplex e poliamida, tudo no atacado. O catálogo completo está no link da bio."},
    {"pilar": 2, "gancho": "Já pensou em ter a *sua loja* de moda fitness?", "quadros": ["A mini franquia Lulu é uma loja online sua, pronta pra divulgar.", "O catálogo se atualiza sozinho, você foca em vender."], "cta": "Conheça a mini franquia no link da bio", "selo": "MINI FRANQUIA · LINK NA BIO", "legenda": "Quer ter a sua própria loja de moda fitness? A mini franquia Lulu entrega uma loja online pronta, com catálogo sempre atualizado. Saiba mais no link da bio."},
    {"pilar": 2, "gancho": "Sua loja online *pronta* em vez de começar do zero", "quadros": ["Catálogo, fotos e preços já organizados pra você divulgar.", "Mais tempo pra atender cliente e vender."], "cta": "Saiba como no link da bio", "selo": "MINI FRANQUIA · LINK NA BIO", "legenda": "Começar uma loja do zero dá trabalho. Com a mini franquia Lulu você recebe a loja online pronta e foca no que importa: vender. Detalhes no link da bio."},
    {"pilar": 3, "gancho": "O *erro* que trava muita revendedora", "quadros": ["Comprar só o que você gosta e esquecer o que a cliente procura.", "Ouça sua cliente antes de montar o pedido."], "cta": "Monte um pedido certeiro no link da bio", "legenda": "Muita revendedora compra pelo gosto próprio e esquece de perguntar o que a cliente quer. Antes de fechar o pedido, ouça quem compra. Catálogo no link da bio."},
    {"pilar": 3, "gancho": "Revender sem *divulgar* não funciona", "quadros": ["Foto boa, vitrine organizada e postagem todo dia fazem diferença.", "Quem aparece, vende."], "cta": "Pegue as peças no link da bio", "legenda": "Não adianta ter peça bonita parada. Foto boa e constância nas postagens colocam sua revenda na frente da cliente. Veja os kits no link da bio."},
    {"pilar": 4, "gancho": "Frete *grátis* a partir de 6 kits", "quadros": ["Pedido mínimo de 4 kits e 10% de desconto pagando no Pix.", "Condição pensada pra quem revende."], "cta": "Faça seu pedido no link da bio", "legenda": "Pedido mínimo de 4 kits, frete grátis a partir de 6 e 10% de desconto no Pix. Condições pensadas pra quem revende. Veja os kits no link da bio."},
    {"pilar": 4, "gancho": "Comprar no atacado *ficou mais fácil*", "quadros": ["Escolha os kits, pague no Pix com 10% off ou em até 3x no cartão.", "Seu pedido sai organizado e você acompanha tudo."], "cta": "Peça pelo link da bio", "legenda": "Escolha os kits, pague no Pix com 10% de desconto ou em até 3x no cartão. Tudo começa no link da bio."},
    {"pilar": 5, "gancho": "As peças que *mais saem* na moda fitness", "quadros": ["Conjuntos, macacões e leggings com bom caimento sempre giram.", "Modelos plus size ampliam o seu público."], "cta": "Veja os modelos no link da bio", "legenda": "Conjuntos, macacões e leggings com bom caimento giram bem, e a linha plus size amplia seu público. Veja os modelos no link da bio."},
    {"pilar": 6, "gancho": "Moda fitness *de verdade*, feita pra revender", "quadros": ["A Lulu atende revendedoras de todo o Brasil há anos.", "Qualidade que a sua cliente sente no treino."], "cta": "Conheça a Lulu no link da bio", "legenda": "A Lulu Extra Fitness atende revendedoras de todo o Brasil, com peças pensadas pra quem treina. Conheça tudo no link da bio."},
]


def _reserva(dia):
    ops = [b for b in RESERVA if b["pilar"] == dia] or RESERVA
    b = dict(random.choice(ops))
    b["pilar"] = PILARES[dia][0]
    b.setdefault("selo", "LINK NA BIO")
    b["mecanismo"] = "reserva"
    b["hashtags"] = ["#modafitness", "#revendedora", "#atacado", "#lulumodafitness", "#roupafitness", "#revendademoda", "#empreendedorismofeminino"]
    return _validar(b)


def gerar_briefing(recentes):
    dia = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).weekday()
    pilar, instrucao = PILARES[dia]
    mecanismo = random.choice(MECANISMOS)
    for tentativa in (1, 2):
        try:
            b = _validar(_chamar_deepseek(pilar, instrucao, mecanismo, recentes))
            if b["gancho"] in recentes:
                raise ValueError("gancho repetido")
            print(f"Laboratório (DeepSeek, {pilar} / {mecanismo}): {b['gancho']}")
            return b
        except Exception as e:
            print(f"  laboratório tentativa {tentativa} falhou: {str(e)[:120]}")
    b = _reserva(dia)
    print(f"Laboratório (banco reserva, {pilar}): {b['gancho']}")
    return b
