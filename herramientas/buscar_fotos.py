# Busca fotos de dominio público (CC0 / PDM) en Openverse y arma una hoja de contacto por tema.
import json, sys, os, io, urllib.request, urllib.parse
from PIL import Image, ImageDraw, ImageFont
temas = json.load(open("herramientas/temas_fotos.json"))
os.makedirs("banco", exist_ok=True)
F = ImageFont.truetype("fuentes/Inter-Black.otf", 26)
UA = {"User-Agent": "hidrofresh-reels/1.0 (github actions)"}
creditos = {}
for tema, q in temas.items():
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({"action": "query", "format": "json", "generator": "search",
        "gsrsearch": q + " filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 50, "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1200})
    try:
        pags = sorted(json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40))["query"]["pages"].values(), key=lambda p: p.get("index", 99))
        res = []
        for p in pags:
            ii = p["imageinfo"][0]; lic = ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "").lower()
            if "cc0" in lic or "public domain" in lic or lic.startswith("pd"):
                res.append({"url": ii.get("thumburl", ii["url"]), "foreign_landing_url": ii["descriptionurl"], "license": lic})
    except Exception as e:
        print(tema, "error", e); continue
    ims = []
    for r in res:
        if len(ims) >= 8: break
        try:
            im = Image.open(io.BytesIO(urllib.request.urlopen(urllib.request.Request(r["url"], headers=UA), timeout=30).read())).convert("RGB")
            if min(im.size) < 500: continue
            im.thumbnail((1400, 1400)); k = len(ims) + 1
            im.save(f"banco/{tema}_{k}.jpg", quality=88); ims.append(im)
            creditos[f"{tema}_{k}"] = {"fuente": r.get("foreign_landing_url"), "licencia": r.get("license")}
        except Exception as e:
            print(tema, "img", e)
    print(tema, len(ims))
    import time; time.sleep(1)
    if ims:
        T = 260; S = Image.new("RGB", (T * 4, T * 2), "white"); d = ImageDraw.Draw(S)
        for i, im in enumerate(ims):
            t = im.copy(); t.thumbnail((T, T)); x, y = (i % 4) * T, (i // 4) * T
            S.paste(t, (x, y)); d.rectangle([x, y, x + 40, y + 32], fill="black"); d.text((x + 6, y), str(i + 1), font=F, fill="yellow")
        S.save(f"banco/_hoja_{tema}.jpg", quality=80)
json.dump(creditos, open("banco/creditos.json", "w"), indent=1)
