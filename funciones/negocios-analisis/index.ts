// deno-lint-ignore-file no-explicit-any
import { createClient } from "npm:@supabase/supabase-js@2";
// negocios-analisis v1 — Prospectos de nuevos negocios (panel de Hidro Fresh y panel de León vía su función puente).
// Fuentes oficiales/abiertas, costo USD 0:
//  • Mercado Público: términos de todas las órdenes de compra del país (mp_nac_term, resumido a diario en neg_mp_rank):
//    volumen 90 días, crecimiento vs los 90 días anteriores, % por Compra Ágil (lo más fácil de postular) y % por Convenio Marco.
//    "Estudiar" toma OC reales del rubro (API oficial de Mercado Público): cuántos proveedores distintos venden, cuánto se lleva
//    el principal, precios unitarios, y las Compras Ágiles abiertas hoy.
//  • Mercado Libre: su API exige sesión y su sitio bloquea robots, así que se usa el buscador Exa (índice web) sobre
//    mercadolibre.cl: publicaciones, rango de precios, tiendas, envíos internacionales y búsquedas relacionadas.
//  • Margen estimado = precio unitario pagado por el Estado vs precio bajo (p25) en Mercado Libre.
// Modos: {clasificar:{max?}} {ranking:{orden?,q?,rubro?,limite?}} {estudiar:{termino}} {ml:{q}} {comex:true} {origenes:"hs"}
function svc() {
  const raw = Deno.env.get("SUPABASE_SECRET_KEYS");
  const k = raw ? JSON.parse(raw)["default"] : Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  return createClient(Deno.env.get("SUPABASE_URL")!, k!);
}
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info, x-cron-token, x-ia-externo", "Access-Control-Allow-Methods": "POST, OPTIONS" };
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { ...CORS, "content-type": "application/json" } });
async function autorizado(req: Request, sb: any): Promise<boolean> {
  const cron = req.headers.get("x-cron-token");
  if (cron) {
    const { data } = await sb.from("app_config").select("clave,valor").in("clave", ["cron_token", "ia_externo_token"]);
    return (data ?? []).some((x: any) => !!x.valor && cron === String(x.valor) && (x.clave === "cron_token" || !!req.headers.get("x-ia-externo")));
  }
  const t = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, ""); if (!t) return false;
  const { data, error } = await sb.auth.getUser(t); const email = data?.user?.email?.toLowerCase(); if (error || !email) return false;
  const { data: u } = await sb.from("app_usuarios").select("activo").eq("email", email).maybeSingle(); return !!u?.activo;
}
const T0 = { v: 0 }; const resta = () => 140_000 - (Date.now() - T0.v);
const nrm = (s: any) => String(s ?? "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9ñ ]+/g, " ").replace(/\s+/g, " ").trim();
const med = (a: number[]) => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y); const m = Math.floor(s.length / 2); return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2); };
const pct = (a: number[], p: number) => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.max(0, Math.round((s.length - 1) * p)))]; };
const CFG: Record<string, string> = {};
async function cfg(sb: any) {
  const { data } = await sb.from("app_config").select("clave,valor").in("clave", ["cron_token", "exa_api_key", "linkup_api_key"]);
  for (const x of data ?? []) CFG[x.clave] = String(x.valor ?? "");
}
async function ia(prompt: string, sistema: string, max = 6000) {
  const r = await fetch(`${Deno.env.get("SUPABASE_URL")}/functions/v1/ia-router`, {
    method: "POST", signal: AbortSignal.timeout(Math.max(20_000, Math.min(100_000, resta() - 8000))),
    headers: { "Content-Type": "application/json", "x-cron-token": CFG.cron_token },
    body: JSON.stringify({ chat: { prompt, sistema, tarea: "extraccion", json: true, max_tokens: max, funcion: "negocios-analisis", limite_ms: Math.max(20_000, Math.min(95_000, resta() - 10000)) } }),
  });
  const j = await r.json().catch(() => null);
  if (!j?.ok) throw new Error(j?.error ?? "IA no disponible");
  const t = String(j.texto).replace(/^```(json)?/m, "").replace(/```\s*$/m, "").trim();
  return JSON.parse(t.slice(t.search(/[\[{]/)));
}

// ---------- clasificar términos (producto/servicio vs ruido) ----------
async function clasificar(sb: any, max = 450) {
  const { data: ya } = await sb.from("neg_term_clase").select("termino");
  const hechos = new Set((ya ?? []).map((x: any) => x.termino));
  const { data: cand } = await sb.from("neg_mp_rank").select("termino,rec").gte("rec", 30).order("rec", { ascending: false }).limit(6000);
  const pend = (cand ?? []).filter((x: any) => !hechos.has(x.termino)).slice(0, max).map((x: any) => x.termino);
  let hecho = 0; const errores: string[] = [];
  for (let i = 0; i < pend.length && resta() > 35_000; i += 150) {
    const lote = pend.slice(i, i + 150);
    try {
      const r = await ia(`Estos son términos (pares de palabras, sin tildes) sacados de los nombres de órdenes de compra del Estado de Chile en Mercado Público.
Para CADA término indica si describe un PRODUCTO o SERVICIO concreto que un proveedor podría vender (p:1) o si es ruido (p:0): nombres de personas, lugares, comunas, programas, glosas administrativas, números de resolución, palabras sueltas sin producto.
Devuelve JSON {"t":[{"t":"<término exacto>","p":0|1,"r":"<rubro corto si p=1: Alimentos, Aseo e higiene, Oficina y papelería, Computación, Ferretería y construcción, Salud e insumos médicos, Medicamentos, Mobiliario, Vestuario y textil, Eventos y regalos, Transporte, Mantención y reparaciones, Servicios profesionales, Educación y didácticos, Deporte y recreación, Vehículos y repuestos, Agua y medio ambiente, Seguridad, Otros>","e":0|1 (1 si es muy estacional, ej. fiestas patrias, navidad),"n":"<nombre legible en español con tildes>"}]}
Términos:\n${lote.join("\n")}`, "Responde SOLO con JSON válido.", 8000);
      const filas = (r?.t ?? []).filter((x: any) => lote.includes(String(x.t))).map((x: any) => ({ termino: String(x.t), producto: Number(x.p) === 1, rubro: x.p ? String(x.r ?? "Otros").slice(0, 40) : null, estacional: Number(x.e) === 1, nombre: String(x.n ?? x.t).slice(0, 80) }));
      if (filas.length) { await sb.from("neg_term_clase").upsert(filas, { onConflict: "termino" }); hecho += filas.length; }
    } catch (e) { errores.push(String((e as Error).message).slice(0, 160)); }
  }
  return { ok: true, clasificados: hecho, pendientes: Math.max(0, pend.length - hecho), errores };
}

// ---------- ranking ----------
async function ranking(sb: any, b: any) {
  const lim = Math.min(Number(b.limite) || 400, 1000);
  let q = sb.from("neg_mp_vista").select("*");
  const texto = nrm(b.q ?? "");
  if (texto) q = q.ilike("busca", `%${texto}%`); else q = q.eq("producto", true);
  if (b.rubro) q = q.eq("rubro", b.rubro);
  if (b.sin_estacionales !== false && !texto) q = q.neq("estacional", true);
  const orden = String(b.orden ?? "crec");
  if (orden === "crec") q = q.gte("ant", 15).order("crec_pct", { ascending: false, nullsFirst: false });
  else if (orden === "facil") q = q.gte("rec", 40).order("facilidad", { ascending: false }).order("rec", { ascending: false });
  else if (orden === "competencia") q = q.not("proveedores", "is", null).order("proveedores", { ascending: true }).order("rec", { ascending: false });
  else if (orden === "margen") q = q.not("margen_pct", "is", null).order("margen_pct", { ascending: false });
  else q = q.order("rec", { ascending: false });
  const { data, error } = await q.limit(lim);
  if (error) throw new Error(error.message);
  const { data: rb } = await sb.from("neg_term_clase").select("rubro").eq("producto", true);
  const rubros: Record<string, number> = {}; for (const x of rb ?? []) if (x.rubro) rubros[x.rubro] = (rubros[x.rubro] ?? 0) + 1;
  const { count: sinClase } = await sb.from("neg_mp_rank").select("termino", { count: "exact", head: true }).gte("rec", 30);
  const { count: conClase } = await sb.from("neg_term_clase").select("termino", { count: "exact", head: true });
  const { data: act } = await sb.from("neg_mp_rank").select("actualizado").limit(1);
  return { ok: true, filas: data ?? [], rubros, clasificados: conClase ?? 0, por_clasificar: Math.max(0, (sinClase ?? 0) - (conClase ?? 0)), actualizado: act?.[0]?.actualizado ?? null };
}

// ---------- Mercado Público: estudiar un término ----------
const API = "https://api.mercadopublico.cl/servicios/v1/publico";
async function mpApi(path: string, tk: string): Promise<any> {
  for (let i = 0; i < 3; i++) {
    try {
      const r = await fetch(`${API}/${path}${path.includes("?") ? "&" : "?"}ticket=${tk}`, { headers: { Accept: "application/json" }, signal: AbortSignal.timeout(15_000) });
      if (r.status === 429 || r.status >= 500) { await new Promise((ok) => setTimeout(ok, 1200 * (i + 1))); continue; }
      return await r.json();
    } catch (_) { await new Promise((ok) => setTimeout(ok, 800)); }
  }
  return null;
}
async function estudiarMP(sb: any, termino: string) {
  const tk = Deno.env.get("MERCADOPUBLICO_TICKET"); if (!tk) throw new Error("Falta MERCADOPUBLICO_TICKET");
  const palabras = nrm(termino).split(" ").filter((w) => w.length > 2);
  const patron = "%" + palabras.join("%") + "%";
  const { data: ocs } = await sb.from("mp_oc_nac").select("codigo,fecha,nombre,detalle").ilike("nombre", patron).order("fecha", { ascending: false }).limit(60);
  const L = ocs ?? [];
  const prov: Record<string, { n: number; monto: number; nombre: string }> = {}; const precios: number[] = []; const montos: number[] = []; const ejemplos: any[] = [];
  let vistas = 0;
  const usar = async (d: any, oc: any) => {
    if (!d) return; vistas++;
    const rut = String(d.Proveedor?.RutSucursal ?? d.proveedor_rut ?? "").trim(); const nom = String(d.Proveedor?.Nombre ?? d.proveedor ?? "").trim();
    const monto = Number(d.Total ?? d.TotalNeto ?? d.total ?? 0) || 0;
    if (rut || nom) { const k = rut || nom; prov[k] ??= { n: 0, monto: 0, nombre: nom }; prov[k].n++; prov[k].monto += monto; }
    if (monto) montos.push(monto);
    for (const it of d.Items?.Listado ?? d.items ?? []) {
      const tx = nrm(`${it.Producto ?? it.producto ?? ""} ${it.EspecificacionComprador ?? it.EspecificacionProveedor ?? it.detalle ?? ""}`);
      const p = Number(it.PrecioNeto ?? it.precio ?? 0);
      if (p > 0 && palabras.some((w) => tx.includes(w))) precios.push(p);
    }
    if (ejemplos.length < 8) ejemplos.push({ codigo: oc.codigo, fecha: oc.fecha, nombre: oc.nombre, proveedor: nom, monto, tipo: d.Tipo ?? d.tipo ?? null });
  };
  for (const oc of L) {
    if (resta() < 55_000 || vistas >= 25) break;
    if (oc.detalle && (oc.detalle.Proveedor || oc.detalle.proveedor)) { await usar(oc.detalle, oc); continue; }
    if (vistas >= 25) break;
    const j = await mpApi(`ordenesdecompra.json?codigo=${encodeURIComponent(oc.codigo)}`, tk);
    const d = j?.Listado?.[0]; if (d) { await usar(d, oc); sb.from("mp_oc_nac").update({ detalle: d, detalle_en: new Date().toISOString() }).eq("codigo", oc.codigo).then(() => {}, () => {}); }
  }
  const P = Object.values(prov).sort((a, b) => b.n - a.n);
  const totalN = P.reduce((s, x) => s + x.n, 0) || 0;
  const { data: ca } = await sb.from("ca_indice").select("codigo,nombre,organismo,region,fecha_cierre,monto").ilike("nombre", patron).eq("estado", "publicada").gt("fecha_cierre", new Date().toISOString()).order("fecha_cierre").limit(8);
  const { count: ca90 } = await sb.from("ca_indice").select("codigo", { count: "exact", head: true }).ilike("nombre", patron);
  return {
    ocs_encontradas: L.length, ocs_vistas: vistas,
    proveedores: P.length || null, top_proveedor: P[0]?.nombre ?? null, top_pct: totalN ? Math.round((P[0].n / totalN) * 100) : null,
    lideres: P.slice(0, 5).map((x) => ({ nombre: x.nombre, ocs: x.n, monto: Math.round(x.monto) })),
    precio_unit_med: med(precios), precio_unit_min: pct(precios, 0), precio_unit_max: pct(precios, 1), precios_n: precios.length,
    monto_oc_med: med(montos), ejemplos, ca_abiertas: ca ?? [], ca_total_indice: ca90 ?? 0,
  };
}

// ---------- Mercado Libre vía Exa ----------
async function estudiarML(q: string) {
  const k = CFG.exa_api_key; if (!k) throw new Error("Falta la clave del buscador (exa_api_key)");
  const r = await fetch("https://api.exa.ai/search", {
    method: "POST", signal: AbortSignal.timeout(30_000), headers: { "content-type": "application/json", "x-api-key": k },
    body: JSON.stringify({ query: `${q} mercadolibre chile`, includeDomains: ["mercadolibre.cl"], numResults: 6, contents: { text: { maxCharacters: 7000 } } }),
  });
  if (!r.ok) throw new Error("Buscador " + r.status + ": " + (await r.text()).slice(0, 120));
  const j = await r.json();
  const items: { t: string; p: number; intl: boolean; full: boolean; vend: number | null; tienda: string | null; url: string }[] = []; const vistos = new Set<string>();
  const relacionadas = new Set<string>(); const paginas: string[] = [];
  const num = (s: string) => Number(s.replace(/\./g, "").replace(",", "."));
  const vendidos = (s: string) => { const m = s.match(/\+?\s?(\d+(?:[.,]\d+)?)\s*(mil)?\s*vendid/i); return m ? Math.round(num(m[1]) * (m[2] ? 1000 : 1)) : null; };
  for (const res of j.results ?? []) {
    const tx = String(res.text ?? ""); paginas.push(res.url);
    const rel = tx.split("Búsquedas relacionadas")[0].split("\n").filter((l) => /^- /.test(l.trim())).map((l) => l.trim().slice(2).trim()).filter((x) => x && x.length < 60);
    const raices = nrm(q).split(" ").filter((w) => w.length > 3).map((w) => w.slice(0, 5));
    for (const x of rel.slice(0, 12)) if (raices.some((r) => nrm(x).includes(r))) relacionadas.add(x);
    if (/articulo\.mercadolibre|\/p\/MLC|MLC-?\d/.test(res.url) && !/listado\./.test(res.url)) {
      const p = tx.match(/\$\s?([\d.]{3,})/); const t = String(res.title ?? "").replace(/\s*\|\s*MercadoLibre.*$/i, "").trim();
      if (p && t && !vistos.has(nrm(t))) { vistos.add(nrm(t)); items.push({ t, p: num(p[1]), intl: /internacional/i.test(tx), full: /llega gratis|full/i.test(tx), vend: vendidos(tx), tienda: null, url: res.url }); }
      continue;
    }
    const bloques = tx.split(/\n(?=(?:\d+\.\s*)?#{2,3}\s)/);
    for (const bl of bloques) {
      const tm = bl.match(/^(?:\d+\.\s*)?#{2,3}\s*(.+)/); if (!tm) continue;
      const t = tm[1].trim(); if (/explora|promocionad|resultados|ir a la tienda|textiles premium/i.test(t) || t.length < 8) continue;
      const pm = bl.match(/\n\s*\$\s?([\d.]{3,})/); if (!pm) continue;
      const key = nrm(t); if (vistos.has(key)) continue; vistos.add(key);
      const tienda = bl.match(/\nPor\s+([^\n]{2,40})/)?.[1]?.trim() ?? null;
      items.push({ t, p: num(pm[1]), intl: /internacional/i.test(bl), full: /llega gratis|full/i.test(bl), vend: vendidos(bl), tienda, url: res.url });
    }
  }
  const P = items.map((x) => x.p).filter((x) => x > 0);
  const tiendas = new Set(items.map((x) => x.tienda).filter(Boolean));
  const p25 = pct(P, 0.25), p75 = pct(P, 0.75), m = med(P);
  return {
    q, publicaciones: items.length, precio_min: pct(P, 0), precio_p25: p25, precio_med: m, precio_p75: p75, precio_max: pct(P, 1),
    dispersion_pct: m && p25 != null && p75 != null ? Math.round(((p75 - p25) / m) * 100) : null,
    internacional_pct: items.length ? Math.round((items.filter((x) => x.intl).length / items.length) * 100) : null,
    envio_gratis_pct: items.length ? Math.round((items.filter((x) => x.full).length / items.length) * 100) : null,
    tiendas_oficiales: tiendas.size, vendidos_vistos: items.reduce((s, x) => s + (x.vend ?? 0), 0) || null,
    relacionadas: [...relacionadas].slice(0, 12), muestra: items.slice(0, 12), paginas: paginas.slice(0, 6),
  };
}

async function guardar(sb: any, tipo: string, termino: string, datos: any) {
  await sb.from("neg_estudio").upsert({ clave: `${tipo}:${termino}`, tipo, termino, datos, creado: new Date().toISOString() }, { onConflict: "clave" });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  T0.v = Date.now();
  const sb = svc();
  try {
    if (!(await autorizado(req, sb))) return json({ error: "Sesión no válida" }, 401);
    await cfg(sb);
    const b = await req.json().catch(() => ({}));
    if (b.clasificar) return json(await clasificar(sb, Number(b.clasificar.max) || 450));
    if (b.ranking) return json(await ranking(sb, b.ranking));
    if (b.estudios) { const { data } = await sb.from("neg_estudio").select("*").eq("tipo", b.estudios).order("creado", { ascending: false }).limit(300); return json({ ok: true, filas: data ?? [] }); }
    if (b.estudiar) {
      const termino = nrm(b.estudiar.termino ?? b.estudiar); if (!termino) return json({ error: "Falta término" }, 400);
      const mp = await estudiarMP(sb, termino);
      let ml: any = null; try { ml = await estudiarML(String(b.estudiar.nombre ?? termino)); await guardar(sb, "ml", nrm(b.estudiar.nombre ?? termino), ml); } catch (e) { ml = { error: String((e as Error).message) }; }
      const margen = mp.precio_unit_med && ml?.precio_p25 ? Math.round(((mp.precio_unit_med - ml.precio_p25) / mp.precio_unit_med) * 100) : null;
      const datos = { ...mp, ml, margen_pct: margen, nota_margen: margen == null ? "Sin precios comparables" : "Estimado: precio unitario neto pagado por el Estado vs precio bajo (p25) en Mercado Libre. Revisa que sea el mismo producto y unidad." };
      await guardar(sb, "mp", termino, datos);
      return json({ ok: true, termino, datos });
    }
    if (b.ml) { const q = String(b.ml.q ?? b.ml).trim(); if (!q) return json({ error: "Falta búsqueda" }, 400); const d = await estudiarML(q); await guardar(sb, "ml", nrm(q), d); return json({ ok: true, q, datos: d }); }
    if (b.comex) {
      const [{ data: R }, { data: c }] = await Promise.all([sb.from("comex_ranking").select("*").eq("nivel", 4).order("valor_usd", { ascending: false, nullsFirst: false }).limit(2000), sb.from("comex_carga").select("*")]);
      return json({ ok: true, filas: R ?? [], carga: c?.[0] ?? null });
    }
    if (b.origenes) { const { data } = await sb.from("comex_origen").select("*").eq("hs", String(b.origenes)).order("valor_usd", { ascending: false }); return json({ ok: true, origenes: data ?? [] }); }
    return json({ error: "Falta parámetro" }, 400);
  } catch (e) { return json({ error: e instanceof Error ? e.message : String(e) }, 500); }
});
