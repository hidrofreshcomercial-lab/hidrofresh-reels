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
TREN = ["SUSTENTABILIDAD", "INNOVACIÓN", "TECNOLOGÍA", "MEDIO AMBIENTE", "ENERGÍA", "AHORRO DE AGUA", "RECICLAJE DE AGUA", "FUTURO"]
PASO = 0.42    # segundos por palabra del tren
FIN = 0.15 + 0.25 + len(TREN) * PASO + 1.9  # cierre: página blanca, tren de palabras y la marca
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


# ---------- tomas (fotos completas, más chicas, sobre fondo difuminado de la misma foto) ----------
def r_esq(im, r=34):
    m = Image.new("L", im.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, im.width - 1, im.height - 1], r, fill=255); return m

CACHE = {}
def preparar(foto):
    if foto in CACHE:
        return CACHE[foto]
    im = Image.open(os.path.join(FOTOS, f"{foto:02d}.jpg")).convert("RGB")
    esc = max(W / im.width, H / im.height)
    bg = im.resize((int(im.width * esc) + 2, int(im.height * esc) + 2), Image.BILINEAR)
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H)).filter(ImageFilter.GaussianBlur(38))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (8, 20, 28)), 0.35)
    # foto completa: cabe en 90% del ancho y 60% del alto (a 1,2x para que el zoom no se vea borroso)
    e2 = min(W * 0.90 / im.width, H * 0.60 / im.height) * 1.2
    fg = im.resize((int(im.width * e2), int(im.height * e2)), Image.LANCZOS)
    CACHE[foto] = (bg, fg, r_esq(fg)); return CACHE[foto]

usadas = {s["foto"] for s in spec["segmentos"]}
POOL = [int(f[:2]) for f in sorted(os.listdir(FOTOS)) if f.endswith(".jpg") and int(f[:2]) not in usadas and int(f[:2]) not in spec.get("excluir", [])]
semilla = sum(ord(c) for c in nombre); POOL = POOL[semilla % max(1, len(POOL)):] + POOL[:semilla % max(1, len(POOL))]
TOMAS = []  # (inicio, fin, foto, dirección)
segs = spec["segmentos"]; ip = 0
for k, s_ in enumerate(segs):
    a = seg_ini.get(k, 0.0)
    b = seg_ini.get(k + 1, DUR_VOZ) if k + 1 < len(segs) else DUR_VOZ + 0.15
    partes = max(1, round((b - a) / 2.0))  # una toma cada ~2 s; la primera es la foto del texto, las demás otras fotos tuyas
    for j in range(partes):
        foto = s_["foto"] if j == 0 or not POOL else POOL[(ip := ip + 1) % len(POOL)]
        TOMAS.append((a + (b - a) * j / partes, a + (b - a) * (j + 1) / partes, foto, (k * 3 + j) % 4))
FOTO_Y = int(H * 0.40)


def ease(x):
    return 1 - (1 - min(max(x, 0), 1)) ** 3


def fondo(t):
    for (a, b, foto, d) in TOMAS:
        if a <= t < b:
            break
    else:
        a, b, foto, d = TOMAS[-1]
    bg, fg, mask = preparar(foto)
    u = min(1, (t - a) / max(0.01, b - a))
    golpe = 1 + 0.16 * (1 - ease((t - a) / 0.22))           # zoom de golpe al entrar
    z = (0.80 + 0.06 * u) * golpe                              # zoom lento (sobre la foto completa)
    dx, dy = [(1, 0), (-1, 0), (0, 1), (0, -1)][d]
    w2, h2 = int(fg.width * z), int(fg.height * z)
    fr = bg.copy()
    # el fondo también se mueve un poco
    if u:
        zb = 1 + 0.05 * u; cw, ch = W / zb, H / zb
        fr = bg.resize((W, H), Image.BILINEAR, box=((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2))
    img = fg.resize((w2, h2), Image.BILINEAR); m = mask.resize((w2, h2), Image.BILINEAR)
    x = (W - w2) // 2 + int(dx * 28 * (u - 0.5) * 2); y = FOTO_Y - h2 // 2 + int(dy * 22 * (u - 0.5) * 2)
    sombra = Image.new("L", (w2 + 60, h2 + 60), 0); ImageDraw.Draw(sombra).rounded_rectangle([30, 36, w2 + 30, h2 + 36], 40, fill=150)
    fr.paste(Image.new("RGB", sombra.size, (0, 0, 0)), (x - 30, y - 30), sombra.filter(ImageFilter.GaussianBlur(18)))
    fr.paste(img, (x, y), m)
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
    y = int(H * 0.70 + (1 - pop) * 60)
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


COLORES_TREN = [(11, 110, 117), (0, 120, 200), (29, 140, 70), (11, 110, 117), (230, 140, 0), (0, 120, 200), (29, 140, 70), (11, 110, 117)]
def f_ajuste(txt, maxw, size=118):
    f = ImageFont.truetype(F_BLACK, size)
    while ImageDraw.Draw(Image.new("L", (1, 1))).textlength(txt, font=f) > maxw and size > 50:
        size -= 6; f = ImageFont.truetype(F_BLACK, size)
    return f

def cierre(d, t):
    u = t - (DUR_VOZ + 0.15)
    if u < 0:
        return
    d.rectangle([0, 0, W, H], fill=(255, 255, 255, int(255 * ease(u / 0.25))))   # página blanca
    v = u - 0.25
    if v < 0:
        return
    i = int(v // PASO)
    if i < len(TREN):                                       # tren: entra por la derecha, pasa al centro y sale por la izquierda
        r = (v - i * PASO) / PASO
        x0 = W if r < 0.3 else 0
        if r < 0.3: off = (1 - ease(r / 0.3)) * W
        elif r < 0.72: off = 0
        else: off = -ease((r - 0.72) / 0.28) * W
        txt = TREN[i]; f = f_ajuste(txt, W - 120)
        wl = d.textlength(txt, font=f)
        d.text(((W - wl) / 2 + off, H * 0.45), txt, font=f, fill=(*COLORES_TREN[i % len(COLORES_TREN)], 255))
        # rieles del tren
        d.rectangle([0, int(H * 0.45) + 150, W, int(H * 0.45) + 156], fill=(11, 110, 117, 90))
        return
    w = v - len(TREN) * PASO                                # marca
    pop = 0.6 + 0.4 * ease(w / 0.25) + 0.06 * math.sin(min(w, 0.6) * 12) * (1 - min(1, w / 0.6))
    f = ImageFont.truetype(F_BLACK, max(20, int(150 * pop)))
    txt = "HIDRO FRESH"; wl = d.textlength(txt, font=f)
    d.text(((W - wl) / 2, H * 0.40 - 75 * pop), txt, font=f, fill=(0, 120, 200, 255))
    sub = "Plantas de tratamiento · Cloro · Bacterias"; wl = d.textlength(sub, font=f_med)
    d.text(((W - wl) / 2, H * 0.40 + 110), sub, font=f_med, fill=(11, 110, 117, int(255 * ease((w - 0.2) / 0.3))))
    if w > 0.35:
        a = ease((w - 0.35) / 0.3); pulso = 1 + 0.03 * math.sin(w * 9)
        txt = "WhatsApp +56 9 8494 6508"; wt = d.textlength(txt, font=f_wa)
        bw = wt * pulso; bx = (W - bw) / 2
        d.rounded_rectangle([bx - 36, 1180, bx + bw + 36, 1300], 60, fill=(*VERDE, int(250 * a)))
        d.text(((W - wt) / 2, 1208), txt, font=f_wa, fill=(*BLANCO, int(255 * a)))


SOMBRA = Image.new("RGBA", (W, H), (0, 0, 0, 0))
_g = np.zeros((H, W, 4), np.uint8); _y = np.arange(H)
_g[:, :, 3] = (np.clip((_y - H * 0.62) / (H * 0.18), 0, 1) * 110).astype(np.uint8)[:, None]
SOMBRA = Image.fromarray(_g, "RGBA")


def capa(t):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # degradado oscuro abajo para que se lean los subtítulos
    if t < DUR_VOZ + 0.15:
        im.alpha_composite(SOMBRA)
    gancho(d, t); subtitulo(d, t); cierre(d, t)
    # barra de progreso
    d.rectangle([0, 0, int(W * min(1, t / TOTAL)), 12], fill=(*VERDE, 255))
    d.text((40, H - 70), "Voz generada con IA", font=f_peq, fill=(255, 255, 255, 170) if t < DUR_VOZ + 0.3 else (90, 110, 112, 200))
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
marcas = [a for (a, b, f_, d_) in TOMAS[1:]] + [DUR_VOZ + 0.15] + [DUR_VOZ + 0.4 + k * PASO for k in range(len(TREN))]
for k, a in enumerate(marcas):
    i = int(max(0, a - 0.12) * sr); g = 0.6 if k > len(TOMAS) else 1.0
    pista[i:i + len(ws)] += g * ws[:len(pista) - i]
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
