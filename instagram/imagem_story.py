"""
Gera a imagem do Story: foto real do produto + faixa de marca com
"Link na bio". Como a Meta não deixa colocar o link-sticker de verdade
via automação, escrevemos o convite direto na imagem.
"""

import io
import os
import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

LARGURA, ALTURA = 1080, 1920  # proporção 9:16 padrão de Story

FONTE_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/baloo2/Baloo2%5Bwght%5D.ttf"
FONTE_LOCAL = "_tmp_font.ttf"
FONTE_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

COR_ACCENT = (255, 61, 128)      # --accent do site
COR_TEXTO = (255, 255, 255)

FONTE_EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"


def _eh_emoji(ch: str) -> bool:
    """Heurística simples: intervalos Unicode onde vivem os emojis mais
    comuns. A fonte da marca (Baloo 2) não tem esses glifos — sem isso,
    eles apareciam como quadradinhos (❐) na imagem publicada de verdade."""
    cp = ord(ch)
    faixas = [
        (0x2190, 0x21FF), (0x2300, 0x27BF), (0x2B00, 0x2BFF),
        (0x1F000, 0x1FAFF), (0xFE0F, 0xFE0F), (0x200D, 0x200D),
    ]
    return any(a <= cp <= b for a, b in faixas)


def _carregar_fonte(tamanho: int, peso: str = "ExtraBold"):
    """Tenta a fonte da marca (Baloo 2); se falhar por qualquer motivo
    (sem internet, URL mudou etc.), cai pra uma fonte segura do sistema
    — nunca deixa a automação quebrar por causa de fonte."""
    try:
        if not os.path.exists(FONTE_LOCAL):
            resp = requests.get(FONTE_URL, timeout=20)
            resp.raise_for_status()
            with open(FONTE_LOCAL, "wb") as f:
                f.write(resp.content)
        fonte = ImageFont.truetype(FONTE_LOCAL, tamanho)
        try:
            fonte.set_variation_by_name(peso)
        except Exception:
            pass  # fonte baixou mas não é variável por algum motivo — usa do jeito que veio
        return fonte
    except Exception as e:
        print(f"Aviso: não consegui usar a fonte da marca ({e}). Usando fonte alternativa.")
        return ImageFont.truetype(FONTE_FALLBACK, tamanho)


def _fonte_que_cabe(draw, texto: str, largura_max: int, tamanho_max: int, tamanho_min: int, peso: str):
    """Escolhe o maior tamanho de fonte (dentro do intervalo) que ainda
    deixa o texto caber em largura_max — pra frases curtas ('Link na
    bio') ficarem grandes e frases mais longas ('Malha grossa, não
    marca') não estourarem a imagem. Ignora emojis na medição (eles são
    desenhados com a fonte de emoji, calculada à parte)."""
    texto_medida = "".join(c for c in texto if not _eh_emoji(c))
    tamanho = tamanho_max
    while tamanho > tamanho_min:
        fonte = _carregar_fonte(tamanho, peso)
        bbox = draw.textbbox((0, 0), texto_medida, font=fonte)
        if (bbox[2] - bbox[0]) <= largura_max:
            return fonte
        tamanho -= 4
    return _carregar_fonte(tamanho_min, peso)


def _largura_segmento(draw, segmento: str, fonte, tamanho_linha: int) -> tuple:
    """Retorna (largura, imagem_ou_None). Pra emoji, pré-renderiza a
    imagem colorida já no tamanho certo (a fonte de emoji só aceita um
    tamanho fixo internamente, por isso rendeializamos à parte e
    redimensionamos, em vez de desenhar direto com draw.text)."""
    if _eh_emoji(segmento[0]):
        img = _renderizar_emoji(segmento, tamanho_linha)
        return img.width, img
    bbox = draw.textbbox((0, 0), segmento, font=fonte)
    return bbox[2] - bbox[0], None


TAMANHO_FONTE_EMOJI_FIXO = 109  # única resolução que a fonte de emoji do sistema aceita


def _renderizar_emoji(segmento: str, altura_alvo: int) -> Image.Image:
    """Desenha o(s) emoji(s) na resolução fixa que a fonte aceita e
    redimensiona pra altura alvo, preservando a transparência (cor)."""
    fonte = ImageFont.truetype(FONTE_EMOJI, TAMANHO_FONTE_EMOJI_FIXO)
    tmp = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(tmp)
    bbox = d.textbbox((0, 0), segmento, font=fonte, embedded_color=True)
    largura = max(bbox[2] - bbox[0], 1)
    altura = max(bbox[3] - bbox[1], 1)
    img = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((-bbox[0], -bbox[1]), segmento, font=fonte, embedded_color=True)
    escala = altura_alvo / altura
    novo_tamanho = (max(int(largura * escala), 1), max(int(altura * escala), 1))
    return img.resize(novo_tamanho, Image.LANCZOS)


def _desenhar_linha_com_emoji(canvas: Image.Image, draw, linha: str, y: int, fonte, largura_total_imagem: int):
    """Desenha uma linha centralizada, alternando entre a fonte da marca
    (texto normal) e emoji colorido pré-renderizado — sem isso, emojis
    viram quadradinhos na imagem publicada."""
    segmentos, atual, tipo_atual = [], "", None
    for ch in linha:
        tipo = "emoji" if _eh_emoji(ch) else "texto"
        if tipo != tipo_atual and atual:
            segmentos.append((tipo_atual, atual))
            atual = ""
        atual += ch
        tipo_atual = tipo
    if atual:
        segmentos.append((tipo_atual, atual))

    tamanho_linha = fonte.size
    partes = []  # (tipo, conteudo_ou_imagem, largura)
    for tipo, seg in segmentos:
        if tipo == "emoji":
            try:
                largura, img = _largura_segmento(draw, seg, fonte, tamanho_linha)
                partes.append(("emoji", img, largura))
            except Exception:
                pass  # ambiente sem suporte a emoji colorido — só pula o glifo
        else:
            bbox = draw.textbbox((0, 0), seg, font=fonte)
            partes.append(("texto", seg, bbox[2] - bbox[0]))

    largura_total = sum(p[2] for p in partes)
    x = (largura_total_imagem - largura_total) / 2

    for tipo, conteudo, largura in partes:
        if tipo == "emoji":
            canvas.paste(conteudo, (int(x), int(y)), conteudo)
        else:
            draw.text((x, y), conteudo, font=fonte, fill=COR_TEXTO)
        x += largura


def _baixar_foto_produto(url_imagem: str) -> Image.Image:
    resp = requests.get(url_imagem, timeout=20)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def _preencher_cover(img: Image.Image, largura: int, altura: int) -> Image.Image:
    """Redimensiona 'cobrindo' o quadro todo e corta o excesso, mantendo
    o centro — igual ao object-fit: cover do CSS."""
    return ImageOps.fit(img, (largura, altura), method=Image.LANCZOS, centering=(0.5, 0.4))


def gerar_imagem_story(url_foto_produto: str, texto: str = "Link na bio") -> bytes:
    foto = _baixar_foto_produto(url_foto_produto)
    canvas = _preencher_cover(foto, LARGURA, ALTURA)

    # faixa gradiente na parte de baixo, pra o texto ficar legível
    faixa_altura = 620
    faixa = Image.new("RGBA", (LARGURA, faixa_altura), (0, 0, 0, 0))
    draw_faixa = ImageDraw.Draw(faixa)
    for y in range(faixa_altura):
        alpha = int(210 * (y / faixa_altura))
        draw_faixa.line([(0, y), (LARGURA, y)], fill=(20, 8, 15, alpha))
    canvas = canvas.convert("RGBA")
    canvas.alpha_composite(faixa, dest=(0, ALTURA - faixa_altura))

    draw = ImageDraw.Draw(canvas)

    # selo pequeno "LULU" no topo
    fonte_marca = _carregar_fonte(54, "Bold")
    draw.text((48, 64), "LULU", font=fonte_marca, fill=COR_TEXTO)

    # texto principal: até 2 linhas (destaque + chamada pra bio), cada
    # uma com o maior tamanho de fonte que ainda cabe na largura da tela
    linhas = [l for l in texto.split("\n") if l.strip()]
    largura_max = LARGURA - 120

    linhas_com_fonte = []
    for i, linha in enumerate(linhas):
        tamanho_max = 84 if i == 0 else 68
        fonte = _fonte_que_cabe(draw, linha, largura_max, tamanho_max, 40, "ExtraBold")
        linhas_com_fonte.append((linha, fonte))

    # altura de cada linha = altura do "M" maiúsculo na fonte escolhida (aproximação estável)
    alturas = [draw.textbbox((0, 0), "Mg", font=f)[3] for _, f in linhas_com_fonte]
    espacamento = 24
    altura_total = sum(alturas) + espacamento * (len(linhas_com_fonte) - 1)
    y = ALTURA - 200 - altura_total

    for (linha, fonte), altura_linha in zip(linhas_com_fonte, alturas):
        _desenhar_linha_com_emoji(canvas, draw, linha, y, fonte, LARGURA)
        y += altura_linha + espacamento

    # pilulazinha rosa decorativa abaixo do texto (assinatura visual do site)
    draw.rounded_rectangle([LARGURA/2 - 90, ALTURA - 150, LARGURA/2 + 90, ALTURA - 116], radius=16, fill=COR_ACCENT)

    saida = io.BytesIO()
    canvas.convert("RGB").save(saida, format="JPEG", quality=90)
    return saida.getvalue()
