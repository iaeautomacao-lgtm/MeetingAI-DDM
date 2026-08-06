import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from app.extensions import celery, get_mysql_connection
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


def _normalizar_datetime_mysql(value):
    """
    Converte data ISO com timezone para datetime UTC sem timezone,
    formato aceito pelo MariaDB DATETIME.
    """
    if not value:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        texto = str(value).strip().replace("Z", "+00:00")

        try:
            dt = datetime.fromisoformat(texto)
        except ValueError:
            return value

    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

    return dt


def _json_list(value) -> list:
    """Converte JSON salvo como texto para lista Python."""
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    return []


def _atualizar_reuniao_mysql(
    reuniao_id: str,
    campos: dict,
) -> None:
    """Atualiza campos permitidos de uma reunião no MySQL."""
    if not reuniao_id or not campos:
        return

    campos_permitidos = {
        "status",
        "transcricao_full",
        "utterances",
        "duracao_minutos",
        "topicos",
        "decisoes",
        "pendencias",
        "resumo_executivo",
        "sentimento_geral",
        "participantes",
        "erro_msg",
    }

    campos_validos = {
        campo: valor
        for campo, valor in campos.items()
        if campo in campos_permitidos
    }

    if not campos_validos:
        return

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()

        atribuicoes = []
        valores = []

        for campo, valor in campos_validos.items():
            atribuicoes.append(f"`{campo}` = %s")

            if isinstance(valor, (list, dict)):
                valor = json.dumps(
                    valor,
                    ensure_ascii=False,
                    default=str,
                )

            valores.append(valor)

        valores.append(reuniao_id)

        cursor.execute(
            f"""
            UPDATE reunioes
            SET {", ".join(atribuicoes)}
            WHERE id = %s
            """,
            tuple(valores),
        )

        connection.commit()

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


def _get_active_users() -> list[dict]:
    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                ms_user_id,
                nome,
                email,
                setor
            FROM usuarios
            WHERE ativo = 1
            """
        )

        return cursor.fetchall()

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# ── Sync Usuários (Azure AD → MySQL) ──────────────────────────────────────────

@celery.task
def sync_usuarios_ad():
    """Sincroniza usuários do Azure AD no MySQL. Roda a cada 1h."""
    domain = os.getenv("TEAMS_DOMAIN", "grupoddm.com.br")
    users = get_users(domain)

    if not users:
        return

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()

        for user in users:
            email = (user.get("mail") or "").strip().lower()

            if not email:
                continue

            cursor.execute(
                """
                INSERT INTO usuarios (
                    id,
                    ms_user_id,
                    nome,
                    email,
                    setor,
                    cargo,
                    ativo,
                    atualizado_em
                )
                VALUES (
                    UUID(),
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                ON DUPLICATE KEY UPDATE
                    nome = VALUES(nome),
                    email = VALUES(email),
                    setor = VALUES(setor),
                    cargo = VALUES(cargo),
                    ativo = VALUES(ativo),
                    atualizado_em = VALUES(atualizado_em)
                """,
                (
                    user["id"],
                    user.get("displayName", ""),
                    email,
                    user.get("department", ""),
                    user.get("jobTitle", ""),
                    1,
                    datetime.now(timezone.utc),
                ),
            )

        connection.commit()

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# ── Sync Reuniões Teams ───────────────────────────────────────────────────────

@celery.task
def sync_reunioes_teams():
    """
    Busca novas reuniões do Teams e salva no MySQL.

    Roda conforme SYNC_INTERVAL_MINUTES.
    """
    since = _iso_since(hours=25)
    users = _get_active_users()

    for user in users:
        user_id = user.get("ms_user_id")

        if not user_id:
            continue

        meetings = get_meetings(user_id, since)

        for meeting in meetings:
            ms_meeting_id = meeting.get("id")

            if not ms_meeting_id:
                continue

            connection = None
            cursor = None

            try:
                connection = get_mysql_connection()
                cursor = connection.cursor(dictionary=True)

                cursor.execute(
                    """
                    SELECT id
                    FROM reunioes
                    WHERE ms_meeting_id = %s
                    LIMIT 1
                    """,
                    (ms_meeting_id,),
                )

                existente = cursor.fetchone()

                if existente:
                    continue

                reuniao_id = str(uuid.uuid4())

                cursor.execute(
                    """
                    INSERT INTO reunioes (
                        id,
                        ms_meeting_id,
                        titulo,
                        setor,
                        data,
                        plataforma,
                        status
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        reuniao_id,
                        ms_meeting_id,
                        meeting.get(
                            "subject",
                            "Reunião Teams",
                        ),
                        user.get("setor", ""),
                        meeting.get("startDateTime"),
                        "teams",
                        "pending",
                    ),
                )

                connection.commit()

                processar_reuniao_teams.delay(
                    reuniao_id,
                    user_id,
                    ms_meeting_id,
                )

            except Exception:
                if connection is not None:
                    connection.rollback()
                raise

            finally:
                if cursor is not None:
                    cursor.close()

                if (
                    connection is not None
                    and connection.is_connected()
                ):
                    connection.close()


@celery.task(bind=True, max_retries=3)
def processar_reuniao_teams(
    self,
    reuniao_id: str,
    user_id: str,
    ms_meeting_id: str,
):
    """
    Busca a transcrição VTT do Teams, analisa com IA
    e salva o resultado no MySQL.
    """
    try:
        _atualizar_reuniao_mysql(
            reuniao_id,
            {
                "status": "processing",
                "erro_msg": None,
            },
        )

        vtt = get_transcript_vtt(
            user_id,
            ms_meeting_id,
        )

        if not vtt:
            _atualizar_reuniao_mysql(
                reuniao_id,
                {
                    "status": "sem_transcricao",
                },
            )
            return "sem_transcricao"

        utterances = parse_vtt(vtt)

        full_text = " ".join(
            item.get("texto", "")
            for item in utterances
            if item.get("texto")
        )

        duracao = None

        if utterances:
            ultimo_end_ms = utterances[-1].get("end_ms")

            if ultimo_end_ms is not None:
                duracao = int(
                    ultimo_end_ms / 60000
                )

        analise = extrair_reuniao(
            full_text,
            utterances,
        )

        _atualizar_reuniao_mysql(
            reuniao_id,
            {
                "status": "completed",
                "transcricao_full": full_text,
                "utterances": utterances,
                "duracao_minutos": duracao,
                "topicos": analise.get(
                    "topicos",
                    [],
                ),
                "decisoes": analise.get(
                    "decisoes",
                    [],
                ),
                "pendencias": analise.get(
                    "pendencias",
                    [],
                ),
                "resumo_executivo": analise.get(
                    "resumo_executivo",
                    "",
                ),
                "sentimento_geral": analise.get(
                    "sentimento_geral",
                    "neutro",
                ),
                "participantes": analise.get(
                    "participantes_ativos",
                    [],
                ),
                "erro_msg": None,
            },
        )

        return "completed"

    except Exception as exc:
        try:
            _atualizar_reuniao_mysql(
                reuniao_id,
                {
                    "status": "error",
                    "erro_msg": str(exc),
                },
            )
        except Exception:
            pass

        raise self.retry(
            exc=exc,
            countdown=60,
        )

# ── Gravações Recall.ai (bot "DDM" entra na reunião) ─────────────────────────

def _processar_recall(reuniao_id: str, bot_id: str):
    """
    Baixa a transcrição do bot Skribby, analisa com IA
    e atualiza a reunião no MySQL.

    Função síncrona usada pela task Celery,
    pelo webhook e pelo processamento manual.
    """
    from app.pipeline.skribby_client import (
        get_bot,
        bot_status,
        parse_skribby_transcript,
        extract_skribby_participants,
    )

    def atualizar_reuniao(campos: dict) -> None:
        if not campos:
            return

        connection = None
        cursor = None

        try:
            connection = get_mysql_connection()
            cursor = connection.cursor()

            atribuicoes = []
            valores = []

            for coluna, valor in campos.items():
                atribuicoes.append(f"`{coluna}` = %s")

                if isinstance(valor, (list, dict)):
                    valor = json.dumps(
                        valor,
                        ensure_ascii=False,
                    )

                valores.append(valor)

            valores.append(reuniao_id)

            sql = f"""
                UPDATE reunioes
                SET {", ".join(atribuicoes)}
                WHERE id = %s
            """

            cursor.execute(sql, tuple(valores))
            connection.commit()

        except Exception:
            if connection is not None:
                connection.rollback()
            raise

        finally:
            if cursor is not None:
                cursor.close()

            if (
                connection is not None
                and connection.is_connected()
            ):
                connection.close()

    try:
        bot = get_bot(bot_id)
        status = bot_status(bot)

        # Bot ainda está na reunião ou processando.
        if status and status != "finished":
            estados_falha = {
                "not_admitted",
                "bot_detected",
                "auth_required",
                "invalid_credentials",
                "invalid_api_key",
                "failed",
            }

            novo_status = (
                "error"
                if status in estados_falha
                else "pending"
            )

            campos = {
                "status": novo_status
            }

            if novo_status == "error":
                campos["erro_msg"] = (
                    f"bot Skribby: {status}"
                )

            atualizar_reuniao(campos)

            return novo_status

        atualizar_reuniao({
            "status": "processing",
            "erro_msg": None,
        })

        utterances = parse_skribby_transcript(bot)

        if not utterances:
            atualizar_reuniao({
                "status": "sem_transcricao"
            })

            return "sem_transcricao"

        # O Skribby manda os nomes reais em participants[] e a diarização em
        # transcript[].speaker, sem ligar os dois. Cruza pelos eventos de fala
        # quando existem; senão infere pelo diálogo. O que não resolver fica
        # "Speaker N" para renomear no painel.
        from app.pipeline.locutores import identificar_locutores

        utterances, mapa_locutores, origem_locutores = identificar_locutores(
            bot,
            utterances,
        )

        if mapa_locutores:
            logging.getLogger(__name__).info(
                "Locutores identificados por %s: %s",
                origem_locutores,
                mapa_locutores,
            )

        full_text = " ".join(
            utterance.get("texto", "")
            for utterance in utterances
            if utterance.get("texto")
        )

        duracao = None

        if utterances:
            ultimo_end_ms = (
                utterances[-1].get("end_ms")
            )

            if ultimo_end_ms is not None:
                duracao = int(
                    ultimo_end_ms / 60000
                )

        analise = extrair_reuniao(
            full_text,
            utterances,
        )

        participantes = (
            analise.get("participantes_ativos")
            or extract_skribby_participants(bot)
            or []
        )

        atualizar_reuniao({
            "status": "completed",
            "transcricao_full": full_text,
            "utterances": utterances,
            "duracao_minutos": duracao,
            "topicos": analise.get("topicos", []),
            "decisoes": analise.get("decisoes", []),
            "pendencias": analise.get("pendencias", []),
            "key_takeaways": analise.get("key_takeaways", []),
            "riscos": analise.get("riscos", []),
            "perguntas_abertas": analise.get("perguntas_abertas", []),
            "clima": analise.get("clima", {}),
            "resumo_executivo": analise.get(
                "resumo_executivo",
                "",
            ),
            "sentimento_geral": analise.get(
                "sentimento_geral",
                "neutro",
            ),
            "participantes": participantes,
            "erro_msg": None,
        })

        return "completed"

    except Exception as exc:
        try:
            atualizar_reuniao({
                "status": "error",
                "erro_msg": str(exc),
            })

        except Exception:
            pass

        raise

@celery.task
def limpar_lixeira_expirada():
    """Apaga de vez as reuniões que passaram do prazo de retenção da lixeira."""
    from app.api.routes import purgar_lixeira_expirada

    return purgar_lixeira_expirada()


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
    """Busca novos e-mails do Outlook e salva no MySQL."""
    from app.pipeline.graph import get_emails

    since = _iso_since(hours=25)
    domain = os.getenv("TEAMS_DOMAIN", "grupoddm.com.br").lower()
    users = _get_active_users()

    for user in users:
        user_id = user.get("ms_user_id")

        if not user_id:
            continue

        emails = get_emails(user_id, since)

        for email in emails:
            msg_id = email.get("id")

            if not msg_id or email.get("isDraft"):
                continue

            remetente_info = (
                email.get("from", {})
                .get("emailAddress", {})
            )

            remetente = (
                remetente_info.get("address", "")
                .strip()
                .lower()
            )

            if not remetente.endswith(f"@{domain}"):
                continue

            destinatarios = [
                {
                    "nome": (
                        recipient.get("emailAddress", {})
                        .get("name", "")
                    ),
                    "email": (
                        recipient.get("emailAddress", {})
                        .get("address", "")
                        .strip()
                        .lower()
                    ),
                }
                for recipient in email.get("toRecipients", [])
            ]

            email_id = str(uuid.uuid4())
            connection = None
            cursor = None

            try:
                connection = get_mysql_connection()
                cursor = connection.cursor()

                cursor.execute(
                    """
                    INSERT IGNORE INTO emails (
                        id,
                        message_id,
                        de_email,
                        de_nome,
                        para,
                        assunto,
                        setor_remetente,
                        data,
                        thread_id,
                        plataforma,
                        status,
                        criado_em
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        email_id,
                        msg_id,
                        remetente,
                        remetente_info.get("name", ""),
                        json.dumps(
                            destinatarios,
                            ensure_ascii=False,
                            default=str,
                        ),
                        email.get("subject", ""),
                        user.get("setor", ""),
                        _normalizar_datetime_mysql(
                            email.get("receivedDateTime")
                        ),
                        email.get("conversationId"),
                        "outlook",
                        "pending",
                        datetime.now(timezone.utc).replace(
                            tzinfo=None
                        ),
                    ),
                )

                inserido = cursor.rowcount > 0
                connection.commit()

            except Exception:
                if connection is not None:
                    connection.rollback()
                raise

            finally:
                if cursor is not None:
                    cursor.close()

                if (
                    connection is not None
                    and connection.is_connected()
                ):
                    connection.close()

            if inserido:
                processar_email.delay(
                    email_id,
                    email.get("bodyPreview", ""),
                    email.get("subject", ""),
                    remetente,
                    destinatarios,
                )


# ── Sync E-mails IMAP ─────────────────────────────────────────────────────────

@celery.task
def sync_emails_imap():
    """Busca novos e-mails por IMAP e salva no MySQL."""
    from flask import current_app
    from app.pipeline.imap_client import get_emails_imap

    if not current_app.config.get("IMAP_HOST"):
        return

    setor_remetente = (
        current_app.config.get("IMAP_USER", "")
        .split("@")[0]
    )

    since = datetime.now(timezone.utc) - timedelta(hours=25)
    emails = get_emails_imap(since)

    for mail in emails:
        msg_id = mail.get("message_id")

        if not msg_id:
            continue

        remetente = (
            mail.get("de_email", "")
            .strip()
            .lower()
        )

        destinatarios = mail.get("para", []) or []
        email_id = str(uuid.uuid4())

        connection = None
        cursor = None

        try:
            connection = get_mysql_connection()
            cursor = connection.cursor()

            cursor.execute(
                """
                INSERT IGNORE INTO emails (
                    id,
                    message_id,
                    de_email,
                    de_nome,
                    para,
                    assunto,
                    setor_remetente,
                    data,
                    thread_id,
                    plataforma,
                    status,
                    criado_em
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    email_id,
                    msg_id,
                    remetente,
                    mail.get("de_nome", ""),
                    json.dumps(
                        destinatarios,
                        ensure_ascii=False,
                        default=str,
                    ),
                    mail.get("assunto", ""),
                    setor_remetente,
                    _normalizar_datetime_mysql(
                        mail.get("data")
                    ),
                    mail.get("thread_id", ""),
                    "imap",
                    "pending",
                    datetime.now(timezone.utc).replace(
                        tzinfo=None
                    ),
                ),
            )

            inserido = cursor.rowcount > 0
            connection.commit()

        except Exception:
            if connection is not None:
                connection.rollback()
            raise

        finally:
            if cursor is not None:
                cursor.close()

            if (
                connection is not None
                and connection.is_connected()
            ):
                connection.close()

        if inserido:
            processar_email.delay(
                email_id,
                mail.get("corpo", ""),
                mail.get("assunto", ""),
                remetente,
                destinatarios,
            )


# ── Processamento de e-mail ───────────────────────────────────────────────────

@celery.task(bind=True, max_retries=3)
def processar_email(
    self,
    email_id: str,
    body_preview: str,
    assunto: str,
    de_email: str,
    destinatarios: list,
):
    """
    Analisa e-mail com IA, atualiza o e-mail no MySQL
    e atualiza o grafo de interações.
    """
    connection = None
    cursor = None

    try:
        analise = extrair_email(
            assunto,
            body_preview,
            de_email,
        )

        temas = analise.get("temas", []) or []

        connection = get_mysql_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE emails
            SET
                status = %s,
                resumo = %s,
                temas = %s,
                sentimento = %s,
                categoria = %s,
                relevante = %s,
                erro_msg = NULL
            WHERE id = %s
            """,
            (
                "completed",
                analise.get("resumo", ""),
                json.dumps(
                    temas,
                    ensure_ascii=False,
                    default=str,
                ),
                analise.get(
                    "sentimento",
                    "neutro",
                ),
                analise.get(
                    "categoria",
                    "corporativo",
                ),
                1 if analise.get(
                    "relevante",
                    True,
                ) else 0,
                email_id,
            ),
        )

        for destinatario in destinatarios:
            destinatario_email = (
                destinatario.get("email", "")
                .strip()
                .lower()
            )

            if not destinatario_email:
                continue

            for tema in temas:
                tema_texto = str(tema).strip()

                if not tema_texto:
                    continue

                cursor.execute(
                    """
                    INSERT INTO interacoes (
                        id,
                        pessoa_a,
                        pessoa_b,
                        tema,
                        contagem,
                        ultima_interacao
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s
                    )
                    ON DUPLICATE KEY UPDATE
                        contagem = COALESCE(contagem, 0) + 1,
                        ultima_interacao =
                            VALUES(ultima_interacao)
                    """,
                    (
                        str(uuid.uuid4()),
                        de_email.strip().lower(),
                        destinatario_email,
                        tema_texto,
                        1,
                        datetime.now(timezone.utc).replace(
                            tzinfo=None
                        ),
                    ),
                )

        connection.commit()
        return "completed"

    except Exception as exc:
        if connection is not None:
            connection.rollback()

        error_connection = None
        error_cursor = None

        try:
            error_connection = get_mysql_connection()
            error_cursor = error_connection.cursor()

            error_cursor.execute(
                """
                UPDATE emails
                SET
                    status = %s,
                    erro_msg = %s
                WHERE id = %s
                """,
                (
                    "error",
                    str(exc),
                    email_id,
                ),
            )

            error_connection.commit()

        finally:
            if error_cursor is not None:
                error_cursor.close()

            if (
                error_connection is not None
                and error_connection.is_connected()
            ):
                error_connection.close()

        raise self.retry(
            exc=exc,
            countdown=60,
        )

    finally:
        if cursor is not None:
            cursor.close()

        if (
            connection is not None
            and connection.is_connected()
        ):
            connection.close()


# ── Resumo Executivo Diário ───────────────────────────────────────────────────

@celery.task
def gerar_resumo_diario():
    """Gera e salva no MySQL o resumo executivo do dia."""
    from app.pipeline.analysis import extrair_resumo_diario

    hoje = datetime.now(timezone.utc).date()
    amanha = hoje + timedelta(days=1)

    inicio = datetime.combine(
        hoje,
        datetime.min.time(),
    )

    fim = datetime.combine(
        amanha,
        datetime.min.time(),
    )

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                decisoes,
                pendencias,
                resumo_executivo,
                setor
            FROM reunioes
            WHERE excluida_em IS NULL
              AND data >= %s
              AND data < %s
              AND status = %s
            """,
            (
                inicio,
                fim,
                "completed",
            ),
        )

        reunioes = cursor.fetchall()

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM emails
            WHERE data >= %s
              AND data < %s
              AND status = %s
            """,
            (
                inicio,
                fim,
                "completed",
            ),
        )

        total_emails = cursor.fetchone()["total"]

        todas_decisoes = []
        todas_pendencias = []

        for reuniao in reunioes:
            todas_decisoes.extend(
                _json_list(reuniao.get("decisoes"))
            )

            todas_pendencias.extend(
                _json_list(reuniao.get("pendencias"))
            )

        alertas = [
            pendencia
            for pendencia in todas_pendencias
            if not pendencia.get("responsavel")
        ]

        resumo = extrair_resumo_diario(
            todas_decisoes,
            todas_pendencias,
        )

        cursor.execute(
            """
            INSERT INTO resumos_diarios (
                id,
                data,
                total_reunioes,
                total_emails,
                destaques,
                alertas,
                resumo_texto,
                criado_em
            )
            VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                total_reunioes =
                    VALUES(total_reunioes),
                total_emails =
                    VALUES(total_emails),
                destaques =
                    VALUES(destaques),
                alertas =
                    VALUES(alertas),
                resumo_texto =
                    VALUES(resumo_texto)
            """,
            (
                str(uuid.uuid4()),
                hoje,
                len(reunioes),
                total_emails,
                json.dumps(
                    todas_decisoes[:10],
                    ensure_ascii=False,
                    default=str,
                ),
                json.dumps(
                    alertas,
                    ensure_ascii=False,
                    default=str,
                ),
                resumo,
                datetime.now(timezone.utc).replace(
                    tzinfo=None
                ),
            ),
        )

        connection.commit()

        return {
            "data": hoje.isoformat(),
            "total_reunioes": len(reunioes),
            "total_emails": total_emails,
        }

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if (
            connection is not None
            and connection.is_connected()
        ):
            connection.close()
