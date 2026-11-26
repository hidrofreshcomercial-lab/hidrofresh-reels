// deno-lint-ignore-file no-explicit-any
// ia-router v1.8 (+ regla única "el cliente es el héroe" para todo mensaje a clientes) v1.7 (+ panel de León: acepta ia_externo_token con cabecera x-ia-externo, solo para este enrutador) v1.6 (+ proveedores estilo FreeLLMAPI: Cerebras, NVIDIA NIM, Mistral, GitHub Models y un FreeLLMAPI propio opcional; se descubren solos en el catálogo diario cuando hay clave) v1.5 (plazo por modelo cubre también la lectura de la respuesta; Google saturado → sus "lite" primero; 403 de un modelo no pausa todo el proveedor) v1.4 (chat: proveedores intercalados y 25 s máx. por modelo; si Google está saturado salta a Groq/OpenRouter) v1.3 (+ vigilancia de gasto en OpenRouter con aviso al celular) v1.2 (conversación: rápidos primero, 15 s máx. por modelo) v1.1 (+ conversación con herramientas para el bot de WhatsApp) — enrutador de IA SOLO GRATIS para Hidro Fresh (presupuesto obligatorio USD 0).
// Orden: Gemini (capa gratuita) → Groq (free tier) → Cerebras → OpenRouter (solo ":free", precio máx. 0) → Mistral (Experiment) → NVIDIA NIM
// → GitHub Models → Cloudflare Workers AI → FreeLLMAPI propio → Ollama local/propio si está configurado.
// Claves en app_config: gemini_api_key, groq_api_key, cerebras_api_key, openrouter_api_key, mistral_api_key, nvidia_api_key, github_api_key,
// cloudflare_api_key + cloudflare_account_id, freellmapi_api_key + freellmapi_url, ollama_url (+ ollama_token).
// Llamadas (x-cron-token o sesión de usuario autorizado):
//   {chat:{prompt, sistema?, tarea?:"extraccion"|"redaccion"|"razonamiento"|"rapido", json?:bool, max_tokens?, web?:bool|string, funcion?, limite_ms?}}
//   {mensajes:{messages, tools?, tool_choice?, max_tokens?, funcion?, preferir?}}  conversación estilo OpenAI con herramientas
//   {catalogo:true}  verifica en vivo qué modelos existen y son gratis (y agrega los de proveedores nuevos con clave)
//   {estado:true}    cuotas, uso de hoy y errores
//   {probar:true}    una llamada mínima a cada modelo activo (opcional proveedor:"cerebras")
//   {vigilar:true}   confirma que el gasto sigue en USD 0 (cron cada hora)
import { createClient } from "npm:@supabase/supabase-js@2";

const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info, x-cron-token, x-ia-externo", "Access-Control-Allow-Methods": "POST, OPTIONS" };
const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { ...CORS, "content-type": "application/json" } });
function svc() {
  const raw = Deno.env.get("SUPABASE_SECRET_KEYS");
  const k = raw ? JSON.parse(raw)["default"] : Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  return createClient(Deno.env.get("SUPABASE_URL")!, k!);
}
async function autorizado(req: Request, sb: any) {
  const cron = req.headers.get("x-cron-token");
  if (cron) { const { data } = await sb.from("app_config").select("clave,valor").in("clave", ["cron_token", "ia_externo_token"]); return (data ?? []).some((x: any) => !!x.valor && cron === String(x.valor) && (x.clave === "cron_token" || !!req.headers.get("x-ia-externo"))); }
  const t = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, ""); if (!t) return false;
  const { data, error } = await sb.auth.getUser(t); const email = data?.user?.email?.toLowerCase(); if (error || !email) return false;
  const { data: u } = await sb.from("app_usuarios").select("activo").eq("email", email).maybeSingle(); return !!u?.activo;
}

const T0 = { v: 0, lim: 140_000, porModelo: 45_000 }; const resta = () => T0.lim - (Date.now() - T0.v);
async function fetchT(url: string, init: RequestInit = {}, ms = 45_000) {
  const ctl = new AbortController(); const tm = setTimeout(() => ctl.abort(), Math.max(1000, Math.min(ms, resta() - 1500)));
  try { return await fetch(url, { ...init, signal: ctl.signal }); } finally { clearTimeout(tm); }
}
// v1.5: igual que fetchT pero el plazo también cubre la lectura del cuerpo (antes un modelo lento podía tardar 100 s
// leyendo la respuesta y el agente cortaba la llamada al router con "The signal has been aborted").
async function fetchTexto(url: string, init: RequestInit = {}, ms = 45_000): Promise<{ r: Response; tx: string }> {
  const ctl = new AbortController(); const tm = setTimeout(() => ctl.abort(), Math.max(1000, Math.min(ms, resta() - 1500)));
  try { const r = await fetch(url, { ...init, signal: ctl.signal }); const tx = await r.text(); return { r, tx }; } finally { clearTimeout(tm); }
}

// ---------- claves (nunca se devuelven ni se registran) ----------
const CFG: Record<string, string> = {};
// v1.8: REGLA ÚNICA "el cliente es el héroe" para TODO texto que va a un cliente (correos, WhatsApp, respuestas, bot, redes).
// Se guarda en app_config.regla_mensajes (editable) y se agrega al sistema de cualquier llamada cuya "funcion" escriba a clientes.
const REGLA_DEF = `REGLA OBLIGATORIA DE HIDRO FRESH PARA TODO MENSAJE A UN CLIENTE O PROSPECTO: el cliente es el héroe. Orden fijo: 1) su problema o situación (en sus palabras, concreto); 2) cómo se soluciona; 3) recién aquí quiénes somos: "Soy Miguel Fuenzalida, de Hidro Fresh: le ayudamos a…" (una sola frase sobre nosotros); 4) una pregunta o llamado concreto. PROHIBIDO abrir presentándonos ("le saluda Miguel…", "les escribo de Hidro Fresh", "soy Miguel de Hidro Fresh", "en Hidro Fresh diseñamos…") y PROHIBIDO ofrecer visitas, diagnósticos o levantamientos "sin costo"/"gratis" (la visita en terreno es a costo acotado; lo sin costo es una videollamada o revisar antecedentes que nos envíen).`;
const FUNC_CLIENTE = /prospeccion|equipo-mineria|correos-entrantes|agentes-equipo|agente-investigador|ig-comentarios|wa-|whatsapp|respuesta|cotiz|redes|reel|caption|post/i;
const REGLA = { txt: REGLA_DEF };
async function cargarClaves(sb: any) {
  try { const { data: rg } = await sb.from("app_config").select("valor").eq("clave", "regla_mensajes").maybeSingle(); if (rg?.valor) REGLA.txt = String(rg.valor); } catch (_) { /* usa la regla por defecto */ }
  const { data } = await sb.from("app_config").select("clave,valor").or("clave.like.%_api_key,clave.like.ollama_%,clave.like.cloudflare_%,clave.like.freellmapi_%,clave.eq.ia_presupuesto_usd");
  for (const x of data ?? []) CFG[x.clave] = String(x.valor ?? "").trim();
}
const clave = (p: string) => (Deno.env.get(p.toUpperCase() + "_API_KEY") ?? CFG[p + "_api_key"] ?? "").trim();

// ---------- proveedores ----------
type Prov = { url: (m: string) => string; key: () => string; tipo: "gemini" | "openai"; extra?: () => Record<string, string>; pago_posible?: boolean };
const PROV: Record<string, Prov> = {
  gemini: { tipo: "gemini", key: () => clave("gemini"), url: (m) => `https://generativelanguage.googleapis.com/v1beta/models/${m}:generateContent` },
  groq: { tipo: "openai", key: () => clave("groq"), url: () => "https://api.groq.com/openai/v1/chat/completions" },
  cerebras: { tipo: "openai", key: () => clave("cerebras"), url: () => "https://api.cerebras.ai/v1/chat/completions" },
  openrouter: { tipo: "openai", key: () => clave("openrouter"), url: () => "https://openrouter.ai/api/v1/chat/completions", pago_posible: true, extra: () => ({ "HTTP-Referer": "https://hidrofresh.cl", "X-Title": "Hidro Fresh" }) },
  mistral: { tipo: "openai", key: () => clave("mistral"), url: () => "https://api.mistral.ai/v1/chat/completions" },
  nvidia: { tipo: "openai", key: () => clave("nvidia"), url: () => "https://integrate.api.nvidia.com/v1/chat/completions" },
  github: { tipo: "openai", key: () => clave("github"), url: () => "https://models.github.ai/inference/chat/completions" },
  cloudflare: { tipo: "openai", key: () => clave("cloudflare"), url: () => `https://api.cloudflare.com/client/v4/accounts/${CFG["cloudflare_account_id"] ?? ""}/ai/v1/chat/completions` },
  freellmapi: { tipo: "openai", key: () => (CFG["freellmapi_url"] ? clave("freellmapi") || "freellmapi" : ""), url: () => `${(CFG["freellmapi_url"] ?? "").replace(/\/+$/, "")}/v1/chat/completions` },
  ollama: { tipo: "openai", key: () => CFG["ollama_token"] || (CFG["ollama_url"] ? "ollama" : ""), url: () => `${(CFG["ollama_url"] ?? "").replace(/\/+$/, "")}/v1/chat/completions` },
};
const LIMITE_PROV_DIA: Record<string, number> = { openrouter: 50 }; // cuentas con menos de USD 10 comprados: 50 solicitudes gratis al día (compartidas)
const ORDEN_PROV: Record<string, number> = { gemini: 0, groq: 1, cerebras: 2, openrouter: 3, mistral: 4, nvidia: 5, github: 6, cloudflare: 7, freellmapi: 8, ollama: 9 };

// ---------- candado USD 0 ----------
function esGratis(m: any): boolean {
  if (!m.gratis || !PROV[m.proveedor]) return false;
  if (m.proveedor === "openrouter" && !String(m.modelo).endsWith(":free")) return false; // jamás un modelo de pago de OpenRouter
  return true;
}
class Cobro extends Error {}

// ---------- reinicios de cuota ----------
function proximaMedianoche(tz: string) {
  const ahora = new Date();
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }).formatToParts(ahora).map((x) => [x.type, x.value]));
  const transcurrido = (Number(p.hour) * 3600 + Number(p.minute) * 60 + Number(p.second)) * 1000;
  return new Date(ahora.getTime() - transcurrido + 864e5 + 60_000);
}
const dur = (s: string) => { let ms = 0; for (const [, n, u] of String(s).matchAll(/([\d.]+)(ms|h|m|s)/g)) ms += Number(n) * (u === "h" ? 3600e3 : u === "m" ? 60e3 : u === "ms" ? 1 : 1e3); return ms; };

// ---------- búsqueda web independiente (para modelos sin navegación) ----------
async function buscarWeb(q: string): Promise<{ fuente: string; items: { titulo: string; url: string; texto: string }[] }> {
  const ok = (r: Response) => r.ok;
  const intentos: [string, () => Promise<any[]>][] = [
    ["tavily", async () => { const k = clave("tavily"); if (!k) return []; const r = await fetchT("https://api.tavily.com/search", { method: "POST", headers: { Authorization: "Bearer " + k, "content-type": "application/json" }, body: JSON.stringify({ query: q, max_results: 8, search_depth: "basic" }) }, 20_000); if (!ok(r)) throw new Error("tavily " + r.status); return ((await r.json()).results ?? []).map((x: any) => ({ titulo: x.title, url: x.url, texto: String(x.content ?? "").slice(0, 700) })); }],
    ["linkup", async () => { const k = clave("linkup"); if (!k) return []; const r = await fetchT("https://api.linkup.so/v1/search", { method: "POST", headers: { Authorization: "Bearer " + k, "content-type": "application/json" }, body: JSON.stringify({ q, depth: "standard", outputType: "searchResults" }) }, 20_000); if (!ok(r)) throw new Error("linkup " + r.status); return ((await r.json()).results ?? []).slice(0, 8).map((x: any) => ({ titulo: x.name ?? x.title, url: x.url, texto: String(x.content ?? "").slice(0, 700) })); }],
    ["exa", async () => { const k = clave("exa"); if (!k) return []; const r = await fetchT("https://api.exa.ai/search", { method: "POST", headers: { "x-api-key": k, "content-type": "application/json" }, body: JSON.stringify({ query: q, numResults: 8, contents: { text: { maxCharacters: 700 } } }) }, 20_000); if (!ok(r)) throw new Error("exa " + r.status); return ((await r.json()).results ?? []).map((x: any) => ({ titulo: x.title, url: x.url, texto: String(x.text ?? "").slice(0, 700) })); }],
    ["serper", async () => { const k = clave("serper"); if (!k) return []; const r = await fetchT("https://google.serper.dev/search", { method: "POST", headers: { "X-API-KEY": k, "Content-Type": "application/json" }, body: JSON.stringify({ q, gl: "cl", hl: "es", num: 8 }) }, 20_000); if (!ok(r)) throw new Error("serper " + r.status); return ((await r.json()).organic ?? []).map((o: any) => ({ titulo: o.title, url: o.link, texto: o.snippet ?? "" })); }],
  ];
  for (const [n, f] of intentos) { try { const it = await f(); if (it.length) return { fuente: n, items: it }; } catch { /* siguiente buscador */ } }
  return { fuente: "", items: [] };
}

// ---------- selección ----------
const est = (s: string) => Math.ceil(s.length / 3.5);
async function usoHoy(sb: any) {
  const desde = new Date(Date.now() - 864e5).toISOString();
  const { data } = await sb.from("ia_uso").select("proveedor,modelo,ok,status,creado").gte("creado", desde).limit(20000);
  const porModelo: Record<string, number> = {}, porProv: Record<string, number> = {};
  const utc0 = new Date(); utc0.setUTCHours(0, 0, 0, 0);
  for (const u of data ?? []) {
    if (u.status === 429 || u.status === 503) continue;
    if (new Date(u.creado) >= utc0) { porModelo[u.proveedor + ":" + u.modelo] = (porModelo[u.proveedor + ":" + u.modelo] ?? 0) + 1; porProv[u.proveedor] = (porProv[u.proveedor] ?? 0) + 1; }
  }
  return { porModelo, porProv };
}
async function candidatos(sb: any, tarea: string, tokens: number) {
  const { data } = await sb.from("ia_modelos").select("*").eq("activo", true).eq("gratis", true);
  const { porModelo, porProv } = await usoHoy(sb);
  const ahora = Date.now();
  const lista = (data ?? []).filter((m: any) => esGratis(m) && PROV[m.proveedor].key()
    && !(m.agotado_hasta && new Date(m.agotado_hasta).getTime() > ahora)
    && m.ctx >= tokens && (!m.tpm || m.tpm >= tokens)
    && (!m.rpd || (porModelo[m.id] ?? 0) < m.rpd)
    && (!LIMITE_PROV_DIA[m.proveedor] || (porProv[m.proveedor] ?? 0) < LIMITE_PROV_DIA[m.proveedor]));
  return lista.sort((a: any, b: any) => {
    const ta = a.tareas.includes(tarea) ? 0 : 1, tb = b.tareas.includes(tarea) ? 0 : 1;
    if (a.proveedor === "ollama" || b.proveedor === "ollama") return (ORDEN_PROV[a.proveedor] ?? 5) - (ORDEN_PROV[b.proveedor] ?? 5); // Ollama siempre al final
    return ta - tb || b.calidad - a.calidad || (ORDEN_PROV[a.proveedor] ?? 5) - (ORDEN_PROV[b.proveedor] ?? 5);
  });
}

// ---------- una llamada ----------
async function llamar(m: any, sistema: string, prompt: string, quiereJson: boolean, maxTok: number) {
  const P = PROV[m.proveedor]; const key = P.key();
  if (P.tipo === "gemini") {
    const gemma = /^gemma/.test(m.modelo);
    const body: any = { contents: [{ role: "user", parts: [{ text: gemma && sistema ? sistema + "\n\n" + prompt : prompt }] }], generationConfig: { temperature: 0.2, maxOutputTokens: maxTok, ...(quiereJson && m.json_nativo ? { responseMimeType: "application/json" } : {}) } };
    if (sistema && !gemma) body.systemInstruction = { parts: [{ text: sistema }] };
    const { r, tx } = await fetchTexto(P.url(m.modelo), { method: "POST", headers: { "Content-Type": "application/json", "x-goog-api-key": key }, body: JSON.stringify(body) }, T0.porModelo);
    if (!r.ok) return { ok: false, status: r.status, err: tx, headers: r.headers };
    const j = JSON.parse(tx); const u = j.usageMetadata ?? {};
    const texto = (j.candidates?.[0]?.content?.parts ?? []).filter((p: any) => !p.thought).map((p: any) => p.text ?? "").join("");
    return { ok: !!texto, status: texto ? 200 : 204, texto, tin: u.promptTokenCount ?? 0, tout: (u.candidatesTokenCount ?? 0) + (u.thoughtsTokenCount ?? 0), costo: 0, err: texto ? "" : "respuesta vacía (" + (j.candidates?.[0]?.finishReason ?? "?") + ")" };
  }
  const msgs = [...(sistema ? [{ role: "system", content: sistema }] : []), { role: "user", content: prompt }];
  const body: any = { model: m.modelo, temperature: 0.2, max_tokens: maxTok, messages: msgs };
  if (quiereJson && m.json_nativo) body.response_format = { type: "json_object" };
  if (m.proveedor === "openrouter") { body.usage = { include: true }; body.provider = { max_price: { prompt: 0, completion: 0, request: 0, image: 0 }, allow_fallbacks: false }; }
  if (m.proveedor === "groq" && /gpt-oss|qwen3/.test(m.modelo)) body.reasoning_effort = /qwen3/.test(m.modelo) ? "none" : "low";
  if (m.proveedor === "cerebras" && /gpt-oss/.test(m.modelo)) body.reasoning_effort = "low";
  let { r, tx } = await fetchTexto(P.url(m.modelo), { method: "POST", headers: { Authorization: "Bearer " + key, "Content-Type": "application/json", ...(P.extra?.() ?? {}) }, body: JSON.stringify(body) }, T0.porModelo);
  if (r.status === 400 && (body.response_format || body.reasoning_effort)) { delete body.response_format; delete body.reasoning_effort; ({ r, tx } = await fetchTexto(P.url(m.modelo), { method: "POST", headers: { Authorization: "Bearer " + key, "Content-Type": "application/json", ...(P.extra?.() ?? {}) }, body: JSON.stringify(body) }, T0.porModelo)); }
  if (!r.ok) return { ok: false, status: r.status, err: tx, headers: r.headers };
  const j = JSON.parse(tx); const u = j.usage ?? {};
  const costo = Number(u.cost ?? 0) || 0;
  if (m.proveedor === "openrouter" && costo > 0) throw new Cobro(`OpenRouter informó costo ${costo} USD en ${m.modelo}`);
  const texto = String(j.choices?.[0]?.message?.content ?? "").replace(/<think>[\s\S]*?<\/think>/g, "").trim();
  return { ok: !!texto, status: texto ? 200 : 204, texto, tin: u.prompt_tokens ?? 0, tout: u.completion_tokens ?? 0, costo, headers: r.headers, err: texto ? "" : "respuesta vacía" };
}

// ---------- qué hacer con cada error ----------
async function castigar(sb: any, m: any, status: number, err: string, h?: Headers) {
  let msg = err; try { const j = JSON.parse(err); msg = j?.error?.message ?? j?.message ?? err; } catch { /* texto */ }
  msg = String(msg).replace(/\s+/g, " ").slice(0, 300);
  const u: any = { actualizado: new Date().toISOString(), motivo: `${status}: ${msg}`.slice(0, 300) };
  if (status === 429) {
    let hasta = 0;
    const ra = h?.get("retry-after"); if (ra) hasta = Date.now() + (Number(ra) > 0 ? Number(ra) * 1000 : dur(ra));
    const rr = h?.get("x-ratelimit-reset"); if (!hasta && rr && /^\d{12,}$/.test(rr)) hasta = Number(rr);
    const rd = err.match(/"retryDelay":\s*"([\d.]+)s"/); if (!hasta && rd) hasta = Date.now() + Number(rd[1]) * 1000;
    if (/per ?day|PerDay|RPD|TPD|daily|free-models-per-day/i.test(err)) {
      hasta = Math.max(hasta, (m.proveedor === "gemini" ? proximaMedianoche("America/Los_Angeles") : m.proveedor === "openrouter" ? proximaMedianoche("UTC") : new Date(Date.now() + 3600e3)).getTime());
      if (m.proveedor === "openrouter" && /free-models-per-day/i.test(err)) { await sb.from("ia_modelos").update({ agotado_hasta: new Date(hasta).toISOString(), motivo: "cupo diario gratis de OpenRouter agotado" }).eq("proveedor", "openrouter"); }
    }
    u.agotado_hasta = new Date(hasta || Date.now() + 60_000).toISOString();
  } else if (status === 503 || status === 500 || status === 502 || status === 504 || status === 0) u.agotado_hasta = new Date(Date.now() + 3 * 60_000).toISOString();
  else if (status === 404) { u.activo = false; u.motivo = "404: el modelo ya no existe"; }
  else if (status === 402) { await sb.from("ia_modelos").update({ activo: false, motivo: "402: el proveedor pide pago; se desactiva (presupuesto USD 0)" }).eq("proveedor", m.proveedor); return; }
  else if (status === 403 && /only available|not available|not allowed|harness|region|terms|moderation/i.test(msg)) { await sb.from("ia_modelos").update({ activo: false, motivo: `403 (solo este modelo): ${msg}`.slice(0, 300), actualizado: new Date().toISOString() }).eq("id", m.id); return; } // v1.5: restricción del modelo, no de la clave
  else if (status === 401 || status === 403) { await sb.from("ia_modelos").update({ agotado_hasta: new Date(Date.now() + 6 * 3600e3).toISOString(), motivo: `${status}: clave rechazada` }).eq("proveedor", m.proveedor); return; }
  else if (status === 413) { /* demasiado grande para este modelo: no se castiga */ return; }
  else u.agotado_hasta = new Date(Date.now() + 10 * 60_000).toISOString();
  await sb.from("ia_modelos").update(u).eq("id", m.id);
}
async function anotarCupo(sb: any, m: any, h?: Headers) {
  if (!h) return;
  const rq = h.get("x-ratelimit-remaining-requests"), tk = h.get("x-ratelimit-remaining-tokens"), lq = h.get("x-ratelimit-limit-requests"), lt = h.get("x-ratelimit-limit-tokens");
  if (rq || tk) await sb.from("ia_modelos").update({ restante_req: rq ? Number(rq) : null, restante_tok: tk ? Number(tk) : null, ...(lq ? { rpd: Number(lq) } : {}), ...(lt ? { tpm: Number(lt) } : {}), actualizado: new Date().toISOString() }).eq("id", m.id);
}

// ---------- chat con el trencito ----------
async function chat(sb: any, c: any) {
  const tarea = ["extraccion", "redaccion", "razonamiento", "rapido"].includes(c.tarea) ? c.tarea : "extraccion";
  const quiereJson = c.json !== false;
  const maxTok = Math.min(Math.max(Number(c.max_tokens) || 4000, 64), 8000);
  let sistema = String(c.sistema ?? (quiereJson ? "Responde SOLO con JSON válido, sin texto adicional." : ""));
  if (FUNC_CLIENTE.test(String(c.funcion ?? "")) || c.cliente === true) sistema = (sistema ? sistema + "\n\n" : "") + REGLA.txt;
  let prompt = String(c.prompt ?? ""); if (!prompt) throw new Error("Falta prompt");
  let web = false;
  if (c.web) {
    const q = typeof c.web === "string" ? c.web : prompt.slice(0, 200);
    const w = await buscarWeb(q);
    if (w.items.length) { web = true; prompt = `RESULTADOS DE BÚSQUEDA WEB (${w.fuente}, ${new Date().toISOString().slice(0, 10)}):\n${w.items.map((x, i) => `[${i}] ${x.titulo} | ${x.url} | ${x.texto}`).join("\n")}\n\n${prompt}`; }
  }
  const tokens = est(sistema + prompt) + maxTok;
  // v1.4: proveedores intercalados (Gemini, Groq, Cerebras, …) para que si uno está saturado se llegue rápido a los respaldos; máximo 25 s por modelo.
  const ordenada = await candidatos(sb, tarea, tokens);
  const grupos: Record<string, any[]> = {}; for (const m of ordenada) (grupos[m.proveedor] ??= []).push(m);
  const lista: any[] = []; const provs = Object.keys(grupos);
  for (let i = 0; lista.length < ordenada.length; i++) for (const p of provs) if (grupos[p][i]) lista.push(grupos[p][i]);
  T0.porModelo = 25_000;
  const intentos: string[] = []; let geminiSaturado = false;
  const cola = [...lista];
  while (cola.length) {
    const m = cola.shift()!;
    if (resta() < 12_000) break;
    if (!esGratis(m)) continue; // doble candado
    if (geminiSaturado && m.proveedor === "gemini" && !/lite/.test(m.modelo)) continue; // Google saturado: solo se prueban sus "lite"
    const t = Date.now();
    let r: any;
    try { r = await llamar(m, sistema, prompt, quiereJson, maxTok); }
    catch (e) {
      if (e instanceof Cobro) {
        await sb.from("ia_modelos").update({ activo: false, gratis: false, motivo: "COBRO DETECTADO — proveedor bloqueado: " + e.message }).eq("proveedor", m.proveedor);
        await sb.from("ia_uso").insert({ funcion: c.funcion, tarea, proveedor: m.proveedor, modelo: m.modelo, ok: false, status: 402, ms: Date.now() - t, error: "COBRO DETECTADO: " + e.message });
        continue;
      }
      r = { ok: false, status: 0, err: String((e as Error)?.message ?? e) };
    }
    await sb.from("ia_uso").insert({ funcion: c.funcion ?? null, tarea, proveedor: m.proveedor, modelo: m.modelo, ok: r.ok, status: r.status, tok_in: r.tin ?? null, tok_out: r.tout ?? null, ms: Date.now() - t, costo_usd: r.costo ?? 0, web, error: r.ok ? null : String(r.err ?? "").replace(/\s+/g, " ").slice(0, 1500) });
    if (r.ok) {
      await anotarCupo(sb, m, r.headers);
      await sb.from("ia_modelos").update({ usos_total: (m.usos_total ?? 0) + 1, motivo: null, agotado_hasta: null }).eq("id", m.id);
      return { ok: true, texto: r.texto, proveedor: m.proveedor, modelo: m.modelo, tokens_in: r.tin, tokens_out: r.tout, costo_usd: 0, web, intentos };
    }
    intentos.push(`${m.proveedor}:${m.modelo} ${r.status}`);
    if (m.proveedor === "gemini" && (r.status === 503 || r.status === 0) && !geminiSaturado) {
      geminiSaturado = true;
      // v1.5: Google saturado → sus modelos "lite" (responden en ~2-4 s) pasan al frente, antes que respaldos lentos
      const lite = cola.filter((x: any) => x.proveedor === "gemini" && /lite/.test(x.modelo));
      const resto = cola.filter((x: any) => !(x.proveedor === "gemini" && /lite/.test(x.modelo)));
      cola.splice(0, cola.length, ...lite, ...resto);
    }
    await castigar(sb, m, r.status, String(r.err ?? ""), r.headers);
  }
  return { ok: false, error: lista.length ? "Todos los modelos gratis fallaron o están en pausa: " + intentos.join(" | ") : "No hay modelos gratis disponibles ahora (cuotas agotadas o en pausa); se reintentará cuando se renueven", intentos };
}


// ---------- conversación con herramientas (bot de WhatsApp): solo modelos gratis que soportan tools ----------
const URL_COMPAT: Record<string, string> = { gemini: "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions" };
const urlConv = (m: any) => URL_COMPAT[m.proveedor] ?? PROV[m.proveedor].url(m.modelo);
const sirveTools = (m: any) => (m.proveedor === "gemini" && !/^gemma/.test(m.modelo))
  || (m.proveedor === "groq" && /gpt-oss-120b|gpt-oss-20b|qwen/.test(m.modelo))
  || (m.proveedor === "cerebras" && /gpt-oss|qwen|llama|glm|zai/i.test(m.modelo))
  || (m.proveedor === "mistral" && !/codestral|devstral/i.test(m.modelo))
  || (m.proveedor === "github" && /gpt-4|gpt-5/i.test(m.modelo));
function limpiarPara(prov: string, messages: any[]) {
  // otro proveedor no entiende las firmas internas de Gemini; se quitan al cambiar de proveedor
  if (prov === "gemini") return messages;
  return messages.map((x) => x.tool_calls ? { ...x, tool_calls: x.tool_calls.map((t: any) => ({ id: t.id, type: t.type ?? "function", function: t.function })) } : x);
}
async function chatMensajes(sb: any, c: any) {
  let messages = Array.isArray(c.messages) ? c.messages : []; if (!messages.length) throw new Error("Faltan messages");
  if (FUNC_CLIENTE.test(String(c.funcion ?? "")) || c.cliente === true) messages = [{ role: "system", content: "En esta conversación con un cliente: céntrate en su problema y en cómo se soluciona; no abras presentando a Hidro Fresh ni a Miguel y nunca ofrezcas visitas o diagnósticos en terreno sin costo (la visita es a costo acotado; lo sin costo es una videollamada o revisar antecedentes)." }, ...messages];
  const maxTok = Math.min(Math.max(Number(c.max_tokens) || 700, 64), 4000);
  const tokens = est(JSON.stringify(messages) + JSON.stringify(c.tools ?? [])) + maxTok;
  // en conversación manda la rapidez (el cliente espera en WhatsApp): Groq y Cerebras (~1 s) y los Gemini "lite" primero
  const rapidez = (m: any) => m.proveedor === "groq" ? (/120b/.test(m.modelo) ? 0 : 1) : m.proveedor === "cerebras" ? 1 : /lite/.test(m.modelo) ? 2 : 3;
  let lista = (await candidatos(sb, c.tarea ?? "redaccion", tokens)).filter(sirveTools).sort((a: any, b: any) => rapidez(a) - rapidez(b) || b.calidad - a.calidad);
  if (c.preferir) lista = [...lista.filter((m: any) => m.id === c.preferir), ...lista.filter((m: any) => m.id !== c.preferir)];
  const intentos: string[] = [];
  for (const m of lista) {
    if (resta() < 8_000) break;
    if (!esGratis(m)) continue;
    const t = Date.now();
    const body: any = { model: m.modelo, messages: limpiarPara(m.proveedor, messages), temperature: c.temperature ?? 0.3, max_tokens: maxTok };
    if (c.tools?.length) { body.tools = c.tools; body.tool_choice = c.tool_choice ?? "auto"; }
    if ((m.proveedor === "groq" || m.proveedor === "cerebras") && /gpt-oss/.test(m.modelo)) body.reasoning_effort = "low";
    if (m.proveedor === "gemini") body.reasoning_effort = "low"; // menos "pensamiento" = respuesta rápida
    let r: Response | null = null, tx = "";
    try { r = await fetchT(urlConv(m), { method: "POST", headers: { Authorization: "Bearer " + PROV[m.proveedor].key(), "Content-Type": "application/json", ...(PROV[m.proveedor].extra?.() ?? {}) }, body: JSON.stringify(body) }, 15_000); tx = await r.text(); }
    catch (e) { tx = String((e as Error)?.message ?? e); }
    const st = r?.status ?? 0;
    let j: any = null; try { j = JSON.parse(tx); } catch { /* texto */ }
    const msg = r?.ok ? j?.choices?.[0]?.message : null;
    const ok = !!msg && (!!msg.content || !!msg.tool_calls?.length);
    const u = j?.usage ?? {};
    await sb.from("ia_uso").insert({ funcion: c.funcion ?? null, tarea: "conversacion", proveedor: m.proveedor, modelo: m.modelo, ok, status: ok ? 200 : st, tok_in: u.prompt_tokens ?? null, tok_out: u.completion_tokens ?? null, ms: Date.now() - t, costo_usd: 0, error: ok ? null : tx.replace(/\s+/g, " ").slice(0, 1500) });
    if (ok) {
      await anotarCupo(sb, m, r!.headers);
      await sb.from("ia_modelos").update({ usos_total: (m.usos_total ?? 0) + 1 }).eq("id", m.id);
      return { ok: true, message: msg, proveedor: m.proveedor, modelo: m.modelo, id_modelo: m.id, intentos };
    }
    intentos.push(`${m.id} ${st}`);
    if (st === 400) continue; // formato no aceptado por este modelo: probar otro sin castigarlo
    await castigar(sb, m, st, tx, r?.headers);
  }
  return { ok: false, error: "Sin modelo gratis disponible para la conversación: " + (intentos.join(" | ") || "todos en pausa"), intentos };
}


// ---------- vigilancia de gasto (debe ser siempre USD 0) ----------
// Lee el gasto acumulado de la clave de OpenRouter (consulta gratuita). Si sube respecto de la base, bloquea OpenRouter y avisa al celular.
async function vigilar(sb: any) {
  const out: any = { revisado: new Date().toISOString() };
  const k = clave("openrouter");
  if (k) {
    try {
      const r = await fetchT("https://openrouter.ai/api/v1/key", { headers: { Authorization: "Bearer " + k } }, 15_000);
      const d = (await r.json())?.data ?? {};
      const uso = Number(d.usage ?? 0); out.openrouter = { gasto_total_usd: uso, gasto_hoy_usd: d.usage_daily ?? null, limite_usd: d.limit ?? null, saldo_usd: d.limit_remaining ?? null };
      const { data: b } = await sb.from("app_config").select("valor").eq("clave", "openrouter_gasto_base").maybeSingle();
      if (!b) await sb.from("app_config").upsert({ clave: "openrouter_gasto_base", valor: String(uso) });
      else if (uso > Number(b.valor) + 0.0001) {
        const sube = Math.round((uso - Number(b.valor)) * 10000) / 10000;
        out.alerta = `OpenRouter registró un gasto de USD ${sube}`;
        await sb.from("ia_modelos").update({ activo: false, motivo: "Bloqueado por vigilancia: OpenRouter registró gasto" }).eq("proveedor", "openrouter");
        await sb.from("app_config").upsert({ clave: "openrouter_gasto_base", valor: String(uso) });
        try { await sb.rpc("wa_notificar", { p: { topic: "hidrofresh-wa-92t4l9df", title: "⚠️ Gasto en IA detectado", message: `OpenRouter registró USD ${sube} de gasto. Se bloqueó OpenRouter en el enrutador; alguna función usa un modelo de pago. Revisa con Claude.`, priority: 5, tags: ["warning"] } }); } catch (_) { /* aviso opcional */ }
      }
    } catch (e) { out.openrouter_error = String(e).slice(0, 200); }
  }
  const { data: cobros } = await sb.from("ia_uso").select("id").gt("costo_usd", 0).limit(1);
  out.cobros_en_registro = cobros?.length ?? 0;
  return out;
}

// ---------- v1.6: proveedores extra estilo FreeLLMAPI (se descubren solos cuando hay clave) ----------
type Extra = { modelos: () => string; filtro: RegExp; rpm: number; rpd: number | null; tpm: number | null; nota: string; lista?: (j: any) => any[] };
const EXTRA: Record<string, Extra> = {
  cerebras: { modelos: () => "https://api.cerebras.ai/v1/models", filtro: /gpt-oss|qwen|llama|glm|zai/i, rpm: 30, rpd: 14400, tpm: 60000, nota: "Cerebras free tier (~1M tokens/día)" },
  mistral: { modelos: () => "https://api.mistral.ai/v1/models", filtro: /^(mistral-(large|medium|small)-latest|magistral-(medium|small)-latest|ministral-8b-latest)$/i, rpm: 60, rpd: null, tpm: 500000, nota: "Mistral plan Experiment (gratis)" },
  nvidia: { modelos: () => "https://integrate.api.nvidia.com/v1/models", filtro: /nemotron.*(ultra|super)|deepseek|qwen3|kimi|glm|gpt-oss|llama-3\.3-70|mistral-large/i, rpm: 40, rpd: null, tpm: null, nota: "NVIDIA NIM (programa de desarrolladores, gratis)" },
  github: { modelos: () => "https://models.github.ai/catalog/models", filtro: /gpt-4\.1|gpt-4o|gpt-5|deepseek|llama|mistral|grok|phi-4/i, rpm: 10, rpd: 50, tpm: null, nota: "GitHub Models (cupo gratis)", lista: (j) => (Array.isArray(j) ? j : j.data ?? []).filter((x: any) => !x.supported_output_modalities || x.supported_output_modalities.includes("text")) },
  freellmapi: { modelos: () => `${(CFG["freellmapi_url"] ?? "").replace(/\/+$/, "")}/v1/models`, filtro: /.*/, rpm: 60, rpd: null, tpm: null, nota: "FreeLLMAPI propio (enruta 30+ proveedores gratis)" },
};
const NO_CHAT = /embed|guard|rerank|tts|whisper|ocr|moderation|safety|reward|retriever|parse|vlm-only|clip|audio|image-gen|flux|sdxl/i;
const calidadExtra = (id: string) => /deepseek-(v3|r1|v4)|kimi|qwen3-235|qwen3\.\d|gpt-oss-120|nemotron.*ultra|mistral-large|gpt-4\.1$|gpt-5|glm-4\.[5-9]|glm-5/i.test(id) ? 75 : /70b|qwen3|gpt-oss|mistral-medium|magistral|gpt-4o|nemotron.*super|grok/i.test(id) ? 65 : 55;
async function catalogoExtra(sb: any, out: any, ahora: string) {
  for (const [p, e] of Object.entries(EXTRA)) {
    if (!PROV[p].key()) continue;
    try {
      const r = await fetchT(e.modelos(), { headers: { Authorization: "Bearer " + PROV[p].key(), Accept: "application/json" } }, 20_000);
      if (!r.ok) { out[p + "_error"] = r.status + " " + (await r.text()).replace(/\s+/g, " ").slice(0, 150); continue; }
      const j = await r.json();
      const items: any[] = e.lista ? e.lista(j) : (j.data ?? []);
      const vistos = items.map((x: any) => ({ id: String(x.id ?? x.name ?? ""), ctx: Number(x.context_length ?? x.max_context_length ?? x.limits?.max_input_tokens ?? 0) || 128000 }))
        .filter((x) => x.id && e.filtro.test(x.id) && !NO_CHAT.test(x.id)).slice(0, 12);
      out[p] = vistos.map((x) => x.id);
      const { data: existentes } = await sb.from("ia_modelos").select("id,modelo").eq("proveedor", p);
      const ya = new Set((existentes ?? []).map((x: any) => x.modelo));
      const nuevos = vistos.filter((x) => !ya.has(x.id)).map((x) => ({
        id: p + ":" + x.id, proveedor: p, modelo: x.id,
        tareas: ["extraccion", "redaccion", "rapido", ...(/r1|reason|think|magistral|gpt-oss|qwen3|kimi|ultra|gpt-5/i.test(x.id) ? ["razonamiento"] : [])],
        calidad: calidadExtra(x.id), ctx: x.ctx, rpm: e.rpm, rpd: e.rpd, tpm: e.tpm, json_nativo: true, gratis: true, activo: true, visto_en_catalogo: ahora, nota: e.nota,
      }));
      if (nuevos.length) await sb.from("ia_modelos").insert(nuevos);
      for (const v of existentes ?? []) await sb.from("ia_modelos").update(out[p].includes(v.modelo) ? { visto_en_catalogo: ahora } : { activo: false, motivo: "ya no aparece en el catálogo del proveedor" }).eq("id", v.id);
    } catch (err) { out[p + "_error"] = String(err).slice(0, 200); }
  }
}

// ---------- catálogo en vivo ----------
async function catalogo(sb: any) {
  const out: any = {}; const ahora = new Date().toISOString();
  // Gemini: lista oficial del API
  if (clave("gemini")) {
    try {
      const r = await fetchT("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", { headers: { "x-goog-api-key": clave("gemini") } }, 20_000);
      const j = await r.json(); const ids = (j.models ?? []).filter((x: any) => (x.supportedGenerationMethods ?? []).includes("generateContent")).map((x: any) => String(x.name).replace(/^models\//, ""));
      out.gemini = ids.filter((x: string) => /flash|gemma/.test(x));
      const { data: seeds } = await sb.from("ia_modelos").select("id,modelo").eq("proveedor", "gemini");
      for (const s of seeds ?? []) await sb.from("ia_modelos").update(ids.includes(s.modelo) ? { visto_en_catalogo: ahora } : { activo: false, motivo: "no aparece en el catálogo de Google" }).eq("id", s.id);
    } catch (e) { out.gemini_error = String(e); }
  }
  // Groq
  if (clave("groq")) {
    try {
      const r = await fetchT("https://api.groq.com/openai/v1/models", { headers: { Authorization: "Bearer " + clave("groq") } }, 20_000);
      const ids = ((await r.json()).data ?? []).map((x: any) => x.id); out.groq = ids;
      const { data: seeds } = await sb.from("ia_modelos").select("id,modelo").eq("proveedor", "groq");
      for (const s of seeds ?? []) await sb.from("ia_modelos").update(ids.includes(s.modelo) ? { visto_en_catalogo: ahora } : { activo: false, motivo: "no aparece en el catálogo de Groq" }).eq("id", s.id);
    } catch (e) { out.groq_error = String(e); }
  }
  // OpenRouter: SOLO ids ":free" con precio 0 en todo
  if (clave("openrouter")) {
    try {
      const r = await fetchT("https://openrouter.ai/api/v1/models", {}, 20_000);
      const L = ((await r.json()).data ?? []).filter((x: any) => String(x.id).endsWith(":free") && ["prompt", "completion", "request", "image"].every((k) => !x.pricing?.[k] || Number(x.pricing[k]) === 0) && (x.architecture?.output_modalities ?? ["text"]).includes("text"));
      out.openrouter = L.map((x: any) => x.id);
      const cal = (id: string) => /deepseek|qwen3-235|kimi|gpt-oss-120|llama-3\.3-70|glm-4\.5|mistral-medium|nemotron-ultra/i.test(id) ? 70 : /70b|72b|qwen3|gemma-3-27|mistral-small/i.test(id) ? 60 : 50;
      const filas = L.map((x: any) => ({ id: "openrouter:" + x.id, proveedor: "openrouter", modelo: x.id, tareas: ["extraccion", "redaccion", "rapido", ...(/deepseek-r1|qwq|reason|think/i.test(x.id) ? ["razonamiento"] : [])], calidad: cal(x.id), ctx: Number(x.context_length) || 32000, rpm: 20, rpd: 50, json_nativo: (x.supported_parameters ?? []).includes("response_format"), gratis: true, visto_en_catalogo: ahora, nota: "OpenRouter :free (precio 0 verificado)" }));
      if (filas.length) await sb.from("ia_modelos").upsert(filas, { onConflict: "id" });
      const { data: viejos } = await sb.from("ia_modelos").select("id,modelo").eq("proveedor", "openrouter");
      for (const v of viejos ?? []) if (!out.openrouter.includes(v.modelo)) await sb.from("ia_modelos").update({ activo: false, gratis: false, motivo: "ya no es gratis o no existe en OpenRouter" }).eq("id", v.id);
    } catch (e) { out.openrouter_error = String(e); }
  }
  // v1.6: Cerebras, Mistral, NVIDIA, GitHub Models y FreeLLMAPI propio
  await catalogoExtra(sb, out, ahora);
  // Ollama propio (opcional)
  if (CFG["ollama_url"]) {
    try {
      const r = await fetchT(CFG["ollama_url"].replace(/\/+$/, "") + "/api/tags", { headers: CFG["ollama_token"] ? { Authorization: "Bearer " + CFG["ollama_token"] } : {} }, 10_000);
      const ms = ((await r.json()).models ?? []).map((x: any) => x.name); out.ollama = ms;
      if (ms.length) await sb.from("ia_modelos").upsert(ms.map((n: string) => ({ id: "ollama:" + n, proveedor: "ollama", modelo: n, tareas: ["extraccion", "redaccion", "rapido"], calidad: 30, ctx: 32000, json_nativo: true, gratis: true, visto_en_catalogo: ahora, nota: "Ollama local (sin costo)" })), { onConflict: "id" });
    } catch (e) { out.ollama_error = String(e); }
  }
  out.opcionales_sin_clave = ["cerebras", "mistral", "nvidia", "github", "cloudflare", "freellmapi"].filter((p) => !PROV[p].key());
  return out;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  T0.v = Date.now(); T0.lim = 140_000; T0.porModelo = 45_000;
  const sb = svc();
  try {
    if (!(await autorizado(req, sb))) return json({ error: "Sesión no válida" }, 401);
    const body = await req.json().catch(() => ({}));
    await cargarClaves(sb);
    if (Number(CFG["ia_presupuesto_usd"] ?? 0) !== 0) return json({ error: "El presupuesto de IA debe ser USD 0 (app_config ia_presupuesto_usd). El enrutador no opera con presupuesto distinto de 0." }, 400);
    if (body?.chat) { if (body.chat.limite_ms) T0.lim = Math.max(15_000, Math.min(140_000, Number(body.chat.limite_ms))); return json(await chat(sb, body.chat)); }
    if (body?.mensajes) { if (body.mensajes.limite_ms) T0.lim = Math.max(10_000, Math.min(140_000, Number(body.mensajes.limite_ms))); return json(await chatMensajes(sb, body.mensajes)); }
    if (body?.catalogo) return json(await catalogo(sb));
    if (body?.vigilar) return json(await vigilar(sb));
    if (body?.estado) {
      const { data: ms } = await sb.from("ia_modelos").select("id,proveedor,modelo,calidad,activo,gratis,agotado_hasta,motivo,restante_req,restante_tok,rpd,usos_total").order("proveedor").order("calidad", { ascending: false });
      const { data: hoy } = await sb.from("ia_resumen_hoy").select("*");
      const { data: err } = await sb.from("ia_uso").select("creado,proveedor,modelo,status,error").eq("ok", false).order("creado", { ascending: false }).limit(15);
      const { data: cobros } = await sb.from("ia_uso").select("id").gt("costo_usd", 0).limit(1);
      return json({ presupuesto_usd: 0, costo_registrado_total: cobros?.length ? "REVISAR: hay usos con costo" : 0, proveedores_sin_clave: Object.keys(PROV).filter((p) => !PROV[p].key()), modelos: ms, hoy, ultimos_errores: err });
    }
    if (body?.probar) {
      const { data: ms } = await sb.from("ia_modelos").select("*").eq("activo", true).eq("gratis", true);
      const res: any = {};
      const elegidos = (ms ?? []).filter((m: any) => (!body.proveedor || m.proveedor === body.proveedor) && esGratis(m) && PROV[m.proveedor].key()).sort((a: any, b: any) => b.calidad - a.calidad);
      const orN = elegidos.filter((m: any) => m.proveedor === "openrouter").slice(0, 3).map((m: any) => m.id); // no gastar el cupo diario de OpenRouter en pruebas
      for (const m of elegidos.filter((m: any) => m.proveedor !== "openrouter" || orN.includes(m.id))) {
        if (resta() < 15_000) { res[m.id] = "sin tiempo"; continue; }
        const t = Date.now();
        try {
          const r: any = await llamar(m, "Responde SOLO con JSON válido.", 'Devuelve {"ok":true}', true, 400);
          await sb.from("ia_uso").insert({ funcion: "ia-router:probar", tarea: "rapido", proveedor: m.proveedor, modelo: m.modelo, ok: r.ok, status: r.status, tok_in: r.tin ?? null, tok_out: r.tout ?? null, ms: Date.now() - t, costo_usd: r.costo ?? 0, error: r.ok ? null : String(r.err).replace(/\s+/g, " ").slice(0, 1500) });
          res[m.id] = r.ok ? `OK ${Date.now() - t} ms · ${r.tin}+${r.tout} tok · costo ${r.costo ?? 0}` : `${r.status}: ${String(r.err).replace(/\s+/g, " ").slice(0, 120)}`;
          if (!r.ok) await castigar(sb, m, r.status, String(r.err ?? ""), r.headers); else await anotarCupo(sb, m, r.headers);
        } catch (e) { res[m.id] = (e instanceof Cobro ? "COBRO: " : "error: ") + String((e as Error).message).slice(0, 120); if (e instanceof Cobro) await sb.from("ia_modelos").update({ activo: false, gratis: false, motivo: "COBRO DETECTADO" }).eq("proveedor", m.proveedor); }
      }
      return json(res);
    }
    return json({ error: "Falta parámetro" }, 400);
  } catch (e) { return json({ error: e instanceof Error ? e.message : String(e) }, 500); }
});
