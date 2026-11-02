// Recebe eventos do site (visita, clique no WhatsApp, pedido iniciado) e guarda
// no Netlify Blobs. Cada evento vira UMA chave nova (nada de contador), com os
// dados codificados no próprio nome da chave — assim o relatório lê tudo só
// listando as chaves. Não guarda dado pessoal (sem nome, telefone ou IP).
import { getStore } from "@netlify/blobs";

const TIPOS = new Set(["visita", "whats", "pedido"]);
const LOJAS = new Set(["kits", "avulso", "links"]);

function limpa(v, max = 40) {
  return String(v ?? "")
    .toLowerCase()
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9._-]/g, "")
    .slice(0, max);
}

export function nomeLoja(context) {
  return context?.deploy?.context === "production" ? "eventos" : "eventos-teste";
}

export function montarChave(d, agora = new Date()) {
  const t = limpa(d.t, 10);
  const loja = limpa(d.loja, 10);
  if (!TIPOS.has(t) || !LOJAS.has(loja)) return null;
  const salvador = new Date(agora.getTime() - 3 * 3600 * 1000);
  const dia = salvador.toISOString().slice(0, 10);
  const valor = Math.max(0, Math.min(1e6, Math.round(Number(d.valor) || 0)));
  const itens = Math.max(0, Math.min(10000, Math.round(Number(d.itens) || 0)));
  const campos = [
    t, loja, limpa(d.origem) || "direto", limpa(d.pedido, 16), valor, itens,
    limpa(d.pag, 10), limpa(d.v, 16), limpa(d.prod, 300),
  ];
  const id = `${agora.getTime()}-${Math.random().toString(36).slice(2, 8)}`;
  return `${dia}/${id}~${campos.join("~")}`;
}

export default async (req, context) => {
  if (req.method !== "POST") return new Response("ok", { status: 200 });
  try {
    const ua = req.headers.get("user-agent") || "";
    if (/bot|crawl|spider|preview|facebookexternalhit|headless/i.test(ua)) {
      return new Response(null, { status: 204 });
    }
    const texto = (await req.text()).slice(0, 2000);
    const chave = montarChave(JSON.parse(texto || "{}"));
    if (!chave) return new Response(null, { status: 204 });
    await getStore(nomeLoja(context)).set(chave, "1");
    return new Response(null, { status: 204 });
  } catch (e) {
    console.error("evento falhou:", e?.message);
    return new Response(null, { status: 204 });
  }
};
