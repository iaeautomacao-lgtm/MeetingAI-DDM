# Anotacoes adiadas: "X | None" (PEP 604) so avalia em runtime a partir
# do Python 3.10, e o interpretador do cPanel e mais antigo. Sem isso o
# app quebra no import em producao.
from __future__ import annotations

import os
import json
import uuid
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    definir_gestor,
    atualizar_nome,
    alterar_senha,
    login_session,
    logout_session,
    is_authed,
    is_admin,
    sessao_email,
    sessao_setor,
    sessao_setores,
    tem_acesso_total,
    is_gestor_setor,
    _buscar_acesso,
)

_REUNIOES_COLUNAS_CACHE = None
_IDEIAS_OCULTAS_TABELA_CACHE = None


def _normalizar_texto_acesso(valor: str) -> str:
    return " ".join((valor or "").strip().lower().split())


def _colunas_reunioes() -> set[str]:
    global _REUNIOES_COLUNAS_CACHE
    if _REUNIOES_COLUNAS_CACHE is not None:
        return _REUNIOES_COLUNAS_CACHE

    connection = None
    cursor = None
    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SHOW COLUMNS FROM reunioes")
        _REUNIOES_COLUNAS_CACHE = {
            str(row.get("Field") or "")
            for row in cursor.fetchall()
            if row.get("Field")
        }
    except Exception:
        current_app.logger.exception("Erro ao inspecionar colunas de reunioes")
        _REUNIOES_COLUNAS_CACHE = set()
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()

    return _REUNIOES_COLUNAS_CACHE


def _tem_coluna_reunioes(nome: str) -> bool:
    return nome in _colunas_reunioes()


def _tem_tabela_ideias_ocultas() -> bool:
    global _IDEIAS_OCULTAS_TABELA_CACHE
    if _IDEIAS_OCULTAS_TABELA_CACHE is not None:
        return _IDEIAS_OCULTAS_TABELA_CACHE

    connection = None
    cursor = None
    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SHOW TABLES LIKE %s", ("ideias_ocultas_usuario",))
        _IDEIAS_OCULTAS_TABELA_CACHE = cursor.fetchone() is not None
    except Exception:
        current_app.logger.exception("Erro ao verificar tabela ideias_ocultas_usuario")
        _IDEIAS_OCULTAS_TABELA_CACHE = False
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()

    return _IDEIAS_OCULTAS_TABELA_CACHE


def _normalizar_lista_texto(valor) -> list[str]:
    if isinstance(valor, list):
        items = valor
    elif isinstance(valor, str) and valor.strip():
        texto = valor.strip()
        try:
            parsed = json.loads(texto)
            items = parsed if isinstance(parsed, list) else [texto]
        except json.JSONDecodeError:
            items = texto.replace(";", ",").replace("\n", ",").split(",")
    else:
        items = []

    normalizados = []
    for item in items:
        texto = str(item or "").strip()
        if texto and texto not in normalizados:
            normalizados.append(texto)
    return normalizados


def _json_like_param(valor: str) -> str:
    return '%"' + json.dumps(valor, ensure_ascii=False)[1:-1] + '"%'


def _parse_datetime_reuniao(valor: str) -> datetime | None:
    texto = (valor or "").strip()
    if not texto:
        return None
    try:
        parsed = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _scheduled_start_timestamp(valor: str) -> int | None:
    data = _parse_datetime_reuniao(valor)
    if not data:
        return None
    # O campo datetime-local trabalha com precisão de minuto. Quando o
    # usuário escolhe "agora", a requisição pode chegar alguns minutos depois
    # do horário informado. Nesse caso, o bot deve entrar imediatamente, não
    # ser criado como uma reunião agendada.
    if data <= datetime.now(timezone.utc) + timedelta(minutes=5):
        return None
    return int(data.timestamp())


def _solicitantes_sessao() -> list[str]:
    email = sessao_email()
    valores = []

    if email:
        valores.append(email)
        acesso = _buscar_acesso(email) or {}
        nome = acesso.get("nome")
        if nome:
            valores.append(nome)

    return list(dict.fromkeys(
        valor
        for valor in (_normalizar_texto_acesso(v) for v in valores)
        if valor
    ))


def _escopo_reunioes_sql() -> tuple[str, list]:
    if tem_acesso_total():
        return "", []

    tem_share_setores = _tem_coluna_reunioes("compartilhado_setores")
    tem_share_emails = _tem_coluna_reunioes("compartilhado_emails")
    tem_visibilidade = _tem_coluna_reunioes("visibilidade_setor")
    email = sessao_email()

    if is_gestor_setor():
        setores = sessao_setores()
        if not setores:
            return " AND 1 = 0", []
        placeholders = ", ".join(["%s"] * len(setores))
        partes = [f"setor IN ({placeholders})"]
        params = list(setores)
        if tem_share_setores:
            partes.extend(["COALESCE(compartilhado_setores, '') LIKE %s"] * len(setores))
            params.extend(_json_like_param(setor) for setor in setores)
        if tem_share_emails and email:
            partes.append("COALESCE(compartilhado_emails, '') LIKE %s")
            params.append(_json_like_param(email))
        return " AND (" + " OR ".join(partes) + ")", params

    solicitantes = _solicitantes_sessao()
    setores = sessao_setores()
    if not solicitantes and not setores:
        return " AND 1 = 0", []

    partes = []
    params = []
    if solicitantes:
        placeholders = ", ".join(["%s"] * len(solicitantes))
        partes.append(f"LOWER(TRIM(COALESCE(solicitante, ''))) IN ({placeholders})")
        params.extend(solicitantes)
    if tem_visibilidade:
        visiveis = []
        visiveis_params = []
        if setores:
            placeholders = ", ".join(["%s"] * len(setores))
            visiveis.append(f"setor IN ({placeholders})")
            visiveis_params.extend(setores)
            if tem_share_setores:
                visiveis.extend(["COALESCE(compartilhado_setores, '') LIKE %s"] * len(setores))
                visiveis_params.extend(_json_like_param(setor) for setor in setores)
        if tem_share_emails and email:
            visiveis.append("COALESCE(compartilhado_emails, '') LIKE %s")
            visiveis_params.append(_json_like_param(email))
        if visiveis:
            partes.append("(visibilidade_setor = 'todos' AND (" + " OR ".join(visiveis) + "))")
            params.extend(visiveis_params)

    return " AND (" + " OR ".join(partes) + ")", params


def _pode_acessar_reuniao(reuniao: dict) -> bool:
    if tem_acesso_total():
        return True

    compartilhado_setores = _normalizar_lista_texto(reuniao.get("compartilhado_setores"))
    compartilhado_emails = [
        email.lower()
        for email in _normalizar_lista_texto(reuniao.get("compartilhado_emails"))
    ]
    email = (sessao_email() or "").lower()

    if is_gestor_setor():
        setores = sessao_setores()
        return (
            (reuniao.get("setor") or "") in setores
            or any(setor in compartilhado_setores for setor in setores)
            or bool(email and email in compartilhado_emails)
        )

    solicitante = _normalizar_texto_acesso(reuniao.get("solicitante") or "")
    setores = sessao_setores()
    if solicitante and solicitante in _solicitantes_sessao():
        return True
    if reuniao.get("visibilidade_setor") != "todos":
        return False
    return bool(
        (email and email in compartilhado_emails)
        or reuniao.get("setor") in setores
        or any(setor in compartilhado_setores for setor in setores)
    )


def _pode_editar_reuniao(reuniao: dict) -> bool:
    if tem_acesso_total() or is_gestor_setor() and _pode_acessar_reuniao(reuniao):
        return True
    solicitante = _normalizar_texto_acesso(reuniao.get("solicitante") or "")
    return bool(solicitante and solicitante in _solicitantes_sessao())


def _normalizar_json_reuniao(reuniao: dict) -> dict:
    campos_json = (
        "participantes",
        "decisoes",
        "pendencias",
        "topicos",
        "utterances",
        "key_takeaways",
        "riscos",
        "perguntas_abertas",
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

    # `clima` é objeto, não lista — normalizado à parte para o painel não
    # precisar adivinhar o tipo.
    clima = reuniao.get("clima")

    if isinstance(clima, str) and clima.strip():
        try:
            clima = json.loads(clima)
        except json.JSONDecodeError:
            clima = {}

    reuniao["clima"] = clima if isinstance(clima, dict) else {}
    reuniao["compartilhado_setores"] = _normalizar_lista_texto(
        reuniao.get("compartilhado_setores")
    )
    reuniao["compartilhado_emails"] = _normalizar_lista_texto(
        reuniao.get("compartilhado_emails")
    )
    reuniao["visibilidade_setor"] = reuniao.get("visibilidade_setor") or "gestores"

    return reuniao


def _normalizar_json_lista(valor):
    if isinstance(valor, list):
        return valor
    if isinstance(valor, str) and valor.strip():
        try:
            parsed = json.loads(valor)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _score_ideia(ideia: dict) -> int:
    texto = " ".join([
        ideia.get("titulo") or "",
        ideia.get("dor") or "",
        ideia.get("solucao") or "",
        ideia.get("impacto") or "",
    ])
    base = 58 + (len(texto) % 23)
    if (ideia.get("impacto") or "").lower() in {"reduz risco", "aumenta receita"}:
        base += 9
    if len(ideia.get("solucao") or "") > 120:
        base += 6
    return max(55, min(96, base))


def _fallback_ia_ideia(ideia: dict) -> dict:
    setor = ideia.get("setor") or "setor envolvido"
    impacto = ideia.get("impacto") or "impacto operacional"
    titulo = ideia.get("titulo") or f"Melhorar rotina de {setor}"
    ganhos_por_impacto = {
        "Reduz tempo": ["Menos retrabalho", "Ganho de tempo", "Fluxo mais previsível"],
        "Aumenta receita": ["Follow-up mais rápido", "Mais oportunidades visíveis", "Melhor conversão"],
        "Melhora experiência do cliente": ["Menos atrito", "Resposta mais clara", "Atendimento mais consistente"],
        "Reduz risco": ["Redução de risco", "Mais rastreabilidade", "Menos perda de prazo"],
        "Melhora comunicação interna": ["Informação centralizada", "Responsáveis mais claros", "Menos ruído entre áreas"],
    }
    return {
        "titulo": titulo,
        "problema": ideia.get("dor") or "",
        "proposta": ideia.get("solucao") or "",
        "potencial": (
            f"Organizar essa percepção em uma iniciativa de {setor}, "
            f"com responsável definido, métrica simples e validação rápida."
        ),
        "impactos_possiveis": ganhos_por_impacto.get(
            impacto,
            ["Aprendizado rápido", "Decisão mais clara", "Teste com baixo esforço"],
        ),
        "primeiro_passo": (
            f"Criar um piloto de 30 dias em {setor}, acompanhando resultado "
            "antes de ampliar para outras áreas."
        ),
    }


def _desenvolver_ideia_com_ia(ideia: dict) -> dict:
    system = (
        "Você é um parceiro de inovação corporativa do Grupo DDM. "
        "Desenvolva ideias de colaboradores com linguagem acolhedora, objetiva "
        "e prática. Não avalie a pessoa e não use tom de julgamento. "
        "Responda somente JSON válido."
    )
    user = json.dumps(
        {
            "instrucoes": {
                "idioma": "pt-BR",
                "formato": {
                    "titulo": "string curta e executiva",
                    "problema": "string fiel à percepção original",
                    "proposta": "string clara, prática e sem exageros",
                    "potencial": "string com o potencial identificado",
                    "impactos_possiveis": ["3 strings curtas"],
                    "primeiro_passo": "string com um piloto ou ação inicial",
                },
                "restricoes": [
                    "não invente dados",
                    "não use score",
                    "não diga que a ideia original estava ruim",
                ],
            },
            "ideia": ideia,
        },
        ensure_ascii=False,
    )
    try:
        from app.pipeline.analysis import _chat, _parse_json

        raw = _chat(system, user, max_tokens=900, json_mode=True)
        data = _parse_json(raw or "") or {}
    except Exception:
        current_app.logger.exception("Erro ao desenvolver ideia com IA")
        data = {}
    fallback = _fallback_ia_ideia(ideia)
    merged = {**fallback, **{k: v for k, v in data.items() if v}}
    merged["impactos_possiveis"] = (
        merged["impactos_possiveis"]
        if isinstance(merged.get("impactos_possiveis"), list)
        else fallback["impactos_possiveis"]
    )
    return merged


def _normalizar_ideia(row: dict) -> dict:
    row["impactos_possiveis"] = _normalizar_json_lista(row.get("impactos_possiveis"))
    criado = row.get("criado_em")
    if isinstance(criado, datetime):
        row["criado_em"] = criado.isoformat()
    return row


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
    perfil_solicitado = (body.get("perfil_solicitado") or "usuario").strip().lower()

    if not email or len(str(senha)) < 6:
        return jsonify({"erro": "e-mail e senha (mín. 6 caracteres) obrigatórios"}), 400
    if not setor:
        return jsonify({"erro": "setor_obrigatorio", "msg": "Escolha o seu setor."}), 400
    if perfil_solicitado not in {"usuario", "gestor", "diretor"}:
        return jsonify({"erro": "perfil_invalido", "msg": "Escolha um tipo de acesso válido."}), 400
    if not dominio_permitido(email):
        return jsonify({"erro": "dominio_nao_permitido",
                        "msg": "Use um e-mail da empresa (@ddm.adv.br ou @grupoddm.com.br)."}), 403

    try:
        ok, motivo = registrar_acesso(email, senha, nome, setor, perfil_solicitado)
    except Exception as exc:
        current_app.logger.exception("Erro ao registrar acesso no MySQL")
        return jsonify({
            "erro": "falha_ao_registrar",
            "msg": f"Banco MySQL: {exc}",
        }), 500

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
    setores = sessao_setores()
    if email:
        acesso = _buscar_acesso(email)
        nome = (acesso or {}).get("nome") or email.split("@")[0]
        setor = (acesso or {}).get("setor") or setor
        setores = (acesso or {}).get("setores") or setores
    elif is_authed():
        nome = "Diretoria"
    return jsonify({
        "autenticado": is_authed(),
        "email": email,
        "admin": is_admin(),
        "gestor_setor": is_gestor_setor(),
        "nome": nome,
        "setor": setor,
        "setores": setores,
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
    setores = body.get("setores")
    if definir_setor(email, setor, setores):
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


@bp.post("/acessos/gestor")
@require_admin
def acessos_gestor():
    """Admin promove/rebaixa outro acesso a gestor do próprio setor."""
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    virar = bool(body.get("gestor"))
    if definir_gestor(email, virar):
        return jsonify({"ok": True})
    return jsonify({"erro": "não encontrado"}), 404


# ── Hub de Ideias ─────────────────────────────────────────────────────────────

@bp.post("/ideias/desenvolver")
@require_auth
def ideias_desenvolver_rascunho():
    """Desenvolve um rascunho de ideia sem expor chave de IA no frontend."""
    body = request.get_json(silent=True) or {}
    ideia = {
        "titulo": (body.get("titulo") or "").strip(),
        "setor": (body.get("setor") or sessao_setor() or "").strip(),
        "dor": (body.get("dor") or "").strip(),
        "solucao": (body.get("solucao") or "").strip(),
        "impacto": (body.get("impacto") or "").strip(),
        "autor": (body.get("autor") or "").strip() or sessao_email() or "Colaborador DDM",
    }

    if not ideia["dor"] or not ideia["solucao"] or not ideia["setor"] or not ideia["impacto"]:
        return jsonify({
            "erro": "campos_obrigatorios",
            "msg": "Preencha percepção, melhoria, setor e impacto.",
        }), 400

    return jsonify(_desenvolver_ideia_com_ia(ideia)), 200


@bp.get("/ideias")
@require_auth
def ideias_listar():
    """Diretoria vê todas as ideias; gestores veem ideias dos seus setores; usuário vê as próprias."""
    minhas = str(request.args.get("minhas") or "").lower() in {"1", "true", "sim", "yes"}
    email_usuario = sessao_email()
    autores_usuario = _solicitantes_sessao()

    if not minhas and not tem_acesso_total() and not is_admin() and not is_gestor_setor():
        return jsonify({"erro": "acesso_restrito"}), 403

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
                dor,
                solucao,
                impacto,
                autor_nome,
                autor_email,
                ai_titulo,
                ai_problema,
                ai_proposta,
                ai_potencial,
                impactos_possiveis,
                ai_primeiro_passo,
                score,
                status,
                criado_em
            FROM ideias
            WHERE status <> %s
        """
        params = ["arquivada"]

        if minhas:
            if not email_usuario and not autores_usuario:
                return jsonify([]), 200
            partes_autor = []
            if email_usuario:
                partes_autor.append("LOWER(TRIM(autor_email)) = %s")
                params.append(_normalizar_texto_acesso(email_usuario))
            if autores_usuario:
                placeholders = ", ".join(["%s"] * len(autores_usuario))
                partes_autor.append(f"LOWER(TRIM(autor_nome)) IN ({placeholders})")
                params.extend(autores_usuario)
            sql += " AND (" + " OR ".join(partes_autor) + ")"
            if email_usuario and _tem_tabela_ideias_ocultas():
                sql += """
                    AND NOT EXISTS (
                        SELECT 1
                        FROM ideias_ocultas_usuario ocultas
                        WHERE ocultas.ideia_id = ideias.id
                          AND LOWER(TRIM(ocultas.usuario_email)) = %s
                    )
                """
                params.append(_normalizar_texto_acesso(email_usuario))
        elif not tem_acesso_total() and not is_admin():
            setores = sessao_setores()
            if not setores:
                return jsonify([]), 200
            placeholders = ", ".join(["%s"] * len(setores))
            sql += f" AND setor IN ({placeholders})"
            params.extend(setores)

        sql += " ORDER BY criado_em DESC LIMIT 200"

        cursor.execute(sql, tuple(params))
        return jsonify([_normalizar_ideia(row) for row in cursor.fetchall()]), 200
    except Exception as exc:
        current_app.logger.exception("Erro ao listar ideias no MySQL")
        return jsonify({
            "erro": "Não foi possível carregar as ideias.",
            "detalhe": str(exc),
        }), 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


@bp.delete("/ideias/<ideia_id>")
@require_auth
def ideias_excluir(ideia_id: str):
    """Diretoria arquiva a ideia; usuário apenas oculta da própria lista."""
    email_usuario = sessao_email()
    autores_usuario = _solicitantes_sessao()

    connection = None
    cursor = None
    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, autor_email, autor_nome, status
            FROM ideias
            WHERE id = %s AND status <> %s
            """,
            (ideia_id, "arquivada"),
        )
        ideia = cursor.fetchone()
        if not ideia:
            return jsonify({"erro": "ideia_nao_encontrada"}), 404

        if tem_acesso_total() or is_admin():
            cursor.execute(
                """
                UPDATE ideias
                SET status = %s
                WHERE id = %s
                """,
                ("arquivada", ideia_id),
            )
            connection.commit()
            return jsonify({"ok": True, "modo": "arquivada"}), 200

        autor_email = _normalizar_texto_acesso(ideia.get("autor_email") or "")
        autor_nome = _normalizar_texto_acesso(ideia.get("autor_nome") or "")
        pode_ocultar = (
            (email_usuario and autor_email == _normalizar_texto_acesso(email_usuario))
            or (autor_nome and autor_nome in autores_usuario)
        )
        if not pode_ocultar:
            return jsonify({"erro": "acesso_restrito"}), 403

        if not _tem_tabela_ideias_ocultas():
            return jsonify({
                "erro": "migração_pendente",
                "msg": "Rode a migração 2026-09-16_create_ideias_ocultas_usuario.sql para remover ideias da lista do usuário.",
            }), 409

        cursor.execute(
            """
            INSERT INTO ideias_ocultas_usuario (id, ideia_id, usuario_email)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE criado_em = criado_em
            """,
            (str(uuid.uuid4()), ideia_id, email_usuario or autores_usuario[0]),
        )
        connection.commit()
        return jsonify({"ok": True, "modo": "ocultada"}), 200
    except Exception as exc:
        if connection is not None and connection.is_connected():
            connection.rollback()
        current_app.logger.exception("Erro ao excluir/ocultar ideia")
        return jsonify({
            "erro": "Não foi possível remover a ideia.",
            "detalhe": str(exc),
        }), 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


@bp.get("/ideias/notificacoes")
@require_auth
def ideias_notificacoes():
    """Conta ideias novas para a diretoria."""
    if not tem_acesso_total() and not is_admin():
        return jsonify({"novas": 0}), 200

    connection = None
    cursor = None
    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM ideias
            WHERE status = %s
            """,
            ("nova",),
        )
        row = cursor.fetchone() or {}
        return jsonify({"novas": int(row.get("total") or 0)}), 200
    except Exception as exc:
        current_app.logger.exception("Erro ao contar ideias novas")
        return jsonify({
            "erro": "Não foi possível contar as ideias novas.",
            "detalhe": str(exc),
        }), 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


@bp.post("/ideias/notificacoes/visualizar")
@require_auth
def ideias_notificacoes_visualizar():
    """Marca ideias novas como visualizadas pela diretoria."""
    if not tem_acesso_total() and not is_admin():
        return jsonify({"ok": True, "atualizadas": 0}), 200

    connection = None
    cursor = None
    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            UPDATE ideias
            SET status = %s
            WHERE status = %s
            """,
            ("visualizada", "nova"),
        )
        connection.commit()
        return jsonify({
            "ok": True,
            "atualizadas": cursor.rowcount,
        }), 200
    except Exception as exc:
        if connection is not None and connection.is_connected():
            connection.rollback()
        current_app.logger.exception("Erro ao visualizar ideias novas")
        return jsonify({
            "erro": "Não foi possível atualizar as notificações de ideias.",
            "detalhe": str(exc),
        }), 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


@bp.post("/ideias")
@require_auth
def ideias_criar():
    """Usuários, gestores e diretoria podem enviar ideias."""
    body = request.get_json(silent=True) or {}
    setores_permitidos = sessao_setores()
    setor = (body.get("setor") or sessao_setor() or "").strip()
    if is_authed() and not tem_acesso_total() and not is_admin() and setores_permitidos and setor not in setores_permitidos:
        setor = setores_permitidos[0]

    ideia = {
        "id": str(uuid.uuid4()),
        "titulo": (body.get("titulo") or "").strip(),
        "setor": setor,
        "dor": (body.get("dor") or "").strip(),
        "solucao": (body.get("solucao") or "").strip(),
        "impacto": (body.get("impacto") or "").strip(),
        "autor_nome": (body.get("autor") or "").strip() or sessao_email() or "Colaborador DDM",
        "autor_email": sessao_email() or "",
    }

    if not ideia["dor"] or not ideia["solucao"] or not ideia["setor"] or not ideia["impacto"]:
        return jsonify({
            "erro": "campos_obrigatorios",
            "msg": "Preencha percepção, melhoria, setor e impacto.",
        }), 400

    ai = _desenvolver_ideia_com_ia({
        "titulo": ideia["titulo"],
        "setor": ideia["setor"],
        "dor": ideia["dor"],
        "solucao": ideia["solucao"],
        "impacto": ideia["impacto"],
        "autor": ideia["autor_nome"],
    })
    if not ideia["titulo"]:
        ideia["titulo"] = ai.get("titulo") or _fallback_ia_ideia(ideia)["titulo"]

    score = _score_ideia(ideia)
    connection = None
    cursor = None
    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            INSERT INTO ideias (
                id,
                titulo,
                setor,
                dor,
                solucao,
                impacto,
                autor_nome,
                autor_email,
                ai_titulo,
                ai_problema,
                ai_proposta,
                ai_potencial,
                impactos_possiveis,
                ai_primeiro_passo,
                score,
                status,
                criado_em
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (
                ideia["id"],
                ideia["titulo"],
                ideia["setor"],
                ideia["dor"],
                ideia["solucao"],
                ideia["impacto"],
                ideia["autor_nome"],
                ideia["autor_email"],
                ai.get("titulo") or ideia["titulo"],
                ai.get("problema") or ideia["dor"],
                ai.get("proposta") or ideia["solucao"],
                ai.get("potencial") or "",
                json.dumps(ai.get("impactos_possiveis") or [], ensure_ascii=False),
                ai.get("primeiro_passo") or "",
                score,
                "nova",
            ),
        )
        connection.commit()
        ideia_salva = {
            **ideia,
            "ai_titulo": ai.get("titulo") or ideia["titulo"],
            "ai_problema": ai.get("problema") or ideia["dor"],
            "ai_proposta": ai.get("proposta") or ideia["solucao"],
            "ai_potencial": ai.get("potencial") or "",
            "impactos_possiveis": ai.get("impactos_possiveis") or [],
            "ai_primeiro_passo": ai.get("primeiro_passo") or "",
            "score": score,
            "status": "nova",
        }
        return jsonify(ideia_salva), 201
    except Exception as exc:
        if connection is not None:
            connection.rollback()
        current_app.logger.exception("Erro ao salvar ideia no MySQL")
        return jsonify({
            "erro": "Não foi possível salvar a ideia.",
            "detalhe": str(exc),
        }), 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


@bp.post("/ideias/<ideia_id>/desenvolver")
@require_auth
def ideias_desenvolver_salva(ideia_id):
    """Diretoria reprocessa qualquer ideia; gestores reprocessam ideias dos seus setores."""
    if not tem_acesso_total() and not is_admin() and not is_gestor_setor():
        return jsonify({"erro": "acesso_restrito"}), 403

    connection = None
    cursor = None
    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT *
            FROM ideias
            WHERE id = %s
            LIMIT 1
            """,
            (ideia_id,),
        )
        ideia = cursor.fetchone()
        if not ideia:
            return jsonify({"erro": "não encontrado"}), 404

        if not tem_acesso_total() and not is_admin() and (ideia.get("setor") or "") not in sessao_setores():
            return jsonify({"erro": "não encontrado"}), 404

        ai = _desenvolver_ideia_com_ia({
            "titulo": ideia.get("titulo") or "",
            "setor": ideia.get("setor") or "",
            "dor": ideia.get("dor") or "",
            "solucao": ideia.get("solucao") or "",
            "impacto": ideia.get("impacto") or "",
            "autor": ideia.get("autor_nome") or "",
        })
        cursor.execute(
            """
            UPDATE ideias
            SET
                ai_titulo = %s,
                ai_problema = %s,
                ai_proposta = %s,
                ai_potencial = %s,
                impactos_possiveis = %s,
                ai_primeiro_passo = %s
            WHERE id = %s
            """,
            (
                ai.get("titulo") or ideia.get("titulo") or "",
                ai.get("problema") or ideia.get("dor") or "",
                ai.get("proposta") or ideia.get("solucao") or "",
                ai.get("potencial") or "",
                json.dumps(ai.get("impactos_possiveis") or [], ensure_ascii=False),
                ai.get("primeiro_passo") or "",
                ideia_id,
            ),
        )
        connection.commit()
        return jsonify(ai), 200
    except Exception as exc:
        if connection is not None:
            connection.rollback()
        current_app.logger.exception("Erro ao desenvolver ideia salva no MySQL")
        return jsonify({
            "erro": "Não foi possível desenvolver a ideia.",
            "detalhe": str(exc),
        }), 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


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

        escopo_sql, escopo_params = _escopo_reunioes_sql()
        sql += escopo_sql
        params.extend(escopo_params)

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

        escopo_sql, escopo_params = _escopo_reunioes_sql()
        sql += escopo_sql
        params.extend(escopo_params)

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

        escopo_sql, escopo_params = _escopo_reunioes_sql()
        sql += escopo_sql
        params.extend(escopo_params)

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

        escopo_sql, escopo_params = _escopo_reunioes_sql()
        sql += escopo_sql
        params.extend(escopo_params)

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

        escopo_sql, escopo_params = _escopo_reunioes_sql()
        sql_pendencias += escopo_sql
        params_pendencias.extend(escopo_params)

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
        erro_msg,
        status,
        plataforma,
        solicitante,
        cliente,
        modalidade,
        local_reuniao,
        visibilidade_setor,
        compartilhado_setores,
        compartilhado_emails
        FROM reunioes
        WHERE excluida_em IS NULL
        """

        params = []

        # Diretor vê tudo, gestor vê setor, usuário normal vê só o que cadastrou.
        escopo_sql, escopo_params = _escopo_reunioes_sql()
        sql += escopo_sql
        params.extend(escopo_params)

        setor = request.args.get("setor")
        if setor and tem_acesso_total():
            if _tem_coluna_reunioes("compartilhado_setores"):
                sql += " AND (setor = %s OR COALESCE(compartilhado_setores, '') LIKE %s)"
                params.extend([setor, _json_like_param(setor)])
            else:
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
            params.append(
                f"{data_fim} 23:59:59"
                if len(data_fim) == 10
                else data_fim
            )

        usuario = (request.args.get("usuario") or "").strip().lower()
        if usuario:
            termos_usuario = [usuario]
            if usuario.endswith(")") and "(" in usuario:
                nome_usuario, email_usuario = usuario.rsplit("(", 1)
                nome_usuario = nome_usuario.strip()
                email_usuario = email_usuario[:-1].strip()
                termos_usuario = [termo for termo in (nome_usuario, email_usuario) if termo]
            condicoes_usuario = []
            params_usuario = []
            for termo in termos_usuario:
                busca_usuario = f"%{termo}%"
                condicoes_usuario.extend([
                    "LOWER(COALESCE(solicitante, '')) LIKE %s",
                    "LOWER(COALESCE(compartilhado_emails, '')) LIKE %s",
                    "LOWER(COALESCE(participantes, '')) LIKE %s",
                ])
                params_usuario.extend([busca_usuario, busca_usuario, busca_usuario])
            sql += """
             AND (
               {condicoes}
             )
            """.format(condicoes=" OR ".join(condicoes_usuario))
            params.extend(params_usuario)

        cliente = (request.args.get("cliente") or "").strip().lower()
        if cliente:
            sql += " AND LOWER(COALESCE(cliente, '')) LIKE %s"
            params.append(f"%{cliente}%")

        local = (request.args.get("local") or "").strip()
        if local:
            sql += " AND local_reuniao = %s"
            params.append(local)

        tem_filtro_avancado = any((data_inicio, data_fim, usuario, cliente, local))
        sql += f" ORDER BY data DESC LIMIT {200 if tem_filtro_avancado else 50}"

        cursor.execute(sql, params)
        reunioes = [
            _normalizar_json_reuniao(reuniao)
            for reuniao in cursor.fetchall()
        ]

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


@bp.get("/reunioes/filtros")
@require_auth
def opcoes_filtros_reunioes():
    """Valores existentes no banco para preencher os filtros de reuniões."""
    connection = None
    cursor = None
    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        sql = """
        SELECT data, cliente, local_reuniao
        FROM reunioes
        WHERE excluida_em IS NULL
        """
        params = []
        escopo_sql, escopo_params = _escopo_reunioes_sql()
        sql += escopo_sql
        params.extend(escopo_params)
        sql += " ORDER BY data DESC"
        cursor.execute(sql, params)
        linhas = cursor.fetchall()

        datas = set()
        clientes = set()
        locais = set()
        for linha in linhas:
            data = linha.get("data")
            if data:
                if hasattr(data, "strftime"):
                    datas.add(data.strftime("%Y-%m-%d"))
                else:
                    datas.add(str(data)[:10])

            cliente = str(linha.get("cliente") or "").strip()
            if cliente:
                clientes.add(cliente)
            local = str(linha.get("local_reuniao") or "").strip()
            if local:
                locais.add(local)

        return jsonify({
            "datas": sorted(datas, reverse=True),
            "usuarios": [],
            "clientes": sorted(clientes, key=str.casefold),
            "locais": sorted(locais, key=str.casefold),
        }), 200
    except Exception as exc:
        current_app.logger.exception("Erro ao carregar opções dos filtros de reuniões")
        return jsonify({"erro": "falha_ao_carregar_filtros", "msg": str(exc)}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


@bp.get("/reunioes/erros")
@require_admin
def listar_erros_reunioes():
    """Diagnostico interno: ultimas falhas persistidas por reuniao."""
    connection = None
    cursor = None

    try:
        limite = request.args.get("limite", "100")

        try:
            limite = int(limite)
        except (TypeError, ValueError):
            limite = 100

        limite = max(1, min(limite, 200))

        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                id,
                titulo,
                setor,
                solicitante,
                data,
                plataforma,
                status,
                recall_bot_id,
                erro_msg,
                criado_em
            FROM reunioes
            WHERE excluida_em IS NULL
              AND (
                status = %s
                OR COALESCE(erro_msg, '') <> ''
              )
            ORDER BY COALESCE(data, criado_em) DESC
            LIMIT %s
            """,
            ("error", limite),
        )

        return jsonify(cursor.fetchall()), 200

    except Exception as exc:
        current_app.logger.exception(
            "Erro ao listar falhas internas de reuniões"
        )

        return jsonify({
            "erro": "Não foi possível carregar os erros das reuniões.",
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

        if not _pode_acessar_reuniao(reuniao):
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


@bp.post("/reunioes/<reuniao_id>/metadados")
@require_auth
def atualizar_metadados_reuniao(reuniao_id: str):
    """Atualiza dados cadastrais da reunião sem reprocessar transcrição/IA."""
    body = request.get_json(silent=True) or {}

    campos_permitidos = {
        "titulo",
        "solicitante",
        "setor",
        "data",
        "modalidade",
        "local_reuniao",
        "cliente",
        "compartilhado_setores",
        "compartilhado_emails",
        "visibilidade_setor",
    }

    valores = {}
    for campo in campos_permitidos:
        if campo in body:
            valor = body.get(campo)
            if campo in {"compartilhado_setores", "compartilhado_emails"}:
                valores[campo] = json.dumps(
                    _normalizar_lista_texto(valor),
                    ensure_ascii=False,
                )
            else:
                valores[campo] = "" if valor is None else str(valor).strip()

    if "titulo" in valores and not valores["titulo"]:
        return jsonify({
            "erro": "titulo_obrigatorio",
            "msg": "Informe um título para a reunião.",
        }), 400

    if "setor" in valores and not valores["setor"]:
        return jsonify({
            "erro": "setor_obrigatorio",
            "msg": "Informe o setor da reunião.",
        }), 400

    if "visibilidade_setor" in valores and valores["visibilidade_setor"] not in {"todos", "gestores"}:
        return jsonify({"erro": "visibilidade_invalida"}), 400

    if "modalidade" in valores:
        modalidade = valores["modalidade"] or "online"
        if modalidade not in {"online", "presencial"}:
            return jsonify({
                "erro": "modalidade_invalida",
                "msg": "Formato deve ser online ou presencial.",
            }), 400
        valores["modalidade"] = modalidade

    if not valores:
        return jsonify({"ok": True, "atualizados": []}), 200

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                id,
                setor,
                solicitante,
                compartilhado_setores,
                compartilhado_emails
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

        if not _pode_editar_reuniao(reuniao):
            return jsonify({"erro": "não encontrado"}), 404

        atribuicoes = [f"`{campo}` = %s" for campo in valores]
        params = list(valores.values())
        params.append(reuniao_id)

        cursor.execute(
            f"""
            UPDATE reunioes
            SET {", ".join(atribuicoes)}
            WHERE id = %s
            """,
            tuple(params),
        )
        connection.commit()

        return jsonify({
            "ok": True,
            "atualizados": list(valores.keys()),
        }), 200

    except Exception as exc:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception(
            "Erro ao atualizar metadados da reunião %s",
            reuniao_id,
        )

        return jsonify({
            "erro": "falha_ao_atualizar",
            "msg": str(exc),
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
            SELECT
                id,
                setor,
                solicitante,
                recall_bot_id,
                utterances,
                participantes,
                compartilhado_setores,
                compartilhado_emails
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

    if not _pode_acessar_reuniao(reuniao):
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


@bp.post("/reunioes/<reuniao_id>/perguntar")
@require_auth
def perguntar_reuniao(reuniao_id: str):
    """
    Busca semântica: pergunta em linguagem natural sobre a reunião.

    Devolve a resposta e os índices das falas que a sustentam, para o painel
    destacar o trecho em vez de obrigar a ler a transcrição inteira.
    """
    from app.pipeline.analysis import perguntar_sobre_reuniao

    reuniao, erro = _carregar_reuniao_locutores(reuniao_id)

    if erro:
        return erro

    pergunta = ((request.get_json(silent=True) or {}).get("pergunta") or "").strip()

    if not pergunta:
        return jsonify({"erro": "pergunta obrigatória"}), 400

    if len(pergunta) > 500:
        return jsonify({"erro": "pergunta muito longa"}), 400

    utterances = _json_lista(reuniao.get("utterances"))

    try:
        resultado = perguntar_sobre_reuniao(pergunta, utterances)

    except Exception as exc:
        current_app.logger.exception(
            "Erro ao perguntar sobre a reunião %s",
            reuniao_id,
        )

        return jsonify({
            "erro": "Não foi possível consultar o Acordito.",
            "detalhe": str(exc),
        }), 502

    # Devolve o texto das falas citadas junto, para o painel não recarregar.
    resultado["falas"] = [
        {
            "indice": i,
            "speaker": (utterances[i].get("speaker") or "?"),
            "texto": (utterances[i].get("texto") or ""),
        }
        for i in resultado.get("trechos", [])
    ]

    return jsonify(resultado), 200


@bp.post("/reunioes/<reuniao_id>/acoes/<int:indice>")
@require_auth
def atualizar_acao(reuniao_id: str, indice: int):
    """
    Muda o status de uma ação do plano. Corpo: {"status": "concluida"}.

    Quem enxerga a reunião pode marcar — é o que faz a tabela virar
    acompanhamento de verdade, e fica registrado quem marcou e quando.
    """
    # Só interessa a checagem de acesso/setor; as pendências vêm na query abaixo.
    _, erro = _carregar_reuniao_locutores(reuniao_id)

    if erro:
        return erro

    status = ((request.get_json(silent=True) or {}).get("status") or "").strip().lower()

    if status not in ("pendente", "em_andamento", "concluida"):
        return jsonify({"erro": "status inválido"}), 400

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT pendencias
            FROM reunioes
            WHERE id = %s
              AND excluida_em IS NULL
            LIMIT 1
            """,
            (reuniao_id,),
        )

        linha = cursor.fetchone()
        cursor.close()
        cursor = None

        if not linha:
            return jsonify({"erro": "não encontrado"}), 404

        pendencias = _json_lista(linha.get("pendencias"))

        if indice < 0 or indice >= len(pendencias):
            return jsonify({"erro": "ação não encontrada"}), 404

        bruta = pendencias[indice]
        acao: dict = dict(bruta) if isinstance(bruta, dict) else {"tarefa": str(bruta)}

        acao["status"] = status

        if status == "concluida":
            acao["concluida_por"] = sessao_email() or "diretoria"
            acao["concluida_em"] = datetime.now(timezone.utc).isoformat()
        else:
            acao["concluida_por"] = None
            acao["concluida_em"] = None

        pendencias[indice] = acao

        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE reunioes
            SET pendencias = %s
            WHERE id = %s
            """,
            (json.dumps(pendencias, ensure_ascii=False), reuniao_id),
        )

        connection.commit()

        return jsonify({"ok": True, "acao": acao}), 200

    except Exception as exc:
        if connection is not None:
            connection.rollback()

        current_app.logger.exception(
            "Erro ao atualizar ação %d da reunião %s",
            indice,
            reuniao_id,
        )

        return jsonify({
            "erro": "Não foi possível atualizar a ação.",
            "detalhe": str(exc),
        }), 500

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


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
                solicitante,
                setor,
                plataforma,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                reuniao_id,
                request.form.get(
                    "titulo",
                    "Reunião — upload manual",
                ),
                sessao_email() or request.form.get("solicitante", ""),
                sessao_setor() if not tem_acesso_total() else request.form.get("setor", ""),
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

@bp.get("/bots/capacidade")
@require_auth
def capacidade_bots():
    """Ocupação observada dos bots Skribby vinculados ao Meeting DDM."""
    if not tem_acesso_total() and not is_admin():
        return jsonify({"erro": "acesso_negado"}), 403

    connection = None
    cursor = None
    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, titulo, setor, data, recall_bot_id
            FROM reunioes
            WHERE excluida_em IS NULL
              AND status IN ('pending', 'processing')
              AND recall_bot_id IS NOT NULL
              AND recall_bot_id <> ''
            ORDER BY data DESC
            LIMIT 100
            """
        )
        candidatas = cursor.fetchall()
    except Exception as exc:
        current_app.logger.exception("Erro ao carregar bots para cálculo de capacidade")
        return jsonify({"erro": "falha_banco", "msg": str(exc)}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()

    from app.pipeline.skribby_client import (
        ACTIVE_BOT_STATUSES,
        concurrent_bot_limit,
        get_bot,
    )

    bots = []
    falhas = 0
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(candidatas)))) as executor:
        futuros = {
            executor.submit(get_bot, reuniao["recall_bot_id"]): reuniao
            for reuniao in candidatas
        }
        for futuro in as_completed(futuros):
            reuniao = futuros[futuro]
            try:
                bot = futuro.result()
                estado = (bot.get("status") or "").strip()
            except Exception:
                falhas += 1
                current_app.logger.warning(
                    "Não foi possível consultar o bot %s para capacidade",
                    reuniao["recall_bot_id"],
                    exc_info=True,
                )
                continue
            bots.append({
                "reuniao_id": reuniao["id"],
                "titulo": reuniao.get("titulo") or "Reunião",
                "setor": reuniao.get("setor") or "",
                "data": reuniao.get("data"),
                "bot_id": reuniao["recall_bot_id"],
                "status": estado,
                "consome_vaga": estado in ACTIVE_BOT_STATUSES,
            })

    limite = concurrent_bot_limit()
    ativos = sum(1 for bot in bots if bot["consome_vaga"])
    agendados = sum(1 for bot in bots if bot["status"] == "scheduled")
    bots.sort(key=lambda bot: (not bot["consome_vaga"], str(bot["data"])), reverse=False)
    return jsonify({
        "plano": "pay_as_you_go",
        "limite_simultaneo": limite,
        "ativos": ativos,
        "vagas_disponiveis": max(0, limite - ativos),
        "agendados": agendados,
        "consultados": len(bots),
        "falhas_consulta": falhas,
        "status_que_consumem_vaga": sorted(ACTIVE_BOT_STATUSES),
        "bots": bots,
        "observacao": (
            "Contagem dos bots vinculados ao Meeting DDM. Bots scheduled não "
            "consomem vaga; o limite é compartilhado por toda a organização Skribby."
        ),
    }), 200


@bp.post("/gravacoes")
def criar_gravacao():
    """
    Funcionário aciona a gravação: cola o link da reunião,
    o bot Acordito entra, grava e transcreve.

    Cria a reunião no MariaDB com status 'pending'.
    """

    body = request.get_json(silent=True) or {}

    visibilidade_setor = (body.get("visibilidade_setor") or "gestores").strip()
    if visibilidade_setor not in {"todos", "gestores"}:
        return jsonify({"erro": "visibilidade_invalida"}), 400
    if not _tem_coluna_reunioes("visibilidade_setor"):
        return jsonify({
            "erro": "migracao_pendente",
            "msg": "Aplique a migração de visibilidade das reuniões antes de registrar novas reuniões.",
        }), 503

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

    setores_informados = _normalizar_lista_texto(
        body.get("setores") or body.get("compartilhado_setores")
    )
    setor = (body.get("setor") or "").strip()
    if not setor and setores_informados:
        setor = setores_informados[0]

    if is_authed() and not tem_acesso_total():
        setores_sessao = sessao_setores()
        if setores_sessao and setor not in setores_sessao:
            permitido = next(
                (s for s in setores_informados if s in setores_sessao),
                "",
            )
            setor = permitido or setores_sessao[0]

    if not setor:
        return jsonify({
            "erro": "setor_obrigatorio",
            "msg": "Marque ao menos um setor envolvido.",
        }), 400

    setores_extras = [
        s for s in setores_informados
        if s and s.lower() != setor.lower()
    ]
    emails_compartilhados = [
        email.lower()
        for email in _normalizar_lista_texto(body.get("compartilhado_emails"))
        if "@" in email
    ]

    vocabulario_reuniao = [
        body.get("cliente"),
        body.get("titulo"),
        setor,
        *setores_extras,
        "Grupo DDM",
        "DDM",
        "Acordito",
    ]
    data_reuniao = (
        (body.get("data") or "").strip()
        or datetime.now(timezone.utc).isoformat()
    )
    scheduled_start_time = _scheduled_start_timestamp(data_reuniao)
    current_app.logger.info(
        "Reunião Skribby: data=%s modo=%s",
        data_reuniao,
        "agendado" if scheduled_start_time else "entrada imediata",
    )

    # Solicita ao Skribby a criação do bot.
    try:
        inicio_criacao_bot = time.monotonic()
        bot = create_bot(
            meeting_url,
            custom_vocabulary=vocabulario_reuniao,
            scheduled_start_time=scheduled_start_time,
        )
        current_app.logger.info(
            "Skribby create_bot concluído em %.2fs; modo=%s",
            time.monotonic() - inicio_criacao_bot,
            "agendado" if scheduled_start_time else "imediato",
        )

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

    titulo = (
        (body.get("titulo") or "").strip()
        or "Reunião (Skribby)"
    )

    solicitante = (body.get("solicitante") or "").strip()
    if is_authed() and sessao_email():
        solicitante = sessao_email()

    modalidade = (body.get("modalidade") or "online").strip()
    local_reuniao = (body.get("local_reuniao") or "").strip()
    cliente = (body.get("cliente") or "").strip()

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()

        colunas = [
            "id",
            "titulo",
            "solicitante",
            "setor",
            "data",
            "plataforma",
            "status",
            "visibilidade_setor",
            "recall_bot_id",
            "modalidade",
            "local_reuniao",
            "cliente",
        ]
        valores_insert = [
            reuniao_id,
            titulo,
            solicitante,
            setor,
            data_reuniao,
            "skribby",
            "pending",
            visibilidade_setor,
            bot_id,
            modalidade,
            local_reuniao,
            cliente,
        ]

        if setores_extras and _tem_coluna_reunioes("compartilhado_setores"):
            colunas.append("compartilhado_setores")
            valores_insert.append(
                json.dumps(setores_extras, ensure_ascii=False)
            )

        if emails_compartilhados and _tem_coluna_reunioes("compartilhado_emails"):
            colunas.append("compartilhado_emails")
            valores_insert.append(
                json.dumps(emails_compartilhados, ensure_ascii=False)
            )

        cursor.execute(
            f"""
            INSERT INTO reunioes ({", ".join(colunas)})
            VALUES ({", ".join(["%s"] * len(colunas))})
            """,
            tuple(valores_insert),
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
        "status": (
            "bot agendado"
            if scheduled_start_time
            else "bot entrando na reunião"
        ),
        "scheduled_start_time": scheduled_start_time,
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

    if tipo == "status_update" and novo_status and bot_id:
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

                if novo_status == "finished":
                    threading.Thread(
                        target=_processar_recall,
                        args=(reuniao_id, bot_id),
                        daemon=True,
                    ).start()

                elif novo_status in (
                    "not_admitted",
                    "auth_required",
                    "invalid_credentials",
                    "invalid_api_key",
                    "failed",
                ):
                    stop_reason = (
                        (body.get("data") or {}).get("stop_reason")
                        or ""
                    )
                    from app.pipeline.skribby_client import classify_bot_issue
                    issue = classify_bot_issue(novo_status, stop_reason)
                    erro_msg = (
                        f"{issue['titulo']}: {issue['mensagem']} "
                        f"Ação sugerida: {issue['acao']}"
                    )
                    if issue.get("tecnico"):
                        erro_msg += f" | técnico: {issue['tecnico']}"

                    cursor.execute(
                        """
                        UPDATE reunioes
                        SET status = %s,
                            erro_msg = %s
                        WHERE id = %s
                        """,
                        ("error", erro_msg, reuniao_id),
                    )
                    connection.commit()

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


@bp.get("/gravacoes/<reuniao_id>/status")
@require_auth
def status_gravacao(reuniao_id: str):
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
                erro_msg,
                setor,
                solicitante,
                compartilhado_setores,
                compartilhado_emails
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

        if not _pode_acessar_reuniao(reuniao):
            return jsonify({"erro": "não encontrado"}), 404

        bot_id = reuniao.get("recall_bot_id")
        if not bot_id:
            return jsonify({
                "erro": "reunião sem bot Skribby"
            }), 400

    except Exception as exc:
        current_app.logger.exception(
            "Erro ao buscar reunião para status do Skribby"
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

    try:
        from app.pipeline.skribby_client import (
            classify_bot_issue,
            get_bot,
            bot_status,
        )

        bot = get_bot(bot_id)
        status = bot_status(bot)
        stop_reason = bot.get("stop_reason") or ""
        classificacao = classify_bot_issue(status, stop_reason)

        return jsonify({
            "bot_id": bot_id,
            "bot_status": status,
            "stop_reason": stop_reason,
            "classificacao": classificacao,
            # Neste endpoint, `status` precisa ser o estado real do bot.
            # O estado interno da reunião pode continuar como `pending`.
            "status": status,
            "reuniao_status": reuniao.get("status"),
            "erro_msg": reuniao.get("erro_msg") or "",
        }), 200

    except Exception as exc:
        current_app.logger.exception(
            "Erro ao consultar status do bot Skribby %s",
            bot_id,
        )

        return jsonify({
            "erro": "falha_skribby",
            "msg": str(exc),
        }), 502


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
                setor,
                solicitante,
                compartilhado_setores,
                compartilhado_emails
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

        if not _pode_acessar_reuniao(reuniao):
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

@bp.get("/extensao/usuario")
def usuario_da_extensao():
    """Preenche nome e setor na extensão a partir de um e-mail exato aprovado."""
    email = (request.args.get("email") or "").strip().lower()
    if not email or not dominio_permitido(email):
        return jsonify({"erro": "email_invalido"}), 400

    connection = None
    cursor = None
    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT nome, setor
            FROM painel_acessos
            WHERE LOWER(email) = %s AND ativo = 1 AND aprovado = 1
            LIMIT 1
            """,
            (email,),
        )
        usuario = cursor.fetchone()
        if not usuario:
            return jsonify({"erro": "usuario_nao_encontrado"}), 404
        return jsonify({
            "nome": usuario.get("nome") or email.split("@")[0],
            "setor": usuario.get("setor") or "",
        }), 200
    except Exception:
        current_app.logger.exception("Erro ao consultar usuario da extensao")
        return jsonify({"erro": "falha_ao_consultar_usuario"}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()

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


@bp.get("/reunioes/compartilhamento/usuarios")
@require_auth
def listar_usuarios_compartilhamento():
    """Lista usuários aprovados que podem receber uma reunião compartilhada."""
    email_atual = (sessao_email() or "").strip().lower()
    usuarios = []
    for acesso in listar_acessos():
        email = (acesso.get("email") or "").strip().lower()
        if not email or email == email_atual:
            continue
        if not acesso.get("ativo") or not acesso.get("aprovado"):
            continue
        usuarios.append({
            "email": email,
            "nome": acesso.get("nome") or email.split("@")[0],
            "setor": acesso.get("setor") or "",
            "setores": acesso.get("setores") or [],
        })
    usuarios.sort(key=lambda item: (item["nome"].lower(), item["email"]))
    return jsonify(usuarios), 200


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
