# Cómo hacer un reel nuevo

1. Escribir `guiones/reelN.json` (gancho + 5-8 segmentos, 22-30 s, cierre con WhatsApp). Planta de tratamiento primero; cloro y bacterias después. Nunca nombrar clientes.
2. Modelos de voz (si faltan): `kokoro-v1.0.int8.onnx` y `voices-v1.0.bin` desde
   https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0 en `$KOKORO_DIR` (pip: kokoro-onnx soundfile).
3. `python3 armar.py guiones/reelN.json` → `salida/reelN.mp4`. Revisar fotogramas antes de subir.
4. Commit y push a `main`.
5. En Supabase (proyecto mplgrbwehbzmksjzgqsd) agregar la fila en `ig_posts` (n, tipo REELS, titulo, video `reelN.mp4`, caption, fecha_publicacion, estado `programado`).
   `ig-publicar` (cron cada 15 min) descarga el video desde este repo al bucket `redes` y lo publica en Instagram y Facebook.
