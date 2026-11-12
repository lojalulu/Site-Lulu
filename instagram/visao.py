"""
Visão simples para as fotos do fornecedor (Reels, carrosséis e posts):
  - aparar_bordas: tira faixas lisas (pretas/brancas) que vêm "coladas" na foto
  - rostos: acha rostos (OpenCV, se instalado) para nada ficar em cima deles
  - lugar_livre: escolhe onde pôr uma etiqueta/selo sem cobrir rosto nem texto

Se o OpenCV não estiver instalado, tudo continua funcionando: a "zona provável
da cabeça" (alto e centro da foto) é evitada no lugar dos rostos detectados.
"""

import functools

from PIL import Image, ImageChops


# ------------------------------------------------------------------ bordas
def aparar_bordas(img, tolerancia=18, minimo=0.02):
    """Corta faixas uniformes (pretas, brancas ou de qualquer cor lisa) nas 4 bordas.
    Só corta se a faixa tiver pelo menos `minimo` do tamanho (evita cortes à toa)."""
    try:
        rgb = img.convert("RGB")
        w, h = rgb.size
        caixa = [0, 0, w, h]
        for canto in ((0, 0), (w - 1, h - 1)):
            cor = rgb.getpixel(canto)
            fundo = Image.new("RGB", rgb.size, cor)
            dif = ImageChops.difference(rgb, fundo).convert("L").point(lambda v: 255 if v > tolerancia else 0)
            bb = dif.getbbox()
            if not bb:
                continue
            caixa = [max(caixa[0], bb[0]), max(caixa[1], bb[1]), min(caixa[2], bb[2]), min(caixa[3], bb[3])]
        x0, y0, x1, y1 = caixa
        if (x1 - x0) < w * 0.5 or (y1 - y0) < h * 0.5:
            return img  # cortaria demais: provavelmente fundo de estúdio liso, não borda
        if x0 < w * minimo and y0 < h * minimo and (w - x1) < w * minimo and (h - y1) < h * minimo:
            return img
        return img.crop((x0, y0, x1, y1))
    except Exception:  # noqa: BLE001
        return img


# ------------------------------------------------------------------ rostos
@functools.lru_cache(maxsize=1)
def _detectores():
    try:
        import cv2  # noqa: WPS433
        base = cv2.data.haarcascades
        frente = cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml")
        perfil = cv2.CascadeClassifier(base + "haarcascade_profileface.xml")
        if frente.empty():
            return None
        return cv2, frente, perfil
    except Exception:  # noqa: BLE001
        return None


def opencv_ok():
    return _detectores() is not None


def rostos(img):
    """Lista de caixas (x0, y0, x1, y1) em coordenadas de `img`. None = detector indisponível."""
    d = _detectores()
    if d is None:
        return None
    cv2, frente, perfil = d
    import numpy as np  # noqa: WPS433
    w, h = img.size
    esc = min(1.0, 900 / max(w, h))
    peq = img.convert("RGB").resize((max(1, int(w * esc)), max(1, int(h * esc))))
    cinza = cv2.equalizeHist(cv2.cvtColor(np.array(peq), cv2.COLOR_RGB2GRAY))
    lado_min = max(24, int(min(peq.size) * 0.04))
    achados = []
    for det, espelhar, viz in ((frente, False, 5), (perfil, False, 7), (perfil, True, 7)):
        g = cv2.flip(cinza, 1) if espelhar else cinza
        for (x, y, cw, ch) in det.detectMultiScale(g, scaleFactor=1.1, minNeighbors=viz, minSize=(lado_min, lado_min)):
            if espelhar:
                x = g.shape[1] - x - cw
            achados.append((x / esc, y / esc, (x + cw) / esc, (y + ch) / esc))
    # rosto de verdade fica na metade de cima da pessoa: descarta "rostos" no pé da foto (estampa, tênis)
    return [c for c in achados if c[1] < h * 0.62]


# ------------------------------------------------------------------ posição livre
def _inter(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


def zonas_proibidas(img, regioes_foto, folga=0.30):
    """Caixas a evitar: rostos detectados (com folga) em `img`; se não houver detector ou
    nenhum rosto for achado, a zona provável da cabeça de cada foto (alto e centro)."""
    caixas = rostos(img)
    zonas = []
    if caixas:
        for x0, y0, x1, y1 in caixas:
            fw, fh = (x1 - x0), (y1 - y0)
            zonas.append((x0 - fw * folga - 40, y0 - fh * folga - 40, x1 + fw * folga + 40, y1 + fh * (folga + 0.4) + 40))
    else:
        for x0, y0, x1, y1 in regioes_foto:
            rw, rh = x1 - x0, y1 - y0
            zonas.append((x0 + rw * 0.22, y0, x1 - rw * 0.22, y0 + rh * 0.34))
    return zonas


def lugar_livre(tamanho, candidatos, proibidas):
    """Primeiro candidato (x, y) cuja caixa não encosta em nenhuma zona proibida.
    Se nenhum estiver 100% livre, devolve o de menor sobreposição (e a sobreposição)."""
    w, h = tamanho
    melhor, menor = None, None
    for x, y in candidatos:
        caixa = (x, y, x + w, y + h)
        sob = sum(_inter(caixa, z) for z in proibidas)
        if sob == 0:
            return (x, y), 0
        if menor is None or sob < menor:
            melhor, menor = (x, y), sob
    return melhor, menor
