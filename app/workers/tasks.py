import os
from datetime import datetime, timedelta, timezone

from app.extensions import celery, get_supabase
from app.pipeline.graph import (
    get_users,
    get_meetings,
    get_transcript_vtt,
    parse_vtt,
)
from app.pipeline.analysis import extrair_reuniao, extrair_email


# ── Helpers ───────────────────────────────────────────────────────────────────

def _iso_since(hours: int = 24) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_active_users() -> list[dict]:
    db = get_supabase()
    resp = db.table("usuarios").select("ms_user_id,nome,email,setor").eq("ativo", True).execute()
    return resp.data or []


# ── Sync Usuários (Azure AD → Supabase) ───────────────────────────────────────

@celery.task
def sync_usuarios_ad():
    """Sincroniza usuários do Azure AD. Roda a cada 1h."""
    domain = os.getenv("TEAMS_DOMAIN", "grupoddm.com.br")
    users = get_users(domain)
    if not users:
        return

    db = get_supabase()
    for u in users:
        if not u.get("mail"):
            continue
        db.table("usuarios").upsert(
            {
                "ms_user_id": u["id"],
                "nome": u.get("displayName", ""),
                "email": u["mail"].lower(),
                "setor": u.get("department", ""),
                "cargo": u.get("jobTitle", ""),
                "ativo": True,
                "atualizado_em": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="ms_user_id",
        ).execute()


# ── Sync Reuniões Teams ───────────────────────────────────────────────────────

@celery.task
def sync_reunioes_teams():
    """Poll de novas reuniões Teams. Roda a cada SYNC_INTERVAL_MINUTES."""
    since = _iso_since(hours=25)  # 25h para cobrir sobreposições
    users = _get_active_users()

    for user in users:
        user_id = user["ms_user_id"]
        meetings = get_meetings(user_id, since)

        db = get_supabase()
        for meeting in meetings:
            ms_id = meeting.get("id")
            if not ms_id:
                continue

            # evita reprocessar
            exists = (
                db.table("reunioes")
                .select("id")
                .eq("ms_meeting_id", ms_id)
                .execute()
            )
            if exists.data:
                continue

            # insere com status pending
            row = db.table("reunioes").insert(
                {
                    "ms_meeting_id": ms_id,
                    "titulo": meeting.get("subject", "Reunião Teams"),
                    "setor": user.get("setor", ""),
                    "data": meeting.get("startDateTime"),
                    "plataforma": "teams",
                    "status": "pending",
                }
            ).execute()

            if row.data:
                reuniao_id = row.data[0]["id"]
                processar_reuniao_teams.delay(
                    reuniao_id, user_id, ms_id
                )


@celery.task(bind=True, max_retries=3)
def processar_reuniao_teams(self, reuniao_id: str, user_id: str, ms_meeting_id: str):
    """Busca VTT, analisa com Claude, salva no Supabase."""
    db = get_supabase()
    try:
        db.table("reunioes").update({"status": "processing"}).eq("id", reuniao_id).execute()

        vtt = get_transcript_vtt(user_id, ms_meeting_id)

        if not vtt:
            db.table("reunioes").update(
                {"status": "sem_transcricao"}
            ).eq("id", reuniao_id).execute()
            return

        utterances = parse_vtt(vtt)
        full_text = " ".join(u["texto"] for u in utterances)

        duracao = None
        if utterances:
            duracao = int(utterances[-1]["end_ms"] / 60000)

        analise = extrair_reuniao(full_text, utterances)

        db.table("reunioes").update(
            {
                "status": "completed",
                "transcricao_full": full_text,
                "utterances": utterances,
                "duracao_minutos": duracao,
                "topicos": analise.get("topicos", []),
                "decisoes": analise.get("decisoes estrategicas", []),
                "pendencias": analise.get("pendencias", []),
                "resumo_executivo": analise.get("resumo_executivo", ""),
                "sentimento_geral": analise.get("sentimento_geral", "neutro"),
                "participantes": analise.get("participantes_ativos", []),
            }
        ).eq("id", reuniao_id).execute()

    except Exception as e:
        db.table("reunioes").update(
            {"status": "error", "erro_msg": str(e)}
        ).eq("id", reuniao_id).execute()
        raise self.retry(exc=e, countdown=60)


# ── Gravações Recall.ai (bot "DDM" entra na reunião) ─────────────────────────

def _processar_recall(reuniao_id: str, bot_id: str):
    """
    Baixa a transcrição do bot Recall, analisa com IA e grava no Supabase.
    Função síncrona — usada tanto pela task Celery quanto pela thread do webhook
    (funciona sem Redis).
    """
    from app.pipeline.recall_client import fetch_transcript

    db = get_supabase()
    try:
        db.table("reunioes").update({"status": "processing"}).eq("id", reuniao_id).execute()

        utterances = fetch_transcript(bot_id)
        if not utterances:
            db.table("reunioes").update(
                {"status": "sem_transcricao"}
            ).eq("id", reuniao_id).execute()
            return

        full_text = " ".join(u["texto"] for u in utterances)
        duracao = int(utterances[-1]["end_ms"] / 60000) if utterances else None

        analise = extrair_reuniao(full_text, utterances)

        db.table("reunioes").update(
            {
                "status": "completed",
                "transcricao_full": full_text,
                "utterances": utterances,
                "duracao_minutos": duracao,
                "topicos": analise.get("topicos", []),
                "decisoes": analise.get("decisoes estrategicas", []),
                "pendencias": analise.get("pendencias", []),
                "resumo_executivo": analise.get("resumo_executivo", ""),
                "sentimento_geral": analise.get("sentimento_geral", "neutro"),
                "participantes": analise.get("participantes_ativos", []),
            }
        ).eq("id", reuniao_id).execute()

    except Exception as e:
        db.table("reunioes").update(
            {"status": "error", "erro_msg": str(e)}
        ).eq("id", reuniao_id).execute()
        raise


@celery.task(bind=True, max_retries=3)
def processar_gravacao_recall(self, reuniao_id: str, bot_id: str):
    """Wrapper Celery de _processar_recall (retry em falha)."""
    try:
        _processar_recall(reuniao_id, bot_id)
    except Exception as e:
        raise self.retry(exc=e, countdown=60)


# ── Sync E-mails Outlook ──────────────────────────────────────────────────────

@celery.task
def sync_emails_outlook():
    """Poll de novos e-mails Outlook. Roda a cada SYNC_INTERVAL_MINUTES."""
    from app.pipeline.graph import get_emails

    since = _iso_since(hours=25)
    domain = os.getenv("TEAMS_DOMAIN", "grupoddm.com.br")
    users = _get_active_users()
    db = get_supabase()

    for user in users:
        emails = get_emails(user["ms_user_id"], since)

        for email in emails:
            msg_id = email.get("id")
            if not msg_id or email.get("isDraft"):
                continue

            # filtra apenas e-mails corporativos
            remetente = email.get("from", {}).get("emailAddress", {}).get("address", "")
            if not remetente.endswith(f"@{domain}"):
                continue

            exists = (
                db.table("emails")
                .select("id")
                .eq("message_id", msg_id)
                .execute()
            )
            if exists.data:
                continue

            destinatarios = [
                {
                    "nome": r["emailAddress"].get("name", ""),
                    "email": r["emailAddress"].get("address", "").lower(),
                }
                for r in email.get("toRecipients", [])
            ]

            row = db.table("emails").insert(
                {
                    "message_id": msg_id,
                    "de_email": remetente.lower(),
                    "de_nome": email["from"]["emailAddress"].get("name", ""),
                    "para": destinatarios,
                    "assunto": email.get("subject", ""),
                    "setor_remetente": user.get("setor", ""),
                    "data": email.get("receivedDateTime"),
                    "thread_id": email.get("conversationId"),
                    "plataforma": "outlook",
                    "status": "pending",
                }
            ).execute()

            if row.data:
                processar_email.delay(
                    row.data[0]["id"],
                    email.get("bodyPreview", ""),
                    email.get("subject", ""),
                    remetente,
                    destinatarios,
                )


@celery.task
def sync_emails_imap():
    """
    Poll de novos e-mails via IMAP (cPanel). Alternativa ao Microsoft Graph
    para caixas fora do Microsoft 365. Roda a cada SYNC_INTERVAL_MINUTES.
    """
    from datetime import datetime, timedelta, timezone
    from flask import current_app
    from app.pipeline.imap_client import get_emails_imap

    if not current_app.config.get("IMAP_HOST"):
        return  # IMAP não configurado

    corp = [d.strip().lower() for d in current_app.config["CORP_DOMAINS"].split(",") if d.strip()]
    setor_remetente = current_app.config.get("IMAP_USER", "").split("@")[0]

    since = datetime.now(timezone.utc) - timedelta(hours=25)
    emails = get_emails_imap(since)
    db = get_supabase()

    for mail in emails:
        msg_id = mail.get("message_id")
        remetente = mail.get("de_email", "")
        if not msg_id:
            continue

        # evita reprocessar
        exists = db.table("emails").select("id").eq("message_id", msg_id).execute()
        if exists.data:
            continue

        row = db.table("emails").insert(
            {
                "message_id": msg_id,
                "de_email": remetente,
                "de_nome": mail.get("de_nome", ""),
                "para": mail.get("para", []),
                "assunto": mail.get("assunto", ""),
                "setor_remetente": setor_remetente,
                "data": mail.get("data"),
                "thread_id": mail.get("thread_id", ""),
                "plataforma": "imap",
                "status": "pending",
            }
        ).execute()

        if row.data:
            processar_email.delay(
                row.data[0]["id"],
                mail.get("corpo", ""),
                mail.get("assunto", ""),
                remetente,
                mail.get("para", []),
            )


@celery.task(bind=True, max_retries=3)
def processar_email(
    self,
    email_id: str,
    body_preview: str,
    assunto: str,
    de_email: str,
    destinatarios: list,
):
    """Analisa e-mail com Claude, atualiza Supabase e grafo de interações."""
    db = get_supabase()
    try:
        analise = extrair_email(assunto, body_preview, de_email)

        db.table("emails").update(
            {
                "status": "completed",
                "resumo": analise.get("resumo", ""),
                "temas": analise.get("temas", []),
                "sentimento": analise.get("sentimento", "neutro"),
                "categoria": analise.get("categoria", "corporativo"),
                "relevante": analise.get("relevante", True),
            }
        ).eq("id", email_id).execute()

        # atualiza grafo de interações
        temas = analise.get("temas", [])
        for dest in destinatarios:
            dest_email = dest.get("email", "")
            if not dest_email:
                continue
            for tema in temas:
                db.table("interacoes").upsert(
                    {
                        "pessoa_a": de_email,
                        "pessoa_b": dest_email,
                        "tema": tema,
                        "contagem": 1,
                        "ultima_interacao": datetime.now(timezone.utc).isoformat(),
                    },
                    on_conflict="pessoa_a,pessoa_b,tema",
                ).execute()

    except Exception as e:
        db.table("emails").update(
            {"status": "error", "erro_msg": str(e)}
        ).eq("id", email_id).execute()
        raise self.retry(exc=e, countdown=60)


# ── Áudio avulso (fallback Azure Speech) ─────────────────────────────────────

@celery.task(bind=True, max_retries=3)
def processar_audio_avulso(self, reuniao_id: str, audio_path: str):
    """Fallback para upload manual de MP3/MP4 via Azure Speech."""
    from app.pipeline.audio import transcrever

    db = get_supabase()
    try:
        db.table("reunioes").update({"status": "processing"}).eq("id", reuniao_id).execute()

        result = transcrever(audio_path)
        analise = extrair_reuniao(result["text"], result["utterances"])

        duracao = None
        if result.get("audio_duration_ms"):
            duracao = int(result["audio_duration_ms"] / 60000)

        db.table("reunioes").update(
            {
                "status": "completed",
                "transcricao_full": result["text"],
                "utterances": result["utterances"],
                "duracao_minutos": duracao,
                "topicos": analise.get("topicos", []),
                "decisoes": analise.get("decisoes estrategicas", []),
                "pendencias": analise.get("pendencias", []),
                "resumo_executivo": analise.get("resumo_executivo", ""),
                "sentimento_geral": analise.get("sentimento_geral", "neutro"),
                "participantes": analise.get("participantes_ativos", []),
            }
        ).eq("id", reuniao_id).execute()

    except Exception as e:
        db.table("reunioes").update(
            {"status": "error", "erro_msg": str(e)}
        ).eq("id", reuniao_id).execute()
        raise self.retry(exc=e, countdown=60)

    finally:
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)


# ── Resumo Executivo Diário ───────────────────────────────────────────────────

@celery.task
def gerar_resumo_diario():
    """Agrega dados do dia e gera resumo para diretoria. Roda às 18h."""
    from app.pipeline.analysis import extrair_resumo_diario

    db = get_supabase()
    hoje = datetime.now(timezone.utc).date().isoformat()

    reunioes = (
        db.table("reunioes")
        .select("decisoes,pendencias,resumo_executivo,setor")
        .gte("data", hoje)
        .eq("status", "completed")
        .execute()
    ).data or []

    emails = (
        db.table("emails")
        .select("id")
        .gte("data", hoje)
        .eq("status", "completed")
        .execute()
    ).data or []

    todas_decisoes = [d for r in reunioes for d in (r.get("decisoes") or [])]
    todas_pendencias = [p for r in reunioes for p in (r.get("pendencias") or [])]

    resumo = extrair_resumo_diario(todas_decisoes, todas_pendencias)

    db.table("resumos_diarios").upsert(
        {
            "data": hoje,
            "total_reunioes": len(reunioes),
            "total_emails": len(emails),
            "destaques": todas_decisoes[:10],
            "alertas": [p for p in todas_pendencias if not p.get("responsavel")],
            "resumo_texto": resumo,
        },
        on_conflict="data",
    ).execute()
