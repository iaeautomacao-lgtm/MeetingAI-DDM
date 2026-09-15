"""
Skribby client — bot "Acordito" entra na reunião (Teams/Zoom/Meet), grava e transcreve.
Substitui o Recall.ai. Mesma interface (create_bot / get_bot / bot_status / fetch_transcript)
para o resto do pipeline não precisar mudar.
Docs: https://skribby.io/docs
"""

from __future__ import annotations

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
    # Plano Free do Skribby libera Groq Whisper Large v3 Turbo.
    # Modelos com diarização (nomes de locutor) exigem Pay As You Go.
    model = os.getenv("SKRIBBY_MODEL", "").strip()
    return model or "soniox/stt-async-v5"


def _lang() -> str:
    return os.getenv("SKRIBBY_LANG", "pt").strip()


def _headers() -> dict:
    key = os.getenv("SKRIBBY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("SKRIBBY_API_KEY não configurada")
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
    url = f"{base}/api/skribby/webhook"
    # Segredo compartilhado opcional: autentica o webhook (senão qualquer um posta).
    secret = os.getenv("SKRIBBY_WEBHOOK_SECRET", "").strip()
    if secret:
        from urllib.parse import quote
        url += f"?token={quote(secret, safe='')}"
    return url


def _initial_chat_message() -> str:
    return (
        os.getenv("SKRIBBY_INITIAL_CHAT_MESSAGE", "").strip()
        or (
            "Olá! Sou o Acordito, o assistente do Grupo DDM. "
            "Estou aqui para acompanhar e registrar a reunião."
        )
    )


def _custom_vocabulary(extra: list[str] | None = None) -> list[str]:
    configured = os.getenv("SKRIBBY_CUSTOM_VOCABULARY", "")
    words = [
        item.strip()
        for item in configured.replace("\n", ",").split(",")
        if item.strip()
    ]

    for item in extra or []:
        item = str(item or "").strip()
        if item:
            words.append(item)

    return list(dict.fromkeys(words))


def _detect_service(meeting_url: str) -> str:
    """Descobre a plataforma pela URL. Skribby exige: gmeet | teams | zoom."""
    u = (meeting_url or "").lower()
    if "zoom.us" in u:
        return "zoom"
    if "teams.microsoft.com" in u or "teams.live.com" in u or "teams." in u:
        return "teams"
    if "meet.google.com" in u:
        return "gmeet"
    raise ValueError("serviço de reunião não suportado")


# ── Bot ────────────────────────────────────────────────────────────────────────

def create_bot(
    meeting_url: str,
    bot_name: str | None = None,
    custom_vocabulary: list[str] | None = None,
    scheduled_start_time: int | None = None,
) -> dict:
    """
    Cria bot que entra na reunião, grava e transcreve.
    Retorna o JSON do bot (o id fica em ['id']).
    """
    payload = {
        "meeting_url": meeting_url,
        "service": _detect_service(meeting_url),
        "bot_name": bot_name or _bot_name(),
        "lang": _lang(),
        # Bot sai sozinho → vira 'finished' → gera transcrição (e não gasta crédito à toa).
        "stop_options": {
            "waiting_room_timeout": int(os.getenv("SKRIBBY_WAITING_ROOM_TIMEOUT", "10")),
            "empty_meeting_timeout": int(os.getenv("SKRIBBY_EMPTY_TIMEOUT", "2")),
            "last_person_detection": int(os.getenv("SKRIBBY_LAST_PERSON", "1")),
            "time_limit": int(os.getenv("SKRIBBY_TIME_LIMIT", "180")),
        },
    }

    model = _model()
    if model:
        payload["transcription_model"] = model

    if scheduled_start_time:
        payload["scheduled_start_time"] = int(scheduled_start_time)

    payload["initial_chat_message"] = _initial_chat_message()

    avatar = _avatar_url()
    if avatar:
        payload["bot_avatar_url"] = avatar  # câmera do bot = Acordito (16:9)

    webhook = _webhook_url()
    if webhook:
        payload["webhook_url"] = webhook

    # Add-on de realtime. Pela documentação é o que faz o Skribby cruzar o áudio
    # com a lista de participantes da plataforma e trocar "Speaker 1" pelo nome
    # real, além de emitir os eventos started-speaking/stopped-speaking. Com o
    # modelo async (soniox/stt-async-v5) nada disso vem. Desligado por padrão:
    # é cobrado à parte e ainda não confirmamos se o nome persiste no
    # transcript guardado após a reunião. Ligar com SKRIBBY_REALTIME_AUDIO=1.
    vocabulary = _custom_vocabulary(custom_vocabulary)
    if vocabulary:
        payload["custom_vocabulary"] = vocabulary

    if os.getenv("SKRIBBY_REALTIME_AUDIO", "").strip() in ("1", "true", "True"):
        payload["realtime_audio"] = True

    resp = requests.post(f"{_base()}/bot", headers=_headers(), json=payload, timeout=30)
    _raise_for_status(resp)
    return resp.json()


def get_bot(bot_id: str) -> dict:
    # with-speaker-events=true traz a timeline de participantes (nomes dos speakers)
    resp = requests.get(
        f"{_base()}/bot/{bot_id}",
        headers=_headers(),
        params={"with-speaker-events": "true"},
        timeout=30,
    )
    _raise_for_status(resp)
    return resp.json()


def _raise_for_status(resp: requests.Response) -> None:
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        detail = ""
        try:
            data = resp.json()
            detail = data.get("message") or data.get("error") or str(data)
        except Exception:
            detail = (resp.text or "").strip()
        if not detail and resp.status_code == 403:
            detail = (
                "Skribby recusou a criação do bot. Possíveis causas: limite de "
                "bots simultâneos, limite mensal de horas do plano Free, ou "
                "permissão insuficiente da conta/chave para criar bots."
            )
        if not detail:
            detail = "Resposta sem detalhes do Skribby."
        raise RuntimeError(f"{resp.status_code} {resp.reason}: {detail}") from exc


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
    return parse_skribby_transcript(bot)


def _clean_participant_name(name: str) -> str:
    name = (name or "").strip()
    suffixes = (" (Guest)", "(Guest)")
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def extract_skribby_participants(bot: dict) -> list[dict]:
    """Extrai os nomes reais que aparecem como participantes da reuniao."""
    participants = []
    seen = set()

    for item in (bot or {}).get("participants") or []:
        if not isinstance(item, dict):
            continue

        name = _clean_participant_name(item.get("name") or "")
        if not name or name.lower() == _bot_name().lower():
            continue

        key = name.lower()
        if key in seen:
            continue

        seen.add(key)
        participants.append({
            "nome": name,
        })

    return participants


def _speaker_map_from_participants(bot: dict) -> dict:
    """Mapeia IDs de speaker para nomes quando o Skribby entregar esse vinculo."""
    speaker_map = {}
    for item in (bot or {}).get("participants") or []:
        if not isinstance(item, dict):
            continue

        name = _clean_participant_name(item.get("name") or "")
        if not name:
            continue

        for key in ("speaker", "speaker_id", "speakerId", "id"):
            value = item.get(key)
            if value is not None:
                speaker_map[str(value)] = name

    return speaker_map


def _speaker_label(u: dict, speaker_map: dict | None = None) -> str:
    """Nome do locutor de uma fala. Usa speaker_name, senão o palpite, senão Speaker N, senão ?."""
    nome = u.get("speaker_name")
    if nome:
        return _clean_participant_name(nome)
    palpites = u.get("potential_speaker_names") or []
    if palpites:
        # pode vir como [{"name":..,"confidence":..}] ou ["Nome"]
        p0 = palpites[0]
        if isinstance(p0, dict) and p0.get("name"):
            return _clean_participant_name(p0["name"])
        if isinstance(p0, str):
            return _clean_participant_name(p0)
    if u.get("speaker") is not None:
        speaker_key = str(u.get("speaker"))
        if speaker_map and speaker_key in speaker_map:
            return speaker_map[speaker_key]
        return f"Speaker {u.get('speaker')}"
    return "?"


def _fala(u: dict, speaker_map: dict | None = None) -> dict | None:
    texto = (u.get("transcript") or u.get("text") or "").strip()
    if not texto:
        return None
    start = u.get("start") or 0
    end = u.get("end") or start
    return {
        "speaker": _speaker_label(u, speaker_map),
        "texto": texto,
        "start_ms": int(float(start) * 1000),
        "end_ms": int(float(end) * 1000),
    }


def parse_skribby_transcript(source) -> list[dict]:
    """
    Converte o array `transcript` do Skribby em utterances [{speaker, texto, start_ms, end_ms}].
    Cada segmento traz uma sublista `utterances` (fala a fala) — é ela que dá a divisão
    por locutor. Se não houver, cai pro texto do próprio segmento.
    Falas seguidas do MESMO locutor são unidas numa linha só (fica mais limpo).
    """
    if isinstance(source, dict):
        segments = source.get("transcript") or []
        speaker_map = _speaker_map_from_participants(source)
    else:
        segments = source or []
        speaker_map = {}

    brutas = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        data = seg.get("data") if isinstance(seg.get("data"), dict) else seg
        subs = data.get("utterances")
        if isinstance(subs, list) and subs:
            for u in subs:
                if isinstance(u, dict):
                    f = _fala(u, speaker_map)
                    if f:
                        brutas.append(f)
        else:
            f = _fala(data, speaker_map)
            if f:
                brutas.append(f)

    # une falas consecutivas do MESMO locutor (só quando há nome real —
    # se for tudo "?" mantém quebrado em turnos, senão viraria um blob de novo)
    utterances = []
    for f in brutas:
        if (utterances and utterances[-1]["speaker"] == f["speaker"]
                and f["speaker"] != "?"):
            utterances[-1]["texto"] += " " + f["texto"]
            utterances[-1]["end_ms"] = f["end_ms"]
        else:
            utterances.append(f)
    return utterances
