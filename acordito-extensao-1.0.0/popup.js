import {
  DEFAULT_API_BASE,
  normalizarBase,
  urlDeReuniao,
  extrairLink,
  lerPrefs,
} from "./shared.js";

const $ = (id) => document.getElementById(id);

let apiBase = DEFAULT_API_BASE;
let usuarioReconhecido = null;
let buscaUsuarioTimer = null;
let buscaUsuarioVersao = 0;

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

async function reconhecerUsuario({ silencioso = false } = {}) {
  const email = $("usuarioEmail").value.trim().toLowerCase();
  const versao = ++buscaUsuarioVersao;
  usuarioReconhecido = null;
  $("solicitante").value = "";
  if (!email || !$("usuarioEmail").checkValidity()) {
    $("usuarioStatus").textContent = email && !silencioso ? "Informe um e-mail corporativo válido." : "";
    $("usuarioStatus").className = "user-status";
    return false;
  }

  $("usuarioStatus").textContent = "Consultando cadastro...";
  $("usuarioStatus").className = "user-status";
  try {
    const r = await fetch(apiBase + "/api/extensao/usuario?email=" + encodeURIComponent(email));
    const usuario = await r.json().catch(() => ({}));
    if (versao !== buscaUsuarioVersao) return false;
    if (!r.ok) throw new Error(r.status === 404 ? "Cadastro não encontrado ou ainda não aprovado." : "Não foi possível consultar o cadastro.");
    usuarioReconhecido = { email, nome: usuario.nome, setor: usuario.setor };
    $("solicitante").value = usuario.nome;
    if (usuario.setor) {
      const seletor = $("setor");
      if (![...seletor.options].some((opcao) => opcao.value === usuario.setor)) {
        seletor.add(new Option(usuario.setor, usuario.setor));
      }
      seletor.value = usuario.setor;
    }
    $("usuarioStatus").textContent = "Cadastro reconhecido.";
    $("usuarioStatus").className = "user-status ok";
    await chrome.storage.local.set({ usuarioEmail: email });
    return true;
  } catch (e) {
    if (versao !== buscaUsuarioVersao) return false;
    $("usuarioStatus").textContent = e.message;
    $("usuarioStatus").className = "user-status err";
    return false;
  }
}

async function enviar(ev) {
  ev.preventDefault();

  const url = $("url").value.trim();
  const email = $("usuarioEmail").value.trim().toLowerCase();

  if (!url) return;
  if (!urlDeReuniao(url)) {
    msg("Use um link do Teams, Zoom ou Google Meet.", false);
    return;
  }
  if ((!usuarioReconhecido || usuarioReconhecido.email !== email) && !(await reconhecerUsuario())) {
    msg("Informe o e-mail de um usuário aprovado no painel.", false);
    return;
  }
  const solicitante = usuarioReconhecido.nome;
  const visibilidade_setor = $("visibilidade_setor").value;

  const dataInput = $("data_reuniao").value;

  const body = {
    meeting_url: url,
    titulo: $("titulo").value.trim(),
    data: dataInput ? new Date(dataInput).toISOString() : "",
    solicitante,
    setor: $("setor").value,
    visibilidade_setor,
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
      usuarioEmail: email,
      solicitante,
      setor: body.setor,
      modalidade: body.modalidade,
      local_reuniao: body.local_reuniao,
    });

    msg(
      d.scheduled_start_time
        ? "Reunião agendada. O Acordito tentará entrar no horário informado."
        : "O Acordito está a caminho da reunião. A ata fica disponível para a diretoria ao final.",
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

  $("usuarioEmail").value = prefs.usuarioEmail || "";
  $("modalidade").value = prefs.modalidade || "online";
  $("local_reuniao").value = prefs.local_reuniao || "Online";
  $("visibilidade_setor").value = "gestores";
  $("data_reuniao").value = agoraLocal();
  $("foot").textContent = apiBase.replace(/^https?:\/\//, "");

  const achou = await usarAba({ silencioso: true });
  if (!achou) {
    aviso(
      "Abra a reunião nesta aba ou cole o link. A reunião precisa estar em andamento ou prestes a começar — se houver sala de espera, admita o Acordito."
    );
  }

  await carregarSetores(prefs.setor);
  if (prefs.usuarioEmail) reconhecerUsuario({ silencioso: true });

  $("usuarioEmail").addEventListener("input", () => {
    clearTimeout(buscaUsuarioTimer);
    buscaUsuarioVersao++;
    usuarioReconhecido = null;
    $("solicitante").value = "";
    $("usuarioStatus").textContent = "";
    buscaUsuarioTimer = setTimeout(() => reconhecerUsuario({ silencioso: true }), 450);
  });
  $("usuarioEmail").addEventListener("blur", () => {
    clearTimeout(buscaUsuarioTimer);
    if (!usuarioReconhecido) reconhecerUsuario({ silencioso: true });
  });

  $("form").addEventListener("submit", enviar);
  $("btnAba").addEventListener("click", () => usarAba());
  $("btnColar").addEventListener("click", colarLink);
  $("cfg").addEventListener("click", (e) => {
    e.preventDefault();
    chrome.runtime.openOptionsPage();
  });
}

init();
