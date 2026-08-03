"""
Autenticacao por sessao para o painel, com auto-cadastro e aprovacao do admin.

Login exige ativo=1 e aprovado=1.
Senha-mestre (DIRECTOR_PASSWORD) = acesso de emergencia do diretor/admin.
"""

import hmac
import os
from functools import wraps

from flask import jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import get_mysql_connection


def _hash(senha: str) -> str:
    return generate_password_hash(str(senha), method="pbkdf2:sha256")


def _corp_domains() -> list[str]:
    raw = os.getenv("CORP_DOMAINS", "ddm.adv.br,grupoddm.com.br")
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def dominio_permitido(email: str) -> bool:
    email = (email or "").strip().lower()
    return "@" in email and email.split("@", 1)[1] in _corp_domains()


def _admin_emails() -> list[str]:
    raw = os.getenv(
        "ADMIN_EMAILS",
        "gisele.oliveira@ddm.adv.br,dimaio@ddm.adv.br,joao.dimaio@ddm.adv.br",
    )
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def _setores_diretoria() -> list[str]:
    raw = os.getenv("DIRECTOR_SECTORS", "Diretores,Diretoria")
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def setor_diretoria(setor: str) -> bool:
    return (setor or "").strip().lower() in _setores_diretoria()


def _buscar_acesso(email: str) -> dict | None:
    email = (email or "").strip().lower()

    if not email:
        return None

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                email,
                nome,
                setor,
                senha_hash,
                ativo,
                aprovado,
                is_admin
            FROM painel_acessos
            WHERE email = %s
            LIMIT 1
            """,
            (email,),
        )

        return cursor.fetchone()

    except Exception:
        return None

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


def _update(email: str, campos: dict) -> None:
    email = (email or "").strip().lower()

    if not email or not campos:
        return

    campos_permitidos = {
        "nome",
        "setor",
        "senha_hash",
        "ativo",
        "aprovado",
        "is_admin",
    }

    campos_validos = {
        chave: valor
        for chave, valor in campos.items()
        if chave in campos_permitidos
    }

    if not campos_validos:
        return

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()

        set_sql = ", ".join(
            f"{campo} = %s"
            for campo in campos_validos
        )

        valores = list(campos_validos.values())
        valores.append(email)

        cursor.execute(
            f"""
            UPDATE painel_acessos
            SET {set_sql}
            WHERE email = %s
            """,
            valores,
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


def check_master_password(pw: str) -> bool:
    esperada = os.getenv("DIRECTOR_PASSWORD", "").strip()
    if not esperada:
        return False
    return hmac.compare_digest(str(pw or ""), esperada)


check_password = check_master_password


def registrar_acesso(
    email: str,
    senha: str,
    nome: str = "",
    setor: str = "",
) -> tuple[bool, str]:
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

        _update(
            email,
            {
                "senha_hash": _hash(senha),
                "nome": nome or acesso.get("nome", ""),
                "setor": setor or acesso.get("setor", ""),
            },
        )

        return True, "pendente"

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO painel_acessos (
                email,
                nome,
                setor,
                senha_hash,
                ativo,
                aprovado,
                is_admin
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                email,
                nome or "",
                setor,
                _hash(senha),
                1,
                0,
                0,
            ),
        )

        connection.commit()

        return True, "pendente"

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


def verificar_login(email: str, senha: str) -> dict | None:
    acesso = _buscar_acesso(email)
    if not acesso or not acesso.get("ativo") or not acesso.get("aprovado"):
        return None

    senha_hash = acesso.get("senha_hash")
    if not senha_hash or not check_password_hash(senha_hash, str(senha or "")):
        return None

    return acesso


def status_cadastro(email: str, senha: str) -> str | None:
    acesso = _buscar_acesso(email)
    if not acesso:
        return None

    senha_hash = acesso.get("senha_hash")
    if (
        senha_hash
        and check_password_hash(senha_hash, str(senha or ""))
        and not acesso.get("aprovado")
    ):
        return "pendente"

    return None


def listar_acessos() -> list[dict]:
    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                email,
                nome,
                setor,
                ativo,
                aprovado,
                is_admin,
                criado_em
            FROM painel_acessos
            ORDER BY criado_em DESC
            """
        )

        return cursor.fetchall()

    except Exception:
        return []

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


def aprovar_acesso(email: str) -> bool:
    if not _buscar_acesso(email):
        return False
    _update(email, {"aprovado": 1, "ativo": 1})
    return True


def definir_setor(email: str, setor: str) -> bool:
    if not _buscar_acesso(email):
        return False
    _update(email, {"setor": (setor or "").strip()})
    return True


def definir_admin(email: str, virar_admin: bool) -> bool:
    email = (email or "").strip().lower()
    if not _buscar_acesso(email):
        return False
    _update(email, {"is_admin": 1 if virar_admin else 0})
    return True


def eh_admin(email: str) -> bool:
    email = (email or "").strip().lower()
    if email in _admin_emails():
        return True
    acesso = _buscar_acesso(email)
    return bool(acesso and acesso.get("is_admin"))


def atualizar_nome(email: str, nome: str) -> bool:
    email = (email or "").strip().lower()
    if not email or not _buscar_acesso(email):
        return False
    _update(email, {"nome": (nome or "").strip()})
    return True


def alterar_senha(
    email: str,
    senha_atual: str,
    senha_nova: str,
) -> tuple[bool, str]:
    email = (email or "").strip().lower()
    acesso = _buscar_acesso(email)

    if not acesso:
        return False, "nao_encontrado"

    if len(str(senha_nova or "")) < 6:
        return False, "senha_curta"

    atual_hash = acesso.get("senha_hash")
    if not atual_hash or not check_password_hash(
        atual_hash,
        str(senha_atual or ""),
    ):
        return False, "senha_atual_incorreta"

    _update(email, {"senha_hash": _hash(senha_nova)})
    return True, "ok"


def rejeitar_acesso(email: str) -> bool:
    email = (email or "").strip().lower()

    if not _buscar_acesso(email):
        return False

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            DELETE FROM painel_acessos
            WHERE email = %s
            """,
            (email,),
        )

        connection.commit()

        return cursor.rowcount > 0

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


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
    if not is_adm and email:
        acesso = _buscar_acesso(email)
        is_adm = bool(acesso and acesso.get("is_admin"))

    session["admin"] = is_adm
    session["acesso_total"] = is_adm or setor_diretoria(setor) or (not email)
    session.permanent = True


def logout_session() -> None:
    for key in ("diretor", "email", "admin", "setor", "acesso_total"):
        session.pop(key, None)


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
            return jsonify({"erro": "nao autenticado"}), 401
        return fn(*args, **kwargs)

    return wrapper


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_authed():
            return jsonify({"erro": "nao autenticado"}), 401
        if not is_admin():
            return jsonify({"erro": "acesso restrito ao administrador"}), 403
        return fn(*args, **kwargs)

    return wrapper
