// Constantes e helpers compartilhados entre popup e options.

// Mesma lista aceita pelo backend em app/api/routes.py (_MEETING_HOSTS).
export const MEETING_HOSTS = [
  "teams.microsoft.com",
  "teams.live.com",
  "zoom.us",
  "meet.google.com",
];

export const DEFAULT_API_BASE = "https://meeting.grupoddm.ia.br";

export function normalizarBase(valor) {
  return (valor || "").trim().replace(/\/+$/, "") || DEFAULT_API_BASE;
}

export function urlDeReuniao(url) {
  let u;
  try {
    u = new URL(url);
  } catch {
    return false;
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") return false;
  const host = u.hostname.toLowerCase();
  return MEETING_HOSTS.some((h) => host === h || host.endsWith("." + h));
}

// Procura um link de reuniao dentro de um texto colado (convite do Teams etc).
export function extrairLink(texto) {
  const candidatos = (texto || "").match(/https?:\/\/[^\s<>"')]+/g) || [];
  return candidatos.find(urlDeReuniao) || "";
}

export async function lerPrefs() {
  return chrome.storage.local.get({
    apiBase: DEFAULT_API_BASE,
    solicitante: "",
    setor: "",
    modalidade: "online",
    local_reuniao: "Online",
  });
}
