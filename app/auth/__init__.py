"""
Autenticação por sessão para o painel.
- Tela pública (registrar reunião) NÃO exige login.
- Dashboard e endpoints de dados exigem sessão autenticada.

Dois modos de login:
  1. E-mail + senha própria — allowlist na tabela `painel_acessos` (Supabase).
     Só e-mail presente e ativo=true entra; senha guardada como hash.
  2. Senha-mestre (DIRECTOR_PASSWORD no .env) — login de emergência do diretor.
     Se DIRECTOR_PASSWORD vazia, o modo mestre fica desabilitado.
"""

import hmac
import os
from functools import wraps

from flask import session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import get_supabase


# ── Consultas à allowlist ─────────────────────────────────────────────────────

def _buscar_acesso(email: str) -> dict | None:
    """Retorna a linha de painel_acessos por e-mail (case-insensitive) ou None."""
    email = (email or "").strip().lower()
    if not email:
        return None
    try:
        db = get_supabase()
        resp = (
            db.table("painel_acessos")
            .select("email,nome,senha_hash,ativo")
            .eq("email", email)
            .limit(1)
            .execute()
        )
    except Exception:
        # tabela ausente ou falha de conexão → trata como não-permitido (nunca 500 no login)
        return None
    dados = resp.data or []
    return dados[0] if dados else None


def email_permitido(email: str) -> bool:
    acesso = _buscar_acesso(email)
    return bool(acesso and acesso.get("ativo"))


# ── Master password (fallback diretor) ────────────────────────────────────────

def check_master_password(pw: str) -> bool:
    """Compara com DIRECTOR_PASSWORD em tempo constante. Vazia = desabilitado."""
    esperada = os.getenv("DIRECTOR_PASSWORD", "").strip()
    if not esperada:
        return False
    return hmac.compare_digest(str(pw or ""), esperada)


# retrocompat: rotas antigas ainda importam check_password
check_password = check_master_password


# ── Login por e-mail + senha ──────────────────────────────────────────────────

def verificar_login(email: str, senha: str) -> dict | None:
    """
    Valida e-mail (allowlist) + senha (hash). Retorna a linha do acesso em sucesso,
    ou None. Se o e-mail é permitido mas ainda não tem senha, retorna None
    (o front deve mandar o usuário para o fluxo de 1º acesso).
    """
    acesso = _buscar_acesso(email)
    if not acesso or not acesso.get("ativo"):
        return None
    senha_hash = acesso.get("senha_hash")
    if not senha_hash:
        return None
    if not check_password_hash(senha_hash, str(senha or "")):
        return None
    return acesso


def precisa_definir_senha(email: str) -> bool:
    """True se o e-mail é permitido, ativo, e ainda não tem senha definida."""
    acesso = _buscar_acesso(email)
    return bool(acesso and acesso.get("ativo") and not acesso.get("senha_hash"))


def definir_senha(email: str, senha: str) -> bool:
    """
    Define a senha no 1º acesso. Só funciona se o e-mail é permitido, ativo,
    e ainda NÃO tem senha (evita reset por terceiros). Retorna True em sucesso.
    """
    email_norm = (email or "").strip().lower()
    if not precisa_definir_senha(email_norm):
        return False
    if len(str(senha or "")) < 6:
        return False
    db = get_supabase()
    db.table("painel_acessos").update(
        {"senha_hash": generate_password_hash(str(senha))}
    ).eq("email", email_norm).execute()
    return True


# ── Sessão ────────────────────────────────────────────────────────────────────

def is_authed() -> bool:
    return bool(session.get("diretor"))


def login_session(email: str = "") -> None:
    session["diretor"] = True
    session["email"] = (email or "").strip().lower()
    session.permanent = True


def logout_session() -> None:
    session.pop("diretor", None)
    session.pop("email", None)


def sessao_email() -> str:
    return session.get("email", "") or ""


def require_auth(fn):
    """Decorator p/ endpoints de API que só usuários autenticados acessam."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_authed():
            return jsonify({"erro": "não autenticado"}), 401
        return fn(*args, **kwargs)
    return wrapper
