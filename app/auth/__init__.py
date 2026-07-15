"""
Autenticação por sessão para o painel — com auto-cadastro + aprovação do admin.

Fluxo:
  1. Pessoa com e-mail de domínio da empresa se cadastra (e-mail + senha).
     → cria conta PENDENTE (aprovado=false). NÃO loga ainda.
  2. Admin (ADMIN_EMAILS) vê o pedido na aba "Acessos" do painel e aprova/rejeita.
  3. Só depois de aprovado a pessoa consegue logar.

Login exige ativo=true E aprovado=true.
Senha-mestre (DIRECTOR_PASSWORD) = acesso de emergência do diretor (admin).
"""

import hmac
import os
from functools import wraps

from flask import session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import get_supabase


def _hash(senha: str) -> str:
    # pbkdf2 é suportado em qualquer runtime (o scrypt padrão do Werkzeug
    # falha no Python serverless da Vercel — OpenSSL sem scrypt → 500).
    return generate_password_hash(str(senha), method="pbkdf2:sha256")


# ── Domínios / admin ──────────────────────────────────────────────────────────

def _corp_domains() -> list[str]:
    raw = os.getenv("CORP_DOMAINS", "ddm.adv.br,grupoddm.com.br")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def dominio_permitido(email: str) -> bool:
    email = (email or "").strip().lower()
    return "@" in email and email.split("@", 1)[1] in _corp_domains()


def _admin_emails() -> list[str]:
    raw = os.getenv("ADMIN_EMAILS", "gisele.oliveira@ddm.adv.br,dimaio@ddm.adv.br")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


# Setores com acesso total (veem todos os setores e todas as reuniões).
def _setores_diretoria() -> list[str]:
    raw = os.getenv("DIRECTOR_SECTORS", "Diretores,Diretoria")
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def setor_diretoria(setor: str) -> bool:
    return (setor or "").strip().lower() in _setores_diretoria()


# ── Consultas ─────────────────────────────────────────────────────────────────

def _buscar_acesso(email: str) -> dict | None:
    email = (email or "").strip().lower()
    if not email:
        return None
    try:
        db = get_supabase()
        resp = (
            db.table("painel_acessos")
            .select("email,nome,setor,senha_hash,ativo,aprovado")
            .eq("email", email)
            .limit(1)
            .execute()
        )
    except Exception:
        # tabela ausente ou falha de conexão → trata como não-permitido (nunca 500 no login)
        return None
    dados = resp.data or []
    return dados[0] if dados else None


# ── Master password (fallback diretor) ────────────────────────────────────────

def check_master_password(pw: str) -> bool:
    """Compara com DIRECTOR_PASSWORD em tempo constante. Vazia = desabilitado."""
    esperada = os.getenv("DIRECTOR_PASSWORD", "").strip()
    if not esperada:
        return False
    return hmac.compare_digest(str(pw or ""), esperada)


# retrocompat
check_password = check_master_password


# ── Cadastro (self-service, cria pendente) ────────────────────────────────────

def registrar_acesso(email: str, senha: str, nome: str = "", setor: str = "") -> tuple[bool, str]:
    """
    Cria (ou completa) um pedido de acesso PENDENTE.
    Retorna (ok, motivo). Não loga — precisa de aprovação do admin.
    O setor é escolhido no cadastro e fica travado (só admin muda depois).
    """
    email = (email or "").strip().lower()
    setor = (setor or "").strip()
    if not dominio_permitido(email):
        return False, "dominio_nao_permitido"
    if len(str(senha or "")) < 6:
        return False, "senha_curta"
    if not setor:
        return False, "setor_obrigatorio"

    acesso = _buscar_acesso(email)
    if acesso:
        if acesso.get("aprovado"):
            return False, "ja_cadastrado"
        # pendente: atualiza senha/nome/setor e segue aguardando
        _update(email, {
            "senha_hash": _hash(senha),
            "nome": nome or acesso.get("nome", ""),
            "setor": setor or acesso.get("setor", ""),
        })
        return True, "pendente"

    db = get_supabase()
    db.table("painel_acessos").insert({
        "email": email,
        "nome": nome or "",
        "setor": setor,
        "senha_hash": _hash(senha),
        "ativo": True,
        "aprovado": False,
    }).execute()
    return True, "pendente"


def _update(email: str, campos: dict) -> None:
    db = get_supabase()
    db.table("painel_acessos").update(campos).eq("email", (email or "").strip().lower()).execute()


# ── Login ─────────────────────────────────────────────────────────────────────

def verificar_login(email: str, senha: str) -> dict | None:
    """Valida e-mail + senha + ativo + aprovado. Retorna a linha ou None."""
    acesso = _buscar_acesso(email)
    if not acesso or not acesso.get("ativo") or not acesso.get("aprovado"):
        return None
    senha_hash = acesso.get("senha_hash")
    if not senha_hash or not check_password_hash(senha_hash, str(senha or "")):
        return None
    return acesso


def status_cadastro(email: str, senha: str) -> str | None:
    """
    Para dar mensagem correta quando o login falha:
    'pendente' se a senha bate mas ainda não foi aprovado; senão None.
    """
    acesso = _buscar_acesso(email)
    if not acesso:
        return None
    senha_hash = acesso.get("senha_hash")
    if senha_hash and check_password_hash(senha_hash, str(senha or "")) and not acesso.get("aprovado"):
        return "pendente"
    return None


# ── Ações de admin ────────────────────────────────────────────────────────────

def listar_acessos() -> list[dict]:
    try:
        db = get_supabase()
        resp = (
            db.table("painel_acessos")
            .select("email,nome,setor,ativo,aprovado,criado_em")
            .order("criado_em", desc=True)
            .execute()
        )
        return resp.data or []
    except Exception:
        return []


def aprovar_acesso(email: str) -> bool:
    if not _buscar_acesso(email):
        return False
    _update(email, {"aprovado": True, "ativo": True})
    return True


def definir_setor(email: str, setor: str) -> bool:
    """Admin troca o setor de um acesso (usuário comum não pode)."""
    if not _buscar_acesso(email):
        return False
    _update(email, {"setor": (setor or "").strip()})
    return True


def atualizar_nome(email: str, nome: str) -> bool:
    """Usuário atualiza o próprio nome."""
    email = (email or "").strip().lower()
    if not email or not _buscar_acesso(email):
        return False
    _update(email, {"nome": (nome or "").strip()})
    return True


def alterar_senha(email: str, senha_atual: str, senha_nova: str) -> tuple[bool, str]:
    """Troca a senha do próprio usuário. Exige a senha atual correta."""
    email = (email or "").strip().lower()
    acesso = _buscar_acesso(email)
    if not acesso:
        return False, "nao_encontrado"
    if len(str(senha_nova or "")) < 6:
        return False, "senha_curta"
    atual_hash = acesso.get("senha_hash")
    if not atual_hash or not check_password_hash(atual_hash, str(senha_atual or "")):
        return False, "senha_atual_incorreta"
    _update(email, {"senha_hash": _hash(senha_nova)})
    return True, "ok"


def rejeitar_acesso(email: str) -> bool:
    """Remove o pedido (rejeita). Não deixa órfão."""
    email = (email or "").strip().lower()
    if not _buscar_acesso(email):
        return False
    db = get_supabase()
    db.table("painel_acessos").delete().eq("email", email).execute()
    return True


# ── Sessão ────────────────────────────────────────────────────────────────────

def is_authed() -> bool:
    return bool(session.get("diretor"))


def is_admin() -> bool:
    return bool(session.get("admin"))


def login_session(email: str = "", admin: bool = False, setor: str = "") -> None:
    session["diretor"] = True
    email = (email or "").strip().lower()
    session["email"] = email
    session["setor"] = (setor or "").strip()
    is_adm = bool(admin) or (email in _admin_emails())
    session["admin"] = is_adm
    # Acesso total = admin OU setor de diretoria OU login-mestre (sem e-mail).
    session["acesso_total"] = is_adm or setor_diretoria(setor) or (not email)
    session.permanent = True


def logout_session() -> None:
    for k in ("diretor", "email", "admin", "setor", "acesso_total"):
        session.pop(k, None)


def sessao_email() -> str:
    return session.get("email", "") or ""


def sessao_setor() -> str:
    return session.get("setor", "") or ""


def tem_acesso_total() -> bool:
    return bool(session.get("acesso_total"))


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_authed():
            return jsonify({"erro": "não autenticado"}), 401
        return fn(*args, **kwargs)
    return wrapper


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_authed():
            return jsonify({"erro": "não autenticado"}), 401
        if not is_admin():
            return jsonify({"erro": "acesso restrito ao administrador"}), 403
        return fn(*args, **kwargs)
    return wrapper
