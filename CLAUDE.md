# Cómo hacer un reel nuevo

1. Escribir `guiones/reelN.json` (gancho + 5-8 segmentos, 22-30 s, cierre con WhatsApp). Planta de tratamiento primero; cloro y bacterias después. Nunca nombrar clientes.
2. Voz: llamar a la función `ia-voz` de Supabase con {nombre, texto (líneas del guion separadas por salto de línea), voz:"Kore", estilo:"", validar:false} → redes/voz/<nombre>.wav. NO poner instrucciones de estilo: Gemini las lee en voz alta.
3. Push del guion a `main`: GitHub Actions (`.github/workflows/reels.yml`) arma `salida/reelN.mp4` con esa voz y lo sube al repo. Revisar fotogramas.
4. (Kokoro local queda solo como respaldo si no existe la voz de Gemini.)
5. En Supabase (proyecto mplgrbwehbzmksjzgqsd) agregar la fila en `ig_posts` (n, tipo REELS, titulo, video `reelN.mp4`, caption, fecha_publicacion, estado `programado`).
   `ig-publicar` (cron cada 15 min) descarga el video desde este repo al bucket `redes` y lo publica en Instagram y Facebook.

## Clips de video (vocera con IA)
- Un segmento puede llevar `"video": "videos/archivo.mp4"` en vez de `"foto"`: va a pantalla completa. Si dos segmentos seguidos usan el mismo video, el clip sigue corriendo.
- `"recorte": 1.14` acerca el clip (sirve para sacar la marca de agua de Hailuo).
- Clips: Google Flow (Veo, gratis ~5/día, opción Ingredients con foto de la vocera + foto de la planta) y Hailuo (Omni Reference). Pedir "plain black polo shirt, no logo" y "nobody else in the scene".
- Los subtítulos esquivan rostros solos (detector YuNet en `fuentes/rostros/yunet.onnx`).
