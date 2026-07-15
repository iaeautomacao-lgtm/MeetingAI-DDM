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
    login_session,
    logout_session,
    is_authed,
    is_admin,
    sessao_email,
)


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
        if verificar_login(email, senha):
            login_session(email)
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

    if not email or len(str(senha)) < 6:
        return jsonify({"erro": "e-mail e senha (mín. 6 caracteres) obrigatórios"}), 400
    if not dominio_permitido(email):
        return jsonify({"erro": "dominio_nao_permitido",
                        "msg": "Use um e-mail da empresa (@ddm.adv.br ou @grupoddm.com.br)."}), 403

    ok, motivo = registrar_acesso(email, senha, nome)
    if ok:
        return jsonify({"ok": True, "pendente": True,
                        "msg": "Cadastro enviado. Aguarde a aprovação do administrador."})
    if motivo == "ja_cadastrado":
        return jsonify({"erro": "ja_cadastrado", "msg": "E-mail já cadastrado. Faça login."}), 409
    if motivo == "senha_curta":
        return jsonify({"erro": "senha_curta", "msg": "Senha mínima de 6 caracteres."}), 400
    return jsonify({"erro": "dominio_nao_permitido"}), 403


@bp.post("/auth/logout")
def auth_logout():
    logout_session()
    return jsonify({"ok": True})


@bp.get("/auth/status")
def auth_status():
    from app.auth import _buscar_acesso
    email = sessao_email()
    nome = ""
    if email:
        acesso = _buscar_acesso(email)
        nome = (acesso or {}).get("nome") or email.split("@")[0]
    elif is_authed():
        nome = "Diretoria"
    return jsonify({"autenticado": is_authed(), "email": email, "admin": is_admin(), "nome": nome})


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


# ── Live ──────────────────────────────────────────────────────────────────────

@bp.get("/live/teams")
@require_auth
def live_teams():
    """Reuniões Teams que iniciaram nas últimas 4h e ainda não concluíram."""
    db = get_supabase()
    desde = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    resultado = (
        db.table("reunioes")
        .select("id,titulo,setor,data,participantes,status")
        .gte("data", desde)
        .in_("status", ["pending", "processing"])
        .eq("plataforma", "teams")
        .order("data", desc=True)
        .execute()
    )
    return jsonify(resultado.data or [])


@bp.get("/live/processando")
@require_auth
def live_processando():
    """Reuniões em transcrição/análise agora."""
    db = get_supabase()
    resultado = (
        db.table("reunioes")
        .select("id,titulo,setor,status")
        .eq("status", "processing")
        .order("data", desc=True)
        .limit(20)
        .execute()
    )
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

    reunioes = (
        db.table("reunioes")
        .select("id,titulo,setor,data,duracao_minutos,participantes,resumo_executivo,decisoes,pendencias,status")
        .gte("data", desde)
        .eq("status", "completed")
        .order("data", desc=True)
        .execute()
    ).data or []

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

    reunioes = db.table("reunioes").select(
        "id,titulo,setor,data,duracao_minutos,participantes,resumo_executivo,status"
    ).order("data", desc=True).limit(10).execute().data

    emails_count = db.table("emails").select("id", count="exact").execute().count

    pendencias = db.table("reunioes").select("pendencias").eq("status", "completed").execute().data
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

    if setor := request.args.get("setor"):
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


# ── Gravações Recall.ai (bot "DDM" entra na reunião) ─────────────────────────

@bp.post("/gravacoes")
def criar_gravacao():
    """
    Funcionário aciona a gravação: cola o link da reunião, o bot DDM entra,
    grava e transcreve. Cria a reunião com status 'pending'.
    """
    from app.pipeline.recall_client import create_bot

    body = request.get_json(silent=True) or {}
    meeting_url = (body.get("meeting_url") or "").strip()
    if not meeting_url:
        return jsonify({"erro": "meeting_url obrigatório"}), 400

    try:
        bot = create_bot(meeting_url)
    except Exception as e:
        return jsonify({"erro": f"Recall: {e}"}), 502

    bot_id = bot.get("id")
    db = get_supabase()
    row = db.table("reunioes").insert(
        {
            "titulo": body.get("titulo") or "Reunião (Recall)",
            "solicitante": (body.get("solicitante") or "").strip(),
            "setor": body.get("setor", ""),
            "data": datetime.now(timezone.utc).isoformat(),
            "plataforma": "recall",
            "status": "pending",
            "recall_bot_id": bot_id,
        }
    ).execute()

    return jsonify(
        {
            "reuniao_id": row.data[0]["id"],
            "bot_id": bot_id,
            "status": "bot entrando na reunião",
        }
    ), 202


@bp.post("/recall/webhook")
def recall_webhook():
    """
    Recebe eventos do Recall. Em 'bot.done' (mídia pronta) dispara o processamento
    da transcrição numa thread e responde 200 rápido (Recall exige 2xx em 15s).
    """
    import threading
    from app.workers.tasks import _processar_recall

    body = request.get_json(silent=True) or {}
    event = body.get("event", "")
    bot_id = (((body.get("data") or {}).get("bot")) or {}).get("id")

    if event == "bot.done" and bot_id:
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
    Só funciona depois que o bot terminou (status Recall 'done').
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
        return jsonify({"erro": "reunião sem bot Recall"}), 400

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
