"""
Recall.ai client — bot "DDM" entra na reunião (Teams/Zoom/Meet), grava e transcreve.
Substitui o Microsoft Graph para captura de reuniões (não precisa de App Registration).
Docs: https://docs.recall.ai
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()


def _region() -> str:
    # us-west-2 = pay-as-you-go (default). Outras: us-east-1, eu-central-1, ap-northeast-1.
    return os.getenv("RECALL_REGION", "us-west-2").strip()


def _base() -> str:
    return f"https://{_region()}.recall.ai/api/v1"


def _bot_name() -> str:
    return os.getenv("RECALL_BOT_NAME", "DDM").strip() or "DDM"


def _headers() -> dict:
    key = os.getenv("RECALL_API_KEY", "").strip()
    return {
        "Authorization": f"Token {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ── Bot ────────────────────────────────────────────────────────────────────────

def create_bot(meeting_url: str, bot_name: str | None = None) -> dict:
    """
    Cria bot que entra na reunião, grava e transcreve.
    Retorna o JSON do bot (o id fica em ['id']).
    """
    payload = {
        "meeting_url": meeting_url,
        "bot_name": bot_name or _bot_name(),
        "recording_config": {
            "transcript": {"provider": {"recallai_streaming": {}}}
        },
    }
    resp = requests.post(f"{_base()}/bot", headers=_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_bot(bot_id: str) -> dict:
    resp = requests.get(f"{_base()}/bot/{bot_id}", headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def bot_status(bot: dict) -> str:
    """Último código de status do bot (ex.: 'done', 'in_call_recording', 'fatal')."""
    changes = bot.get("status_changes") or []
    if changes:
        return changes[-1].get("code", "")
    return (bot.get("status") or {}).get("code", "")


# ── Transcrição ─────────────────────────────────────────────────────────────────

def _transcript_download_url(bot: dict) -> str | None:
    recordings = bot.get("recordings") or []
    if not recordings:
        return None
    shortcuts = recordings[0].get("media_shortcuts") or {}
    transcript = shortcuts.get("transcript") or {}
    data = transcript.get("data") or {}
    return data.get("download_url")


def fetch_transcript(bot_id: str) -> list[dict]:
    """
    Baixa a transcrição do bot e converte para o formato de utterances usado
    pelo pipeline: [{speaker, texto, start_ms, end_ms}].
    Retorna lista vazia se ainda não há transcrição.
    """
    bot = get_bot(bot_id)
    url = _transcript_download_url(bot)
    if not url:
        return []
    # download_url já vem assinado — não enviar header de auth.
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return parse_recall_transcript(resp.json())


def parse_recall_transcript(segments: list) -> list[dict]:
    """
    Converte o JSON de transcrição do Recall (lista de segmentos) em utterances.
    Cada segmento = 1 participante falando; agrega as palavras em uma fala.
    """
    utterances = []
    for seg in segments or []:
        words = seg.get("words") or []
        if not words:
            continue
        speaker = (seg.get("participant") or {}).get("name") or "?"
        texto = " ".join((w.get("text") or "") for w in words).strip()
        if not texto:
            continue
        start = (words[0].get("start_timestamp") or {}).get("relative") or 0
        end = (words[-1].get("end_timestamp") or {}).get("relative") or start
        utterances.append({
            "speaker": speaker,
            "texto": texto,
            "start_ms": int(float(start) * 1000),
            "end_ms": int(float(end) * 1000),
        })
    return utterances
