"""
Carrosséis do feed (desde 12/11/2026 — pedido do Lucas: feed SÓ com luluextra.com,
posts simples e carrosséis sobre peças, preços e assuntos variados).

Todas as lâminas saem em JPEG 1080x1350 (4:5, o formato que ocupa mais tela no feed),
com a identidade da Lulu (rosa #FF3D80, ameixa #2B1524, fundo #FFF6FA, Baloo 2).
Etiqueta de preço "tag de roupa" posicionada longe do rosto (visao.py).
Textos das lâminas informativas: SÓ fatos confirmados (mesmos da Stelita e do site).
"""

import io
import re

from PIL import Image, ImageDraw, ImageFilter, ImageOps

import visao
from imagem_story import _baixar_foto_produto, _carregar_fonte

W, H = 1080, 1350
ROSA = (255, 61, 128)
AMEIXA = (43, 21, 36)
FUNDO = (255, 246, 250)
BRANCO = (255, 255, 255)
DOURADO = (255, 177, 0)


def fonte(t, peso="ExtraBold"):
    return _carregar_fonte(t, peso)


def baixar(url):
    return visao.aparar_bordas(_baixar_foto_produto(url))


def foto_4x5(foto, w=W, h=H):
    """Foto ocupando o quadro todo (corte com o alto preservado, onde fica o rosto);
    foto larga/quadrada fica inteira sobre fundo borrado dela mesma (não corta a roupa)."""
    if foto.width / foto.height <= 0.9:
        return ImageOps.fit(foto, (w, h), method=Image.LANCZOS, centering=(0.5, 0.25))
    fundo = ImageOps.fit(foto, (w, h), method=Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
    fundo = Image.blend(fundo, Image.new("RGB", (w, h), FUNDO), 0.35)
    esc = min(w / foto.width, h / foto.height)
    f = foto.resize((int(foto.width * esc), int(foto.height * esc)), Image.LANCZOS)
    fundo.paste(f, ((w - f.width) // 2, (h - f.height) // 2))
    return fundo


def _por_palavra(texto):
    """'*não ficam transparentes*' -> '*não* *ficam* *transparentes*' (destaque sobrevive à quebra de linha)."""
    return re.sub(r"\*([^*]+)\*", lambda m: " ".join(f"*{w}*" for w in m.group(1).split()), texto)


def quebrar(draw, texto, f, largura):
    linhas, atual = [], ""
    for p in _por_palavra(texto).split():
        t = (atual + " " + p).strip()
        if draw.textlength(t.replace("*", ""), font=f) > largura and atual:
            linhas.append(atual)
            atual = p
        else:
            atual = t
    if atual:
        linhas.append(atual)
    return linhas


def texto_destaque(d, xy, linha, f, cor=BRANCO, cor_dest=ROSA, contorno=None, centro=False, largura=W):
    """Escreve a linha com *palavras* em destaque (rosa)."""
    partes = re.split(r"(\*[^*]+\*)", linha)
    total = sum(d.textlength(p.strip("*"), font=f) for p in partes)
    x, y = xy
    if centro:
        x = (largura - total) / 2
    for p in partes:
        if not p:
            continue
        dest = p.startswith("*") and p.endswith("*")
        t = p.strip("*")
        kw = {"stroke_width": 4, "stroke_fill": contorno} if contorno else {}
        d.text((x, y), t, font=f, fill=cor_dest if dest else cor, **kw)
        x += d.textlength(t, font=f)


def etiqueta(rotulo, preco, esc=1.0):
    valor = f"R$ {preco:.2f}".replace(".", ",")
    f1, f2 = fonte(int(30 * esc)), fonte(int(60 * esc))
    d0 = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    w = int(max(d0.textlength(valor, font=f2), d0.textlength(rotulo, font=f1)) + 80 * esc)
    h = int(160 * esc)
    im = Image.new("RGBA", (w + 30, h + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((20, 10, w + 20, h), radius=int(30 * esc), fill=ROSA + (255,), outline=BRANCO + (255,), width=5)
    d.ellipse((34, 24, 34 + int(24 * esc), 24 + int(24 * esc)), fill=AMEIXA + (255,), outline=BRANCO + (255,), width=3)
    cx = 20 + w / 2 + 8
    d.text((cx - d0.textlength(rotulo, font=f1) / 2, 10 + 26 * esc), rotulo, font=f1, fill=(255, 235, 242, 255))
    d.text((cx - d0.textlength(valor, font=f2) / 2, 10 + 62 * esc), valor, font=f2, fill=BRANCO + (255,))
    return im.rotate(6, resample=Image.BICUBIC, expand=True)


def _por_etiqueta(base, et, evitar=()):
    """Cola a etiqueta num canto sem rosto (e fora das faixas de texto em `evitar`)."""
    zonas = visao.zonas_proibidas(base, [(0, 0, base.width, base.height)]) + list(evitar)
    m = 34
    cands = [(base.width - et.width - m, m + 70), (m, m + 70), (base.width - et.width - m, 520), (m, 520),
             (m, 760), (base.width - et.width - m, 760)]
    pos, _ = visao.lugar_livre(et.size, cands, zonas)
    rgba = base.convert("RGBA")
    rgba.alpha_composite(et, (int(pos[0]), int(pos[1])))
    return rgba.convert("RGB")


def _faixa_baixo(img, altura=420, forca=220):
    grad = Image.new("L", (1, altura))
    for y in range(altura):
        grad.putpixel((0, y), int(forca * (y / altura) ** 1.4))
    escuro = Image.new("RGB", (W, altura), (20, 8, 15))
    trecho = img.crop((0, H - altura, W, H))
    img.paste(Image.composite(escuro, trecho, grad.resize((W, altura))), (0, H - altura))
    return img


def _marca(d, cor=BRANCO):
    d.text((44, 38), "LULU EXTRA FITNESS", font=fonte(30, "Bold"), fill=cor)


def _rodape(d, cor=BRANCO, texto="luluextra.com"):
    f = fonte(32, "Bold")
    d.text(((W - d.textlength(texto, font=f)) / 2, H - 70), texto, font=f, fill=cor)


# ------------------------------------------------------------------ lâminas
def slide_produto(foto, rotulo=None, preco=None, nome="", selo=None):
    img = _faixa_baixo(foto_4x5(foto))
    d = ImageDraw.Draw(img)
    _marca(d)
    if selo:  # ex.: NOVIDADE
        f = fonte(34)
        w = d.textlength(selo, font=f) + 60
        d.rounded_rectangle((W - w - 40, 30, W - 40, 92), radius=31, fill=DOURADO)
        d.text((W - w - 10, 38), selo, font=f, fill=AMEIXA)
    if nome:
        f = fonte(46)
        linhas = quebrar(d, nome, f, W - 120)[:2]
        y = H - 110 - 56 * len(linhas)
        for ln in linhas:
            d.text((60, y), ln, font=f, fill=BRANCO, stroke_width=3, stroke_fill=(20, 8, 15))
            y += 56
    _rodape(d, (255, 214, 230))
    if rotulo and preco:
        img = _por_etiqueta(img, etiqueta(rotulo, preco), evitar=[(0, H - 260, W, H)])
    return img


def slide_capa(foto, titulo, sub="", chamada="ARRASTA PRO LADO →"):
    img = foto_4x5(foto)
    img = _faixa_baixo(img, altura=760, forca=235)
    d = ImageDraw.Draw(img)
    _marca(d)
    f = fonte(92)
    linhas = quebrar(d, titulo, f, W - 120)[:4]
    fs = fonte(42, "Bold")
    sub_l = quebrar(d, sub, fs, W - 140)[:2] if sub else []
    y = H - 200 - 104 * len(linhas) - 54 * len(sub_l)
    for ln in linhas:
        texto_destaque(d, (60, y), ln, f, contorno=(24, 8, 20))
        y += 104
    y += 10
    for ln in sub_l:
        d.text((62, y), ln, font=fs, fill=(255, 225, 236))
        y += 54
    fc = fonte(34)
    w = d.textlength(chamada, font=fc) + 70
    d.rounded_rectangle((W - w - 50, H - 120, W - 50, H - 50), radius=35, fill=ROSA)
    d.text((W - w - 15, H - 112), chamada, font=fc, fill=BRANCO)
    return img


def slide_info(numero, titulo, texto, foto=None):
    """Texto em cima (grande, fácil de ler no celular) e foto do catálogo embaixo."""
    img = Image.new("RGB", (W, H), FUNDO)
    topo = 130
    if foto is not None:  # foto embaixo, corte pelo alto (mostra a modelo, não só o tronco)
        card = ImageOps.fit(foto, (W - 120, 500), method=Image.LANCZOS, centering=(0.5, 0.12))
        m = Image.new("L", card.size, 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, card.width - 1, card.height - 1), radius=44, fill=255)
        img.paste(card, (60, H - 130 - 500), m)
    d = ImageDraw.Draw(img)
    _marca(d, ROSA)
    if numero:
        d.ellipse((60, topo, 160, topo + 100), fill=ROSA)
        fn = fonte(60)
        d.text((110 - d.textlength(str(numero), font=fn) / 2, topo + 8), str(numero), font=fn, fill=BRANCO)
        xt = 190
    else:
        xt = 60
    ft = fonte(72)
    lt = quebrar(d, titulo, ft, W - xt - 60)[:3]
    y = topo + 4
    for ln in lt:
        texto_destaque(d, (xt, y), ln, ft, cor=AMEIXA)
        y += 82
    y = max(y + 28, topo + 140)
    fx = fonte(48 if foto is not None else 54, "SemiBold")
    for par in texto.split("\n"):
        for ln in quebrar(d, par, fx, W - 120):
            texto_destaque(d, (60, y), ln, fx, cor=(70, 40, 60))
            y += int(fx.size * 1.32)
        y += 20
    d.line((60, H - 100, W - 60, H - 100), fill=(255, 200, 220), width=3)
    _rodape(d, ROSA)
    return img


def slide_final(fotos, titulo="Monte seu pedido em *luluextra.com*", sub="Link na bio • pedido pelo WhatsApp"):
    img = Image.new("RGB", (W, H), AMEIXA)
    d = ImageDraw.Draw(img)
    for y in range(H):
        k = y / H
        d.line((0, y, W, y), fill=(int(43 + 45 * k), int(21 + 4 * k), int(36 + 24 * k)))
    n = min(3, len(fotos))
    if n:
        wc = 290
        x0 = (W - (n * wc + (n - 1) * 24)) // 2
        for i in range(n):
            c = ImageOps.fit(fotos[i], (wc, 390), method=Image.LANCZOS, centering=(0.5, 0.25))
            m = Image.new("L", c.size, 0)
            ImageDraw.Draw(m).rounded_rectangle((0, 0, wc - 1, 389), radius=30, fill=255)
            img.paste(c, (x0 + i * (wc + 24), 200 + (26 if i % 2 else 0)), m)
    d = ImageDraw.Draw(img)
    _marca(d, (255, 190, 215))
    f = fonte(80)
    y = 700
    for ln in quebrar(d, titulo, f, W - 140)[:3]:
        texto_destaque(d, (0, y), ln, f, centro=True)
        y += 94
    fs = fonte(40, "Bold")
    d.text(((W - d.textlength(sub, font=fs)) / 2, y + 30), sub, font=fs, fill=(255, 214, 230))
    return img


def salvar(img, caminho):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=90, optimize=True)
    with open(caminho, "wb") as f:
        f.write(buf.getvalue())


# ------------------------------------------------------------------ temas informativos
# SÓ fatos confirmados (site, checkout e Stelita, 04/11/2026). Mudou frete/regra? atualizar aqui.
TEMAS_INFO = {
    "como_comprar": {
        "capa": ("Como comprar na *Lulu* em 3 passos", "Atacado de moda fitness, direto da fábrica"),
        "passos": [("Escolha seus *kits*", "Entre em luluextra.com e escolha no mínimo 4 kits.\nCada kit tem 5 peças do mesmo modelo, em cores variadas."),
                   ("Finalize no *site*", "Escolha o frete e a forma de pagamento:\nPix com 10% de desconto nas peças ou cartão em até 3x sem juros."),
                   ("Confirme no *WhatsApp*", "O pedido chega no nosso WhatsApp e a gente cuida do envio pra todo o Brasil.")],
        "legenda": ["Comprar na Lulu é simples assim 👇", "Escolhe os kits no site, finaliza e confirma pelo WhatsApp.",
                    "Pedido mínimo: 4 kits. A partir de 6, o frete Vip é grátis."],
    },
    "frete": {
        "capa": ("Frete dos kits *sem mistério*", "Salvador e todo o Brasil"),
        "passos": [("Econômico", "*R$ 39,90* — até 9 dias úteis."),
                   ("Vip rápido", "*R$ 90,00* — até 7 dias úteis."),
                   ("Vip *grátis*", "A partir de *6 kits* no pedido, o frete Vip sai grátis pra Salvador e pro Brasil todo.\nO prazo conta a partir da postagem.")],
        "legenda": ["Quanto custa o frete dos kits? 🚚", "Econômico R$ 39,90 (até 9 dias úteis) ou Vip R$ 90 (até 7 dias úteis).",
                    "Fechando 6 kits ou mais, o Vip sai grátis pra Salvador e pro Brasil todo."],
    },
    "tamanhos": {
        "capa": ("Guia de *tamanhos* dos kits", "O tamanho vem no nome de cada produto"),
        "passos": [("Sem tamanho ou *Slim*", "Veste do 36 ao 42."),
                   ("*Midi*", "Veste 42/44."),
                   ("*Plus* ou GG", "Veste do 46 ao 50.\nAs 5 peças do kit vêm no mesmo tamanho; o que varia são as cores.")],
        "legenda": ["Salva esse guia de tamanhos 📌", "Slim (ou sem tamanho no nome): 36 ao 42. Midi: 42/44. Plus/GG: 46 ao 50.",
                    "No site dá pra filtrar os modelos por tamanho."],
    },
    "tecido": {
        "capa": ("Por que nossas peças *não ficam transparentes*", "Suplex e poliamida de verdade"),
        "passos": [("*Zero* transparência", "Pode agachar: as malhas da Lulu não ficam transparentes."),
                   ("As *malhas*", "Suplex Vip, Poliamida Premium e Poliamida Canelado.\nA malha de cada modelo aparece no site."),
                   ("Dica de *lavagem*", "Lave do avesso, sem amaciante e seque à sombra: a peça dura muito mais.")],
        "legenda": ["O teste do agachamento que toda cliente faz ✅", "Nossas malhas são zero transparência: Suplex Vip, Poliamida Premium e Poliamida Canelado.",
                    "Dica extra: lave do avesso, sem amaciante, e seque à sombra."],
    },
    "kit": {
        "capa": ("O que vem num *kit* da Lulu?", "Kit pronto pra revender"),
        "passos": [("*5 peças* por kit", "Do mesmo modelo e do mesmo tamanho."),
                   ("*Cores* variadas", "Cada kit chega com sortimento de cores: vitrine colorida com um pedido só."),
                   ("Catálogo *toda semana*", "O catálogo de luluextra.com é atualizado toda semana. Pedido mínimo: 4 kits.")],
        "legenda": ["O que vem num kit da Lulu? 👇", "5 peças do mesmo modelo e tamanho, em cores variadas.",
                    "Pedido mínimo de 4 kits, catálogo novo toda semana."],
    },
    "dicas_venda": {
        "capa": ("3 dicas pra vender mais *moda fitness*", "Pra quem revende no WhatsApp e no Instagram"),
        "passos": [("Foto que *vende*", "Mostre o conjunto montado, com luz natural e fundo limpo."),
                   ("Responda *rápido*", "Cliente que espera esfria. Mande foto da peça no corpo pra ela se imaginar usando."),
                   ("Tire a dúvida de *tamanho*", "Peça a medida da cliente e compare com o guia de tamanhos da peça.")],
        "legenda": ["3 dicas simples pra vender mais moda fitness 💡", "Salva pra consultar depois.",
                    "Precisando de peça pra revender? Os kits estão em luluextra.com."],
    },
    "lulu": {
        "capa": ("Prazer, somos a *Lulu*", "Moda fitness no atacado desde 2013"),
        "passos": [("Nascida em *Salvador*", "A Lulu nasceu em Salvador e atende revendedoras do Brasil todo."),
                   ("Fábrica *própria*", "Confecção própria em Recife desde 2013."),
                   ("Tudo pelo *site*", "Catálogo atualizado toda semana em luluextra.com e pedido confirmado pelo WhatsApp.")],
        "legenda": ["Você já conhece a história da Lulu? 💗", "Nascemos em Salvador e temos fábrica própria em Recife desde 2013.",
                    "Hoje a vitrine é toda online: luluextra.com."],
    },
}
