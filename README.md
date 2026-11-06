# Reels Hidro Fresh

Reels verticales para Instagram (@hidrofresh.cl) y la página de Facebook, hechos gratis:
voz con IA (Kokoro, acento latino), fotos reales de plantas, subtítulos y cierre con el WhatsApp.

- `guiones/reelN.json`: texto de cada escena y la foto que la acompaña.
- `fotos/NN.jpg`: fotos de obras y plantas, sin datos de clientes.
- `armar.py`: arma el video (`python3 armar.py guiones/reelN.json`).
- `salida/reelN.mp4`: videos listos. El publicador de Supabase (`ig-publicar`) los trae solo desde aquí
  al bucket `redes` y los publica según la fecha de `ig_posts`.
