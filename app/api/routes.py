# Anotacoes adiadas: "X | None" (PEP 604) so avalia em runtime a partir
# do Python 3.10, e o interpretador do cPanel e mais antigo. Sem isso o
# app quebra no import em producao.
from __future__ import annotations

import os
import json
import uuid
from datetime import datetime, timedelta, timezone
from flask import request, jsonify, current_app
from werkzeug.utils import secure_filename

from app.api import bp
from app.extensions import get_mysql_connection
from app.auth import (
    require_auth,
    require_admin,
    check_master_password,
    verificar_login,
    status_cadastro,
    registrar_acesso,
    dominio_permitido,
    listar_acessos,
    aprovar_acesso,
    rejeitar_acesso,
    definir_setor,
    definir_admin,
    atualizar_nome,
    alterar_senha,
    login_session,
    logout_session,
    is_authed,
    is_admin,
    sessao_email,
    sessao_setor,
    tem_acesso_total,
    _buscar_acesso,
)


def _q_reunioes_do_setor(q):
    """Aplica o filtro de setor: usuário comum só vê o próprio setor; diretoria vê tudo."""
    if not tem_acesso_total():
        q = q.eq("setor", sessao_setor())
    return q


def _normalizar_json_reuniao(reuniao: dict) -> dict:
    campos_json = (
        "participantes",
        "decisoes",
        "pendencias",
        "topicos",
        "utterances",
    )

    for campo in campos_json:
        valor = reuniao.get(campo)

        if isinstance(valor, str):
            texto = valor.strip()
            if not texto:
                reuniao[campo] = []
                continue

            try:
                reuniao[campo] = json.loads(texto)
            except json.JSONDecodeError:
                reuniao[campo] = []

        elif valor is None:
            reuniao[campo] = []

    return reuniao


# Hosts de reunião aceitos no /gravacoes (endpoint público). Bloqueia
# javascript:/file:/URL interna e evita que o bot entre em URL arbitrária.
_MEETING_HOSTS = (
    "teams.microsoft.com", "teams.live.com",
    "zoom.us", "meet.google.com",
)


def _meeting_url_valida(url: str) -> bool:
    from urllib.parse import urlparse
    try:
        p = urlparse((url or "").strip())
    except Exception:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname.lower()
    return any(host == h or host.endswith("." + h) for h in _MEETING_HOSTS)


# ── Health ────────────────────────────────────────────────────────────────────

@bp.get("/health")
def health():
    return jsonify({"status": "ok"})


# ── Auth (login diretor) ──────────────────────────────────────────────────────

@bp.post("/auth/login")
def auth_login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    senha = body.get("senha", "")

    # 1) login-mestre (diretor/admin): só senha, sem e-mail
    if not email and check_master_password(senha):
        login_session("", admin=True)
        return jsonify({"ok": True})

    if email:
        # 2) e-mail + senha própria (precisa estar aprovado)
        acesso = verificar_login(email, senha)
        if acesso:
            login_session(email, setor=acesso.get("setor", ""))
            return jsonify({"ok": True})
        # 3) senha bate mas ainda não aprovado → aguardando
        if status_cadastro(email, senha) == "pendente":
            return jsonify({"erro": "aguardando_aprovacao", "pendente": True}), 403

    return jsonify({"erro": "credenciais inválidas"}), 401


@bp.post("/auth/registrar")
def auth_registrar():
    """Auto-cadastro: cria pedido PENDENTE (não loga). Admin aprova no painel."""
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    senha = body.get("senha", "")
    nome = (body.get("nome") or "").strip()
    setor = (body.get("setor") or "").strip()

    if not email or len(str(senha)) < 6:
        return jsonify({"erro": "e-mail e senha (mín. 6 caracteres) obrigatórios"}), 400
    if not setor:
        return jsonify({"erro": "setor_obrigatorio", "msg": "Escolha o seu setor."}), 400
    if not dominio_permitido(email):
        return jsonify({"erro": "dominio_nao_permitido",
                        "msg": "Use um e-mail da empresa (@ddm.adv.br ou @grupoddm.com.br)."}), 403

    ok, motivo = registrar_acesso(email, senha, nome, setor)
    if ok:
        return jsonify({"ok": True, "pendente": True,
                        "msg": "Cadastro enviado. Aguarde a aprovação do administrador."})
    if motivo == "ja_cadastrado":
        return jsonify({"erro": "ja_cadastrado", "msg": "E-mail já cadastrado. Faça login."}), 409
    if motivo == "senha_curta":
        return jsonify({"erro": "senha_curta", "msg": "Senha mínima de 6 caracteres."}), 400
    if motivo == "setor_obrigatorio":
        return jsonify({"erro": "setor_obrigatorio", "msg": "Escolha o seu setor."}), 400
    return jsonify({"erro": "dominio_nao_permitido"}), 403


@bp.post("/auth/logout")
def auth_logout():
    logout_session()
    return jsonify({"ok": True})


@bp.get("/auth/status")
def auth_status():
    email = sessao_email()
    nome = ""
    setor = sessao_setor()
    if email:
        acesso = _buscar_acesso(email)
        nome = (acesso or {}).get("nome") or email.split("@")[0]
        setor = (acesso or {}).get("setor") or setor
    elif is_authed():
        nome = "Diretoria"
    return jsonify({
        "autenticado": is_authed(),
        "email": email,
        "admin": is_admin(),
        "nome": nome,
        "setor": setor,
        "acesso_total": tem_acesso_total(),
    })


@bp.post("/auth/perfil")
@require_auth
def auth_perfil():
    """Usuário atualiza o próprio nome (setor é travado — só admin muda)."""
    email = sessao_email()
    if not email:
        return jsonify({"erro": "conta-mestre não tem perfil editável"}), 400
    nome = ((request.get_json(silent=True) or {}).get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "nome obrigatório"}), 400
    if atualizar_nome(email, nome):
        return jsonify({"ok": True})
    return jsonify({"erro": "não encontrado"}), 404


@bp.post("/auth/senha")
@require_auth
def auth_senha():
    """Usuário troca a própria senha (exige a senha atual)."""
    email = sessao_email()
    if not email:
        return jsonify({"erro": "conta-mestre não troca senha aqui"}), 400
    body = request.get_json(silent=True) or {}
    ok, motivo = alterar_senha(email, body.get("senha_atual", ""), body.get("senha_nova", ""))
    if ok:
        return jsonify({"ok": True})
    msgs = {
        "senha_atual_incorreta": "Senha atual incorreta.",
        "senha_curta": "A nova senha precisa de no mínimo 6 caracteres.",
        "nao_encontrado": "Conta não encontrada.",
    }
    return jsonify({"erro": motivo, "msg": msgs.get(motivo, "Erro ao trocar senha.")}), 400


# ── Gestão de acessos (somente admin) ─────────────────────────────────────────

@bp.get("/acessos")
@require_admin
def acessos_listar():
    return jsonify(listar_acessos())


@bp.post("/acessos/aprovar")
@require_admin
def acessos_aprovar():
    email = ((request.get_json(silent=True) or {}).get("email") or "").strip().lower()
    if aprovar_acesso(email):
        return jsonify({"ok": True})
    return jsonify({"erro": "não encontrado"}), 404


@bp.post("/acessos/rejeitar")
@require_admin
def acessos_rejeitar():
    email = ((request.get_json(silent=True) or {}).get("email") or "").strip().lower()
    if rejeitar_acesso(email):
        return jsonify({"ok": True})
    return jsonify({"erro": "não encontrado"}), 404


@bp.post("/acessos/setor")
@require_admin
def acessos_setor():
    """Admin troca o setor de um acesso (usuário comum não pode trocar o próprio)."""
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    setor = (body.get("setor") or "").strip()
    if definir_setor(email, setor):
        return jsonify({"ok": True})
    return jsonify({"erro": "não encontrado"}), 404


@bp.post("/acessos/admin")
@require_admin
def acessos_admin():
    """Admin promove/rebaixa outro acesso a administrador."""
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    virar = bool(body.get("admin"))
    if definir_admin(email, virar):
        return jsonify({"ok": True})
    return jsonify({"erro": "não encontrado"}), 404


# ── Live ──────────────────────────────────────────────────────────────────────

@bp.get("/live/teams")
@require_auth
def live_teams():
    """Reuniões Teams iniciadas nas últimas 4h e ainda não concluídas."""
    connection = None
    cursor = None

    try:
        desde = datetime.now(timezone.utc) - timedelta(hours=4)

        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        sql = """
            SELECT
                id,
                titulo,
                setor,
                data,
                participantes,
                status
            FROM reunioes
            WHERE excluida_em IS NULL
              AND data >= %s
              AND status IN (%s, %s)
              AND plataforma = %s
        """

        params = [
            desde,
            "pending",
            "processing",
            "teams",
        ]

        if not tem_acesso_total():
            sql += " AND setor = %s"
            params.append(sessao_setor())

        sql += " ORDER BY data DESC"

        cursor.execute(sql, params)
        reunioes = cursor.fetchall()

        reunioes = [
            _normalizar_json_reuniao(reuniao)
            for reuniao in reunioes
        ]

        return jsonify(reunioes), 200

    except Exception as exc:
        current_app.logger.exception(
            "Erro ao carregar reuniões ao vivo no MySQL"
        )

        return jsonify({
            "erro": "Não foi possível carregar as reuniões ao vivo.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


@bp.get("/live/processando")
@require_auth
def live_processando():
    """Reuniões atualmente em transcrição ou análise."""
    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        sql = """
            SELECT
                id,
                titulo,
                setor,
                status
            FROM reunioes
            WHERE excluida_em IS NULL
              AND status = %s
        """

        params = ["processing"]

        if not tem_acesso_total():
            sql += " AND setor = %s"
            params.append(sessao_setor())

        sql += " ORDER BY data DESC LIMIT 20"

        cursor.execute(sql, params)
        reunioes = cursor.fetchall()

        items = [
            {
                **reuniao,
                "progresso": 60
            }
            for reuniao in reunioes
        ]

        return jsonify(items), 200

    except Exception as exc:
        current_app.logger.exception(
            "Erro ao carregar reuniões em processamento no MySQL"
        )

        return jsonify({
            "erro": "Não foi possível carregar as reuniões em processamento.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# ── Dashboard summary ─────────────────────────────────────────────────────────

@bp.get("/dashboard/summary")
@require_auth
def dashboard_summary():
    connection = None
    cursor = None

    try:
        periodo = request.args.get("periodo", "7d")
        dias = {"7d": 7, "15d": 15, "30d": 30}.get(periodo, 7)
        desde = datetime.now(timezone.utc) - timedelta(days=dias)

        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        sql = """
            SELECT
                id,
                titulo,
                setor,
                data,
                duracao_minutos,
                participantes,
                resumo_executivo,
                decisoes,
                pendencias,
                status
            FROM reunioes
            WHERE excluida_em IS NULL
              AND data >= %s
              AND status = %s
        """

        params = [desde, "completed"]

        if not tem_acesso_total():
            sql += " AND setor = %s"
            params.append(sessao_setor())

        sql += " ORDER BY data DESC"

        cursor.execute(sql, params)
        reunioes = cursor.fetchall()

        reunioes = [
            _normalizar_json_reuniao(reuniao)
            for reuniao in reunioes
        ]

        todas_decisoes = [
            decisao
            for reuniao in reunioes
            for decisao in (reuniao.get("decisoes") or [])
        ]

        todas_pendencias = [
            pendencia
            for reuniao in reunioes
            for pendencia in (reuniao.get("pendencias") or [])
        ]

        sem_responsavel = [
            pendencia
            for pendencia in todas_pendencias
            if not pendencia.get("responsavel")
        ]

        por_setor = {}

        for reuniao in reunioes:
            setor = reuniao.get("setor") or "Outros"
            por_setor[setor] = por_setor.get(setor, 0) + 1

        return jsonify({
            "total_reunioes": len(reunioes),
            "total_decisoes": len(todas_decisoes),
            "total_pendencias": len(todas_pendencias),
            "sem_responsavel": len(sem_responsavel),
            "ultimas_reunioes": reunioes[:5],
            "decisoes_recentes": todas_decisoes[:10],
            "pendencias_sem_responsavel": sem_responsavel[:10],
            "por_setor": [
                {"setor": setor, "total": total}
                for setor, total in por_setor.items()
            ],
        })

    except Exception as exc:
        current_app.logger.exception(
            "Erro ao carregar resumo do dashboard no MySQL"
        )

        return jsonify({
            "erro": "Não foi possível carregar o dashboard.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# ── Dashboard (legado) ────────────────────────────────────────────────────────

@bp.get("/dashboard")
@require_auth
def dashboard():
    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        sql = """
            SELECT
                id,
                titulo,
                setor,
                data,
                duracao_minutos,
                participantes,
                resumo_executivo,
                status
            FROM reunioes
            WHERE excluida_em IS NULL
        """

        params = []

        if not tem_acesso_total():
            sql += " AND setor = %s"
            params.append(sessao_setor())

        sql += " ORDER BY data DESC LIMIT 10"

        cursor.execute(sql, params)
        reunioes = cursor.fetchall()

        reunioes = [
            _normalizar_json_reuniao(reuniao)
            for reuniao in reunioes
        ]

        sql_pendencias = """
            SELECT pendencias
            FROM reunioes
            WHERE excluida_em IS NULL
              AND status = %s
        """

        params_pendencias = ["completed"]

        if not tem_acesso_total():
            sql_pendencias += " AND setor = %s"
            params_pendencias.append(sessao_setor())

        cursor.execute(sql_pendencias, params_pendencias)
        registros_pendencias = cursor.fetchall()

        todas_pendencias = []

        for registro in registros_pendencias:
            normalizado = _normalizar_json_reuniao(registro)
            todas_pendencias.extend(
                normalizado.get("pendencias") or []
            )

        pendencias_sem_dono = [
            pendencia
            for pendencia in todas_pendencias
            if not pendencia.get("responsavel")
        ]

        return jsonify({
            "ultimas_reunioes": reunioes,
            "total_emails": 0,
            "pendencias_sem_dono": pendencias_sem_dono[:20],
        })

    except Exception as exc:
        current_app.logger.exception(
            "Erro ao carregar dashboard legado no MySQL"
        )

        return jsonify({
            "erro": "Não foi possível carregar o dashboard.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# ── Reuniões ──────────────────────────────────────────────────────────────────

@bp.get("/reunioes")
@require_auth
def listar_reunioes():
    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        sql = """
        SELECT
        id,
        titulo,
        setor,
        data,
        duracao_minutos,
        participantes,
        resumo_executivo,
        status,
        plataforma
        FROM reunioes
        WHERE excluida_em IS NULL
        """

        params = []

        # Usuário comum só vê reuniões do próprio setor
        if not tem_acesso_total():
            sql += " AND setor = %s"
            params.append(sessao_setor())

        setor = request.args.get("setor")
        if setor and tem_acesso_total():
            sql += " AND setor = %s"
            params.append(setor)

        status = request.args.get("status")
        if status:
            sql += " AND status = %s"
            params.append(status)

        data_inicio = request.args.get("de")
        if data_inicio:
            sql += " AND data >= %s"
            params.append(data_inicio)

        data_fim = request.args.get("ate")
        if data_fim:
            sql += " AND data <= %s"
            params.append(data_fim)

        sql += " ORDER BY data DESC LIMIT 50"

        cursor.execute(sql, params)
        reunioes = cursor.fetchall()

        return jsonify(reunioes), 200

    except Exception as exc:
        current_app.logger.exception("Erro ao listar reuniões no MySQL")

        return jsonify({
            "erro": "Não foi possível carregar as reuniões.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


@bp.get("/reunioes/<reuniao_id>")
@require_auth
def detalhe_reuniao(reuniao_id: str):
    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM reunioes
            WHERE id = %s
              AND excluida_em IS NULL
            LIMIT 1
            """,
            (reuniao_id,),
        )

        reuniao = cursor.fetchone()

        if not reuniao:
            return jsonify({"erro": "não encontrado"}), 404

        if (
            not tem_acesso_total()
            and (reuniao.get("setor") or "") != sessao_setor()
        ):
            return jsonify({"erro": "não encontrado"}), 404

        return jsonify(_normalizar_json_reuniao(reuniao)), 200

    except Exception as exc:
        current_app.logger.exception(
            "Erro ao buscar reunião %s no MySQL",
            reuniao_id,
        )

        return jsonify({
            "erro": "Não foi possível carregar a reunião.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


def _carregar_reuniao_locutores(reuniao_id: str):
    """Linha da reunião + checagem de setor. Devolve (reuniao, erro_response)."""
    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, setor, recall_bot_id, utterances, participantes
            FROM reunioes
            WHERE id = %s
              AND excluida_em IS NULL
            LIMIT 1
            """,
            (reuniao_id,),
        )

        reuniao = cursor.fetchone()

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    if not reuniao:
        return None, (jsonify({"erro": "não encontrado"}), 404)

    if (
        not tem_acesso_total()
        and (reuniao.get("setor") or "") != sessao_setor()
    ):
        return None, (jsonify({"erro": "não encontrado"}), 404)

    return reuniao, None


def _json_lista(valor):
    if isinstance(valor, list):
        return valor

    if isinstance(valor, (bytes, bytearray)):
        valor = valor.decode("utf-8", "replace")

    if isinstance(valor, str) and valor.strip():
        try:
            dados = json.loads(valor)
        except json.JSONDecodeError:
            return []

        return dados if isinstance(dados, list) else []

    return []


def _nome_locutor_valido(nome: str) -> str | None:
    """Sanitiza o nome digitado/escolhido no painel."""
    nome = " ".join((nome or "").split())

    if not nome or len(nome) > 80:
        return None

    if any(ord(c) < 32 for c in nome):
        return None

    return nome


@bp.get("/reunioes/<reuniao_id>/locutores")
@require_auth
def listar_locutores(reuniao_id: str):
    """
    Locutores da transcrição + nomes reais dos participantes (candidatos).

    O Skribby não liga a diarização ('Speaker 1') aos nomes; quando a IA não
    consegue inferir pelo diálogo, o painel usa isto para corrigir à mão.
    """
    from app.pipeline.locutores import rotulo_generico

    reuniao, erro = _carregar_reuniao_locutores(reuniao_id)

    if erro:
        return erro

    utterances = _json_lista(reuniao.get("utterances"))

    locutores = []
    for u in utterances:
        nome = (u.get("speaker") or "").strip()
        if nome and nome not in [item["nome"] for item in locutores]:
            locutores.append({
                "nome": nome,
                "generico": rotulo_generico(nome),
                "falas": 0,
            })

    contagem = {}
    for u in utterances:
        nome = (u.get("speaker") or "").strip()
        contagem[nome] = contagem.get(nome, 0) + 1

    for item in locutores:
        item["falas"] = contagem.get(item["nome"], 0)

    # Nomes reais: vêm do Skribby, que os guarda junto da gravação.
    candidatos = []
    bot_id = reuniao.get("recall_bot_id")

    if bot_id:
        try:
            from app.pipeline.skribby_client import (
                get_bot,
                extract_skribby_participants,
            )

            candidatos = [
                p["nome"]
                for p in extract_skribby_participants(get_bot(bot_id))
                if p.get("nome")
            ]

        except Exception:
            # Gravação expirada ou Skribby fora: painel cai no campo livre.
            current_app.logger.info(
                "Sem candidatos do Skribby para a reunião %s",
                reuniao_id,
            )

    return jsonify({
        "locutores": locutores,
        "candidatos": candidatos,
    }), 200


@bp.post("/reunioes/<reuniao_id>/locutores")
@require_auth
def renomear_locutores(reuniao_id: str):
    """
    Renomeia locutores na transcrição. Corpo: {"mapa": {"Speaker 1": "Nome"}}.

    Vale para rótulo genérico e para corrigir nome que a IA errou.
    """
    reuniao, erro = _carregar_reuniao_locutores(reuniao_id)

    if erro:
        return erro

    body = request.get_json(silent=True) or {}
    mapa_bruto = body.get("mapa")

    if not isinstance(mapa_bruto, dict) or not mapa_bruto:
        return jsonify({"erro": "mapa obrigatório"}), 400

    mapa = {}
    for de, para in mapa_bruto.items():
        de = (de or "").strip()
        nome = _nome_locutor_valido(para)

        if not de or not nome or de == nome:
            continue

        mapa[de] = nome

    if not mapa:
        return jsonify({"erro": "nenhum nome válido"}), 400

    if len(set(mapa.values())) != len(mapa.values()):
        return jsonify({
            "erro": "nomes_repetidos",
            "msg": "Cada locutor precisa de um nome diferente.",
        }), 400

    utterances = _json_lista(reuniao.get("utterances"))

    if not utterances:
        return jsonify({"erro": "reunião sem transcrição"}), 400

    trocadas = 0
    for u in utterances:
        atual = (u.get("speaker") or "").strip()
        if atual in mapa:
            u["speaker"] = mapa[atual]
            trocadas += 1

    if not trocadas:
        return jsonify({
            "erro": "locutor_inexistente",
            "msg": "Nenhum locutor da transcrição corresponde ao pedido.",
        }), 400

    # Mantém o card Participantes coerente com a transcrição.
    participantes = _json_lista(reuniao.get("participantes"))
    for p in participantes:
        if isinstance(p, dict) and (p.get("nome") or "").strip() in mapa:
            p["nome"] = mapa[p["nome"].strip()]

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE reunioes
            SET utterances = %s, participantes = %s
            WHERE id = %s
            """,
            (
                json.dumps(utterances, ensure_ascii=False),
                json.dumps(participantes, ensure_ascii=False),
                reuniao_id,
            ),
        )

        connection.commit()

    except Exception as exc:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception(
            "Erro ao renomear locutores da reunião %s",
            reuniao_id,
        )

        return jsonify({
            "erro": "Não foi possível salvar os nomes.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return jsonify({
        "ok": True,
        "falas_atualizadas": trocadas,
        "mapa": mapa,
    }), 200


# ── Lixeira de reuniões ───────────────────────────────────────────────────────
#
# Excluir não apaga: marca `excluida_em`. A reunião sai do painel, dos KPIs e da
# busca, mas fica recuperável pelo prazo de retenção. Depois disso é apagada de
# vez — pela task do Celery, ou na primeira vez que alguém abrir a lixeira
# (produção no cPanel não mantém worker vivo, então não dá para depender só do
# agendador).

def dias_retencao_lixeira() -> int:
    try:
        return max(1, int(os.getenv("LIXEIRA_DIAS", "30")))
    except (TypeError, ValueError):
        return 30


def purgar_lixeira_expirada() -> int:
    """Apaga definitivamente o que passou da retenção. Devolve quantas saíram."""
    dias = dias_retencao_lixeira()

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()

        cursor.execute(
            f"""
            DELETE FROM reunioes
            WHERE excluida_em IS NOT NULL
              AND excluida_em < NOW() - INTERVAL {dias} DAY
            """
        )

        apagadas = cursor.rowcount or 0
        connection.commit()

        if apagadas:
            current_app.logger.info(
                "Lixeira: %d reuniões apagadas por vencimento (%d dias)",
                apagadas,
                dias,
            )

        return apagadas

    except Exception:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception("Falha ao purgar a lixeira")
        return 0

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


@bp.post("/reunioes/<reuniao_id>/excluir")
@require_admin
def excluir_reuniao(reuniao_id: str):
    """Manda a reunião para a lixeira (recuperável durante a retenção)."""
    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE reunioes
            SET excluida_em = NOW(), excluida_por = %s
            WHERE id = %s
              AND excluida_em IS NULL
            """,
            (sessao_email() or "diretoria", reuniao_id),
        )

        afetadas = cursor.rowcount or 0
        connection.commit()

    except Exception as exc:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception(
            "Erro ao excluir a reunião %s",
            reuniao_id,
        )

        return jsonify({
            "erro": "Não foi possível excluir a reunião.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    if not afetadas:
        return jsonify({"erro": "não encontrado"}), 404

    purgar_lixeira_expirada()

    return jsonify({
        "ok": True,
        "retencao_dias": dias_retencao_lixeira(),
    }), 200


@bp.post("/reunioes/<reuniao_id>/restaurar")
@require_admin
def restaurar_reuniao(reuniao_id: str):
    """Tira a reunião da lixeira."""
    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE reunioes
            SET excluida_em = NULL, excluida_por = NULL
            WHERE id = %s
              AND excluida_em IS NOT NULL
            """,
            (reuniao_id,),
        )

        afetadas = cursor.rowcount or 0
        connection.commit()

    except Exception as exc:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception(
            "Erro ao restaurar a reunião %s",
            reuniao_id,
        )

        return jsonify({
            "erro": "Não foi possível restaurar a reunião.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    if not afetadas:
        return jsonify({"erro": "não encontrado"}), 404

    return jsonify({"ok": True}), 200


@bp.get("/lixeira")
@require_admin
def listar_lixeira():
    """Reuniões na lixeira, com quantos dias faltam para o apagamento."""
    purgar_lixeira_expirada()

    dias = dias_retencao_lixeira()

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            f"""
            SELECT
                id,
                titulo,
                setor,
                data,
                duracao_minutos,
                status,
                solicitante,
                excluida_em,
                excluida_por,
                DATEDIFF(
                    excluida_em + INTERVAL {dias} DAY,
                    NOW()
                ) AS dias_restantes
            FROM reunioes
            WHERE excluida_em IS NOT NULL
            ORDER BY excluida_em DESC
            LIMIT 200
            """
        )

        reunioes = cursor.fetchall()

        return jsonify({
            "reunioes": reunioes,
            "retencao_dias": dias,
        }), 200

    except Exception as exc:
        current_app.logger.exception("Erro ao listar a lixeira")

        return jsonify({
            "erro": "Não foi possível carregar a lixeira.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


@bp.post("/lixeira/limpar")
@require_admin
def limpar_lixeira():
    """
    Esvazia a lixeira agora — apagamento DEFINITIVO, sem volta.

    Por padrão apaga tudo o que está na lixeira. Com {"somente_expiradas": true}
    apaga só o que já passou da retenção.
    """
    body = request.get_json(silent=True) or {}

    if body.get("somente_expiradas"):
        return jsonify({
            "ok": True,
            "apagadas": purgar_lixeira_expirada(),
            "somente_expiradas": True,
        }), 200

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            DELETE FROM reunioes
            WHERE excluida_em IS NOT NULL
            """
        )

        apagadas = cursor.rowcount or 0
        connection.commit()

        current_app.logger.warning(
            "Lixeira esvaziada por %s: %d reuniões apagadas definitivamente",
            sessao_email() or "diretoria",
            apagadas,
        )

    except Exception as exc:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception("Erro ao esvaziar a lixeira")

        return jsonify({
            "erro": "Não foi possível esvaziar a lixeira.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return jsonify({"ok": True, "apagadas": apagadas}), 200


@bp.post("/reunioes/upload")
@require_auth
def upload_audio():
    """Fallback: upload manual de áudio MP3/MP4 para transcrição via Azure Speech."""
    from app.workers.tasks import processar_audio_avulso

    if "audio" not in request.files:
        return jsonify({"erro": "campo 'audio' obrigatório"}), 400

    arquivo = request.files["audio"]
    if not arquivo.filename:
        return jsonify({"erro": "arquivo inválido"}), 400

    ext = os.path.splitext(arquivo.filename)[1].lower()
    if ext not in (".mp3", ".mp4", ".wav", ".m4a"):
        return jsonify({"erro": "formato não suportado"}), 400

    nome = f"{uuid.uuid4()}{ext}"
    pasta = os.path.join(current_app.instance_path, "uploads")
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, secure_filename(nome))
    arquivo.save(caminho)

    reuniao_id = str(uuid.uuid4())

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO reunioes (
                id,
                titulo,
                setor,
                plataforma,
                status
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                reuniao_id,
                request.form.get(
                    "titulo",
                    "Reunião — upload manual",
                ),
                request.form.get("setor", ""),
                "avulso",
                "pending",
            ),
        )

        connection.commit()

    except Exception as exc:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception(
            "Erro ao criar reunião de upload manual"
        )

        return jsonify({
            "erro": "falha_ao_salvar",
            "msg": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    processar_audio_avulso.delay(reuniao_id, caminho)

    return jsonify({
        "reuniao_id": reuniao_id,
        "status": "pending",
    }), 202


# ── Gravações Skribby (bot "Acordito" entra na reunião) ──────────────────────

@bp.post("/gravacoes")
def criar_gravacao():
    """
    Funcionário aciona a gravação: cola o link da reunião,
    o bot Acordito entra, grava e transcreve.

    Cria a reunião no MariaDB com status 'pending'.
    """

    body = request.get_json(silent=True) or {}

    meeting_url = (body.get("meeting_url") or "").strip()

    if not meeting_url:
        return jsonify({
            "erro": "meeting_url obrigatório"
        }), 400

    if not _meeting_url_valida(meeting_url):
        return jsonify({
            "erro": "meeting_url inválido",
            "msg": "Use um link do Teams, Zoom ou Google Meet.",
        }), 400

    # Carrega o cliente Skribby apenas quando a rota for utilizada.
    try:
        from app.pipeline.skribby_client import create_bot

    except Exception as exc:
        current_app.logger.exception(
            "Falha ao carregar o cliente Skribby"
        )

        return jsonify({
            "erro": "dependencia_ausente",
            "msg": (
                f"Falha ao carregar o cliente Skribby: {exc}. "
                "Rode 'pip install -r requirements.txt' no servidor."
            ),
        }), 500

    # Solicita ao Skribby a criação do bot.
    try:
        bot = create_bot(meeting_url)

    except Exception as exc:
        current_app.logger.exception(
            "Falha ao criar bot no Skribby"
        )

        return jsonify({
            "erro": "falha_skribby",
            "msg": f"Skribby: {exc}",
        }), 502

    bot_id = bot.get("id")

    if not bot_id:
        return jsonify({
            "erro": "skribby_sem_bot_id",
            "msg": "Skribby criou uma resposta sem o ID do bot.",
        }), 502

    reuniao_id = str(uuid.uuid4())

    data_reuniao = (
        (body.get("data") or "").strip()
        or datetime.now(timezone.utc).isoformat()
    )

    titulo = (
        (body.get("titulo") or "").strip()
        or "Reunião (Skribby)"
    )

    solicitante = (body.get("solicitante") or "").strip()
    setor = (body.get("setor") or "").strip()
    modalidade = (body.get("modalidade") or "online").strip()
    local_reuniao = (body.get("local_reuniao") or "").strip()
    cliente = (body.get("cliente") or "").strip()

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO reunioes (
                id,
                titulo,
                solicitante,
                setor,
                data,
                plataforma,
                status,
                recall_bot_id,
                modalidade,
                local_reuniao,
                cliente
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
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
                titulo,
                solicitante,
                setor,
                data_reuniao,
                "skribby",
                "pending",
                bot_id,
                modalidade,
                local_reuniao,
                cliente,
            ),
        )

        connection.commit()

    except Exception as exc:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception(
            "Falha ao salvar a reunião no MySQL"
        )

        return jsonify({
            "erro": "falha_ao_salvar",
            "msg": f"Banco MySQL: {exc}",
        }), 502

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return jsonify({
        "reuniao_id": reuniao_id,
        "bot_id": bot_id,
        "status": "bot entrando na reunião",
    }), 202

@bp.post("/skribby/webhook")
def skribby_webhook():
    """
    Recebe eventos do Skribby.

    Quando o status muda para 'finished', localiza a reunião no MySQL
    pelo recall_bot_id e inicia o processamento em segundo plano.
    """

    import threading
    import hmac as _hmac

    from app.workers.tasks import _processar_recall

    secret = os.getenv("SKRIBBY_WEBHOOK_SECRET", "").strip()

    if secret and not _hmac.compare_digest(
        request.args.get("token", ""),
        secret,
    ):
        return jsonify({"erro": "não autorizado"}), 403

    body = request.get_json(silent=True) or {}

    bot_id = body.get("bot_id")
    tipo = body.get("type", "")
    novo_status = (
        (body.get("data") or {}).get("new_status")
        or ""
    )

    if (
        tipo == "status_update"
        and novo_status == "finished"
        and bot_id
    ):
        connection = None
        cursor = None

        try:
            connection = get_mysql_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT id
                FROM reunioes
                WHERE recall_bot_id = %s
                LIMIT 1
                """,
                (bot_id,),
            )

            reuniao = cursor.fetchone()

            if reuniao:
                reuniao_id = reuniao["id"]

                threading.Thread(
                    target=_processar_recall,
                    args=(reuniao_id, bot_id),
                    daemon=True,
                ).start()

        except Exception as exc:
            current_app.logger.exception(
                "Erro ao processar webhook do Skribby"
            )

            return jsonify({
                "erro": "falha_webhook",
                "msg": str(exc),
            }), 500

        finally:
            if cursor is not None:
                cursor.close()

            if (
                connection is not None
                and connection.is_connected()
            ):
                connection.close()

    return jsonify({"ok": True}), 200

@bp.post("/gravacoes/<reuniao_id>/processar")
@require_auth
def processar_gravacao_manual(reuniao_id: str):
    """
    Puxa a transcrição manualmente, sem depender do webhook público.

    Só funciona depois que o bot terminou e a transcrição
    está disponível no Skribby.
    """
    from app.workers.tasks import _processar_recall

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                recall_bot_id,
                status,
                setor
            FROM reunioes
            WHERE id = %s
              AND excluida_em IS NULL
            LIMIT 1
            """,
            (reuniao_id,),
        )

        reuniao = cursor.fetchone()

        if not reuniao:
            return jsonify({"erro": "não encontrado"}), 404

        # Usuário comum só pode processar reunião do próprio setor.
        if (
            not tem_acesso_total()
            and (reuniao.get("setor") or "") != sessao_setor()
        ):
            return jsonify({"erro": "não encontrado"}), 404

        bot_id = reuniao.get("recall_bot_id")

        if not bot_id:
            return jsonify({
                "erro": "reunião sem bot Skribby"
            }), 400

    except Exception as exc:
        current_app.logger.exception(
            "Erro ao buscar reunião para processamento manual"
        )

        return jsonify({
            "erro": "falha_banco",
            "msg": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if (
            connection is not None
            and connection.is_connected()
        ):
            connection.close()

    def buscar_erro_processamento(default: str = "") -> str:
        connection = None
        cursor = None

        try:
            connection = get_mysql_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT erro_msg
                FROM reunioes
                WHERE id = %s
                LIMIT 1
                """,
                (reuniao_id,),
            )
            reuniao_erro = cursor.fetchone() or {}
            return (
                reuniao_erro.get("erro_msg")
                or default
                or "Falha ao processar a reunião."
            )

        except Exception:
            current_app.logger.exception(
                "Erro ao buscar falha salva da reunião %s",
                reuniao_id,
            )
            return default or "Falha ao processar a reunião."

        finally:
            if cursor is not None:
                cursor.close()

            if (
                connection is not None
                and connection.is_connected()
            ):
                connection.close()

    try:
        status = _processar_recall(
            reuniao_id,
            bot_id,
        )

    except Exception as exc:
        current_app.logger.exception(
            "Erro ao processar reunião %s",
            reuniao_id,
        )

        return jsonify({
            "erro": "falha_processamento",
            "status": "error",
            "msg": buscar_erro_processamento(str(exc)),
        }), 502

    if status == "pending":
        return jsonify({
            "status": "pending",
            "msg": (
                "O bot ainda está gravando ou a transcrição "
                "ainda não ficou pronta."
            ),
        }), 202

    if status == "sem_transcricao":
        return jsonify({
            "status": "sem_transcricao",
            "msg": (
                "O bot terminou, mas o Skribby ainda não "
                "retornou a transcrição."
            ),
        }), 202

    if status == "error":
        return jsonify({
            "status": "error",
            "msg": buscar_erro_processamento(
                "O bot terminou com erro."
            ),
        }), 409

    return jsonify({
        "status": "processado"
    }), 200


# ── Setores ───────────────────────────────────────────────────────────────────

@bp.get("/setores")
def listar_setores():
    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM setores
            WHERE ativo = %s
            ORDER BY nome
            """,
            (1,),
        )

        setores = cursor.fetchall()

        return jsonify(setores), 200

    except Exception as exc:
        current_app.logger.exception("Erro ao listar setores no MySQL")

        return jsonify({
            "erro": "Não foi possível carregar os setores.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# ── Usuários ──────────────────────────────────────────────────────────────────

@bp.get("/usuarios")
@require_auth
def listar_usuarios():
    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        sql = """
        SELECT
        id,
        nome,
        email,
        setor,
        cargo
        FROM usuarios
        WHERE ativo = 1
        """

        params = []

        if request.args.get("setor"):
            sql += " AND setor = %s"
            params.append(request.args.get("setor"))

        sql += " ORDER BY nome"

        cursor.execute(sql, params)

        usuarios = cursor.fetchall()

        return jsonify(usuarios)

    except Exception as exc:
        current_app.logger.exception("Erro ao listar usuários")

        return jsonify({
            "erro": str(exc)
        }), 500

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()


# ── Interações (grafo) ────────────────────────────────────────────────────────

@bp.get("/interacoes")
@require_auth
def listar_interacoes():
    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM interacoes
            ORDER BY contagem DESC
            LIMIT 200
            """
        )

        interacoes = cursor.fetchall()

        return jsonify(interacoes), 200

    except Exception as exc:
        current_app.logger.exception("Erro ao listar interações no MySQL")

        return jsonify({
            "erro": "Não foi possível carregar as interações.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


# ── Sync manual ───────────────────────────────────────────────────────────────

@bp.post("/sync/trigger")
@require_auth
def trigger_sync():
    from app.workers.tasks import sync_reunioes_teams, sync_emails_outlook, sync_usuarios_ad

    target = request.json.get("tipo", "all") if request.json else "all"

    if target in ("all", "usuarios"):
        sync_usuarios_ad.delay()
    if target in ("all", "reunioes"):
        sync_reunioes_teams.delay()
    if target in ("all", "emails"):
        sync_emails_outlook.delay()

    return jsonify({"status": "enfileirado", "tipo": target}), 202
