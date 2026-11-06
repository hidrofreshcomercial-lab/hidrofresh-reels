# Arma un reel vertical 1080x1920 a partir de un guion JSON: voz Kokoro (gratis, local), fotos con zoom lento, subtítulos y cierre de marca.
# Uso: python3 armar.py reel1.json
import json, os, subprocess, sys, textwrap
import numpy as np, soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from kokoro_onnx import Kokoro

W, H, FPS = 1080, 1920, 30
F_BLACK = "/usr/share/fonts/opentype/inter/Inter-Black.otf"
F_BOLD = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
AZUL = (0, 120, 200)
BASE = os.path.dirname(os.path.abspath(__file__))
FOTOS = os.path.join(BASE, "fotos")
MODELOS = os.environ.get("KOKORO_DIR", "/home/claude/tts")

spec = json.load(open(sys.argv[1]))
nombre = spec["nombre"]
tmp = os.path.join(BASE, ".tmp", nombre)
os.makedirs(tmp, exist_ok=True)
k = Kokoro(os.path.join(MODELOS, "kokoro-v1.0.int8.onnx"), os.path.join(MODELOS, "voices-v1.0.bin"))


def fondo(foto):
    im = Image.open(f"{FOTOS}/{foto:02d}.jpg").convert("RGB")
    bg = im.copy()
    r = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * r) + 1, int(bg.height * r) + 1)).crop((0, 0, W, H)).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (10, 20, 30)), 0.35)
    r = min(W / im.width, 1500 / im.height)
    if im.height > im.width:  # vertical: llenar casi todo
        r = max(W / im.width, H / im.height)
    fg = im.resize((int(im.width * r), int(im.height * r)))
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    return bg


def caja_texto(d, txt, font, y, ancho=22, color=(255, 255, 255), caja=(0, 0, 0, 170), pad=26):
    lineas = textwrap.wrap(txt, ancho)
    alto = sum(font.getbbox(l)[3] + 14 for l in lineas)
    wmax = max(font.getlength(l) for l in lineas)
    d.rounded_rectangle([(W - wmax) / 2 - pad, y - pad, (W + wmax) / 2 + pad, y + alto + pad - 10], 28, fill=caja)
    for l in lineas:
        d.text(((W - font.getlength(l)) / 2, y), l, font=font, fill=color)
        y += font.getbbox(l)[3] + 14


def capa(seg, i, final):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if i == 0 and spec.get("gancho"):
        caja_texto(d, spec["gancho"], ImageFont.truetype(F_BLACK, 84), 230, 18, (255, 255, 255), (*AZUL, 235))
    if final:
        caja_texto(d, "HIDRO FRESH", ImageFont.truetype(F_BLACK, 96), 300, 20, (255, 255, 255), (*AZUL, 240))
        caja_texto(d, "Plantas de tratamiento · Cloro · Bacterias", ImageFont.truetype(F_BOLD, 44), 470, 30)
        caja_texto(d, "WhatsApp +56 9 8494 6508", ImageFont.truetype(F_BLACK, 66), 1530, 26, (255, 255, 255), (37, 160, 70, 245))
    else:
        caja_texto(d, seg["texto"], ImageFont.truetype(F_BLACK, 66), 1340, 24)
    ImageDraw.Draw(im).text((40, H - 70), "Voz generada con IA", font=ImageFont.truetype(F_BOLD, 30), fill=(255, 255, 255, 170))
    return im


clips, audios = [], []
for i, seg in enumerate(spec["segmentos"]):
    final = i == len(spec["segmentos"]) - 1
    s, sr = k.create(seg["texto"], voice=spec.get("voz", "ef_dora"), speed=spec.get("velocidad", 1.05), lang=spec.get("lang", "es-419"))
    pausa = np.zeros(int(sr * (0.6 if final else 0.18)), dtype=s.dtype)
    s = np.concatenate([np.zeros(int(sr * 0.05), dtype=s.dtype), s, pausa])
    if final:
        s = np.concatenate([s, np.zeros(int(sr * 1.2), dtype=s.dtype)])
    audios.append(s)
    dur = len(s) / sr
    fondo(seg["foto"]).save(f"{tmp}/bg{i}.png")
    capa(seg, i, final).save(f"{tmp}/sub{i}.png")
    n = int(dur * FPS) + 1
    zoom = "min(zoom+0.0009,1.15)" if i % 2 == 0 else "if(eq(on,0),1.15,max(zoom-0.0009,1.0))"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", f"{tmp}/bg{i}.png", "-i", f"{tmp}/sub{i}.png",
                    "-filter_complex", f"[0]scale=2160:3840,zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS}[v];[v][1]overlay,format=yuv420p",
                    "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", f"{tmp}/c{i}.mp4"], check=True)
    clips.append((f"{tmp}/c{i}.mp4", dur))

voz = np.concatenate(audios)
sf.write(f"{tmp}/voz.wav", voz, sr)
with open(f"{tmp}/lista.txt", "w") as f:
    for c, _ in clips:
        f.write(f"file '{c}'\n")
total = len(voz) / sr
out = os.path.join(BASE, "salida", f"{nombre}.mp4")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"{tmp}/lista.txt", "-i", f"{tmp}/voz.wav",
                "-filter_complex", f"[0:v]fade=t=in:st=0:d=0.3,fade=t=out:st={total-0.5:.2f}:d=0.5[v];[1:a]loudnorm=I=-14:TP=-1.5,afade=t=out:st={total-0.6:.2f}:d=0.6[a]",
                "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-profile:v", "high",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", out], check=True)
print(out, round(total, 1), "s")
