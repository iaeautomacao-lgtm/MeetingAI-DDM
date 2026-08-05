"""
Microsoft Graph API client.
Usa client credentials flow (app-only) — sem login de usuário.
Requer permissões: OnlineMeetings.Read.All, OnlineMeetingTranscript.Read.All,
                   CallRecords.Read.All, Mail.Read, User.Read.All
"""
# Anotacoes adiadas: "X | None" (PEP 604) so avalia em runtime a partir
# do Python 3.10, e o interpretador do cPanel e mais antigo. Sem isso o
# app quebra no import em producao.
from __future__ import annotations


import os
import re
import msal
import requests
from dotenv import load_dotenv

load_dotenv()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_msal_app = None


def _get_msal_app():
    global _msal_app
    if _msal_app is None:
        _msal_app = msal.ConfidentialClientApplication(
            os.getenv("AZURE_CLIENT_ID"),
            authority=f"https://login.microsoftonline.com/{os.getenv('AZURE_TENANT_ID')}",
            client_credential=os.getenv("AZURE_CLIENT_SECRET"),
        )
    return _msal_app


def _get_token() -> str:
    result = _get_msal_app().acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    if "access_token" not in result:
        raise RuntimeError(f"MSAL: {result.get('error_description', result.get('error'))}")
    return result["access_token"]


def _headers(accept="application/json") -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Accept": accept,
    }


def _paginate(url: str, params: dict | None = None) -> list:
    results = []
    while url:
        resp = requests.get(url, headers=_headers(), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        params = None
    return results


# ── Usuários ──────────────────────────────────────────────────────────────────

def get_users(domain: str) -> list[dict]:
    """Retorna todos os usuários do domínio com id, nome, email, setor, cargo."""
    return _paginate(
        f"{GRAPH_BASE}/users",
        params={
            "$select": "id,displayName,mail,department,jobTitle",
            "$filter": f"endswith(mail,'{domain}')",
            "$top": 999,
        },
    )


# ── Reuniões Teams ────────────────────────────────────────────────────────────

def get_meetings(user_id: str, since_iso: str) -> list[dict]:
    """Lista online meetings de um usuário a partir de uma data ISO 8601."""
    try:
        return _paginate(
            f"{GRAPH_BASE}/users/{user_id}/onlineMeetings",
            params={"$filter": f"startDateTime ge {since_iso}"},
        )
    except requests.HTTPError as e:
        if e.response.status_code in (403, 404):
            return []
        raise


def get_transcript_vtt(user_id: str, meeting_id: str) -> str | None:
    """
    Busca o conteúdo VTT da primeira transcrição disponível.
    Retorna None se reunião não tem transcrição.
    Requer Teams auto-transcription habilitado pelo admin.
    """
    list_url = f"{GRAPH_BASE}/users/{user_id}/onlineMeetings/{meeting_id}/transcripts"
    resp = requests.get(list_url, headers=_headers(), timeout=30)
    if resp.status_code in (403, 404):
        return None
    resp.raise_for_status()

    transcripts = resp.json().get("value", [])
    if not transcripts:
        return None

    transcript_id = transcripts[0]["id"]
    content_url = (
        f"{GRAPH_BASE}/users/{user_id}/onlineMeetings/{meeting_id}"
        f"/transcripts/{transcript_id}/content"
    )
    resp = requests.get(
        content_url,
        headers=_headers(accept="text/vtt"),
        params={"$format": "text/vtt"},
        timeout=30,
    )
    if resp.status_code in (403, 404):
        return None
    resp.raise_for_status()
    return resp.text


def get_call_record(call_id: str) -> dict:
    """Retorna detalhes de chamada: participantes, duração, plataforma."""
    resp = requests.get(
        f"{GRAPH_BASE}/communications/callRecords/{call_id}",
        headers=_headers(),
        params={"$expand": "sessions($expand=segments)"},
        timeout=30,
    )
    if resp.status_code in (403, 404):
        return {}
    resp.raise_for_status()
    return resp.json()


# ── Parser VTT ────────────────────────────────────────────────────────────────

def parse_vtt(vtt_text: str) -> list[dict]:
    """
    Converte VTT do Teams em lista de utterances.
    Teams usa o formato: <v Nome do Speaker>texto
    """
    utterances = []
    blocks = re.split(r"\n{2,}", vtt_text.strip())

    for block in blocks:
        lines = block.strip().splitlines()
        # procura linha com timestamp (HH:MM:SS.mmm --> HH:MM:SS.mmm)
        ts_line = next((l for l in lines if "-->" in l), None)
        if ts_line is None:
            continue

        start_str, end_str = ts_line.split("-->")
        text_lines = lines[lines.index(ts_line) + 1:]
        text = " ".join(text_lines).strip()

        speaker_match = re.match(r"<v ([^>]+)>(.*)", text)
        if speaker_match:
            speaker = speaker_match.group(1).strip()
            text = speaker_match.group(2).strip()
        else:
            speaker = "?"

        if not text:
            continue

        utterances.append({
            "speaker": speaker,
            "texto": text,
            "start_ms": _vtt_time_to_ms(start_str.strip()),
            "end_ms": _vtt_time_to_ms(end_str.strip()),
        })

    return utterances


def _vtt_time_to_ms(t: str) -> int:
    # HH:MM:SS.mmm ou MM:SS.mmm
    t = t.strip()
    parts = t.replace(",", ".").split(".")
    ms = int(parts[1]) if len(parts) > 1 else 0
    hms = parts[0].split(":")
    if len(hms) == 3:
        h, m, s = int(hms[0]), int(hms[1]), int(hms[2])
    else:
        h, m, s = 0, int(hms[0]), int(hms[1])
    return (h * 3600 + m * 60 + s) * 1000 + ms


# ── E-mails Outlook ───────────────────────────────────────────────────────────

def get_emails(user_id: str, since_iso: str, top: int = 50) -> list[dict]:
    """Lista e-mails recebidos/enviados de um usuário desde since_iso."""
    try:
        return _paginate(
            f"{GRAPH_BASE}/users/{user_id}/messages",
            params={
                "$filter": f"receivedDateTime ge {since_iso}",
                "$select": (
                    "id,from,toRecipients,subject,bodyPreview,"
                    "receivedDateTime,conversationId,isDraft"
                ),
                "$top": top,
                "$orderby": "receivedDateTime desc",
            },
        )
    except requests.HTTPError as e:
        if e.response.status_code in (403, 404):
            return []
        raise
