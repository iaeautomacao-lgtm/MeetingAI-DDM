import { DEFAULT_API_BASE, normalizarBase, lerPrefs } from "./shared.js";

const $ = (id) => document.getElementById(id);

function msg(texto, ok) {
  const el = $("msg");
  el.className = "msg " + (ok ? "ok" : "err");
  el.textContent = texto;
  el.classList.remove("hidden");
}

// Hosts já declarados no manifest. Qualquer outro exige permissão em runtime.
const HOSTS_FIXOS = [
  "meeting.grupoddm.ia.br",
  "127.0.0.1",
  "localhost",
];

async function garantirPermissao(base) {
  let host;
  try {
    host = new URL(base).hostname;
  } catch {
    return false;
  }
  if (HOSTS_FIXOS.includes(host)) return true;
  return chrome.permissions.request({ origins: [base + "/*"] });
}

async function salvar() {
  const base = normalizarBase($("apiBase").value);

  if (!/^https?:\/\//.test(base)) {
    msg("A URL precisa começar com http:// ou https://", false);
    return;
  }

  const ok = await garantirPermissao(base);
  if (!ok) {
    msg("Permissão negada para esse endereço. A extensão não conseguirá enviar.", false);
    return;
  }

  await chrome.storage.local.set({
    apiBase: base,
    solicitante: $("solicitante").value.trim(),
  });

  $("apiBase").value = base;
  msg("Salvo.", true);
}

async function testar() {
  const base = normalizarBase($("apiBase").value);
  try {
    const r = await fetch(base + "/api/health");
    const d = await r.json().catch(() => ({}));
    if (r.ok && d.status === "ok") {
      msg("Servidor respondeu: ok.", true);
    } else {
      msg("Servidor respondeu HTTP " + r.status + ".", false);
    }
  } catch (e) {
    msg("Sem resposta: " + e.message + " (salve o endereço antes de testar).", false);
  }
}

async function init() {
  const prefs = await lerPrefs();
  $("apiBase").value = prefs.apiBase || DEFAULT_API_BASE;
  $("solicitante").value = prefs.solicitante || "";
  $("salvar").addEventListener("click", salvar);
  $("testar").addEventListener("click", testar);
}

init();
