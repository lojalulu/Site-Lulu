"""
Robô de Reels do Instagram: sorteia fotos de produtos do site, monta um
vídeo vertical (zoom suave + transições + frases em alguns quadros +
música livre de direitos) e publica como Reel pela API oficial.

Uso:
  python instagram/postar_reel.py              -> gera e publica
  python instagram/postar_reel.py --so-gerar   -> só gera o vídeo (teste)
"""

import io
import json
import os
import random
import subprocess
import sys
import time

import requests
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imagem_story import _carregar_fonte  # fonte da marca (Baloo 2) com fallback

L, A = 1080, 1920
FPS = 30
FADE = 0.35            # duração da transição (crossfade) entre quadros
DUR_FOTO = 2.2         # quadro só com foto
ROSA = (255, 61, 128)

CATALOGOS = {"kits": "produtos.json", "avulso": "kitavulso/produtos.json"}
HIST = "instagram/historico_reels.json"
SAIDA = "instagram/_saida/reel.mp4"
MUSICAS = "instagram/musicas"

GRAPH = "https://graph.instagram.com/v23.0"
TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
IG_ID = os.environ.get("INSTAGRAM_BUSINESS_ID")

# ---------------------------------------------------------------- textos
# (frase, rótulo-do-selo). Sem emoji: a fonte da marca não tem os glifos.
TEXTOS = {
    "revenda": [
        ("Revenda moda fitness e aumente sua renda", "LINK NA BIO"),
        ("Compre no atacado e revenda com margem", "LINK NA BIO"),
        ("Kits prontos pra você revender", "LINK NA BIO"),
        ("Moda fitness no atacado pra sua revenda", "LINK NA BIO"),
    ],
    "bio": [
        ("Veja o catálogo completo no link da bio", "LINK NA BIO"),
        ("Escolha seus kits no link da bio", "LINK NA BIO"),
        ("Acesse o link da bio e faça seu pedido", "LINK NA BIO"),
    ],
    "franquia": [
        ("Quer ter sua própria loja online de moda fitness?", "MINI FRANQUIA · LINK NA BIO"),
        ("Conheça a mini franquia Lulu", "LINK NA BIO"),
        ("Abra sua loja de moda fitness com a Lulu", "MINI FRANQUIA · LINK NA BIO"),
    ],
}

LEGENDAS = {
    "revenda": "Moda fitness no atacado pra você revender e aumentar sua renda. Veja o catálogo completo no link da bio.",
    "bio": "Os kits da Lulu Extra Fitness estão no link da bio. Escolha os seus e faça seu pedido.",
    "franquia": "Quer ter a sua própria loja de moda fitness? Conheça a mini franquia Lulu no link da bio.",
}
HASHTAGS = "#modafitness #revendedora #atacado #lulumodafitness #roupafitness #revendademoda #empreendedorismofeminino"


# ---------------------------------------------------------------- produtos
def carregar_historico():
    try:
        with open(HIST, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"ids": []}


def baixar(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def escolher_fotos(n=6):
    hist = carregar_historico()
    recentes = set(hist["ids"][-80:])
    loja = random.choice(list(CATALOGOS))
    with open(CATALOGOS[loja], encoding="utf-8") as f:
        catalogo = [p for p in json.load(f) if p.get("imagens")]
    novos = [p for p in catalogo if p["id"] not in recentes] or catalogo
    random.shuffle(novos)
    fotos, usados = [], []
    for p in novos:
        if len(fotos) == n:
            break
        try:
            fotos.append(baixar(random.choice(p["imagens"][:3])))
            usados.append(p["id"])
        except Exception as e:
            print(f"  foto ignorada ({p['id']}): {e}")
    if len(fotos) < 3:
        raise RuntimeError("Poucas fotos disponíveis pra montar o Reel.")
    print(f"Catálogo: {loja} | {len(fotos)} fotos")
    return loja, fotos, usados, hist


# ---------------------------------------------------------------- imagens
def montar_base(foto):
    """Foto inteira centralizada sobre um fundo borrado da própria foto."""
    fundo = ImageOps_cover(foto, L, A).filter(ImageFilter.GaussianBlur(45))
    fundo = Image.blend(fundo, Image.new("RGB", (L, A), (20, 10, 18)), 0.35)
    w, h = foto.size
    esc = min(L / w, 1560 / h)
    fg = foto.resize((int(w * esc), int(h * esc)), Image.LANCZOS)
    fundo.paste(fg, ((L - fg.width) // 2, (A - fg.height) // 2 - 40))
    # leve sobra pra permitir o zoom sem borda
    return fundo


def ImageOps_cover(img, w, h):
    esc = max(w / img.width, h / img.height)
    im = img.resize((int(img.width * esc) + 1, int(img.height * esc) + 1), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def quebrar_linhas(draw, texto, fonte, largura):
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = (atual + " " + palavra).strip()
        if draw.textlength(teste, font=fonte) <= largura:
            atual = teste
        else:
            linhas.append(atual)
            atual = palavra
    linhas.append(atual)
    return linhas


def montar_overlay_texto(frase, selo):
    """Camada RGBA com degradê escuro embaixo, frase e selo rosa."""
    ov = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    grad = Image.new("L", (1, A), 0)
    for y in range(A):
        if y > 1000:
            grad.putpixel((0, y), int(215 * min(1, (y - 1000) / 520)))
    ov.paste(Image.new("RGBA", (L, A), (10, 4, 10, 255)), (0, 0), grad.resize((L, A)))
    d = ImageDraw.Draw(ov)
    largura = 900
    for tam in (92, 84, 76, 68, 60):
        fonte = _carregar_fonte(tam, "ExtraBold")
        linhas = quebrar_linhas(d, frase, fonte, largura)
        if len(linhas) <= 3:
            break
    alt = int(tam * 1.18)
    selo_f = _carregar_fonte(46, "ExtraBold")
    sw = int(d.textlength(selo, font=selo_f)) + 80
    total = alt * len(linhas) + 40 + 84
    y = 1760 - total
    for ln in linhas:
        w = d.textlength(ln, font=fonte)
        d.text(((L - w) / 2, y), ln, font=fonte, fill=(255, 255, 255, 255),
               stroke_width=5, stroke_fill=(20, 6, 16, 255))
        y += alt
    y += 40
    d.rounded_rectangle(((L - sw) // 2, y, (L + sw) // 2, y + 84), radius=42, fill=ROSA + (255,))
    d.text(((L - sw) // 2 + 40, y + 12), selo, font=selo_f, fill=(255, 255, 255, 255))
    return ov


# ---------------------------------------------------------------- vídeo
class Quadro:
    def __init__(self, foto, texto=None, indice=0):
        self.base = montar_base(foto)
        self.overlay = montar_overlay_texto(*texto) if texto else None
        n_palavras = len(texto[0].split()) if texto else 0
        self.dur = max(3.8, 1.4 + 0.38 * n_palavras) if texto else DUR_FOTO
        self.zoom_in = indice % 2 == 0

    def render(self, t):
        p = min(max(t / self.dur, 0), 1)
        z = 1.0 + 0.07 * (p if self.zoom_in else 1 - p)
        cw, ch = L / z, A / z
        x, y = (L - cw) / 2, (A - ch) / 2
        im = self.base.resize((L, A), Image.BILINEAR, box=(x, y, x + cw, y + ch))
        if self.overlay is not None:
            a = min(1.0, max(0.0, (t - 0.25) / 0.45))  # texto surge suave
            if a > 0:
                ov = self.overlay
                if a < 1:
                    ov = ov.copy()
                    ov.putalpha(ov.getchannel("A").point(lambda v: int(v * a)))
                im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
        return im


def escolher_textos():
    temas = list(TEXTOS)
    tema_final = random.choice(temas)
    tema_meio = random.choice([t for t in temas if t != tema_final])
    meio = random.choice(TEXTOS[tema_meio]) if random.random() < 0.75 else None
    final = random.choice(TEXTOS[tema_final])
    return tema_final, meio, final


def gerar_video(fotos, saida):
    tema, meio, final = escolher_textos()
    quadros = []
    for i, foto in enumerate(fotos):
        texto = None
        if i == len(fotos) - 1:
            texto = final
        elif i == 2 and meio:
            texto = meio
        quadros.append(Quadro(foto, texto, i))
    inicios, t = [], 0.0
    for q in quadros:
        inicios.append(t)
        t += q.dur - FADE
    total = t + FADE
    musica = os.path.join(MUSICAS, random.choice(sorted(os.listdir(MUSICAS))))
    print(f"Música: {musica} | duração {total:.1f}s | tema final: {tema}")

    os.makedirs(os.path.dirname(saida), exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{L}x{A}", "-r", str(FPS), "-i", "-",
           "-i", musica,
           "-af", f"afade=t=in:d=0.4,afade=t=out:st={total - 1.6:.2f}:d=1.6",
           "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", saida]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(total * FPS)
    for f in range(n):
        tt = f / FPS
        i = max(k for k, s in enumerate(inicios) if s <= tt)
        im = quadros[i].render(tt - inicios[i])
        if i + 1 < len(quadros) and tt > inicios[i] + quadros[i].dur - FADE:
            prox = quadros[i + 1].render(tt - inicios[i + 1])
            im = Image.blend(im, prox, (tt - (inicios[i] + quadros[i].dur - FADE)) / FADE)
        proc.stdin.write(im.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg falhou ao montar o vídeo.")
    print(f"Vídeo pronto: {saida} ({os.path.getsize(saida) / 1e6:.1f} MB)")
    return tema


# ---------------------------------------------------------------- publicar
def checar(resp, ctx):
    if resp.status_code >= 300:
        raise RuntimeError(f"Erro em {ctx}: {resp.status_code} — {resp.text}")
    return resp.json()


def hospedar_video(caminho):
    """A API do Instagram (login do Instagram) exige uma URL pública do
    vídeo. Publicamos o arquivo numa branch temporária 'reel-tmp' que é
    sobrescrita a cada vez (não incha o histórico do repositório)."""
    import shutil
    import tempfile
    repo, gh = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    tmp = tempfile.mkdtemp()
    shutil.copy(caminho, os.path.join(tmp, "reel.mp4"))
    def git(*a):
        subprocess.run(["git", *a], cwd=tmp, check=True, capture_output=True)
    git("init", "-q", "-b", "reel-tmp")
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "github-actions[bot]@users.noreply.github.com")
    git("add", "reel.mp4")
    git("commit", "-q", "-m", "reel temporario")
    git("push", "-f", f"https://x-access-token:{gh}@github.com/{repo}.git", "reel-tmp:reel-tmp")
    url = f"https://raw.githubusercontent.com/{repo}/reel-tmp/reel.mp4"
    for _ in range(10):
        h = requests.head(url, timeout=30, allow_redirects=True)
        print("  URL do vídeo:", h.status_code, h.headers.get("content-type"), h.headers.get("content-length"))
        if h.status_code == 200:
            break
        time.sleep(5)
    return url


def publicar_reel(caminho, legenda):
    url = hospedar_video(caminho)
    r = requests.post(f"{GRAPH}/{IG_ID}/media", data={
        "media_type": "REELS", "video_url": url, "caption": legenda,
        "share_to_feed": "true", "access_token": TOKEN}, timeout=60)
    cid = checar(r, "criar container do Reel")["id"]
    for _ in range(50):
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
    pub = checar(requests.post(f"{GRAPH}/{IG_ID}/media_publish", data={
        "creation_id": cid, "access_token": TOKEN}, timeout=60), "publicar o Reel")
    return pub["id"]


def main():
    so_gerar = "--so-gerar" in sys.argv
    if not so_gerar and (not TOKEN or not IG_ID):
        print("ERRO: faltam INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID.")
        sys.exit(1)
    loja, fotos, ids, hist = escolher_fotos()
    tema = gerar_video(fotos, SAIDA)
    if so_gerar:
        return
    legenda = LEGENDAS[tema] + "\n\n" + HASHTAGS
    print("Publicando Reel...")
    media_id = publicar_reel(SAIDA, legenda)
    print(f"Reel publicado: {media_id}")
    hist["ids"] = (hist["ids"] + ids)[-300:]
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
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
