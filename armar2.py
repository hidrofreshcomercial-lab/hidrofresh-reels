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
        return sf.read(io.BytesIO(urllib.request.urlopen(VOCES + spec.get("voz_kore", nombre) + ".wav", timeout=60).read()))
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
# voz propia del clip (Lorena hablando con la boca sincronizada): segmento con "voz_propia": segundos.
# Ese tramo usa el audio original del clip y la voz Kore (que trae solo el resto del guion) va a continuación.
def bajar(ruta):
    if not ruta.startswith("http"):
        return ruta if os.path.isabs(ruta) else os.path.join(BASE, ruta)
    dst = os.path.join(tmp, os.path.basename(ruta.split("?")[0]))
    if not os.path.exists(dst):
        open(dst, "wb").write(urllib.request.urlopen(ruta, timeout=120).read())
    return dst
def audio_clip(seg):
    dur = 7.9 if seg["voz_propia"] is True else float(seg["voz_propia"])
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", bajar(seg["video"]), "-t", str(dur), "-vn", "-ac", "1",
                          "-ar", str(sr), "-f", "s16le", "-"], capture_output=True, check=True).stdout
    c = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    if seg["voz_propia"] is True:                          # automático: corta donde termina de hablar
        env = np.convolve(np.abs(c), np.ones(int(sr * 0.05)) / int(sr * 0.05), "same")
        on = np.where(env > 0.12 * env.max())[0]
        c = c[:min(len(c), (on[-1] if len(on) else len(c)) + int(sr * 0.2))]
    return c * (0.9 * np.abs(voz).max()) / max(1e-4, np.abs(c).max())   # mismo volumen que la voz Kore
_sg = spec["segmentos"]
if _sg[0].get("voz_propia"):        # Lorena abre hablando con su voz (boca sincronizada); Kore narra después
    voz = np.concatenate([audio_clip(_sg[0]), np.zeros(int(sr * 0.12), np.float32), voz])
CIERRE_T0 = None
if len(_sg) > 1 and _sg[-1].get("voz_propia"):   # y cierra hablando ella
    voz = np.concatenate([voz, np.zeros(int(sr * 0.15), np.float32)])
    CIERRE_T0 = len(voz) / sr                     # el clip parte justo donde parte su audio (boca sincronizada)
    voz = np.concatenate([voz, audio_clip(_sg[-1])])
DUR_VOZ = len(voz) / sr
TREN = ["SUSTENTABILIDAD", "INNOVACIÓN", "TECNOLOGÍA", "MEDIO AMBIENTE", "ENERGÍA", "AHORRO DE AGUA", "RECICLAJE DE AGUA", "FUTURO"]
PASO = 0.36    # una palabra nueva cada 0,36 s; cada una vive 0,9 s alejándose hacia el fondo
VIDA = 0.9
FIN = 0.15 + 0.25 + (len(TREN) - 1) * PASO + VIDA + 1.9  # cierre: página blanca, palabras al fondo y la marca
TOTAL = DUR_VOZ + FIN


# ---------- palabras con tiempo ----------
def palabras():
    from faster_whisper import WhisperModel
    a16 = voz if sr == 16000 else np.interp(np.arange(0, len(voz), sr / 16000), np.arange(len(voz)), voz).astype(np.float32)
    m = WhisperModel(os.environ.get("WHISPER_DIR", "small"), device="cpu", compute_type="int8")
    guion = " ".join(s["texto"] for s in spec["segmentos"])
    segs, _ = m.transcribe(a16, language="es", word_timestamps=True, condition_on_previous_text=False)
    return [(w.word.strip(), w.start, w.end) for s in segs for w in s.words if w.word.strip()]


try:
    WORDS = palabras()
except Exception as e:
    print("whisper no disponible (", e, "): reparto por largo de palabra")
    toks = " ".join(s["texto"] for s in spec["segmentos"]).split()
    tot = sum(len(t) + 2 for t in toks); t0 = 0.0; WORDS = []
    for t in toks:
        d = DUR_VOZ * (len(t) + 2) / tot; WORDS.append((t, t0, t0 + d)); t0 += d

# los subtítulos usan el texto del guion (bien escrito) alineado palabra a palabra con lo que dice la voz (whisper)
import difflib, unicodedata
def _norm(x):
    x = unicodedata.normalize("NFD", x.lower()); x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ]", "", x)
g_tok = []
for k, s in enumerate(spec["segmentos"]):
    for t in s["texto"].split():
        g_tok.append((t, k))
gn = [_norm(t) for t, _ in g_tok]; wn = [_norm(w[0]) for w in WORDS]
TIEM = [None] * len(g_tok)
for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, gn, wn, autojunk=False).get_opcodes():
    if op == "equal":
        for d in range(i2 - i1):
            TIEM[i1 + d] = (WORDS[j1 + d][1], WORDS[j1 + d][2])
    elif op == "replace" and i2 > i1:
        a0, b0 = WORDS[j1][1], WORDS[j2 - 1][2]; L = sum(len(g_tok[i][0]) + 1 for i in range(i1, i2)); acc = 0
        for i in range(i1, i2):
            n = len(g_tok[i][0]) + 1
            TIEM[i] = (a0 + (b0 - a0) * acc / L, a0 + (b0 - a0) * (acc + n) / L); acc += n
# palabras del guion que la voz no dijo (o whisper no oyó): se reparten entre los vecinos con tiempo
i = 0
while i < len(TIEM):
    if TIEM[i] is None:
        j = i
        while j < len(TIEM) and TIEM[j] is None:
            j += 1
        a0 = TIEM[i - 1][1] if i > 0 else 0.0
        b0 = TIEM[j][0] if j < len(TIEM) else DUR_VOZ
        for q in range(i, j):
            TIEM[q] = (a0 + (b0 - a0) * (q - i) / (j - i), a0 + (b0 - a0) * (q - i + 1) / (j - i))
        i = j
    else:
        i += 1
SUBS = [{"t": t, "seg": k, "a": TIEM[i][0], "b": TIEM[i][1]} for i, (t, k) in enumerate(g_tok)]
print("alineación:", sum(1 for o in difflib.SequenceMatcher(None, gn, wn, autojunk=False).get_matching_blocks() for _ in range(o.size)), "de", len(gn), "palabras exactas")
for i in range(1, len(SUBS)):  # sin solapes
    SUBS[i]["a"] = max(SUBS[i]["a"], SUBS[i - 1]["b"] - 0.02)

# inicio de cada segmento (para cambiar de foto)
seg_ini = {}
for s in SUBS:
    seg_ini.setdefault(s["seg"], s["a"])
seg_ini[0] = 0.0
if CIERRE_T0 is not None:
    seg_ini[len(spec["segmentos"]) - 1] = CIERRE_T0

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
    im = Image.open(os.path.join(FOTOS, (f"{foto:02d}.jpg" if foto < 100 else f"{foto}.jpg"))).convert("RGB")
    esc = max(W / im.width, H / im.height)
    bg = im.resize((int(im.width * esc) + 2, int(im.height * esc) + 2), Image.BILINEAR)
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H)).filter(ImageFilter.GaussianBlur(38))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (8, 20, 28)), 0.35)
    # foto completa: cabe en 90% del ancho y 60% del alto (a 1,2x para que el zoom no se vea borroso)
    e2 = min(W * 0.90 / im.width, H * 0.60 / im.height) * 1.2
    fg = im.resize((int(im.width * e2), int(im.height * e2)), Image.LANCZOS)
    CARAS[foto] = caras(im)
    CACHE[foto] = (bg, fg, r_esq(fg)); return CACHE[foto]


# ---------- rostros: los subtítulos nunca van encima de una cara ----------
CARAS = {}       # foto -> lista de (x0, y0, x1, y1) en fracción de la foto
CARA_ACTUAL = []  # cajas de rostro en pantalla (px) de la toma que se está dibujando
try:
    import cv2
    cv2.setLogLevel(0) if hasattr(cv2, "setLogLevel") else None
    _YUNET = os.path.join(BASE, "fuentes", "rostros", "yunet.onnx")
    _DET = os.path.exists(_YUNET)
except Exception:
    _DET = False
def caras(im):
    """Rostros (detector YuNet de OpenCV), agrandados para cubrir pelo, mentón y cuello."""
    if not _DET:
        return []
    e = 640 / max(im.size); m = im.resize((int(im.width * e), int(im.height * e)))
    a = np.asarray(m)[:, :, ::-1].copy()
    det = cv2.FaceDetectorYN.create(_YUNET, "", (a.shape[1], a.shape[0]), 0.75)
    _, fs = det.detect(a)
    out = []
    for r in (fs if fs is not None else []):
        x, y, w, h = [float(v) for v in r[:4]]
        if w < a.shape[1] * 0.03:          # caras diminutas al fondo no importan
            continue
        out.append(((x - 0.3 * w) / a.shape[1], (y - 0.45 * h) / a.shape[0], (x + 1.3 * w) / a.shape[1], (y + 1.5 * h) / a.shape[0]))
    return out

usadas = {s["foto"] for s in spec["segmentos"] if "foto" in s} | {x for s in spec["segmentos"] for x in s.get("fotos", [])}
POOL = [int(f.split(".")[0]) for f in sorted(os.listdir(FOTOS)) if f.endswith(".jpg") and int(f.split(".")[0]) not in usadas and int(f.split(".")[0]) not in spec.get("excluir", [])]
if spec.get("pool"):
    POOL = [x for x in spec["pool"] if x not in usadas] or POOL
semilla = sum(ord(c) for c in nombre); POOL = POOL[semilla % max(1, len(POOL)):] + POOL[:semilla % max(1, len(POOL))]
TOMAS = []  # (inicio, fin, foto, dirección)
VID_INI = {}
segs = spec["segmentos"]; ip = 0
for k, s_ in enumerate(segs):
    a = seg_ini.get(k, 0.0)
    b = seg_ini.get(k + 1, DUR_VOZ) if k + 1 < len(segs) else DUR_VOZ + 0.15
    if s_.get("video"):                      # toma de video (clip IA o grabado): ocupa todo el segmento, pantalla completa
        vid = s_["video"]
        ini_v = VID_INI.setdefault(vid, a)    # si el segmento anterior usó el mismo video, sigue corriendo
        TOMAS.append((a, b, ("v", vid, ini_v), 0))
        continue
    partes = max(1, round((b - a) / 2.0))  # una toma cada ~2 s; la primera es la foto del texto, las demás otras fotos tuyas
    for j in range(partes):
        extra = s_.get("fotos", [])
        foto = s_["foto"] if j == 0 else (extra[j - 1] if j - 1 < len(extra) else (POOL[(ip := ip + 1) % len(POOL)] if POOL else s_["foto"]))
        TOMAS.append((a + (b - a) * j / partes, a + (b - a) * (j + 1) / partes, foto, (k * 3 + j) % 4))
FOTO_Y = int(H * 0.40)


def ease(x):
    return 1 - (1 - min(max(x, 0), 1)) ** 3


# ---------- clips de video (pantalla completa, se leen en orden con ffmpeg) ----------
_VIDS = {}
RECORTE = {s_["video"]: s_.get("recorte", 1) for s_ in spec["segmentos"] if s_.get("video")}  # >1 acerca el clip (p. ej. para sacar marcas de agua)
def cuadro_video(ruta, tv):
    st = _VIDS.get(ruta)
    ruta_abs = ruta if os.path.isabs(ruta) else os.path.join(BASE, ruta)
    if ruta.startswith("http"):              # clip subido por el puente (Supabase redes/clips/): se descarga una vez
        ruta_abs = os.path.join(tmp, os.path.basename(ruta.split("?")[0]))
        if not os.path.exists(ruta_abs):
            open(ruta_abs, "wb").write(urllib.request.urlopen(ruta, timeout=120).read())
    if st is None:
        cmd = ["ffmpeg", "-loglevel", "error", "-i", ruta_abs, "-vf",
               f"fps={FPS},scale={int(W * RECORTE.get(ruta, 1))}:{int(H * RECORTE.get(ruta, 1))}:force_original_aspect_ratio=increase,crop={W}:{H}:(in_w-{W})/2:(in_h-{H})*0.35",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        st = _VIDS[ruta] = {"p": subprocess.Popen(cmd, stdout=subprocess.PIPE), "i": -1, "img": None, "caras": {}}
    n = max(0, int(tv * FPS))
    while st["i"] < n:
        raw = st["p"].stdout.read(W * H * 3)
        if len(raw) < W * H * 3:
            break                              # se acabó el clip: queda congelado el último cuadro
        st["img"] = Image.frombytes("RGB", (W, H), raw); st["i"] += 1
        if st["i"] % 6 == 0 or not st["caras"]:  # rostros cada 6 cuadros (los subtítulos los esquivan)
            st["caras"]["u"] = [(c[0] * W, c[1] * H, c[2] * W, c[3] * H) for c in caras(st["img"])]
    CARA_ACTUAL[:] = st["caras"].get("u", [])
    return st["img"].copy() if st["img"] is not None else Image.new("RGB", (W, H))


def fondo(t):
    for (a, b, foto, d) in TOMAS:
        if a <= t < b:
            break
    else:
        a, b, foto, d = TOMAS[-1]
    if isinstance(foto, tuple):
        return cuadro_video(foto[1], t - foto[2]), a
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
    CARA_ACTUAL[:] = [(x + c[0] * w2, y + c[1] * h2, x + c[2] * w2, y + c[3] * h2) for c in CARAS.get(foto, [])]
    if a > 0 and t - a < 0.1:                                 # barrido: la imagen entra deslizándose con desenfoque
        k = 1 - (t - a) / 0.1
        desp = int(k * 140) * (1 if d % 2 == 0 else -1)
        fr = fr.transform(fr.size, Image.AFFINE, (1, 0, desp, 0, 1, 0)).filter(ImageFilter.BoxBlur(int(6 + 18 * k)))
        fr = Image.blend(fr, Image.new("RGB", (W, H), BLANCO), 0.25 * k)
    return fr, a


# ---------- capas de texto ----------
f_sub = ImageFont.truetype(F_BLACK, 92)
f_sub_g = ImageFont.truetype(F_BLACK, 104)
F_POP = [ImageFont.truetype(F_BLACK, z) for z in (118, 112, 108, 104)]  # la palabra activa entra grande y se asienta
f_hook = ImageFont.truetype(F_BLACK, 88)
f_peq = ImageFont.truetype(F_BOLD, 30)
f_marca = ImageFont.truetype(F_BLACK, 110)
f_wa = ImageFont.truetype(F_BLACK, 58)
f_med = ImageFont.truetype(F_BOLD, 46)


def texto_borde(d, xy, txt, font, fill, stroke=9):
    d.text(xy, txt, font=font, fill=fill, stroke_width=stroke, stroke_fill=NEGRO)


def subtitulo(d, t):
    g = next((g for g in reversed(GRUPOS) if g[0]["a"] - 0.02 <= t < g[-1]["b"] + 0.18), None)
    if not g or t > DUR_VOZ + 0.2:
        return
    pop = 0.85 + 0.15 * ease((t - g[0]["a"]) / 0.12)
    palabras_ = [s["t"].upper() for s in g]
    activos = [s["a"] <= t < s["b"] + 0.05 for s in g]
    fonts = []
    for s_, act in zip(g, activos):
        if act:
            k = ease((t - s_["a"]) / 0.09); fonts.append(F_POP[min(len(F_POP) - 1, int(k * (len(F_POP) - 1)))])
        else:
            fonts.append(f_sub)
    esp = 24
    anchos = [d.textlength(p, font=f) for p, f in zip(palabras_, fonts)]
    total = sum(anchos) + esp * (len(palabras_) - 1)
    # reparte en líneas que quepan en el ancho (antes una palabra larga se salía de la pantalla)
    lineas, i0, acc = [], 0, 0
    for i, a_ in enumerate(anchos):
        if i > i0 and acc + esp + a_ > W - 120:
            lineas.append([i0, i]); i0, acc = i, a_
        else:
            acc = a_ if i == i0 else acc + esp + a_
    lineas.append([i0, len(palabras_)])
    for k_, (i0, i1) in enumerate(lineas):             # si aún así una palabra sola no cabe, se achica
        w_l = sum(anchos[i0:i1]) + esp * (i1 - i0 - 1)
        if w_l > W - 80:
            f_ = W - 80
            for i in range(i0, i1):
                fonts[i] = fonts[i].font_variant(size=max(50, int(fonts[i].size * f_ / w_l))); anchos[i] = d.textlength(palabras_[i], font=fonts[i])
    alto = 118 * len(lineas) + 30
    y = sub_y(alto) + int((1 - pop) * 60)
    for (i0, i1) in lineas:
        w_l = sum(anchos[i0:i1]) + esp * (i1 - i0 - 1)
        x = (W - w_l) / 2
        for i in range(i0, i1):
            col = AMARILLO if activos[i] else BLANCO
            texto_borde(d, (x, y - (8 if activos[i] else 0)), palabras_[i], fonts[i], col)
            x += anchos[i] + esp
        y += 118


def sub_y(alto):
    # posición normal: 70% de la altura; si choca con un rostro, se busca la franja libre más cercana
    def choca(y0):
        return any(not (y0 + alto < c[1] or y0 > c[3]) for c in CARA_ACTUAL)
    normal = int(H * 0.70)
    if not choca(normal):
        return normal
    for y0 in sorted(range(int(H * 0.27), int(H * 0.86) - alto, 20), key=lambda v: abs(v - normal)):
        if not choca(y0):
            return y0
    return int(H * 0.86) - alto


def gancho(d, t):
    if t > 2.6 or not spec.get("gancho"):
        return
    entra = 0.75 + 0.25 * ease(t / 0.15); sale = 1 - ease((t - 2.3) / 0.3)
    txt = spec["gancho"].upper()
    lineas, cur = [], ""
    for p in txt.split():
        if d.textlength((cur + " " + p).strip(), font=f_hook) > W - 140:
            lineas.append(cur); cur = p
        else:
            cur = (cur + " " + p).strip()
    lineas.append(cur)
    y = 230 - int((1 - entra) * 120)
    for l in lineas:
        w_l = d.textlength(l, font=f_hook)
        x = (W - w_l) / 2 + math.sin(t * 40) * 6 * (1 - ease(t / 0.4))
        d.rounded_rectangle([x - 26, y - 14, x + w_l + 26, y + 104], 18, fill=(*AMARILLO, int(245 * sale)))
        d.text((x, y), l, font=f_hook, fill=(*NEGRO, int(255 * sale)))
        y += 124


_FC = {}
def fuente(z):
    z = max(10, z - z % 2)
    if z not in _FC: _FC[z] = ImageFont.truetype(F_BLACK, z)
    return _FC[z]

COLORES_TREN = [(11, 110, 117), (0, 120, 200), (29, 140, 70), (11, 110, 117), (230, 140, 0), (0, 120, 200), (29, 140, 70), (11, 110, 117)]
def f_ajuste(txt, maxw, size=118):
    f = ImageFont.truetype(F_BLACK, size)
    while ImageDraw.Draw(Image.new("L", (1, 1))).textlength(txt, font=f) > maxw and size > 50:
        size -= 6; f = ImageFont.truetype(F_BLACK, size)
    return f

_dm = ImageDraw.Draw(Image.new("L", (1, 1)))
TAM_TREN = []
for _t in TREN:   # tamaño inicial: la palabra llena el ancho (máx. 170 px de alto)
    z = 170
    while _dm.textlength(_t, font=fuente(z)) > W - 110 and z > 60: z -= 4
    TAM_TREN.append(z)

_LP = os.path.join(BASE, "fuentes", "logo_hidrofresh.png")
LOGO = Image.open(_LP).convert("RGBA") if os.path.exists(_LP) else None


def cierre(d, t, im=None):
    u = t - (DUR_VOZ + 0.15)
    if u < 0:
        return
    a0 = ease(u / 0.22)
    d.rectangle([0, 0, W, H], fill=(255, 255, 255, int(255 * a0)))   # página blanca
    if im is not None and a0 >= 1:
        im.alpha_composite(VINETA_CLARA)
    v = u - 0.25
    if v < 0:
        return
    fin_tren = (len(TREN) - 1) * PASO + VIDA
    if v < fin_tren:
        # cada palabra nace grande y se va al fondo (se achica, sube un poco y se desvanece), con estela
        for i in range(len(TREN) - 1, -1, -1):
            r = (v - i * PASO) / VIDA
            if not 0 <= r <= 1:
                continue
            base = TAM_TREN[i]
            for k, (dr, alfa) in enumerate([(0.0, 1.0)]):
                rr = max(0.0, r - dr)
                esc = 1 - ease(rr) * 0.86
                op = (1 - ease(max(0, rr - 0.35) / 0.65)) * min(1, rr / 0.05 + 0.4) * alfa
                if esc <= 0.05 or op <= 0.02:
                    continue
                f = fuente(int(base * esc))
                wl = d.textlength(TREN[i], font=f)
                y = H * 0.47 - base * 0.42 * esc - 420 * ease(rr)
                col = COLORES_TREN[i % len(COLORES_TREN)]
                d.text(((W - wl) / 2, y), TREN[i], font=f, fill=(*col, int(255 * op)))
        return
    w = v - fin_tren                                         # marca: llega desde el fondo con rebote
    pop = ease(w / 0.3) * (1 + 0.08 * math.sin(min(w, 0.7) * 14) * (1 - min(1, w / 0.7)))
    if LOGO is not None and im is not None and pop > 0.02:   # logo oficial (fuentes/logo_hidrofresh.png)
        lw = int(900 * pop); lh = int(LOGO.height * lw / LOGO.width)
        lg = LOGO.resize((lw, lh), Image.LANCZOS)
        im.alpha_composite(lg, ((W - lw) // 2, int(H * 0.40 - lh / 2 - 40)))
        y_sub = H * 0.40 + 900 * LOGO.height / LOGO.width / 2 - 10
    else:
        f = fuente(int(150 * pop))
        txt = "HIDRO FRESH"; wl = d.textlength(txt, font=f)
        d.text(((W - wl) / 2, H * 0.40 - 75 * pop), txt, font=f, fill=(0, 120, 200, 255))
        y_sub = H * 0.40 + 110
    sub = "Plantas de tratamiento · Cloro · Bacterias"; wl = d.textlength(sub, font=f_med)
    d.text(((W - wl) / 2, y_sub), sub, font=f_med, fill=(11, 110, 117, int(255 * ease((w - 0.25) / 0.3))))
    if w > 0.4:
        a = ease((w - 0.4) / 0.3); pulso = 1 + 0.07 * (0.5 + 0.5 * math.sin(w * 10))   # botón que late
        txt = "COTIZA POR WHATSAPP"; wt = d.textlength(txt, font=f_wa)
        bw = (wt + 100) * pulso; bh = 130 * pulso; bx = (W - bw) / 2; by = 1250 - bh / 2
        for k in range(3):                                   # halo que se expande (incita a tocar)
            r = ((w * 1.4 + k / 3) % 1)
            d.rounded_rectangle([bx - 60 * r, by - 60 * r, bx + bw + 60 * r, by + bh + 60 * r], int(bh / 2 + 60 * r),
                                outline=tuple(int(255 + (cv - 255) * 0.55 * (1 - r) * a) for cv in VERDE) + (255,), width=6)
        d.rounded_rectangle([bx, by, bx + bw, by + bh], int(bh / 2), fill=(*VERDE, int(250 * a)))
        d.text(((W - wt) / 2, by + bh / 2 - 34), txt, font=f_wa, fill=(*BLANCO, int(255 * a)))
        sub2 = "+56 9 8494 6508  ·  toca el link del perfil"; ws2 = d.textlength(sub2, font=f_med)
        if int(w * 2.5) % 2 == 0 or w < 1.2:                 # parpadea
            d.text(((W - ws2) / 2, 1360), sub2, font=f_med, fill=(11, 110, 117, int(255 * a)))
        sub3 = "Desde 2008 · 18 años de experiencia"; ws3 = d.textlength(sub3, font=f_med)
        d.text(((W - ws3) / 2, 1440), sub3, font=f_med, fill=(40, 60, 110, int(255 * ease((w - 0.7) / 0.3))))


SOMBRA = Image.new("RGBA", (W, H), (0, 0, 0, 0))
_g = np.zeros((H, W, 4), np.uint8); _y = np.arange(H)
_g[:, :, 3] = (np.clip((_y - H * 0.62) / (H * 0.18), 0, 1) * 110).astype(np.uint8)[:, None]
SOMBRA = Image.fromarray(_g, "RGBA")


# viñeta (bordes oscuros) y viñeta clara para la página blanca
_yy, _xx = np.mgrid[0:H, 0:W]; _r = np.sqrt(((_xx - W / 2) / (W * 0.62)) ** 2 + ((_yy - H / 2) / (H * 0.62)) ** 2)
_v = np.zeros((H, W, 4), np.uint8); _v[:, :, 3] = (np.clip(_r - 0.55, 0, 1) * 150).astype(np.uint8)
VINETA = Image.fromarray(_v, "RGBA")
_c = np.zeros((H, W, 4), np.uint8); _c[:, :, :3] = (205, 225, 228); _c[:, :, 3] = (np.clip(_r - 0.45, 0, 1) * 160).astype(np.uint8)
VINETA_CLARA = Image.fromarray(_c, "RGBA")
# grano de película: 6 texturas que rotan
_rng = np.random.default_rng(7)
GRANOS = []
for _ in range(6):
    gn = _rng.normal(128, 40, (H // 2, W // 2)).clip(0, 255).astype(np.uint8)
    g4 = np.zeros((H // 2, W // 2, 4), np.uint8); g4[:, :, :3] = gn[:, :, None]; g4[:, :, 3] = 14
    GRANOS.append(Image.fromarray(g4, "RGBA").resize((W, H), Image.NEAREST))
# destello de luz cálida (light leak) que cruza la pantalla en algunos cortes
_lx = np.linspace(-1, 1, W)[None, :]; _ly = np.linspace(-1, 1, H)[:, None]
_l = np.exp(-((_lx * 1.2 + _ly * 0.6) ** 2) / 0.08)
_lk = np.zeros((H, W, 4), np.uint8); _lk[:, :, 0] = 255; _lk[:, :, 1] = 170; _lk[:, :, 2] = 80; _lk[:, :, 3] = (_l * 120).astype(np.uint8)
LEAK = Image.fromarray(_lk, "RGBA")


def capa(t):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # degradado oscuro abajo para que se lean los subtítulos
    if t < DUR_VOZ + 0.15:
        im.alpha_composite(SOMBRA)
    if t < DUR_VOZ + 0.15:
        im.alpha_composite(VINETA)
        for (a, b, f_, d_) in TOMAS[2::3]:                  # destello cálido cada 3 cortes
            if 0 <= t - a < 0.45:
                k = (t - a) / 0.45
                im.alpha_composite(Image.eval(LEAK.transform(LEAK.size, Image.AFFINE, (1, 0, int((k - 0.5) * W * 1.4), 0, 1, 0)), lambda x: x).copy(), (0, 0))
                break
    gancho(d, t); subtitulo(d, t); cierre(d, t, im)
    if t < DUR_VOZ + 0.15:
        im.alpha_composite(GRANOS[int(t * FPS) % len(GRANOS)])
    # barra de progreso
    d.rectangle([0, 0, int(W * min(1, t / TOTAL)), 12], fill=(*VERDE, 255))
    d.text((40, H - 70), "Voz e imágenes con IA" if RECORTE else "Voz generada con IA", font=f_peq, fill=(255, 255, 255, 170) if t < DUR_VOZ + 0.3 else (90, 110, 112, 200))
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
marcas = [a for (a, b, f_, d_) in TOMAS[1:]] + [DUR_VOZ + 0.15] + [DUR_VOZ + 0.4 + k * PASO for k in range(len(TREN))]  # barridos
for k, a in enumerate(marcas):
    i = int(max(0, a - 0.12) * sr); g = 0.6 if k > len(TOMAS) else 1.0
    pista[i:i + len(ws)] += g * ws[:len(pista) - i]
def musica(dur):
    n = int(dur * sr); tt = np.arange(n) / sr; bpm = 104; beat = 60 / bpm
    acordes = [(220.0, 277.18, 329.63), (196.0, 246.94, 293.66), (174.61, 220.0, 261.63), (196.0, 246.94, 329.63)]
    m = np.zeros(n, np.float32)
    for i, ac in enumerate(acordes * 20):
        a = int(i * 4 * beat * sr); b = min(n, int((i + 1) * 4 * beat * sr))
        if a >= n: break
        seg = tt[a:b] - tt[a]; env = np.minimum(1, seg / 0.4) * np.minimum(1, (4 * beat - seg) / 0.4)
        for f0 in ac:
            m[a:b] += 0.05 * env * (np.sin(2 * np.pi * f0 * seg) + 0.3 * np.sin(2 * np.pi * f0 * 2 * seg))
    for k in range(int(dur / beat)):                       # pulso suave tipo bombo
        a = int(k * beat * sr); L = min(int(0.18 * sr), n - a)
        if L <= 0: break
        sg = np.arange(L) / sr; m[a:a + L] += 0.22 * np.sin(2 * np.pi * (55 + 60 * np.exp(-sg * 30)) * sg) * np.exp(-sg * 18)
    return m

mus = musica(TOTAL + 1)[:len(pista)]
env_voz = np.convolve(np.abs(pista), np.ones(int(sr * 0.25)) / (sr * 0.25), "same")
ducking = 1 - 0.75 * np.clip(env_voz / (env_voz.max() * 0.25 + 1e-9), 0, 1)   # la música baja cuando habla
pista += mus * 0.35 * ducking
ib = int((DUR_VOZ + 0.4 + (len(TREN) - 1) * PASO + VIDA) * sr)              # golpe grave al aparecer la marca
L = min(int(0.6 * sr), len(pista) - ib)
if L > 0:
    sg = np.arange(L) / sr; pista[ib:ib + L] += 0.35 * np.sin(2 * np.pi * (40 + 80 * np.exp(-sg * 12)) * sg) * np.exp(-sg * 5)
pista = pista[:int(TOTAL * sr)]
pista *= 0.95 / max(1e-6, np.abs(pista).max())
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
