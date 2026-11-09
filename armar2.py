# Reel "estilo 2.0": cortes rápidos con zoom de golpe, subtítulos palabra por palabra (tipo karaoke) en español,
# gancho animado, barra de progreso, sonido de transición y cierre de marca. 1080x1920, 30 fps.
# Uso: python3 armar2.py guiones/reel1.json [audio.wav]
#   Sin audio: usa la voz Gemini de Supabase (redes/voz/<nombre>.wav) o, si no hay, el audio de salida/<nombre>.mp4.
#   Tiempos de cada palabra: faster-whisper (modelo en $WHISPER_DIR o "small" descargado).
import io, json, math, os, re, subprocess, sys, urllib.request, unicodedata
import numpy as np, soundfile as sf
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
BASE = os.path.dirname(os.path.abspath(__file__))
FOTOS = os.path.join(BASE, "fotos")
F_BLACK = os.path.join(BASE, "fuentes", "Inter-Black.otf")
F_BOLD = os.path.join(BASE, "fuentes", "Inter-Bold.otf")
VOCES = "https://mplgrbwehbzmksjzgqsd.supabase.co/storage/v1/object/public/redes/voz/"
AMARILLO, VERDE, AZUL, BLANCO, NEGRO = (255, 214, 0), (37, 211, 102), (0, 120, 200), (255, 255, 255), (0, 0, 0)

spec = json.load(open(sys.argv[1]))
nombre = spec["nombre"]
tmp = os.path.join(BASE, ".tmp", nombre + "_v2"); os.makedirs(tmp, exist_ok=True)


# ---------- audio ----------
def cargar_audio():
    if len(sys.argv) > 2:
        return sf.read(sys.argv[2])
    try:
        return sf.read(io.BytesIO(urllib.request.urlopen(VOCES + nombre + ".wav", timeout=60).read()))
    except Exception as e:
        print("sin voz en Supabase (", e, "): uso el audio del video anterior")
        mp4 = os.path.join(BASE, "salida", nombre + ".mp4")
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", mp4, "-vn", "-ac", "1", "-ar", "24000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
        return np.frombuffer(raw, np.int16).astype(np.float32) / 32768, 24000


voz, sr = cargar_audio()
if voz.ndim > 1:
    voz = voz.mean(axis=1)
voz = voz.astype(np.float32)
# recorta silencio inicial largo
umbral = 0.02 * np.abs(voz).max(); ini = np.argmax(np.abs(voz) > umbral)
fin = len(voz) - np.argmax(np.abs(voz[::-1]) > umbral)
voz = voz[max(0, ini - int(sr * 0.05)):min(len(voz), fin + int(sr * 0.15))]
DUR_VOZ = len(voz) / sr
FIN = 2.2  # segundos de cierre de marca después de la voz
TOTAL = DUR_VOZ + FIN


# ---------- palabras con tiempo ----------
def palabras():
    from faster_whisper import WhisperModel
    a16 = voz if sr == 16000 else np.interp(np.arange(0, len(voz), sr / 16000), np.arange(len(voz)), voz).astype(np.float32)
    m = WhisperModel(os.environ.get("WHISPER_DIR", "small"), device="cpu", compute_type="int8")
    guion = " ".join(s["texto"] for s in spec["segmentos"])
    segs, _ = m.transcribe(a16, language="es", word_timestamps=True, initial_prompt=guion[:400])
    return [(w.word.strip(), w.start, w.end) for s in segs for w in s.words if w.word.strip()]


try:
    WORDS = palabras()
except Exception as e:
    print("whisper no disponible (", e, "): reparto por largo de palabra")
    toks = " ".join(s["texto"] for s in spec["segmentos"]).split()
    tot = sum(len(t) + 2 for t in toks); t0 = 0.0; WORDS = []
    for t in toks:
        d = DUR_VOZ * (len(t) + 2) / tot; WORDS.append((t, t0, t0 + d)); t0 += d

# los subtítulos usan el texto del guion (bien escrito) alineado con los tiempos de whisper
g_tok = []
for k, s in enumerate(spec["segmentos"]):
    for t in s["texto"].split():
        g_tok.append((t, k))
# alineación simple: reparte los tiempos de whisper sobre las palabras del guion en proporción
n_w, n_g = len(WORDS), len(g_tok)
SUBS = []
for i, (t, k) in enumerate(g_tok):
    a = WORDS[min(n_w - 1, int(i * n_w / n_g))]
    b = WORDS[min(n_w - 1, int((i + 1) * n_w / n_g) - 1 if (i + 1) * n_w / n_g > int(i * n_w / n_g) else int(i * n_w / n_g))]
    SUBS.append({"t": t, "seg": k, "a": a[1], "b": max(a[2], b[2])})
for i in range(1, len(SUBS)):  # sin solapes
    SUBS[i]["a"] = max(SUBS[i]["a"], SUBS[i - 1]["b"] - 0.02)

# inicio de cada segmento (para cambiar de foto)
seg_ini = {}
for s in SUBS:
    seg_ini.setdefault(s["seg"], s["a"])
seg_ini[0] = 0.0

# grupos de subtítulo: hasta 3 palabras, se corta en puntuación o pausa
GRUPOS, cur = [], []
for i, s in enumerate(SUBS):
    cur.append(s)
    corta = len(cur) >= 3 or re.search(r"[.,:;?!]$", s["t"]) or (i + 1 < len(SUBS) and SUBS[i + 1]["a"] - s["b"] > 0.25) or (i + 1 < len(SUBS) and SUBS[i + 1]["seg"] != s["seg"])
    if corta:
        GRUPOS.append(cur); cur = []
if cur:
    GRUPOS.append(cur)


# ---------- tomas (fotos) ----------
def cubrir(foto):
    im = Image.open(os.path.join(FOTOS, f"{foto:02d}.jpg")).convert("RGB")
    esc = max(W * 1.25 / im.width, H * 1.25 / im.height)
    return im.resize((int(im.width * esc) + 2, int(im.height * esc) + 2), Image.LANCZOS)

TOMAS = []  # (inicio, fin, imagen, dirección)
segs = spec["segmentos"]
for k, s in enumerate(segs):
    a = seg_ini.get(k, 0.0)
    b = seg_ini.get(k + 1, DUR_VOZ) if k + 1 < len(segs) else TOTAL
    img = cubrir(s["foto"])
    partes = max(1, round((b - a) / 2.2))  # una toma cada ~2 s: misma foto, otro encuadre
    for j in range(partes):
        TOMAS.append((a + (b - a) * j / partes, a + (b - a) * (j + 1) / partes, img, (k * 3 + j) % 4))


def ease(x):
    return 1 - (1 - min(max(x, 0), 1)) ** 3


def fondo(t):
    for (a, b, img, d) in TOMAS:
        if a <= t < b or (b == TOMAS[-1][1] and t >= a):
            break
    u = (t - a) / max(0.01, b - a)
    golpe = 1 + 0.22 * (1 - ease((t - a) / 0.22))          # zoom de golpe al entrar
    z = (1.0 + 0.10 * u) * golpe                              # zoom lento
    dx, dy = [(1, 0), (-1, 0), (0, 1), (0, -1)][d]
    cw, ch = W / z, H / z
    mx, my = (img.width - cw) / 2, (img.height - ch) / 2
    cx = img.width / 2 + dx * mx * 0.6 * (u - 0.5) * 2
    cy = img.height / 2 + dy * my * 0.6 * (u - 0.5) * 2
    box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
    fr = img.resize((W, H), Image.BILINEAR, box=box)
    if t - a < 0.07 and a > 0:                                # destello blanco en el corte
        fr = Image.blend(fr, Image.new("RGB", (W, H), BLANCO), 0.55 * (1 - (t - a) / 0.07))
    return fr, a


# ---------- capas de texto ----------
f_sub = ImageFont.truetype(F_BLACK, 92)
f_sub_g = ImageFont.truetype(F_BLACK, 104)
f_hook = ImageFont.truetype(F_BLACK, 88)
f_peq = ImageFont.truetype(F_BOLD, 30)
f_marca = ImageFont.truetype(F_BLACK, 110)
f_wa = ImageFont.truetype(F_BLACK, 58)
f_med = ImageFont.truetype(F_BOLD, 46)


def texto_borde(d, xy, txt, font, fill, stroke=9):
    d.text(xy, txt, font=font, fill=fill, stroke_width=stroke, stroke_fill=NEGRO)


def subtitulo(d, t):
    g = next((g for g in GRUPOS if g[0]["a"] - 0.02 <= t < g[-1]["b"] + 0.18), None)
    if not g or t > DUR_VOZ + 0.2:
        return
    pop = 0.85 + 0.15 * ease((t - g[0]["a"]) / 0.12)
    palabras_ = [s["t"].upper() for s in g]
    activos = [s["a"] <= t < s["b"] + 0.05 for s in g]
    fonts = [f_sub_g if act else f_sub for act in activos]
    esp = 24
    anchos = [d.textlength(p, font=f) for p, f in zip(palabras_, fonts)]
    total = sum(anchos) + esp * (len(palabras_) - 1)
    lineas = [[0, len(palabras_)]]
    if total > W - 120 and len(palabras_) > 1:
        lineas = [[0, len(palabras_) - 1], [len(palabras_) - 1, len(palabras_)]]
    y = int(H * 0.60 + (1 - pop) * 60)
    for (i0, i1) in lineas:
        w_l = sum(anchos[i0:i1]) + esp * (i1 - i0 - 1)
        x = (W - w_l) / 2
        for i in range(i0, i1):
            col = AMARILLO if activos[i] else BLANCO
            texto_borde(d, (x, y - (8 if activos[i] else 0)), palabras_[i], fonts[i], col)
            x += anchos[i] + esp
        y += 118


def gancho(d, t):
    if t > 2.6 or not spec.get("gancho"):
        return
    entra = ease(t / 0.25); sale = 1 - ease((t - 2.3) / 0.3)
    txt = spec["gancho"].upper()
    lineas, cur = [], ""
    for p in txt.split():
        if d.textlength((cur + " " + p).strip(), font=f_hook) > W - 140:
            lineas.append(cur); cur = p
        else:
            cur = (cur + " " + p).strip()
    lineas.append(cur)
    y = 260 - int((1 - entra) * 200)
    for l in lineas:
        w_l = d.textlength(l, font=f_hook)
        x = (W - w_l) / 2 + math.sin(t * 40) * 6 * (1 - ease(t / 0.4))
        d.rounded_rectangle([x - 26, y - 14, x + w_l + 26, y + 104], 18, fill=(*AMARILLO, int(245 * sale)))
        d.text((x, y), l, font=f_hook, fill=(*NEGRO, int(255 * sale)))
        y += 124


def cierre(d, t):
    u = t - DUR_VOZ + 0.6
    if u < 0:
        return
    a = ease(u / 0.35)
    d.rectangle([0, 0, W, H], fill=(0, 30, 50, int(170 * a)))
    y0 = 620 - int((1 - a) * 120)
    for txt, f, col, y in [("HIDRO FRESH", f_marca, BLANCO, y0), ("Plantas de tratamiento", f_med, BLANCO, y0 + 150), ("Cloro · Bacterias · Todo Chile", f_med, BLANCO, y0 + 210)]:
        w_l = d.textlength(txt, font=f); d.text(((W - w_l) / 2, y), txt, font=f, fill=(*col, int(255 * a)))
    pulso = 1 + 0.04 * math.sin(u * 9)
    txt = "WhatsApp +56 9 8494 6508"; w_l = d.textlength(txt, font=f_wa) * pulso
    bx = (W - w_l) / 2
    d.rounded_rectangle([bx - 36, 1180, bx + w_l + 36, 1300], 60, fill=(*VERDE, int(250 * a)))
    d.text(((W - d.textlength(txt, font=f_wa)) / 2, 1208), txt, font=f_wa, fill=(*BLANCO, int(255 * a)))


SOMBRA = Image.new("RGBA", (W, H), (0, 0, 0, 0))
_g = np.zeros((H, W, 4), np.uint8); _y = np.arange(H)
_g[:, :, 3] = (np.clip((_y - H * 0.45) / (H * 0.25), 0, 1) * 120).astype(np.uint8)[:, None]
SOMBRA = Image.fromarray(_g, "RGBA")


def capa(t):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # degradado oscuro abajo para que se lean los subtítulos
    im.alpha_composite(SOMBRA)
    gancho(d, t); subtitulo(d, t); cierre(d, t)
    # barra de progreso
    d.rectangle([0, 0, int(W * min(1, t / TOTAL)), 12], fill=(*VERDE, 255))
    d.text((40, H - 70), "Voz generada con IA", font=f_peq, fill=(255, 255, 255, 170))
    return im


# ---------- sonido de transición (barrido suave sintetizado) ----------
def whoosh(dur=0.32):
    n = int(sr * dur); x = np.random.default_rng(1).standard_normal(n).astype(np.float32)
    env = np.sin(np.linspace(0, math.pi, n)) ** 2
    # filtro paso bajo móvil para que "barra"
    k = np.linspace(0.02, 0.35, n); y = np.zeros(n, np.float32); acc = 0.0
    for i in range(n):
        acc += k[i] * (x[i] - acc); y[i] = acc
    return y * env * 0.06

ws = whoosh()
pista = np.zeros(int(TOTAL * sr) + sr, np.float32)
pista[:len(voz)] += voz
for (a, b, img, d_) in TOMAS[1:]:
    i = int(max(0, a - 0.12) * sr); pista[i:i + len(ws)] += ws[:len(pista) - i]
pista = pista[:int(TOTAL * sr)]
wav = os.path.join(tmp, "audio.wav"); sf.write(wav, pista, sr)

# ---------- render ----------
out = os.environ.get("SALIDA") or os.path.join(BASE, "salida", f"{nombre}.mp4")
p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                      "-i", wav, "-filter_complex", "[1:a]loudnorm=I=-14:TP=-1.5[a]", "-map", "0:v", "-map", "[a]",
                      "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-profile:v", "high",
                      "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-shortest", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
n = int(TOTAL * FPS)
for f in range(n):
    t = f / FPS
    fr, _ = fondo(t)
    fr = fr.convert("RGBA"); fr.alpha_composite(capa(t))
    p.stdin.write(fr.convert("RGB").tobytes())
p.stdin.close(); p.wait()
print(out, round(TOTAL, 1), "s ·", len(TOMAS), "tomas ·", len(GRUPOS), "subtítulos")
