// deno-lint-ignore-file no-explicit-any
import { createClient } from "npm:@supabase/supabase-js@2";
// reporte v1.1 (panel León, estructura del panel completo): arma el reporte diario por correo. Lo pide el script de Gmail con x-mail-token y lo envía.
function svc() {
  const raw = Deno.env.get("SUPABASE_SECRET_KEYS");
  const k = raw ? JSON.parse(raw)["default"] : Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  return createClient(Deno.env.get("SUPABASE_URL")!, k!);
}
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "content-type": "application/json" } });
const esc = (s: any) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const clp = (n: any) => n ? "$" + Math.round(Number(n)).toLocaleString("es-CL") : "monto no informado";
const fCh = (f: any) => { if (!f) return "—"; const d = new Date(f); return d.toLocaleDateString("es-CL", { day: "2-digit", month: "short", timeZone: "America/Santiago" }) + " " + d.toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit", timeZone: "America/Santiago" }); };
const urlMP = (o: any) => o.tipo_compra === "Compra Ágil" ? `https://buscador.mercadopublico.cl/ficha?code=${encodeURIComponent(o.codigo)}` : `https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idlicitacion=${encodeURIComponent(o.codigo)}`;

Deno.serve(async (req) => {
  const sb = svc();
  try {
    const { data: t } = await sb.from("app_config").select("valor").eq("clave", "mail_token").maybeSingle();
    if (!t?.valor || req.headers.get("x-mail-token") !== String(t.valor)) return json({ error: "no autorizado" }, 401);
    const { data: pu } = await sb.from("app_config").select("valor").eq("clave", "panel_url").maybeSingle();
    const PANEL = pu?.valor ?? "https://hidrofresh.cl/leon/";
    const ahora = Date.now(), h24 = new Date(ahora - 864e5).toISOString(), hoy = new Date(ahora).toISOString();
    const { data: ops } = await sb.from("oportunidades").select("codigo,titulo,tipo_compra,unidad_compra,region,presupuesto,fecha_cierre,creado_en,interes_estado,rubros")
      .gt("fecha_cierre", hoy).neq("interes_estado", "DESCARTADA").order("fecha_cierre", { ascending: true }).limit(500);
    const { data: rb } = await sb.from("rubros").select("id,nombre,activo").eq("archivado", false).neq("id", "hidrofresh");
    const nomR: Record<string, string> = {}; for (const r of rb ?? []) nomR[r.id] = r.nombre;
    const O = ops ?? [];
    const nuevas = O.filter((o: any) => o.creado_en >= h24 && o.interes_estado === "PENDIENTE").sort((a: any, b: any) => (b.presupuesto ?? 0) - (a.presupuesto ?? 0));
    const cierran = O.filter((o: any) => +new Date(o.fecha_cierre) - ahora < 2 * 864e5 && ["INTERESADA", "PENDIENTE"].includes(o.interes_estado)).slice(0, 15);
    const interes = O.filter((o: any) => o.interes_estado === "INTERESADA");
    const li = (a: any[]) => a.length ? "<ul style=\"margin:4px 0 12px;padding-left:18px\">" + a.map((o: any) => `<li style="margin:4px 0"><a href="${urlMP(o)}"><b>${esc(o.titulo)}</b></a><br><span style="color:#555;font-size:13px">${o.tipo_compra === "Compra Ágil" ? "⚡ Compra Ágil" : "📄 Licitación"} · ${esc(o.unidad_compra ?? "")}${o.region ? " · " + esc(o.region) : ""} · ${clp(o.presupuesto)} · cierra ${fCh(o.fecha_cierre)}${(o.rubros ?? []).length ? " · " + esc((o.rubros ?? []).map((x: string) => nomR[x] ?? x).join(", ")) : ""}</span></li>`).join("") + "</ul>" : "<p style=\"color:#777;margin:4px 0 12px\">Nada por ahora.</p>";
    const h2 = (t: string) => `<h3 style="margin:18px 0 4px;font-size:16px;color:#1d3557">${t}</h3>`;
    const dia = new Date(ahora - 3 * 3600e3).toISOString().slice(0, 10).split("-").reverse().join("-");
    const activos = (rb ?? []).filter((r: any) => r.activo).map((r: any) => r.nombre);
    const html = `<div style="font-family:Arial,sans-serif;font-size:14px;color:#1d2433;max-width:680px">
  <h2 style="margin:0 0 4px;color:#1d3557">Mercado Público · Reporte del ${dia}</h2>
  <p style="margin:0 0 12px;color:#555">Buscando: ${activos.length ? esc(activos.join(", ")) : "<b>sin búsquedas activas</b> (agrégalas en el panel)"} · <a href="${PANEL}">Abrir mi panel</a></p>
  ${h2(`🆕 Nuevas en las últimas 24 h (${nuevas.length})`)}${li(nuevas.slice(0, 25))}
  ${h2(`⏰ Cierran en menos de 48 h (${cierran.length})`)}${li(cierran)}
  ${h2(`⭐ Las que marcaste «Me interesa» (${interes.length})`)}${li(interes.slice(0, 15))}
  <p style="color:#888;font-size:12px;margin-top:16px">Reporte automático de tu panel de Mercado Público. Para cambiar qué se busca entra al panel → «🔎 Mi búsqueda».</p></div>`;
    const asunto = `Mercado Público · ${nuevas.length} nuevas · ${cierran.length} cierran pronto`;
    const { data: dest } = await sb.from("app_config").select("valor").eq("clave", "reporte_para").maybeSingle();
    await sb.from("app_config").upsert({ clave: "reporte_ultimo", valor: new Date().toISOString() });
    return json({ ok: true, para: dest?.valor ?? "leonfuenza27@gmail.com", asunto, html, nuevas: nuevas.length });
  } catch (e) {
    return json({ error: e instanceof Error ? e.message : String(e) }, 500);
  }
});
