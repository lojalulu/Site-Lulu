// Funil "comenta e recebe no Direct" do Instagram.
//
// Quando alguém comenta uma palavra-chave num post/Reel (QUERO, CATÁLOGO, LINK...
// ou FRANQUIA), esta função:
//   1) manda o link por mensagem privada (Direct) respondendo ao comentário;
//   2) responde o comentário em público ("Te mandei no Direct").
//
// Segurança: só aceita chamadas assinadas pela Meta (X-Hub-Signature-256) e
// nunca grava texto de comentário, nome ou id de pessoa. Guarda só o id do
// comentário e um resumo anônimo (hash) da conta (anti-duplicado) e um contador por dia/palavra.
//
// Variáveis no Netlify (Site configuration > Environment variables):
//   INSTAGRAM_ACCESS_TOKEN  - o mesmo token já usado pelos robôs
//   INSTAGRAM_APP_SECRET    - "Chave secreta do app Instagram" (painel da Meta)
//   IG_VERIFY_TOKEN         - uma senha qualquer, a mesma colocada no painel da Meta
//   INSTAGRAM_BUSINESS_ID   - (opcional) padrão 17841401562118752
//   FRANQUIA_URL            - (opcional) link enviado a quem comenta FRANQUIA
//   DIRECT_LIGADO           - "nao" desliga as respostas sem precisar mexer no código
import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { getStore } from "@netlify/blobs";

const GRAPH = "https://graph.instagram.com/v23.0";
const IG_ID_PADRAO = "17841401562118752";
const FRANQUIA_PADRAO = "https://franquialulu.netlify.app";

const PALAVRAS_KIT = ["quero", "catalogo", "link", "preco", "precos", "kit", "kits"];
const PALAVRAS_FRANQUIA = ["franquia"];

const RESPOSTAS_PUBLICAS = [
  "Te mandei no Direct 💗",
  "Enviei no seu Direct! 💗",
  "Pronto! Olha seu Direct 💗",
  "Mandei o link no Direct, confere lá 💗",
];

export function resumo(t) {
  return createHash("sha256").update(String(t)).digest("hex").slice(0, 24);
}

export function normaliza(t) {
  return String(t ?? "")
    .toLowerCase()
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

// "franquia" tem prioridade; depois as palavras dos kits. Palavra inteira apenas.
export function classificar(texto) {
  const palavras = new Set(normaliza(texto).split(" "));
  if (PALAVRAS_FRANQUIA.some((p) => palavras.has(p))) return "franquia";
  if (PALAVRAS_KIT.some((p) => palavras.has(p))) return "kit";
  return null;
}

export function mensagemPrivada(tipo, env = {}) {
  if (tipo === "franquia") {
    const url = env.FRANQUIA_URL || FRANQUIA_PADRAO;
    return (
      "Oi! 💗 Aqui está o link da Franquia Online Lulu:\n" +
      url +
      "\n\nÉ só olhar com calma e, se tiver qualquer dúvida, responde aqui que eu te ajudo."
    );
  }
  return (
    "Oi! 💗 Aqui está o catálogo de kits da Lulu Extra Fitness:\n" +
    "https://luluextra.com/direct\n\n" +
    "Pedido mínimo de 4 kits, frete Vip grátis a partir de 6 kits e 10% de desconto no Pix. " +
    "Se tiver qualquer dúvida, é só responder aqui!"
  );
}

export function assinaturaValida(corpoBruto, cabecalho, segredo) {
  if (!segredo || !cabecalho || !cabecalho.startsWith("sha256=")) return false;
  const recebido = Buffer.from(cabecalho.slice(7));
  // A Meta às vezes assina o texto com acentos escritos como \\uXXXX (minúsculo).
  const escapado = corpoBruto.replace(/[\u0080-\uffff]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
  for (const texto of new Set([corpoBruto, escapado])) {
    const esperado = Buffer.from(createHmac("sha256", segredo).update(texto).digest("hex"));
    if (esperado.length === recebido.length && timingSafeEqual(esperado, recebido)) return true;
  }
  return false;
}

// Aceita a chave do app Instagram e, opcionalmente, a do app Meta (INSTAGRAM_APP_SECRET_FB).
// Devolve o número da chave que bateu (1 ou 2) ou 0.
export function qualChaveAssina(corpo, cabecalho, env) {
  const chaves = [env.INSTAGRAM_APP_SECRET, env.INSTAGRAM_APP_SECRET_FB].map((k) => String(k ?? "").trim());
  for (let i = 0; i < chaves.length; i++) if (chaves[i] && assinaturaValida(corpo, cabecalho, chaves[i])) return i + 1;
  return 0;
}

// Extrai só os comentários novos, de outras pessoas, que não são respostas.
export function comentariosDoPayload(payload) {
  const saida = [];
  for (const entrada of payload?.entry ?? []) {
    for (const mudanca of entrada?.changes ?? []) {
      if (mudanca?.field !== "comments") continue;
      const v = mudanca.value ?? {};
      if (!v.id || !v.text) continue;
      if (v.parent_id) continue; // é resposta a outro comentário
      if (v.from?.id && v.from.id === entrada.id) continue; // somos nós mesmos
      saida.push({ id: String(v.id), texto: String(v.text), autor: String(v.from?.id ?? ""), midia: String(v.media?.id ?? "") });
    }
  }
  return saida;
}

// `deps` existe para os testes trocarem a rede e o armazenamento por versões falsas.
export async function processar(payload, env, deps) {
  const resultado = { vistos: 0, enviados: 0, ignorados: 0, falhas: 0 };
  const igId = env.INSTAGRAM_BUSINESS_ID || IG_ID_PADRAO;
  for (const c of comentariosDoPayload(payload)) {
    resultado.vistos++;
    const tipo = classificar(c.texto);
    if (!tipo) { resultado.ignorados++; continue; }
    // anti-duplicado: mesmo comentário, ou mesma pessoa no mesmo post
    const chaveComentario = `c-${c.id}`;
    const chavePessoa = `p-${resumo(`${c.autor}-${c.midia}-${tipo}`)}`; // só um resumo anônimo, nunca o id da pessoa
    if ((await deps.jaFez(chaveComentario)) || (c.autor && (await deps.jaFez(chavePessoa)))) {
      resultado.ignorados++;
      continue;
    }
    await deps.marcar(chaveComentario);
    if (c.autor) await deps.marcar(chavePessoa);
    const privada = await deps.enviarPrivada(igId, c.id, mensagemPrivada(tipo, env));
    if (!privada) { resultado.falhas++; continue; }
    resultado.enviados++;
    await deps.contar(tipo);
    const publica = RESPOSTAS_PUBLICAS[Math.floor(Math.random() * RESPOSTAS_PUBLICAS.length)];
    await deps.responderPublico(c.id, publica); // se falhar, não atrapalha
  }
  return resultado;
}

function depsReais(env, context) {
  const producao = context?.deploy?.context === "production";
  const marcas = getStore(producao ? "direct-feito" : "direct-feito-teste");
  const contadores = getStore(producao ? "direct-contagem" : "direct-contagem-teste");
  const token = env.INSTAGRAM_ACCESS_TOKEN;
  const chamar = async (url, corpo) => {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(corpo),
    });
    if (!r.ok) {
      let cod = "";
      try { const e = (await r.json()).error ?? {}; cod = `${e.code ?? ""}/${e.error_subcode ?? ""}`; } catch {}
      console.log(`Instagram respondeu ${r.status} (${cod})`); // nunca o corpo inteiro
    }
    return r.ok;
  };
  return {
    jaFez: async (k) => (await marcas.get(k)) !== null,
    marcar: async (k) => { await marcas.set(k, "1"); },
    enviarPrivada: (igId, comentarioId, texto) =>
      chamar(`${GRAPH}/${igId}/messages`, { recipient: { comment_id: comentarioId }, message: { text: texto } }),
    responderPublico: (comentarioId, texto) =>
      chamar(`${GRAPH}/${comentarioId}/replies`, { message: texto }),
    contar: async (tipo) => {
      const dia = new Date(Date.now() - 3 * 3600 * 1000).toISOString().slice(0, 10);
      await contadores.set(`${dia}/${tipo}/${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, "1");
    },
  };
}

export default async (req, context) => {
  const env = process.env;
  const url = new URL(req.url);

  // A Meta confere o endereço uma vez, com GET.
  if (req.method === "GET") {
    const ok =
      url.searchParams.get("hub.mode") === "subscribe" &&
      env.IG_VERIFY_TOKEN &&
      url.searchParams.get("hub.verify_token") === env.IG_VERIFY_TOKEN;
    return ok ? new Response(url.searchParams.get("hub.challenge") ?? "", { status: 200 }) : new Response("negado", { status: 403 });
  }
  if (req.method !== "POST") return new Response("ok", { status: 200 });

  const corpo = await req.text();
  const cab = req.headers.get("x-hub-signature-256");
  const chave = qualChaveAssina(corpo, cab, env);
  if (!chave) {
    // Só diz o MOTIVO e uma "impressão" curta (nunca a chave): ajuda a achar chave errada ou deploy velho.
    const imp = (k) => (k ? createHash("sha256").update(String(k).trim()).digest("hex").slice(0, 6) : "-");
    console.log(`direct: recusado 401 (assinatura_da_meta=${cab ? "sim" : "NAO"}, tamanhos=${String(env.INSTAGRAM_APP_SECRET ?? "").length}/${String(env.INSTAGRAM_APP_SECRET_FB ?? "").length}, impressoes=${imp(env.INSTAGRAM_APP_SECRET)}/${imp(env.INSTAGRAM_APP_SECRET_FB)}, corpo=${corpo.length}b)`);
    return new Response("assinatura invalida", { status: 401 });
  }
  console.log(`direct: assinatura ok (chave ${chave})`);
  if (String(env.DIRECT_LIGADO).toLowerCase() === "nao") return new Response("desligado", { status: 200 });
  try {
    const payload = JSON.parse(corpo);
    const r = await processar(payload, env, depsReais(env, context));
    console.log(`direct: vistos=${r.vistos} enviados=${r.enviados} ignorados=${r.ignorados} falhas=${r.falhas}`);
  } catch (e) {
    console.log("direct: erro", String(e?.message ?? e).slice(0, 200));
  }
  // Sempre 200: a Meta reenvia em caso de erro e isso geraria mensagem duplicada.
  return new Response("ok", { status: 200 });
};
