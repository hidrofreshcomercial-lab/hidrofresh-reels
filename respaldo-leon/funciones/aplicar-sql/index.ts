// deno-lint-ignore-file no-explicit-any
import postgres from "npm:postgres@3.4.4";
import { createClient } from "npm:@supabase/supabase-js@2";
// aplicar-sql v1 (panel León): recibe el esquema exportado del panel principal y lo aplica sentencia por sentencia
// (sigue si una falla y devuelve los errores). Solo con x-cron-token. Herramienta de instalación/actualización.
function svc() {
  const raw = Deno.env.get("SUPABASE_SECRET_KEYS");
  const k = raw ? JSON.parse(raw)["default"] : Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  return createClient(Deno.env.get("SUPABASE_URL")!, k!);
}
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "content-type": "application/json" } });
function partir(t: string) {
  const out: string[] = []; let cur = "", i = 0, dq: string | null = null, linea = false, sq = false;
  while (i < t.length) {
    const c = t[i];
    if (linea) { cur += c; if (c === "\n") linea = false; i++; continue; }
    if (dq) { if (t.startsWith(dq, i)) { cur += dq; i += dq.length; dq = null; continue; } cur += c; i++; continue; }
    if (sq) { cur += c; if (c === "'") { if (t[i + 1] === "'") { cur += "'"; i += 2; continue; } sq = false; } i++; continue; }
    if (c === "-" && t[i + 1] === "-") { linea = true; cur += c; i++; continue; }
    if (c === "'") { sq = true; cur += c; i++; continue; }
    if (c === "$") { const m = t.slice(i).match(/^\$[A-Za-z_0-9]*\$/); if (m) { dq = m[0]; cur += dq; i += dq.length; continue; } }
    if (c === ";") { const s = cur.replace(/^(\s*--[^\n]*\n)+/g, "").trim(); if (s) out.push(s); cur = ""; i++; continue; }
    cur += c; i++;
  }
  const s = cur.replace(/^(\s*--[^\n]*\n)+/g, "").trim(); if (s && !/^(--[^\n]*\n?)+$/.test(s)) out.push(s);
  return out;
}
Deno.serve(async (req) => {
  const sb = svc();
  const { data } = await sb.from("app_config").select("valor").eq("clave", "cron_token").maybeSingle();
  if (!data?.valor || req.headers.get("x-cron-token") !== String(data.valor)) return json({ error: "no autorizado" }, 401);
  const b = await req.json().catch(() => ({}));
  const sentencias = partir(String(b.sql ?? "")).filter((s) => !(b.saltar ?? []).some((p: string) => new RegExp(p, "i").test(s.slice(0, 300))));
  const db = postgres(Deno.env.get("SUPABASE_DB_URL")!, { max: 1, prepare: false });
  const errores: any[] = []; let ok = 0;
  try {
    for (let pasada = 0; pasada < (b.pasadas ?? 2); pasada++) {
      const fallidas: string[] = [];
      for (const s of pasada === 0 ? sentencias : errores.splice(0).map((e) => e.sql)) {
        try { await db.unsafe(s); ok++; } catch (e) { fallidas.push(s); errores.push({ sql: s, error: e instanceof Error ? e.message : String(e) }); }
      }
      if (!fallidas.length) break;
    }
  } finally { await db.end(); }
  return json({ ok: true, total: sentencias.length, aplicadas: ok, errores: errores.map((e) => ({ inicio: e.sql.slice(0, 120), error: e.error })) });
});
