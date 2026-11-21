# Panel de León · Mercado Público (respaldo)

- Panel web: https://hidrofresh.cl/leon/ (archivos en `panel-leon/`, versión L1.1). Usuario `leon`.
- Supabase: proyecto `leon-mercadopublico` (ref vidtrslosuiqsppdpugl, São Paulo).
- Base de datos: copia de la estructura del panel de Hidro Fresh (función `respaldo_esquema()` del proyecto principal), aplicada con la función `aplicar-sql`.
- Funciones de Mercado Público: se copian desde el proyecto de Hidro Fresh con el workflow `.github/workflows/copiar-leon.yml` (secreto `SUPABASE_ACCESS_TOKEN`). Para volver a copiarlas: Actions → «Copiar funciones al panel de León» → Run workflow.
- Propias de León: `reporte` (reporte diario) y `aplicar-sql` (en `funciones/`).
- Reporte diario 08:00 a leonfuenza27@gmail.com: lo envía el script de Gmail de hidrofreshcomercial (función `reporteLeon`).
- Avisos al celular: app ntfy, tema `leon-mp-f955507f55`.
- Secretos en Supabase de León: MERCADOPUBLICO_TICKET (listo), GEMINI_API_KEY (pendiente, para la IA).
