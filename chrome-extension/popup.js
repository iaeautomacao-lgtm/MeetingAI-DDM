import {
  DEFAULT_API_BASE,
  normalizarBase,
  urlDeReuniao,
  extrairLink,
  lerPrefs,
} from "./shared.js";

const $ = (id) => document.getElementById(id);

let apiBase = DEFAULT_API_BASE;

function aviso(texto) {
  const el = $("aviso");
  if (!texto) {
    el.classList.add("hidden");
    return;
  }
  el.textContent = texto;
  el.classList.remove("hidden");
}

function msg(texto, ok) {
  const el = $("msg");
  el.className = "msg " + (ok ? "ok" : "err");
  el.textContent = texto;
  el.classList.remove("hidden");
}

function agoraLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

async function abaAtual() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab || null;
}

// Preenche link e título a partir da aba aberta, se for uma reunião.
async function usarAba({ silencioso = false } = {}) {
  const tab = await abaAtual();
  if (tab && urlDeReuniao(tab.url || "")) {
    $("url").value = tab.url;
    if (!$("titulo").value && tab.title) {
      $("titulo").value = tab.title
        .replace(/\s*[|·–-]\s*(Microsoft Teams|Zoom|Google Meet).*$/i, "")
        .trim()
        .slice(0, 120);
    }
    aviso("");
    return true;
  }
  if (!silencioso) {
    msg(
      "A aba atual não é uma reunião do Teams, Zoom ou Meet. Cole o link manualmente.",
      false
    );
  }
  return false;
}

async function colarLink() {
  try {
    const texto = await navigator.clipboard.readText();
    const link = extrairLink(texto);
    if (!link) {
      msg("Nenhum link de reunião encontrado no que foi copiado.", false);
      return;
    }
    $("url").value = link;
    $("msg").classList.add("hidden");
  } catch {
    msg("Não foi possível ler a área de transferência.", false);
  }
}

async function carregarSetores(salvo) {
  const sel = $("setor");
  try {
    const r = await fetch(apiBase + "/api/setores");
    const setores = await r.json();
    (Array.isArray(setores) ? setores : []).forEach((s) => {
      const o = document.createElement("option");
      o.value = s.nome;
      o.textContent = s.nome;
      sel.appendChild(o);
    });
    if (salvo) sel.value = salvo;
  } catch {
    // Sem rede/servidor: dropdown fica só com a opção vazia (setor é opcional).
  }
}

async function enviar(ev) {
  ev.preventDefault();

  const url = $("url").value.trim();
  const solicitante = $("solicitante").value.trim();

  if (!url) return;
  if (!urlDeReuniao(url)) {
    msg("Use um link do Teams, Zoom ou Google Meet.", false);
    return;
  }
  if (!solicitante) {
    msg("Informe seu nome.", false);
    return;
  }

  const dataInput = $("data_reuniao").value;

  const body = {
    meeting_url: url,
    titulo: $("titulo").value.trim(),
    data: dataInput ? new Date(dataInput).toISOString() : "",
    solicitante,
    setor: $("setor").value,
    modalidade: $("modalidade").value,
    local_reuniao: $("local_reuniao").value,
    cliente: $("cliente").value.trim(),
  };

  const btn = $("btn");
  btn.disabled = true;
  btn.textContent = "Enviando...";

  try {
    const r = await fetch(apiBase + "/api/gravacoes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.msg || d.erro || "HTTP " + r.status);

    // Guarda o que não muda entre reuniões.
    await chrome.storage.local.set({
      solicitante,
      setor: body.setor,
      modalidade: body.modalidade,
      local_reuniao: body.local_reuniao,
    });

    msg(
      "O Acordito está a caminho da reunião. A ata fica disponível para a diretoria ao final.",
      true
    );
    $("url").value = "";
    $("titulo").value = "";
    $("cliente").value = "";
  } catch (e) {
    msg("Não foi possível registrar: " + e.message, false);
  } finally {
    btn.disabled = false;
    btn.textContent = "Enviar Acordito";
  }
}

async function init() {
  const prefs = await lerPrefs();
  apiBase = normalizarBase(prefs.apiBase);

  $("solicitante").value = prefs.solicitante || "";
  $("modalidade").value = prefs.modalidade || "online";
  $("local_reuniao").value = prefs.local_reuniao || "Online";
  $("data_reuniao").value = agoraLocal();
  $("foot").textContent = apiBase.replace(/^https?:\/\//, "");

  const achou = await usarAba({ silencioso: true });
  if (!achou) {
    aviso(
      "Abra a reunião nesta aba ou cole o link. A reunião precisa estar em andamento ou prestes a começar — se houver sala de espera, admita o Acordito."
    );
  }

  carregarSetores(prefs.setor);

  $("form").addEventListener("submit", enviar);
  $("btnAba").addEventListener("click", () => usarAba());
  $("btnColar").addEventListener("click", colarLink);
  $("cfg").addEventListener("click", (e) => {
    e.preventDefault();
    chrome.runtime.openOptionsPage();
  });
}

init();
