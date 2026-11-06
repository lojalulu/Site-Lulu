"""Narração gratuita dos Reels. Tenta voz neural da Microsoft (edge-tts) e, se falhar, a do Google (gTTS).
Se nenhuma funcionar, devolve None e o Reel sai sem narração (nunca trava a postagem)."""
import asyncio
import re
import subprocess

VOZ = "pt-BR-FranciscaNeural"


def limpar(texto):
    t = re.sub(r"[*_#]", "", texto)
    t = re.sub(r"R\$\s*(\d+),(\d{2})", r"\1 reais e \2 centavos", t)  # R$ 199,90 -> 199 reais e 90 centavos
    t = t.replace("R$", "reais ").replace("  ", " ")
    return t.strip()


def duracao(caminho):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", caminho],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def _edge(texto, destino):
    import edge_tts

    async def run():
        await asyncio.wait_for(edge_tts.Communicate(texto, VOZ, rate="+4%").save(destino), timeout=30)
    asyncio.run(run())


def _gtts(texto, destino):
    from gtts import gTTS
    gTTS(texto, lang="pt", tld="com.br").save(destino)


def gerar_voz(texto, destino):
    """Devolve (caminho, duração em segundos) ou None."""
    t = limpar(texto)
    if not t:
        return None
    for nome, fn in (("edge-tts", _edge), ("gtts", _gtts)):
        try:
            fn(t, destino)
            d = duracao(destino)
            if d > 0.3:
                print(f"Voz ({nome}): {d:.1f}s — {t[:50]}")
                return destino, d
        except Exception as e:  # noqa: BLE001
            print(f"Voz {nome} falhou: {type(e).__name__}: {str(e)[:120]}")
    return None
