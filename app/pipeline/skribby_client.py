"""
Skribby client — bot "Acordito" entra na reunião (Teams/Zoom/Meet), grava e transcreve.
Substitui o Recall.ai. Mesma interface (create_bot / get_bot / bot_status / fetch_transcript)
para o resto do pipeline não precisar mudar.
Docs: https://skribby.io/docs
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()


# ── Config ──────────────────────────────────────────────────────────────────────

def _base() -> str:
    # US: platform.skribby.io | Japão: platform-jp.skribby.io
    host = os.getenv("SKRIBBY_HOST", "platform.skribby.io").strip()
    return f"https://{host}/api/v1"


def _bot_name() -> str:
    # reaproveita RECALL_BOT_NAME se SKRIBBY_BOT_NAME não estiver setado
    return (
        os.getenv("SKRIBBY_BOT_NAME")
        or os.getenv("RECALL_BOT_NAME")
        or "Acordito"
    ).strip() or "Acordito"


def _model() -> str:
    # Whisper large v3 turbo (Groq) — rápido e suporta português.
    return os.getenv("SKRIBBY_MODEL", "groq/whisper-large-v3-turbo").strip()


def _lang() -> str:
    return os.getenv("SKRIBBY_LANG", "pt").strip()


def _headers() -> dict:
    key = os.getenv("SKRIBBY_API_KEY", "").strip()
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _avatar_url() -> str | None:
    """URL pública do avatar do Acordito (servido pelo próprio site)."""
    base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/assets/acordito_bot.jpg"


def _webhook_url() -> str | None:
    base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/api/skribby/webhook"


def _detect_service(meeting_url: str) -> str:
    """Descobre a plataforma pela URL. Skribby exige: gmeet | teams | zoom."""
    u = (meeting_url or "").lower()
    if "zoom.us" in u:
        return "zoom"
    if "teams.microsoft.com" in u or "teams.live.com" in u or "teams." in u:
        return "teams"
    # default Google Meet
    return "gmeet"


# ── Bot ────────────────────────────────────────────────────────────────────────

def create_bot(meeting_url: str, bot_name: str | None = None) -> dict:
    """
    Cria bot que entra na reunião, grava e transcreve.
    Retorna o JSON do bot (o id fica em ['id']).
    """
    payload = {
        "meeting_url": meeting_url,
        "service": _detect_service(meeting_url),
        "bot_name": bot_name or _bot_name(),
        "transcription_model": _model(),
        "lang": _lang(),
        # Bot sai sozinho → vira 'finished' → gera transcrição (e não gasta crédito à toa).
        "stop_options": {
            "waiting_room_timeout": int(os.getenv("SKRIBBY_WAITING_ROOM_TIMEOUT", "5")),
            "empty_meeting_timeout": int(os.getenv("SKRIBBY_EMPTY_TIMEOUT", "2")),
            "last_person_detection": int(os.getenv("SKRIBBY_LAST_PERSON", "1")),
            "time_limit": int(os.getenv("SKRIBBY_TIME_LIMIT", "180")),
        },
    }

    avatar = _avatar_url()
    if avatar:
        payload["bot_avatar_url"] = avatar  # câmera do bot = Acordito (16:9)

    webhook = _webhook_url()
    if webhook:
        payload["webhook_url"] = webhook

    resp = requests.post(f"{_base()}/bot", headers=_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_bot(bot_id: str) -> dict:
    # with-speaker-events=true traz a timeline de participantes (nomes dos speakers)
    resp = requests.get(
        f"{_base()}/bot/{bot_id}",
        headers=_headers(),
        params={"with-speaker-events": "true"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def bot_status(bot: dict) -> str:
    """Status atual do bot (ex.: 'finished', 'recording', 'failed', 'not_admitted')."""
    return (bot.get("status") or "") if isinstance(bot, dict) else ""


# ── Transcrição ─────────────────────────────────────────────────────────────────

def fetch_transcript(bot_id: str) -> list[dict]:
    """
    Baixa a transcrição do bot e converte para o formato de utterances usado
    pelo pipeline: [{speaker, texto, start_ms, end_ms}].
    Retorna lista vazia se ainda não há transcrição (status != finished).
    """
    bot = get_bot(bot_id)
    segments = bot.get("transcript") or []
    return parse_skribby_transcript(segments)


def parse_skribby_transcript(segments: list) -> list[dict]:
    """
    Converte o array `transcript` do Skribby em utterances.
    Cada segmento: {transcript, start, end, speaker, speaker_name} (start/end em segundos).
    """
    utterances = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        # o texto pode vir em 'transcript' (REST) ou aninhado em 'data' (evento realtime)
        data = seg.get("data") if isinstance(seg.get("data"), dict) else seg
        texto = (data.get("transcript") or data.get("text") or "").strip()
        if not texto:
            continue
        speaker = (
            data.get("speaker_name")
            or (f"Speaker {data.get('speaker')}" if data.get("speaker") is not None else None)
            or "?"
        )
        start = data.get("start") or 0
        end = data.get("end") or start
        utterances.append({
            "speaker": speaker,
            "texto": texto,
            "start_ms": int(float(start) * 1000),
            "end_ms": int(float(end) * 1000),
        })
    return utterances
