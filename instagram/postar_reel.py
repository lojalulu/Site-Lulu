"""
Robô de Reels premium do Instagram (Lulu Extra Fitness).

Cada Reel é montado do zero, com fotos reais dos produtos:
  - gancho forte nos primeiros segundos (texto grande animado)
  - layouts variados (tela cheia, cartão arredondado, duas fotos)
  - movimentos de câmera e transições dinâmicas
  - etiqueta de preço animada em alguns quadros
  - frases com tempo de leitura calculado pelo número de palavras
  - cartão final de chamada (link da bio)
  - música livre de direitos, sorteada
  - textos criados pelo "laboratório" (DeepSeek), com banco de reserva

Uso:
  python instagram/postar_reel.py              -> gera e publica
  python instagram/postar_reel.py --so-gerar   -> gera, hospeda a prévia (sem publicar)
"""

import datetime
import functools
import itertools
import io
import json
import math
import os
import random
import re
import subprocess
import sys
import time

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageChops

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imagem_story import _carregar_fonte  # noqa: E402  (Baloo 2 com fallback)
import reel_lab  # noqa: E402

L, A = 1080, 1920
FPS = 30
FADE = 0.45            # duração das transições
DUR_FOTO = (2.0, 2.6)  # quadros só de foto
MAX_TOTAL = 29.5       # as músicas têm 30s
ROSA = (255, 61, 128)
DOURADO = (255, 177, 0)
AMEIXA = (43, 21, 36)
BRANCO = (255, 255, 255)

CATALOGOS = {"kits": "produtos.json", "avulso": "kitavulso/produtos.json"}
HIST = "instagram/historico_reels.json"
PASTA_SAIDA = "instagram/_saida"
SAIDA = f"{PASTA_SAIDA}/reel.mp4"
PREVIA = f"{PASTA_SAIDA}/previa.jpg"
MUSICAS = "instagram/musicas"

GRAPH = "https://graph.instagram.com/v23.0"
TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
IG_ID = os.environ.get("INSTAGRAM_BUSINESS_ID")


# ================================================================ utilidades
def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


@functools.lru_cache(maxsize=None)
def fonte(tam, peso="ExtraBold"):
    return _carregar_fonte(tam, peso)


def palavras(txt):
    return len(re.findall(r"\S+", txt.replace("*", "")))


def tempo_leitura(txt, minimo=3.2, base=1.3, por_palavra=0.34):
    """Tempo de tela = entrada da animação + leitura calmada (~3 palavras/s)."""
    return min(7.5, max(minimo, base + por_palavra * palavras(txt)))


def cobrir(img, w, h):
    esc = max(w / img.width, h / img.height)
    im = img.resize((int(img.width * esc) + 1, int(img.height * esc) + 1), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def fundo_borrado(foto, escurecer=0.4):
    f = cobrir(foto, L, A).filter(ImageFilter.GaussianBlur(50))
    return Image.blend(f, Image.new("RGB", (L, A), AMEIXA), escurecer)


def cartao(foto, w, h, raio=46):
    """Foto recortada em cartão arredondado, com sombra suave (RGBA já com sombra)."""
    im = cobrir(foto, w, h).convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=raio, fill=255)
    im.putalpha(mask)
    pad = 60
    sombra = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    m2 = Image.new("L", sombra.size, 0)
    m2.paste(mask.point(lambda v: int(v * 0.55)), (pad, pad + 14))
    sombra.putalpha(m2.filter(ImageFilter.GaussianBlur(26)))
    sombra.alpha_composite(im, (pad, pad))
    return sombra, pad


# ================================================================ texto
def tokens(frase):
    """'Quem revende *moda fitness* ...' -> [(palavra, destaque)]."""
    out, dest = [], False
    for parte in re.split(r"(\*)", frase):
        if parte == "*":
            dest = not dest
        else:
            for p in parte.split():
                out.append((p, dest))
    return out


def quebrar(draw, toks, f, largura):
    linhas, atual, w_atual = [], [], 0
    esp = draw.textlength(" ", font=f)
    for p, d in toks:
        w = draw.textlength(p, font=f)
        if atual and w_atual + esp + w > largura:
            linhas.append(atual)
            atual, w_atual = [], 0
        atual.append((p, d))
        w_atual += (esp if len(atual) > 1 else 0) + w
    if atual:
        linhas.append(atual)
    return linhas


def linhas_renderizadas(frase, tam_max, largura, max_linhas, tam_min=54, cor_dest=ROSA):
    """Devolve lista de imagens RGBA (uma por linha de texto), centralizadas."""
    d0 = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    toks = tokens(frase)
    for tam in range(tam_max, tam_min - 1, -4):
        f = fonte(tam)
        linhas = quebrar(d0, toks, f, largura)
        if len(linhas) <= max_linhas:
            break
    esp = d0.textlength(" ", font=f)
    alt = int(tam * 1.22)
    imgs = []
    for ln in linhas:
        w = int(sum(d0.textlength(p, font=f) for p, _ in ln) + esp * (len(ln) - 1)) + 24
        im = Image.new("RGBA", (w, alt + 16), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        x = 12
        for p, dest in ln:
            d.text((x, 4), p, font=f, fill=(cor_dest if dest else BRANCO) + (255,),
                   stroke_width=max(4, tam // 16), stroke_fill=(24, 8, 20, 255))
            x += d.textlength(p, font=f) + esp
        imgs.append(im)
    return imgs


class BlocoTexto:
    """Linhas que entram uma a uma (sobem + aparecem). Ancorado por y_base (fundo) ou y_centro."""

    def __init__(self, frase, tam_max=96, largura=860, max_linhas=4, y_base=None, y_centro=None,
                 selo=None, atraso=0.25):
        self.linhas = linhas_renderizadas(frase, tam_max, largura, max_linhas)
        self.atraso = atraso
        alt_total = sum(i.height for i in self.linhas)
        self.selo_img = self._selo(selo) if selo else None
        sel_h = (self.selo_img.height + 36) if self.selo_img else 0
        total = alt_total + sel_h
        topo = (y_centro - total // 2) if y_centro is not None else (y_base - total)
        self.pos, y = [], topo
        for im in self.linhas:
            self.pos.append(((L - im.width) // 2 - 20, y))
            y += im.height
        self.selo_pos = ((L - self.selo_img.width) // 2 - 20, y + 36) if self.selo_img else None
        self.topo, self.base = topo, topo + total

    @staticmethod
    def _selo(texto):
        f = fonte(44)
        d0 = ImageDraw.Draw(Image.new("RGB", (4, 4)))
        w = int(d0.textlength(texto, font=f)) + 90
        im = Image.new("RGBA", (w, 88), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((0, 0, w - 1, 87), radius=44, fill=ROSA + (255,))
        d.text((45, 14), texto, font=f, fill=BRANCO + (255,))
        return im

    def desenhar(self, base_rgba, t):
        itens = [(im, p) for im, p in zip(self.linhas, self.pos)]
        if self.selo_img:
            itens.append((self.selo_img, self.selo_pos))
        for i, (im, (x, y)) in enumerate(itens):
            a = ease_out((t - self.atraso - 0.20 * i) / 0.5)
            if a <= 0:
                continue
            yy = int(y + (1 - a) * 50)
            if a < 1:
                im = im.copy()
                im.putalpha(im.getchannel("A").point(lambda v, a=a: int(v * a)))
            base_rgba.alpha_composite(im, (x, yy))


def etiqueta_preco(rotulo, preco):
    """Etiqueta estilo 'tag de roupa' (assinatura visual da Lulu)."""
    valor = f"R$ {preco:.2f}".replace(".", ",")
    f1, f2 = fonte(34), fonte(66)
    d0 = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    w = max(int(d0.textlength(valor, font=f2)), int(d0.textlength(rotulo, font=f1))) + 90
    im = Image.new("RGBA", (w + 40, 190), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((30, 10, w + 30, 180), radius=34, fill=ROSA + (255,), outline=BRANCO + (255,), width=6)
    d.ellipse((46, 26, 74, 54), fill=AMEIXA + (255,), outline=BRANCO + (255,), width=3)  # furinho da tag
    cx = 30 + (w) // 2
    d.text((cx - d0.textlength(rotulo, font=f1) / 2 + 10, 40), rotulo, font=f1, fill=(255, 235, 242, 255))
    d.text((cx - d0.textlength(valor, font=f2) / 2 + 10, 84), valor, font=f2, fill=BRANCO + (255,))
    return im.rotate(7, resample=Image.BICUBIC, expand=True)


# ================================================================ quadros
class Quadro:
    dur = 2.4
    texto = None

    def render(self, t):
        raise NotImplementedError


class QuadroFoto(Quadro):
    """Foto(s) com layout, movimento de câmera, texto opcional e etiqueta de preço."""

    def __init__(self, fotos, layout, movimento, dur, bloco=None, etiqueta=None, escuro=0.0, gancho=False):
        self.dur, self.movimento, self.bloco, self.etiqueta = dur, movimento, bloco, etiqueta
        self.escuro, self.gancho = escuro, gancho
        self.texto = bloco is not None
        if layout == "cheio":
            fundo = fundo_borrado(fotos[0], 0.35)
            w, h = fotos[0].size
            esc = min(L / w, 1560 / h)
            fg = fotos[0].resize((int(w * esc), int(h * esc)), Image.LANCZOS)
            fundo.paste(fg, ((L - fg.width) // 2, (A - fg.height) // 2 - 40))
        elif layout == "cartao":
            fundo = fundo_borrado(fotos[0], 0.55)
            card, pad = cartao(fotos[0], 940, 1240)
            fundo = fundo.convert("RGBA")
            fundo.alpha_composite(card, ((L - card.width) // 2, 330 - pad + 20))
            fundo = fundo.convert("RGB")
        else:  # duo
            fundo = fundo_borrado(fotos[0], 0.55).convert("RGBA")
            for i, ft in enumerate(fotos[:2]):
                card, pad = cartao(ft, 940, 700, 42)
                fundo.alpha_composite(card, ((L - card.width) // 2, 250 + i * 730 - pad))
            fundo = fundo.convert("RGB")
        if escuro:
            fundo = Image.blend(fundo, Image.new("RGB", (L, A), (10, 4, 10)), escuro)
        if bloco is not None:  # escurece pra leitura: geral no gancho, só embaixo nos demais
            grad = Image.new("L", (1, A), 0)
            for y in range(A):
                if gancho:
                    v = 60 + 80 * max(0.0, 1 - abs(y - 900) / 750)
                else:
                    v = 225 * min(1.0, max(0.0, (y - 780) / 470))
                grad.putpixel((0, y), int(v))
            fundo = Image.composite(Image.new("RGB", (L, A), (14, 5, 12)), fundo, grad.resize((L, A)))
        self.base = fundo

    def _camera(self, t):
        p = min(max(t / (self.dur + FADE), 0), 1)
        m = self.movimento
        if m == "zoom_in":
            z, fx = 1.0 + 0.09 * p, 0.5
        elif m == "zoom_out":
            z, fx = 1.09 - 0.09 * p, 0.5
        elif m == "pan_esq":
            z, fx = 1.10, 0.85 - 0.7 * p
        else:  # pan_dir
            z, fx = 1.10, 0.15 + 0.7 * p
        cw, ch = L / z, A / z
        x, y = (L - cw) * fx, (A - ch) / 2
        return self.base.resize((L, A), Image.BILINEAR, box=(x, y, x + cw, y + ch))

    def render(self, t):
        im = self._camera(t)
        if self.bloco is None and self.etiqueta is None:
            return im
        rgba = im.convert("RGBA")
        if self.etiqueta is not None:
            a = ease_out((t - 0.45) / 0.45)
            if a > 0:
                esc = 0.55 + 0.45 * a + 0.12 * math.sin(a * math.pi)  # "pop"
                et = self.etiqueta
                et = et.resize((max(1, int(et.width * esc)), max(1, int(et.height * esc))), Image.BILINEAR)
                if a < 1:
                    et.putalpha(et.getchannel("A").point(lambda v: int(v * a)))
                rgba.alpha_composite(et, (L - et.width - 150, 300))
        if self.bloco is not None:
            self.bloco.desenhar(rgba, t)
        return rgba.convert("RGB")


class QuadroFinal(Quadro):
    """Cartão final: marca, chamada, miniaturas e selo."""

    def __init__(self, cta, selo, fotos):
        self.texto = True
        self.dur = max(4.6, tempo_leitura(cta, 4.6, 2.2, 0.3))
        bg = Image.new("RGB", (L, A), AMEIXA)
        d = ImageDraw.Draw(bg)
        for y in range(A):  # degradê ameixa -> vinho
            k = y / A
            d.line((0, y, L, y), fill=(int(43 + 40 * k), int(21 + 4 * k), int(36 + 22 * k)))
        brilho = Image.new("RGB", (L, A), (0, 0, 0))
        ImageDraw.Draw(brilho).ellipse((-250, 80, 850, 1180), fill=(90, 14, 52))
        bg = ImageChops.add(bg, brilho.filter(ImageFilter.GaussianBlur(160)))
        # miniaturas
        n = min(3, len(fotos))
        w_card = 290
        total = n * w_card + (n - 1) * 26
        x0 = (L - total) // 2
        bg = bg.convert("RGBA")
        for i in range(n):
            card, pad = cartao(fotos[i], w_card, 390, 34)
            bg.alpha_composite(card, (x0 + i * (w_card + 26) - pad, 400 - pad + (28 if i % 2 else 0)))
        self.base = bg.convert("RGB")
        # marca e selos
        f = fonte(40)
        marca = "LULU EXTRA FITNESS"
        dd = ImageDraw.Draw(self.base)
        w = dd.textlength(marca, font=f) + len(marca) * 6
        x = (L - w) / 2
        for ch in marca:
            dd.text((x, 250), ch, font=f, fill=(255, 190, 215))
            x += dd.textlength(ch, font=f) + 6
        dd.line(((L - 120) // 2, 320, (L + 120) // 2, 320), fill=ROSA, width=6)
        self.bloco = BlocoTexto(cta, tam_max=100, largura=860, max_linhas=4, y_centro=1010, selo=selo, atraso=0.35)
        self.site = "luluextra.com"

    def render(self, t):
        rgba = self.base.convert("RGBA")
        self.bloco.desenhar(rgba, t)
        d = ImageDraw.Draw(rgba)
        f = fonte(42, "Bold")
        a = ease_out((t - 1.4) / 0.6)
        if a > 0:
            w = d.textlength(self.site, font=f)
            d.text(((L - w) / 2, self.bloco.base + 54), self.site, font=f, fill=(255, 214, 230, int(235 * a)))
        # leve pulsar no selo é desnecessário; mantém o cartão estável pra leitura
        return rgba.convert("RGB")


# ================================================================ transições
def transicao(a, b, p, tipo):
    p = ease(p)
    if tipo == "fade":
        return Image.blend(a, b, p)
    if tipo == "esq":
        c = Image.new("RGB", (L, A))
        dx = int(L * p)
        c.paste(a, (-dx, 0))
        c.paste(b, (L - dx, 0))
        return c
    if tipo == "cima":
        c = Image.new("RGB", (L, A))
        dy = int(A * p)
        c.paste(a, (0, -dy))
        c.paste(b, (0, A - dy))
        return c
    if tipo == "zoom":  # o próximo "vem de dentro"
        z = 1.25 - 0.25 * p
        cw, ch = L / z, A / z
        bz = b.resize((L, A), Image.BILINEAR, box=((L - cw) / 2, (A - ch) / 2, (L + cw) / 2, (A + ch) / 2))
        return Image.blend(a, bz, p)
    return Image.blend(a, b, p)


# ================================================================ produtos
def carregar_historico():
    try:
        with open(HIST, encoding="utf-8") as f:
            h = json.load(f)
    except Exception:
        h = {}
    h.setdefault("ids", [])
    h.setdefault("ganchos", [])
    return h


def baixar(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def escolher_fotos(n=8):
    hist = carregar_historico()
    recentes = set(hist["ids"][-80:])
    loja = random.choice(list(CATALOGOS))
    with open(CATALOGOS[loja], encoding="utf-8") as f:
        catalogo = [p for p in json.load(f) if p.get("imagens")]
    novos = [p for p in catalogo if p["id"] not in recentes] or catalogo
    random.shuffle(novos)
    itens = []
    for p in novos:
        if len(itens) == n:
            break
        try:
            foto = baixar(random.choice(p["imagens"][:3]))
            itens.append({"foto": foto, "id": p["id"], "preco": float(p.get("preco_final") or 0), "loja": loja})
        except Exception as e:
            print(f"  foto ignorada ({p['id']}): {e}")
    if len(itens) < 4:
        raise RuntimeError("Poucas fotos disponíveis pra montar o Reel.")
    print(f"Catálogo: {loja} | {len(itens)} fotos")
    return itens, hist


# ================================================================ roteiro do vídeo
def montar_quadros(itens, briefing):
    """Roteiro: GANCHO -> fotos -> VALOR -> fotos -> (VALOR 2) -> fotos -> CTA."""
    fotos = [i["foto"] for i in itens]
    usadas = itertools.count()
    movs = ["zoom_in", "pan_esq", "zoom_out", "pan_dir"]
    random.shuffle(movs)
    contador = {"i": 0}

    def mov():
        contador["i"] += 1
        return movs[contador["i"] % 4]

    def prox():
        return fotos[next(usadas) % len(fotos)]

    def rot(item_foto):
        return next((i for i in itens if i["foto"] is item_foto), itens[0])

    def etiqueta(foto):
        it = rot(foto)
        if it["preco"] > 0:
            return etiqueta_preco("KIT" if it["loja"] == "kits" else "PEÇA", it["preco"])
        return None

    quadros = []
    # 1) gancho (primeiros 3+ segundos)
    f = prox()
    bloco = BlocoTexto(briefing["gancho"], tam_max=112, largura=880, max_linhas=4, y_centro=900, atraso=0.15)
    quadros.append(QuadroFoto([f], "cheio", "zoom_in", tempo_leitura(briefing["gancho"], 3.4, 1.4, 0.3), bloco, gancho=True))
    # 2) duas fotos rápidas (uma em duo, uma com preço)
    f1, f2 = prox(), prox()
    quadros.append(QuadroFoto([f1, f2], "duo", mov(), random.uniform(*DUR_FOTO)))
    f = prox()
    quadros.append(QuadroFoto([f], "cartao", mov(), random.uniform(*DUR_FOTO), etiqueta=etiqueta(f)))
    # 3) quadro de valor 1
    f = prox()
    q1 = briefing["quadros"][0]
    quadros.append(QuadroFoto([f], random.choice(["cheio", "cartao"]), mov(), tempo_leitura(q1),
                              BlocoTexto(q1, tam_max=84, largura=840, max_linhas=4, y_base=1470)))
    # 4) fotos de respiro
    f = prox()
    quadros.append(QuadroFoto([f], "cheio", mov(), random.uniform(*DUR_FOTO), etiqueta=etiqueta(f) if random.random() < .5 else None))
    f1, f2 = prox(), prox()
    quadros.append(QuadroFoto([f1, f2], "duo", mov(), random.uniform(*DUR_FOTO)))
    # 5) quadro de valor 2 (se houver)
    if len(briefing["quadros"]) > 1:
        f = prox()
        q2 = briefing["quadros"][1]
        quadros.append(QuadroFoto([f], random.choice(["cheio", "cartao"]), mov(), tempo_leitura(q2),
                                  BlocoTexto(q2, tam_max=84, largura=840, max_linhas=4, y_base=1470)))
    # 6) cartão final
    quadros.append(QuadroFinal(briefing["cta"], briefing["selo"], fotos[-3:] if len(fotos) >= 3 else fotos))

    # cabe nos 30 s da música? tira quadros de foto (sem texto) do meio até caber
    def total(qs):
        return sum(q.dur for q in qs) - FADE * (len(qs) - 1)
    while total(quadros) > MAX_TOTAL:
        cand = [i for i, q in enumerate(quadros[1:-1], 1) if not q.texto]
        if not cand:
            break
        quadros.pop(cand[-1])
    return quadros


def gerar_video(itens, briefing, saida):
    quadros = montar_quadros(itens, briefing)
    tipos = ["fade", "esq", "cima", "zoom"]
    trans = [random.choice(tipos) for _ in quadros[:-1]]
    inicios, t = [], 0.0
    for q in quadros:
        inicios.append(t)
        t += q.dur - FADE
    total = t + FADE
    musica = os.path.join(MUSICAS, random.choice(sorted(os.listdir(MUSICAS))))
    print(f"Música: {musica} | {len(quadros)} quadros | {total:.1f}s | transições: {trans}")

    os.makedirs(os.path.dirname(saida), exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{L}x{A}", "-r", str(FPS), "-i", "-",
           "-stream_loop", "-1", "-i", musica,
           "-af", f"afade=t=in:d=0.4,afade=t=out:st={total - 1.8:.2f}:d=1.8",
           "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", saida]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(total * FPS)
    previa_em = {int((s + min(q.dur - FADE, 3.0) * 0.85) * FPS): None for s, q in zip(inicios, quadros)}
    for fr in range(n):
        tt = fr / FPS
        i = max(k for k, s in enumerate(inicios) if s <= tt)
        im = quadros[i].render(tt - inicios[i])
        if i + 1 < len(quadros):
            t_ini_trans = inicios[i + 1]
            if tt >= t_ini_trans:
                prox = quadros[i + 1].render(tt - inicios[i + 1])
                im = transicao(im, prox, (tt - t_ini_trans) / FADE, trans[i])
        proc.stdin.write(im.tobytes())
        if fr in previa_em:
            previa_em[fr] = im.copy()
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg falhou ao montar o vídeo.")
    print(f"Vídeo pronto: {saida} ({os.path.getsize(saida) / 1e6:.1f} MB)")
    # folha de prévia (pra eu e o Lucas conferirem o visual sem baixar o vídeo)
    frames = [f for f in previa_em.values() if f is not None]
    cols = 5
    lin = math.ceil(len(frames) / cols)
    folha = Image.new("RGB", (cols * 270, lin * 480), (20, 20, 20))
    for k, f in enumerate(frames):
        folha.paste(f.resize((270, 480), Image.LANCZOS), ((k % cols) * 270, (k // cols) * 480))
    folha.save(PREVIA, quality=88)
    return total


# ================================================================ publicação
def checar(resp, ctx):
    if resp.status_code >= 300:
        raise RuntimeError(f"Erro em {ctx}: {resp.status_code} — {resp.text}")
    return resp.json()


def hospedar(arquivos):
    """Publica os arquivos numa branch temporária 'reel-tmp' (sobrescrita a cada vez,
    não incha o histórico). A API do Instagram precisa de uma URL pública do vídeo."""
    import shutil
    import tempfile
    repo, gh = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    tmp = tempfile.mkdtemp()
    for a in arquivos:
        shutil.copy(a, os.path.join(tmp, os.path.basename(a)))

    def git(*a):
        subprocess.run(["git", *a], cwd=tmp, check=True, capture_output=True)
    git("init", "-q", "-b", "reel-tmp")
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "github-actions[bot]@users.noreply.github.com")
    git("add", "-A")
    git("commit", "-q", "-m", "reel temporario")
    git("push", "-f", f"https://x-access-token:{gh}@github.com/{repo}.git", "reel-tmp:reel-tmp")
    base = f"https://raw.githubusercontent.com/{repo}/reel-tmp"
    url = f"{base}/{os.path.basename(arquivos[0])}"
    for _ in range(10):
        h = requests.head(url, timeout=30, allow_redirects=True)
        print("  URL:", h.status_code, h.headers.get("content-type"), h.headers.get("content-length"))
        if h.status_code == 200:
            break
        time.sleep(5)
    return url


def publicar_reel(url, legenda):
    r = requests.post(f"{GRAPH}/{IG_ID}/media", data={
        "media_type": "REELS", "video_url": url, "caption": legenda,
        "share_to_feed": "true", "access_token": TOKEN}, timeout=60)
    cid = checar(r, "criar container do Reel")["id"]
    for _ in range(60):
        time.sleep(6)
        s = checar(requests.get(f"{GRAPH}/{cid}", params={
            "fields": "status_code,status", "access_token": TOKEN}, timeout=30), "status do Reel")
        print("  status:", s.get("status_code"), s.get("status", ""))
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"Meta recusou o vídeo: {s}")
    else:
        raise RuntimeError("Reel não ficou pronto a tempo.")
    for tentativa in range(1, 9):
        r = requests.post(f"{GRAPH}/{IG_ID}/media_publish", data={
            "creation_id": cid, "access_token": TOKEN}, timeout=60)
        if r.status_code < 300:
            return r.json()["id"]
        if "2207027" in r.text or '"code":9007' in r.text:
            print(f"  mídia ainda não pronta (tentativa {tentativa}/8), esperando 8s...")
            time.sleep(8)
            continue
        break
    return checar(r, "publicar o Reel")["id"]


def main():
    so_gerar = "--so-gerar" in sys.argv
    if not so_gerar and (not TOKEN or not IG_ID):
        print("ERRO: faltam INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID.")
        sys.exit(1)
    hist = carregar_historico()
    hoje = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)).date().isoformat()  # data em Salvador
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and hist.get("ultimo_post") == hoje:
        print(f"Reel de hoje ({hoje}) já foi publicado — nada a fazer.")
        return
    itens, hist = escolher_fotos()
    briefing = reel_lab.gerar_briefing(hist["ganchos"])
    print("Briefing:", json.dumps(briefing, ensure_ascii=False))
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    with open(f"{PASTA_SAIDA}/briefing.json", "w", encoding="utf-8") as f:
        json.dump(briefing, f, ensure_ascii=False, indent=1)
    gerar_video(itens, briefing, SAIDA)
    if os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"):
        url = hospedar([SAIDA, PREVIA, f"{PASTA_SAIDA}/briefing.json"])
        print("PRÉVIA DO VÍDEO:", url)
    elif so_gerar:
        return
    if so_gerar:
        return
    # varia: ~40% dos Reels sem nenhuma hashtag; nos demais, de 1 a 3
    qtd = random.choice([0, 0, 1, 2, 3])
    tags = random.sample(briefing["hashtags"], min(qtd, len(briefing["hashtags"])))
    legenda = briefing["legenda"].strip() + (("\n\n" + " ".join(tags)) if tags else "")
    print("Publicando Reel...")
    media_id = publicar_reel(url, legenda)
    print(f"Reel publicado: {media_id}")
    hist["ids"] = (hist["ids"] + [i["id"] for i in itens])[-300:]
    hist["ganchos"] = (hist["ganchos"] + [briefing["gancho"]])[-60:]
    hist["ultimo_post"] = hoje
    with open(HIST, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    ERRO = "instagram/ultimo_erro_reel.txt"
    try:
        main()
        if os.path.exists(ERRO):
            os.remove(ERRO)
    except BaseException:
        import traceback
        with open(ERRO, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()) + "\n" + traceback.format_exc()[-3000:])
        raise
