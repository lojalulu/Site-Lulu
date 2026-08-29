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
    faixa_altura = 520
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

    # texto principal "Link na bio ✨" perto do rodapé
    fonte_cta = _carregar_fonte(84, "ExtraBold")
    texto_completo = f"✨ {texto} ✨"
    bbox = draw.textbbox((0, 0), texto_completo, font=fonte_cta)
    largura_texto = bbox[2] - bbox[0]
    x = (LARGURA - largura_texto) / 2
    y = ALTURA - 260
    draw.text((x, y), texto_completo, font=fonte_cta, fill=COR_TEXTO)

    # pilulazinha rosa decorativa acima do texto (assinatura visual do site)
    draw.rounded_rectangle([LARGURA/2 - 90, y - 46, LARGURA/2 + 90, y - 12], radius=16, fill=COR_ACCENT)

    saida = io.BytesIO()
    canvas.convert("RGB").save(saida, format="JPEG", quality=90)
    return saida.getvalue()
