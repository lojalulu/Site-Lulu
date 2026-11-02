// Entrega ao relatório semanal os eventos de um período (protegido por chave).
// GET /.netlify/functions/dados?de=AAAA-MM-DD&ate=AAAA-MM-DD  (header x-chave)
import { getStore } from "@netlify/blobs";
import { nomeLoja } from "./evento.mjs";

const CAMPOS = ["t", "loja", "origem", "pedido", "valor", "itens", "pag", "v"];

export function lerChave(chave) {
  const [diaId, ...resto] = chave.split("~");
  const [dia, id] = diaId.split("/");
  const ev = { dia, ts: Number(id.split("-")[0]) };
  CAMPOS.forEach((c, i) => { ev[c] = resto[i] ?? ""; });
  ev.valor = Number(ev.valor) || 0;
  ev.itens = Number(ev.itens) || 0;
  return ev;
}

function dias(de, ate) {
  const out = [];
  const d = new Date(de + "T00:00:00Z"), fim = new Date(ate + "T00:00:00Z");
  while (d <= fim && out.length < 62) {
    out.push(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return out;
}

export default async (req, context) => {
  const chave = Netlify.env.get("RELATORIO_CHAVE");
  if (!chave || req.headers.get("x-chave") !== chave) {
    return new Response("nao autorizado", { status: 401 });
  }
  const u = new URL(req.url);
  const re = /^\d{4}-\d{2}-\d{2}$/;
  const de = u.searchParams.get("de"), ate = u.searchParams.get("ate");
  if (!re.test(de || "") || !re.test(ate || "")) {
    return new Response("use ?de=AAAA-MM-DD&ate=AAAA-MM-DD", { status: 400 });
  }
  const store = getStore(nomeLoja(context));
  const eventos = [];
  for (const dia of dias(de, ate)) {
    const { blobs } = await store.list({ prefix: dia + "/" });
    for (const b of blobs) eventos.push(lerChave(b.key));
  }
  return Response.json({ loja: nomeLoja(context), de, ate, total: eventos.length, eventos });
};
