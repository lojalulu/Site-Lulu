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
import visao  # noqa: E402  (rostos e bordas: etiqueta nunca em cima do rosto)
from conteudo import rotulo_kit  # noqa: E402

L, A = 1080, 1920
FPS = 30
FADE = 0.45            # duração das transições
DUR_FOTO = (2.0, 2.6)  # quadros só de foto
DUR_PRECO = 3.8        # quadro com etiqueta de preço: dá tempo de ler (nunca menos que isso)
ESC_ETIQUETA = 1.15    # etiqueta de preço (12/11: um pouco menor; cai p/ 1.0 e 0.85 se não achar canto livre)
ESC_ETIQUETA_MIN = (1.0, 0.85)
MARGEM = 36            # distância da etiqueta até a borda da tela
# zona segura do Reel: o Instagram cobre o topo (~200px), a coluna de botões à direita
# (x > 930, y 1000-1750) e a legenda embaixo (y > 1640)
SEGURO_TOPO, SEGURO_BASE, BOTOES_X, BOTOES_Y = 220, 1600, 920, 980
MAX_TOTAL = 29.5       # as músicas têm 30s
ROSA = (255, 61, 128)
DOURADO = (255, 177, 0)
AMEIXA = (43, 21, 36)
BRANCO = (255, 255, 255)

CATALOGOS = {"kits": "produtos.json"}  # desde 03/11/2026: Reels SÓ dos kits de luluextra.com
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
                 selo=None, atraso=0.25, entrada=0.5, passo=0.20):
        self.frase = frase
        self.entrada, self.passo = entrada, passo
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
            a = ease_out((t - self.atraso - self.passo * i) / self.entrada)
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


def pilula(texto, largura_max=900):
    """Frase de retenção em pílula no topo do quadro (1 ou 2 linhas)."""
    f = fonte(46)
    d0 = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    linhas = [ln for ln in (" ".join(w for w, _ in l) for l in quebrar(d0, [(p, False) for p in texto.split()], f, largura_max - 100))]
    w = int(max(d0.textlength(ln, font=f) for ln in linhas)) + 100
    alt = 96 + 58 * (len(linhas) - 1)
    im = Image.new("RGBA", (w, alt), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, alt - 1), radius=48, fill=AMEIXA + (235,), outline=ROSA + (255,), width=5)
    for k, ln in enumerate(linhas):
        d.text(((w - d0.textlength(ln, font=f)) / 2, 18 + 58 * k), ln, font=f, fill=BRANCO + (255,))
    return im


def tempo_pilula(texto):
    """Quanto tempo a pílula fica 100% visível (12/11: o Lucas achou rápido demais).
    Frase curta (3-4 palavras) ~2,2s (antes ~1,3s); frase de compartilhar (8-10 palavras) ~3,6s."""
    return min(4.0, max(2.2, 1.2 + 0.27 * palavras(texto)))


_ROSTOS = {}


def rostos_da_foto(foto):
    """Rostos detectados na foto original (cache por foto)."""
    k = id(foto)
    if k not in _ROSTOS:
        try:
            _ROSTOS[k] = visao.rostos(foto)
        except Exception as e:  # noqa: BLE001
            print(f"  detecção de rosto falhou ({type(e).__name__}); usando zona provável da cabeça")
            _ROSTOS[k] = None
    return _ROSTOS[k]


def mapa_cobrir(foto, w, h):
    """Como cobrir() coloca a foto num retângulo w x h: (escala, corte_x, corte_y)."""
    esc = max(w / foto.width, h / foto.height)
    return esc, (int(foto.width * esc) + 1 - w) // 2, (int(foto.height * esc) + 1 - h) // 2


class QuadroFoto(Quadro):
    """Foto(s) com layout, movimento de câmera, texto opcional e etiqueta de preço."""

    def __init__(self, fotos, layout, movimento, dur, bloco=None, etiqueta=None, escuro=0.0, gancho=False):
        if etiqueta is not None:
            dur = max(dur, DUR_PRECO)
        self.dur, self.movimento, self.bloco, self.etiqueta = dur, movimento, bloco, etiqueta
        self.escuro, self.gancho = escuro, gancho
        self.chamada = None  # frase de retenção no topo (pílula)
        self.chamada_vis = 2.6  # segundos 100% visível
        self.pos_etiqueta = None
        self.texto = bloco is not None
        self.regioes = []  # (foto, (x0, y0, x1, y1), (escala, corte_x, corte_y)) — onde cada foto está no quadro
        if layout == "tela" and fotos[0].width / fotos[0].height > 0.86:
            layout = "cheio"  # foto larga/quadrada: tela cheia cortaria demais a roupa
        if layout == "tela":  # tela cheia de verdade (gancho): mais impacto no 1º segundo
            fundo = cobrir(fotos[0], L, A)
            self.regioes.append((fotos[0], (0, 0, L, A), mapa_cobrir(fotos[0], L, A)))
        elif layout == "cheio":
            fundo = fundo_borrado(fotos[0], 0.35)
            w, h = fotos[0].size
            esc = min(L / w, 1560 / h)
            fg = fotos[0].resize((int(w * esc), int(h * esc)), Image.LANCZOS)
            px, py = (L - fg.width) // 2, (A - fg.height) // 2 - 40
            fundo.paste(fg, (px, py))
            self.regioes.append((fotos[0], (px, py, px + fg.width, py + fg.height), (esc, -px, -py)))
        elif layout == "cartao":
            fundo = fundo_borrado(fotos[0], 0.55)
            card, pad = cartao(fotos[0], 940, 1240)
            fundo = fundo.convert("RGBA")
            cx, cy = (L - card.width) // 2, 330 - pad + 20
            fundo.alpha_composite(card, (cx, cy))
            fundo = fundo.convert("RGB")
            ex, ey = mapa_cobrir(fotos[0], 940, 1240)[1:]
            esc = mapa_cobrir(fotos[0], 940, 1240)[0]
            self.regioes.append((fotos[0], (cx + pad, cy + pad, cx + pad + 940, cy + pad + 1240), (esc, ex - cx - pad, ey - cy - pad)))
        else:  # duo
            fundo = fundo_borrado(fotos[0], 0.55).convert("RGBA")
            for i, ft in enumerate(fotos[:2]):
                card, pad = cartao(ft, 940, 700, 42)
                cx, cy = (L - card.width) // 2, 250 + i * 730 - pad
                fundo.alpha_composite(card, (cx, cy))
                esc, ex, ey = mapa_cobrir(ft, 940, 700)
                self.regioes.append((ft, (cx + pad, cy + pad, cx + pad + 940, cy + pad + 700), (esc, ex - cx - pad, ey - cy - pad)))
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

    def _caixa_camera(self, t):
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
        return (L - cw) * fx, (A - ch) / 2, z

    def _camera(self, t):
        x, y, z = self._caixa_camera(t)
        return self.base.resize((L, A), Image.BILINEAR, box=(x, y, x + L / z, y + A / z))

    def zonas_rosto(self):
        """Zonas (coordenadas da TELA, já com o movimento de câmera) onde há rosto."""
        zonas = []
        for foto, (rx0, ry0, rx1, ry1), (esc, ox, oy) in self.regioes:
            caixas = rostos_da_foto(foto)
            if caixas:
                for fx0, fy0, fx1, fy1 in caixas:
                    fw, fh = fx1 - fx0, fy1 - fy0
                    # rosto + cabelo + pescoço, com folga
                    b = (fx0 - fw * 0.35, fy0 - fh * 0.45, fx1 + fw * 0.35, fy1 + fh * 0.7)
                    zx0, zy0 = max(rx0, b[0] * esc - ox), max(ry0, b[1] * esc - oy)
                    zx1, zy1 = min(rx1, b[2] * esc - ox), min(ry1, b[3] * esc - oy)
                    if zx1 > zx0 and zy1 > zy0:
                        zonas.append((zx0, zy0, zx1, zy1))
            else:  # sem detector ou nenhum rosto achado: evita o alto-centro da foto (cabeça provável)
                rw, rh = rx1 - rx0, ry1 - ry0
                zonas.append((rx0 + rw * 0.2, ry0, rx1 - rw * 0.2, ry0 + rh * 0.36))
        tela = []
        for zx0, zy0, zx1, zy1 in zonas:  # passa pelo movimento de câmera (início e fim) e junta
            pts = []
            for t in (0.0, self.dur):
                cx, cy, z = self._caixa_camera(t)
                pts += [((zx0 - cx) * z, (zy0 - cy) * z), ((zx1 - cx) * z, (zy1 - cy) * z)]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            tela.append((min(xs) - 24, min(ys) - 24, max(xs) + 24, max(ys) + 24))
        return tela

    def _posicionar_etiqueta(self):
        """Canto livre para a etiqueta: nunca no rosto, nem no texto, nem nos botões do Instagram."""
        proibidas = self.zonas_rosto()
        if self.bloco is not None:
            proibidas.append((0, self.bloco.topo - 30, L, self.bloco.base + 30))
        if self.chamada is not None:
            proibidas.append(((L - self.chamada.width) / 2 - 10, 180, (L + self.chamada.width) / 2 + 10, 215 + self.chamada.height + 20))
        proibidas.append((BOTOES_X, BOTOES_Y, L, SEGURO_BASE + 200))  # botões do Instagram
        melhor = None
        for esc in (ESC_ETIQUETA,) + ESC_ETIQUETA_MIN:
            w, h = int(self.etiqueta.width * esc * 1.08), int(self.etiqueta.height * esc * 1.08)  # 1.08 = "pop"
            cands = [(L - w - MARGEM, SEGURO_TOPO + 10), (MARGEM, SEGURO_TOPO + 10),
                     (L - w - MARGEM, 640), (MARGEM, 640),
                     (MARGEM, 1180), (min(L - w - MARGEM, BOTOES_X - w - 10), 1180),
                     (MARGEM, SEGURO_BASE - h)]
            pos, sob = visao.lugar_livre((w, h), cands, proibidas)
            if sob == 0:
                return pos, esc
            if melhor is None or sob < melhor[2]:
                melhor = (pos, esc, sob)
        return melhor[0], melhor[1]

    def render(self, t):
        im = self._camera(t)
        if self.bloco is None and self.etiqueta is None and self.chamada is None:
            return im
        rgba = im.convert("RGBA")
        if self.chamada is not None:
            a = ease_out((t - 0.30) / 0.35) * (1 - ease_out((t - 0.65 - self.chamada_vis) / 0.30))
            if a > 0:
                pil = self.chamada.copy()
                pil.putalpha(pil.getchannel("A").point(lambda v: int(v * a)))
                rgba.alpha_composite(pil, ((L - pil.width) // 2, 215 + int((1 - a) * -30)))
        if self.etiqueta is not None:
            if self.pos_etiqueta is None:
                self.pos_etiqueta = self._posicionar_etiqueta()
            (ex, ey), esc_base = self.pos_etiqueta
            a = ease_out((t - 0.25) / 0.40)
            if a > 0:
                k = 0.55 + 0.45 * a + 0.08 * math.sin(a * math.pi)  # "pop"
                esc = esc_base * k
                et = self.etiqueta
                et = et.resize((max(1, int(et.width * esc)), max(1, int(et.height * esc))), Image.BILINEAR)
                if a < 1:
                    et.putalpha(et.getchannel("A").point(lambda v: int(v * a)))
                # cresce a partir do centro da posição final (não "pula" de lugar)
                cx = ex + self.etiqueta.width * esc_base / 2
                cy = ey + self.etiqueta.height * esc_base / 2
                rgba.alpha_composite(et, (int(cx - et.width / 2), int(cy - et.height / 2)))
        if self.bloco is not None:
            self.bloco.desenhar(rgba, t)
        return rgba.convert("RGB")


class QuadroFinal(Quadro):
    """Cartão final: marca, chamada, miniaturas e selo."""

    def __init__(self, cta, selo, fotos):
        self.texto = True
        self.frase = cta
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
    h.setdefault("angulos", [])
    h.setdefault("formatos", [])
    h.setdefault("musicas", [])
    return h


def baixar(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return visao.aparar_bordas(Image.open(io.BytesIO(r.content)).convert("RGB"))  # tira faixa preta/branca colada


DIAS_NOVIDADE = 14


def lancamentos_recentes(dias=DIAS_NOVIDADE):
    """{id: data} dos produtos que entraram no catálogo nos últimos `dias` (lancamentos_datas.json do robô)."""
    try:
        with open("lancamentos_datas.json", encoding="utf-8") as f:
            datas = json.load(f)
    except Exception:  # noqa: BLE001
        return {}
    hoje = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)).date()
    out = {}
    for pid, d in datas.items():
        try:
            if (hoje - datetime.date.fromisoformat(d)).days <= dias:
                out[str(pid)] = d
        except ValueError:
            pass
    return out


def ordem_rodizio(catalogo, ids_usados, lancs, max_lanc=3, usos_lanc=2):
    """Ordem das fotos do Reel (12/11/2026):
    1) NOVIDADES primeiro: até `max_lanc` lançamentos recentes que ainda apareceram < `usos_lanc` vezes nos Reels;
    2) depois rodízio de verdade: primeiro quem NUNCA apareceu, depois quem apareceu há mais tempo
       (empate sorteado) — o catálogo inteiro passa antes de repetir."""
    ultimo = {}
    for k, pid in enumerate(ids_usados):
        ultimo[pid] = k
    usos = {}
    for pid in ids_usados[-60:]:
        usos[pid] = usos.get(pid, 0) + 1
    novidades = [p for p in catalogo if p["id"] in lancs and usos.get(p["id"], 0) < usos_lanc]
    novidades.sort(key=lambda p: (lancs[p["id"]], random.random()), reverse=True)
    novidades = novidades[:max_lanc]
    ja = {p["id"] for p in novidades}
    resto = [p for p in catalogo if p["id"] not in ja]
    resto.sort(key=lambda p: (ultimo.get(p["id"], -1), random.random()))
    return novidades + resto, len(novidades)


def escolher_fotos(n=8):
    hist = carregar_historico()
    loja = random.choice(list(CATALOGOS))
    with open(CATALOGOS[loja], encoding="utf-8") as f:
        catalogo = [p for p in json.load(f) if p.get("imagens")]
    lancs = lancamentos_recentes()
    novos, n_lanc = ordem_rodizio(catalogo, [str(i) for i in hist["ids"]], lancs)
    hist["_novidades_no_video"] = n_lanc
    itens = []
    for p in novos:
        if len(itens) == n:
            break
        try:
            # gira também QUAL foto do produto aparece (não sempre a 1ª)
            fotos_p = p["imagens"][:4]
            vezes = sum(1 for i in hist["ids"] if str(i) == p["id"])
            foto = baixar(fotos_p[vezes % len(fotos_p)])
            itens.append({"foto": foto, "id": p["id"], "preco": float(p.get("preco_final") or 0), "loja": loja,
                          "nome": p.get("nome", ""), "novo": p["id"] in lancs})
        except Exception as e:
            print(f"  foto ignorada ({p['id']}): {e}")
    if len(itens) < 4:
        raise RuntimeError("Poucas fotos disponíveis pra montar o Reel.")
    print(f"Catálogo: {loja} | {len(itens)} fotos | novidades no vídeo: {n_lanc} | detector de rosto: {'ok' if visao.opencv_ok() else 'indisponível'}")
    return itens, hist


def texto_preco(itens):
    """Preço real de um kit do vídeo, no formato da regra: '5 Conjuntos por R$ 199,90'."""
    com_preco = [i for i in itens if i["preco"] > 0 and i["loja"] == "kits"]
    if not com_preco:
        return None
    it = min(com_preco, key=lambda i: i["preco"])  # o mais em conta chama mais atenção
    return f"{rotulo_kit(it['nome'])} por R$ {it['preco']:.2f}".replace(".", ",")


CTAS_DIRETO = [
    "Comenta QUERO e te mando o catálogo no Direct",
    "Comenta QUERO que o catálogo chega no seu Direct",
    "Comente QUERO e receba os kits no Direct",
    "Escreve QUERO aqui embaixo e confere seu Direct",
]


def funil_direct_ligado():
    """Interruptor do funil 'comenta QUERO e recebe no Direct'.
    Só liga depois que o webhook do Instagram estiver funcionando (arquivo instagram/funil_direct.txt)."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "funil_direct.txt"), encoding="utf-8") as f:
            return f.read().strip().lower() == "ligado"
    except OSError:
        return False


def aplicar_funil_direct(briefing, indice=0):
    """Chamada final pede o comentário QUERO (a automação manda o link no Direct)."""
    b = dict(briefing)
    b["cta"] = CTAS_DIRETO[indice % len(CTAS_DIRETO)]
    b["selo"] = "COMENTA QUERO"
    # uma chamada só: tira frases que mandam pro "link da bio" para não competir com o comentário
    frases = re.split(r"(?<=[.!?])\s+", b["legenda"].strip())
    leg = " ".join(f for f in frases if not re.search(r"\bbio\b", f, re.I)).strip() or b["legenda"].strip()
    b["legenda"] = leg + "\n\nComenta QUERO aqui embaixo que eu te mando o catálogo completo no Direct 💗"
    return b


def aplicar_funil_franquia(briefing):
    """Reel de franquia: pede o comentário FRANQUIA (a automação manda o link da franquia no Direct)."""
    b = dict(briefing)
    b["cta"] = "Comenta FRANQUIA aqui embaixo"
    b["selo"] = "COMENTA FRANQUIA"
    frases = re.split(r"(?<=[.!?])\s+", b["legenda"].strip())
    leg = " ".join(f for f in frases if not re.search(r"\bbio\b|comenta", f, re.I)).strip() or b["legenda"].strip()
    b["legenda"] = leg + "\n\nComenta FRANQUIA aqui embaixo que eu te mando o link da Franquia Online Lulu no Direct 💗"
    return b


def aplicar_preco(briefing, preco_txt):
    """Troca o marcador {PRECO}. Sem preço disponível, a frase com o marcador sai do vídeo."""
    b = dict(briefing)
    def troca(t):
        return t.replace("{PRECO}", preco_txt) if preco_txt else t
    if preco_txt:
        b["gancho"], b["cta"], b["legenda"] = troca(b["gancho"]), troca(b["cta"]), troca(b["legenda"])
        b["quadros"] = [troca(q) for q in b["quadros"]]
    else:
        b["quadros"] = [q for q in b["quadros"] if "{PRECO}" not in q] or ["Kits prontos de 5 peças com cores variadas."]
        b["gancho"] = b["gancho"].replace("{PRECO}.", "").replace("{PRECO}", "Kits de 5 peças").strip() or "Kits *prontos* de 5 peças"
        b["legenda"] = b["legenda"].replace("{PRECO}", "Kits prontos de 5 peças")
        b["cta"] = b["cta"].replace("{PRECO}", "")
    return b


CHANCE_NARRAR = 0.75


def inserir_compartilhar(legenda, frase):
    """Põe o pedido de envio ANTES da chamada final (QUERO/FRANQUIA), para a chamada continuar por último."""
    partes = legenda.rstrip().split("\n\n")
    if len(partes) > 1 and re.search(r"comenta|link da bio|luluextra", partes[-1], re.I):
        return "\n\n".join(partes[:-1] + [frase, partes[-1]])
    return legenda.rstrip() + "\n\n" + frase


FORMATOS = ["classico", "vitrine", "pergunta", "rapido"]


def escolher_formato(recentes):
    livres = [f for f in FORMATOS if f not in list(recentes)[-2:]]
    return random.choice(livres or FORMATOS)


def escolher_musica(recentes):
    todas = sorted(m for m in os.listdir(MUSICAS) if m.lower().endswith(".mp3"))
    livres = [m for m in todas if m not in list(recentes)[-3:]]
    return random.choice(livres or todas)


# ================================================================ roteiro do vídeo
def bloco_gancho(frase, tam_max=112, largura=880, y_centro=900):
    """Gancho JÁ LEGÍVEL no 1º frame (retenção do 1º segundo): as linhas entram em ~0,3s,
    a primeira já aparece no quadro zero — ninguém vê tela 'vazia'."""
    return BlocoTexto(frase, tam_max=tam_max, largura=largura, max_linhas=4, y_centro=y_centro,
                      atraso=-0.18, entrada=0.30, passo=0.07)


def montar_quadros(itens, briefing, formato="classico", modo="venda"):
    """Roteiros (rodízio, sem repetir os 2 últimos):
    classico: GANCHO -> fotos -> VALOR -> fotos -> VALOR 2 -> CTA
    vitrine:  GANCHO -> 4 kits seguidos, cada um com etiqueta de preço -> VALOR -> CTA
    pergunta: PERGUNTA (tela escura, longa) -> RESPOSTA grande -> fotos -> VALOR 2 -> CTA
    rapido:   GANCHO -> 6 fotos rápidas alternando layouts -> VALOR -> CTA"""
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
        # REGRA: preço só do kit (luluextra.com), no formato "5 Conjuntos por R$ ..."
        # e só no Reel de VENDA (conteúdo/franquia não mostram preço de kit — 12/11/2026)
        if modo == "venda" and it["preco"] > 0 and it["loja"] == "kits":
            return etiqueta_preco(f"{rotulo_kit(it['nome'])} por", it["preco"])
        return None

    quadros = []
    if formato == "vitrine":
        f = prox()
        quadros.append(QuadroFoto([f], "tela", "zoom_in", tempo_leitura(briefing["gancho"], 3.4, 1.4, 0.3),
                                  bloco_gancho(briefing["gancho"]), gancho=True))
        for k in range(4):
            f = prox()
            quadros.append(QuadroFoto([f], ["cartao", "cheio"][k % 2], mov(), 2.3, etiqueta=etiqueta(f) if k in (0, 2) else None))
        for q in briefing["quadros"][:2]:
            f = prox()
            quadros.append(QuadroFoto([f], "cartao", mov(), tempo_leitura(q), BlocoTexto(q, tam_max=84, largura=840, max_linhas=4, y_base=1470)))
        quadros.append(QuadroFinal(briefing["cta"], briefing["selo"], fotos[-3:] if len(fotos) >= 3 else fotos))
    elif formato == "pergunta":
        f = prox()
        quadros.append(QuadroFoto([f], "tela", "zoom_out", tempo_leitura(briefing["gancho"], 3.8, 1.6, 0.3),
                                  bloco_gancho(briefing["gancho"], tam_max=118, largura=900, y_centro=920),
                                  escuro=0.40, gancho=True))
        q1 = briefing["quadros"][0]
        f = prox()
        quadros.append(QuadroFoto([f], "cartao", "zoom_in", tempo_leitura(q1, 3.4, 1.4, 0.34),
                                  BlocoTexto(q1, tam_max=96, largura=860, max_linhas=5, y_centro=1350, atraso=0.2), etiqueta=etiqueta(f)))
        f1, f2 = prox(), prox()
        quadros.append(QuadroFoto([f1, f2], "duo", mov(), random.uniform(*DUR_FOTO)))
        f = prox()
        quadros.append(QuadroFoto([f], "cheio", mov(), random.uniform(*DUR_FOTO), etiqueta=etiqueta(f)))
        if len(briefing["quadros"]) > 1:
            q2 = briefing["quadros"][1]
            f = prox()
            quadros.append(QuadroFoto([f], "cartao", mov(), tempo_leitura(q2), BlocoTexto(q2, tam_max=84, largura=840, max_linhas=4, y_base=1470)))
        quadros.append(QuadroFinal(briefing["cta"], briefing["selo"], fotos[-3:] if len(fotos) >= 3 else fotos))
    elif formato == "rapido":
        f = prox()
        quadros.append(QuadroFoto([f], "tela", "zoom_in", tempo_leitura(briefing["gancho"], 3.2, 1.3, 0.3),
                                  bloco_gancho(briefing["gancho"]), gancho=True))
        lays = ["cheio", "cartao", "duo", "cheio", "cartao", "duo"]
        for k, lay in enumerate(lays):
            fs = [prox(), prox()] if lay == "duo" else [prox()]
            quadros.append(QuadroFoto(fs, lay, mov(), 1.35, etiqueta=etiqueta(fs[0]) if k in (1, 4) else None))
        q = " ".join(briefing["quadros"][:1])
        f = prox()
        quadros.append(QuadroFoto([f], "cheio", mov(), tempo_leitura(q), BlocoTexto(q, tam_max=84, largura=840, max_linhas=4, y_base=1470)))
        quadros.append(QuadroFinal(briefing["cta"], briefing["selo"], fotos[-3:] if len(fotos) >= 3 else fotos))
    if quadros:
        return ajustar_total(quadros)
    # ---- classico
    # 1) gancho (primeiros 3+ segundos)
    f = prox()
    bloco = bloco_gancho(briefing["gancho"])
    quadros.append(QuadroFoto([f], "tela", "zoom_in", tempo_leitura(briefing["gancho"], 3.4, 1.4, 0.3), bloco, gancho=True))
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

    return ajustar_total(quadros)


def duracao_total(qs):
    return sum(q.dur for q in qs) - FADE * (len(qs) - 1)


def ajustar_total(quadros):
    """Cabe nos ~30 s da música? Tira quadros só de foto (sem texto, preço ou pílula) do meio até caber."""
    while duracao_total(quadros) > MAX_TOTAL:
        cand = [i for i, q in enumerate(quadros[1:-1], 1)
                if not q.texto and getattr(q, "etiqueta", None) is None and getattr(q, "chamada", None) is None]
        if not cand:
            break
        quadros.pop(cand[-1])
    return quadros


FRASES_MEIO = ["AGORA VEM O MELHOR", "ATENÇÃO NESSA PARTE", "O DETALHE QUE IMPORTA"]
TEASERS = ["FICA ATÉ O FINAL", "ASSISTE ATÉ O FIM"]

# 12/11/2026 (pedido do Lucas): incentivar o ENVIO do vídeo (o "envio por Direct" é um dos sinais
# que mais aumentam o alcance). Frases fixas e revisadas — a IA não escreve isso.
COMPARTILHAR = {
    "venda": [("MANDA ESSE VÍDEO PRA QUEM VAI REVENDER COM VOCÊ", "Manda esse vídeo pra quem vai revender com você 💌"),
              ("ENVIA PRA AMIGA QUE QUER COMEÇAR A REVENDER", "Envia pra aquela amiga que vive dizendo que quer começar a revender 💌"),
              ("MANDA PRA SUA SÓCIA DE REVENDA", "Manda pra sua sócia de revenda ver também 💌"),
              ("MANDA PRA AMIGA QUE VIVE FALANDO EM REVENDER", "Conhece alguém que quer revender moda fitness? Manda esse vídeo pra ela 💌")],
    "conteudo": [("MANDA ESSA DICA PRA UMA AMIGA LOJISTA", "Manda essa dica pra uma amiga lojista 💌"),
                 ("ENVIA PRA QUEM VENDE MODA FITNESS COM VOCÊ", "Envia pra quem vende moda fitness com você 💌"),
                 ("MANDA ESSE VÍDEO PRA QUEM VAI REVENDER COM VOCÊ", "Manda esse vídeo pra quem vai revender com você 💌")],
    "franquia": [("MANDA PRA AMIGA QUE SONHA COM LOJA ONLINE", "Tem uma amiga que sonha com loja online? Manda esse vídeo pra ela 💌"),
                 ("ENVIA PRA QUEM QUER VENDER PELA INTERNET", "Envia pra quem quer começar a vender pela internet 💌")],
}
CHANCE_COMPARTILHAR = {"venda": 0.55, "conteudo": 0.75, "franquia": 0.5}


def escolher_compartilhar(modo, indice):
    """Devolve (frase da pílula, frase da legenda) ou None. Gira as frases sem repetir seguidas."""
    if random.random() >= CHANCE_COMPARTILHAR.get(modo, 0.5):
        return None
    opcoes = COMPARTILHAR.get(modo) or COMPARTILHAR["venda"]
    return opcoes[indice % len(opcoes)]


def _dar_tempo(q, texto):
    """Pílula com tempo de leitura: o quadro dura o suficiente pra ela entrar, ficar e sair antes da transição."""
    q.chamada = pilula(texto)
    q.chamada_vis = tempo_pilula(texto)
    q.dur = max(q.dur, 0.65 + q.chamada_vis + 0.30 + FADE + 0.1)


def adicionar_retencao(quadros, compartilhar=None):
    """Pílulas: teaser logo no começo, uma antes do 1º quadro de valor e (às vezes) o pedido de envio
    no último quadro de foto antes da chamada final."""
    fotos = [q for q in quadros if isinstance(q, QuadroFoto)]
    if len(quadros) >= 5 and isinstance(quadros[1], QuadroFoto) and quadros[1].bloco is None:
        _dar_tempo(quadros[1], random.choice(TEASERS))
    valor = next((q for q in fotos[1:] if q.bloco is not None and not q.gancho), None)
    if valor is not None and valor.chamada is None:
        _dar_tempo(valor, random.choice(FRASES_MEIO))
    if compartilhar:
        alvo = next((q for q in reversed(fotos[1:]) if q.chamada is None and q is not quadros[1]), None)
        if alvo is not None:
            _dar_tempo(alvo, compartilhar[0])
    ajustar_total(quadros)


def preparar_narracao(quadros):
    """Gera a voz de cada quadro com texto e estica o quadro até caber a fala. Devolve {indice: (arquivo, dur)}."""
    import voz
    falas = {}
    for i, q in enumerate(quadros):
        frase = getattr(getattr(q, "bloco", None), "frase", None) or getattr(q, "frase", None)
        if not frase:
            continue
        r = voz.gerar_voz(frase, f"{PASTA_SAIDA}/voz_{i}.mp3")
        if r is None:
            return {}  # sem voz em um quadro = Reel inteiro sem narração (coerência)
        falas[i] = r
        q.dur = max(q.dur, r[1] + 0.95)  # entrada do texto + fala + respiro
    return falas


def gerar_video(itens, briefing, saida, formato="classico", musica_nome=None, narrar=False, compartilhar=None, modo="venda"):
    quadros = montar_quadros(itens, briefing, formato, modo)
    adicionar_retencao(quadros, compartilhar)
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    falas = {}
    if narrar:
        try:
            falas = preparar_narracao(quadros)
        except Exception as e:  # noqa: BLE001
            print(f"Narração indisponível ({type(e).__name__}): sai sem voz")
            falas = {}
    # loop: o vídeo termina voltando ao 1º quadro, então o replay emenda sem corte
    import copy
    volta = copy.copy(quadros[0])
    volta.dur = FADE + 0.35
    quadros.append(volta)
    tipos = ["fade", "esq", "cima", "zoom"]
    trans = [random.choice(tipos) for _ in quadros[:-2]] + ["fade", "fade"]
    inicios, t = [], 0.0
    for q in quadros:
        inicios.append(t)
        t += q.dur - FADE
    total = t + FADE
    musica = os.path.join(MUSICAS, musica_nome or random.choice(sorted(os.listdir(MUSICAS))))
    print(f"Formato: {formato} | Música: {musica} | {len(quadros)} quadros | {total:.1f}s | narrado: {bool(falas)} | transições: {trans}")

    os.makedirs(os.path.dirname(saida), exist_ok=True)
    entradas = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{L}x{A}", "-r", str(FPS), "-i", "-",
                "-stream_loop", "-1", "-i", musica]
    if falas:
        ordem = sorted(falas)
        for i in ordem:
            entradas += ["-i", falas[i][0]]
        f = [f"[1:a]volume=0.28,afade=t=in:d=0.3[m]"]
        rot = ["[m]"]
        for k, i in enumerate(ordem):
            ms = int((inicios[i] + 0.35) * 1000)
            f.append(f"[{k + 2}:a]adelay={ms}|{ms},volume=1.6[v{k}]")
            rot.append(f"[v{k}]")
        f.append("".join(rot) + f"amix=inputs={len(rot)}:normalize=0:duration=first,afade=t=out:st={total - 0.8:.2f}:d=0.8[a]")
        audio = ["-filter_complex", ";".join(f), "-map", "0:v", "-map", "[a]"]
    else:
        audio = ["-af", f"afade=t=in:d=0.4,afade=t=out:st={total - 1.0:.2f}:d=1.0"]
    cmd = ["ffmpeg", "-v", "error", "-y", *entradas, *audio,
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


def publicar_reel(url, legenda, capa_ms=1200):
    # thumb_offset: a capa do Reel (grade do perfil e feed) é o quadro do GANCHO já legível
    r = requests.post(f"{GRAPH}/{IG_ID}/media", data={
        "media_type": "REELS", "video_url": url, "caption": legenda, "thumb_offset": str(int(capa_ms)),
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
    _agora = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)  # hora de Salvador
    automatico = os.environ.get("GITHUB_EVENT_NAME") == "schedule" or os.environ.get("AUTO") == "true"
    # DOIS REELS POR DIA: "meio" (11h-16h59, conteúdo ou franquia) e "noite" (17h-22h59, venda com QUERO).
    slot = (os.environ.get("SLOT") or "").strip().lower()
    if slot not in ("meio", "noite"):
        slot = "meio" if _agora.hour < 17 else "noite"
    faixa = (11, 16) if slot == "meio" else (17, 22)
    if automatico and os.environ.get("CRON_TESTE") != "1" and not (faixa[0] <= _agora.hour <= faixa[1]):
        print(f"Fora da janela do slot '{slot}' (Salvador {_agora:%H:%M}) — NÃO publica.")
        return
    hoje = _agora.date().isoformat()  # data em Salvador
    chave_trava = "ultimo_post_meio" if slot == "meio" else "ultimo_post"
    if os.environ.get("CRON_TESTE") != "1" and automatico and hist.get(chave_trava) == hoje:
        print(f"Reel '{slot}' de hoje ({hoje}) já foi publicado — nada a fazer.")
        return
    modo = "venda"
    if slot == "meio":
        # a cada 5 Reels do meio do dia, 1 é de franquia (= 1 em cada 10 Reels no total)
        modo = "franquia" if hist.get("contagem_meio", 0) % 5 == 4 else "conteudo"
    if os.environ.get("REEL_MODO") in ("venda", "conteudo", "franquia"):
        modo = os.environ["REEL_MODO"]
    print(f"Slot: {slot} | modo: {modo}")
    itens, hist = escolher_fotos()
    n_novos = hist.pop("_novidades_no_video", 0)
    # tem novidade de verdade no vídeo? o Reel de venda puxa o ângulo "novidade" (se não foi usado há pouco)
    preferido = "novidade" if (modo == "venda" and n_novos >= 2) else None
    briefing = reel_lab.gerar_briefing(hist["ganchos"], hist["angulos"], modo, preferido=preferido)
    briefing = aplicar_preco(briefing, texto_preco(itens))
    if modo == "venda" and funil_direct_ligado():
        briefing = aplicar_funil_direct(briefing, len(hist.get("ganchos", [])))
    elif modo == "franquia":
        briefing = aplicar_funil_franquia(briefing)
    elif modo == "conteudo":
        if briefing.get("selo") in ("", "LINK NA BIO", "LULUEXTRA.COM"):
            briefing["selo"] = "DICA LULU"
    formato = os.environ.get("REEL_FORMATO") or escolher_formato(hist["formatos"])
    musica_nome = escolher_musica(hist["musicas"])
    print("Briefing:", json.dumps(briefing, ensure_ascii=False))
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    with open(f"{PASTA_SAIDA}/briefing.json", "w", encoding="utf-8") as f:
        json.dump(briefing, f, ensure_ascii=False, indent=1)
    env_n = os.environ.get("REEL_NARRAR", "")
    # 12/11/2026: narração (voz lendo o texto da tela) em ~75% dos Reels (antes 35%)
    narrar = (env_n == "1") if env_n in ("0", "1") else random.random() < CHANCE_NARRAR
    compartilhar = escolher_compartilhar(modo, len(hist.get("ganchos", [])))
    if compartilhar:
        briefing["legenda"] = inserir_compartilhar(briefing["legenda"], compartilhar[1])
        with open(f"{PASTA_SAIDA}/briefing.json", "w", encoding="utf-8") as f:
            json.dump(briefing, f, ensure_ascii=False, indent=1)
    print(f"Narração: {narrar} | compartilhar: {compartilhar[0] if compartilhar else '-'}")
    gerar_video(itens, briefing, SAIDA, formato, musica_nome, narrar, compartilhar, modo)
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
    hist["angulos"] = (hist["angulos"] + [briefing.get("angulo", "")])[-30:]
    hist["formatos"] = (hist["formatos"] + [formato])[-30:]
    hist["musicas"] = (hist["musicas"] + [musica_nome])[-30:]
    hist[chave_trava] = hoje
    if slot == "meio":
        hist["contagem_meio"] = hist.get("contagem_meio", 0) + 1
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
