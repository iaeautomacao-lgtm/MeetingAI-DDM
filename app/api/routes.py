import os
import uuid
from datetime import datetime, timedelta, timezone
from flask import request, jsonify, current_app
from werkzeug.utils import secure_filename

from app.api import bp
from app.extensions import get_supabase
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
    """Reuniões Teams que iniciaram nas últimas 4h e ainda não concluíram."""
    db = get_supabase()
    desde = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    q = (
        db.table("reunioes")
        .select("id,titulo,setor,data,participantes,status")
        .gte("data", desde)
        .in_("status", ["pending", "processing"])
        .eq("plataforma", "teams")
        .order("data", desc=True)
    )
    resultado = _q_reunioes_do_setor(q).execute()
    return jsonify(resultado.data or [])


@bp.get("/live/processando")
@require_auth
def live_processando():
    """Reuniões em transcrição/análise agora."""
    db = get_supabase()
    q = (
        db.table("reunioes")
        .select("id,titulo,setor,status")
        .eq("status", "processing")
        .order("data", desc=True)
        .limit(20)
    )
    resultado = _q_reunioes_do_setor(q).execute()
    items = [
        {**r, "progresso": 60 if r["status"] == "processing" else 20}
        for r in (resultado.data or [])
    ]
    return jsonify(items)


# ── Dashboard summary ─────────────────────────────────────────────────────────

@bp.get("/dashboard/summary")
@require_auth
def dashboard_summary():
    db = get_supabase()
    periodo = request.args.get("periodo", "7d")
    dias = {"7d": 7, "15d": 15, "30d": 30}.get(periodo, 7)
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()

    q = (
        db.table("reunioes")
        .select("id,titulo,setor,data,duracao_minutos,participantes,resumo_executivo,decisoes,pendencias,status")
        .gte("data", desde)
        .eq("status", "completed")
        .order("data", desc=True)
    )
    reunioes = (_q_reunioes_do_setor(q).execute()).data or []

    todas_decisoes = [d for r in reunioes for d in (r.get("decisoes") or [])]
    todas_pendencias = [p for r in reunioes for p in (r.get("pendencias") or [])]
    sem_responsavel = [p for p in todas_pendencias if not p.get("responsavel")]

    por_setor: dict = {}
    for r in reunioes:
        s = r.get("setor") or "Outros"
        por_setor[s] = por_setor.get(s, 0) + 1

    return jsonify({
        "total_reunioes": len(reunioes),
        "total_decisoes": len(todas_decisoes),
        "total_pendencias": len(todas_pendencias),
        "sem_responsavel": len(sem_responsavel),
        "ultimas_reunioes": reunioes[:5],
        "decisoes_recentes": todas_decisoes[:10],
        "pendencias_sem_responsavel": sem_responsavel[:10],
        "por_setor": [{"setor": k, "total": v} for k, v in por_setor.items()],
    })


# ── Dashboard (legado) ────────────────────────────────────────────────────────

@bp.get("/dashboard")
@require_auth
def dashboard():
    db = get_supabase()
    hoje = request.args.get("data")

    q = db.table("reunioes").select(
        "id,titulo,setor,data,duracao_minutos,participantes,resumo_executivo,status"
    ).order("data", desc=True).limit(10)
    reunioes = _q_reunioes_do_setor(q).execute().data

    emails_count = db.table("emails").select("id", count="exact").execute().count

    qp = db.table("reunioes").select("pendencias").eq("status", "completed")
    pendencias = _q_reunioes_do_setor(qp).execute().data
    todas = [p for r in pendencias for p in (r.get("pendencias") or []) if not p.get("responsavel")]

    return jsonify({
        "ultimas_reunioes": reunioes,
        "total_emails": emails_count,
        "pendencias_sem_dono": todas[:20],
    })


# ── Reuniões ──────────────────────────────────────────────────────────────────

@bp.get("/reunioes")
@require_auth
def listar_reunioes():
    db = get_supabase()
    q = db.table("reunioes").select(
        "id,titulo,setor,data,duracao_minutos,participantes,resumo_executivo,status,plataforma"
    )
    q = _q_reunioes_do_setor(q)  # usuário comum só vê o próprio setor

    if setor := request.args.get("setor"):
        # só permite filtrar por setor quem tem acesso total (senão ignora)
        if tem_acesso_total():
            q = q.eq("setor", setor)
    if status := request.args.get("status"):
        q = q.eq("status", status)
    if data_inicio := request.args.get("de"):
        q = q.gte("data", data_inicio)
    if data_fim := request.args.get("ate"):
        q = q.lte("data", data_fim)

    resultado = q.order("data", desc=True).limit(50).execute()
    return jsonify(resultado.data)


@bp.get("/reunioes/<reuniao_id>")
@require_auth
def detalhe_reuniao(reuniao_id: str):
    db = get_supabase()
    resultado = db.table("reunioes").select("*").eq("id", reuniao_id).single().execute()
    if not resultado.data:
        return jsonify({"erro": "não encontrado"}), 404
    # isolamento por setor: usuário comum não abre reunião de outro setor
    if not tem_acesso_total() and (resultado.data.get("setor") or "") != sessao_setor():
        return jsonify({"erro": "não encontrado"}), 404
    return jsonify(resultado.data)


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

    db = get_supabase()
    row = db.table("reunioes").insert(
        {
            "titulo": request.form.get("titulo", "Reunião — upload manual"),
            "setor": request.form.get("setor", ""),
            "plataforma": "avulso",
            "status": "pending",
        }
    ).execute()

    reuniao_id = row.data[0]["id"]
    processar_audio_avulso.delay(reuniao_id, caminho)

    return jsonify({"reuniao_id": reuniao_id, "status": "pending"}), 202


# ── Gravações Skribby (bot "Acordito" entra na reunião) ──────────────────────

@bp.post("/gravacoes")
def criar_gravacao():
    """
    Funcionário aciona a gravação: cola o link da reunião, o bot Acordito entra,
    grava e transcreve. Cria a reunião com status 'pending'.
    """
    from app.pipeline.skribby_client import create_bot

    body = request.get_json(silent=True) or {}
    meeting_url = (body.get("meeting_url") or "").strip()
    if not meeting_url:
        return jsonify({"erro": "meeting_url obrigatório"}), 400

    try:
        bot = create_bot(meeting_url)
    except Exception as e:
        return jsonify({"erro": f"Skribby: {e}"}), 502

    bot_id = bot.get("id")
    db = get_supabase()
    row = db.table("reunioes").insert(
        {
            "titulo": body.get("titulo") or "Reunião (Skribby)",
            "solicitante": (body.get("solicitante") or "").strip(),
            "setor": body.get("setor", ""),
            "data": datetime.now(timezone.utc).isoformat(),
            "plataforma": "skribby",
            "status": "pending",
            "recall_bot_id": bot_id,  # coluna reaproveitada p/ guardar o id do bot Skribby
        }
    ).execute()

    return jsonify(
        {
            "reuniao_id": row.data[0]["id"],
            "bot_id": bot_id,
            "status": "bot entrando na reunião",
        }
    ), 202


@bp.post("/skribby/webhook")
def skribby_webhook():
    """
    Recebe eventos do Skribby (type 'status_update'). Quando new_status == 'finished'
    a transcrição está pronta → dispara o processamento numa thread e responde 200 rápido.
    Payload: {bot_id, type, data:{old_status, new_status, stop_reason}, custom_metadata}
    """
    import threading
    from app.workers.tasks import _processar_recall

    body = request.get_json(silent=True) or {}
    bot_id = body.get("bot_id")
    tipo = body.get("type", "")
    novo_status = ((body.get("data") or {}).get("new_status")) or ""

    if tipo == "status_update" and novo_status == "finished" and bot_id:
        db = get_supabase()
        r = db.table("reunioes").select("id").eq("recall_bot_id", bot_id).execute()
        if r.data:
            reuniao_id = r.data[0]["id"]
            threading.Thread(
                target=_processar_recall, args=(reuniao_id, bot_id), daemon=True
            ).start()

    return jsonify({"ok": True}), 200


@bp.post("/gravacoes/<reuniao_id>/processar")
@require_auth
def processar_gravacao_manual(reuniao_id: str):
    """
    Puxa a transcrição manualmente (para testar sem webhook público).
    Só funciona depois que o bot terminou (status Skribby 'finished').
    """
    from app.workers.tasks import _processar_recall

    db = get_supabase()
    r = (
        db.table("reunioes")
        .select("recall_bot_id,status")
        .eq("id", reuniao_id)
        .single()
        .execute()
    )
    if not r.data:
        return jsonify({"erro": "não encontrado"}), 404
    bot_id = r.data.get("recall_bot_id")
    if not bot_id:
        return jsonify({"erro": "reunião sem bot Skribby"}), 400

    try:
        _processar_recall(reuniao_id, bot_id)
    except Exception as e:
        return jsonify({"erro": str(e)}), 502
    return jsonify({"status": "processado"}), 200


# ── E-mails ───────────────────────────────────────────────────────────────────

@bp.get("/emails")
@require_auth
def listar_emails():
    db = get_supabase()
    q = db.table("emails").select(
        "id,de_nome,de_email,assunto,setor_remetente,data,resumo,temas,sentimento,categoria,relevante"
    )

    if setor := request.args.get("setor"):
        q = q.eq("setor_remetente", setor)
    if sentimento := request.args.get("sentimento"):
        q = q.eq("sentimento", sentimento)
    if categoria := request.args.get("categoria"):
        q = q.eq("categoria", categoria)
    # por padrão mostra só relevantes; ?relevante=todos traz tudo
    rel = request.args.get("relevante", "true")
    if rel != "todos":
        q = q.eq("relevante", rel == "true")
    if de := request.args.get("de"):
        q = q.gte("data", de)

    resultado = q.order("data", desc=True).limit(100).execute()
    return jsonify(resultado.data)


# ── Setores ───────────────────────────────────────────────────────────────────

@bp.get("/setores")
def listar_setores():
    db = get_supabase()
    resultado = db.table("setores").select("*").eq("ativo", True).execute()
    return jsonify(resultado.data)


# ── Usuários ──────────────────────────────────────────────────────────────────

@bp.get("/usuarios")
@require_auth
def listar_usuarios():
    db = get_supabase()
    q = db.table("usuarios").select("id,nome,email,setor,cargo").eq("ativo", True)
    if setor := request.args.get("setor"):
        q = q.eq("setor", setor)
    return jsonify(q.execute().data)


# ── Interações (grafo) ────────────────────────────────────────────────────────

@bp.get("/interacoes")
@require_auth
def listar_interacoes():
    db = get_supabase()
    resultado = db.table("interacoes").select("*").order("contagem", desc=True).limit(200).execute()
    return jsonify(resultado.data)


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
