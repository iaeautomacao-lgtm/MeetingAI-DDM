"""
Autenticacao por sessao para o painel, com auto-cadastro e aprovacao do admin.

Login exige ativo=1 e aprovado=1.
Senha-mestre (DIRECTOR_PASSWORD) = acesso de emergencia do diretor/admin.
"""
# Anotacoes adiadas: "X | None" (PEP 604) so avalia em runtime a partir
# do Python 3.10, e o interpretador do cPanel e mais antigo. Sem isso o
# app quebra no import em producao.
from __future__ import annotations


import hmac
import os
import uuid
from functools import wraps

from flask import jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import get_mysql_connection


_TEM_COLUNA_IS_GESTOR = None
_TEM_COLUNA_PERFIL_SOLICITADO = None
_TEM_COLUNA_SETORES = None


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


def _tem_coluna_is_gestor() -> bool:
    global _TEM_COLUNA_IS_GESTOR

    if _TEM_COLUNA_IS_GESTOR is not None:
        return _TEM_COLUNA_IS_GESTOR

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()
        cursor.execute("SHOW COLUMNS FROM painel_acessos LIKE 'is_gestor'")
        _TEM_COLUNA_IS_GESTOR = cursor.fetchone() is not None
    except Exception:
        _TEM_COLUNA_IS_GESTOR = False
    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return _TEM_COLUNA_IS_GESTOR


def _tem_coluna_perfil_solicitado() -> bool:
    global _TEM_COLUNA_PERFIL_SOLICITADO

    if _TEM_COLUNA_PERFIL_SOLICITADO is not None:
        return _TEM_COLUNA_PERFIL_SOLICITADO

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()
        cursor.execute("SHOW COLUMNS FROM painel_acessos LIKE 'perfil_solicitado'")
        _TEM_COLUNA_PERFIL_SOLICITADO = cursor.fetchone() is not None
    except Exception:
        _TEM_COLUNA_PERFIL_SOLICITADO = False
    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return _TEM_COLUNA_PERFIL_SOLICITADO


def _tem_coluna_setores() -> bool:
    global _TEM_COLUNA_SETORES

    if _TEM_COLUNA_SETORES is not None:
        return _TEM_COLUNA_SETORES

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()
        cursor.execute("SHOW COLUMNS FROM painel_acessos LIKE 'setores'")
        _TEM_COLUNA_SETORES = cursor.fetchone() is not None
    except Exception:
        _TEM_COLUNA_SETORES = False
    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

    return _TEM_COLUNA_SETORES


def _normalizar_setores(setores) -> list[str]:
    if setores is None:
        return []

    if isinstance(setores, str):
        raw = setores.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                import json

                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    setores = parsed
                else:
                    setores = [raw]
            except Exception:
                setores = raw.split(",")
        else:
            setores = raw.split(",")

    if not isinstance(setores, (list, tuple, set)):
        setores = [setores]

    normalizados = []
    vistos = set()
    for setor in setores:
        setor = " ".join(str(setor or "").strip().split())
        chave = setor.lower()
        if setor and chave not in vistos:
            vistos.add(chave)
            normalizados.append(setor)

    return normalizados


def _setores_do_acesso(acesso: dict | None) -> list[str]:
    if not acesso:
        return []

    setores = _normalizar_setores(acesso.get("setores"))
    principal = (acesso.get("setor") or "").strip()
    if principal:
        setores = [principal] + setores

    return _normalizar_setores(setores)


def _normalizar_perfil_solicitado(perfil: str) -> str:
    perfil = (perfil or "usuario").strip().lower()
    if perfil in {"usuario", "gestor", "diretor"}:
        return perfil
    return "usuario"


def _buscar_acesso(email: str) -> dict | None:
    email = (email or "").strip().lower()

    if not email:
        return None

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)
        gestor_sql = "is_gestor" if _tem_coluna_is_gestor() else "0 AS is_gestor"
        perfil_sql = (
            "perfil_solicitado"
            if _tem_coluna_perfil_solicitado()
            else "'usuario' AS perfil_solicitado"
        )
        setores_sql = (
            "setores"
            if _tem_coluna_setores()
            else "NULL AS setores"
        )
        cursor.execute(
            f"""
            SELECT
                email,
                nome,
                setor,
                {setores_sql},
                senha_hash,
                ativo,
                aprovado,
                is_admin,
                {gestor_sql},
                {perfil_sql}
            FROM painel_acessos
            WHERE email = %s
            LIMIT 1
            """,
            (email,),
        )

        acesso = cursor.fetchone()
        if acesso:
            acesso["setores"] = _setores_do_acesso(acesso)
        return acesso

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
    if _tem_coluna_is_gestor():
        campos_permitidos.add("is_gestor")
    if _tem_coluna_perfil_solicitado():
        campos_permitidos.add("perfil_solicitado")
    if _tem_coluna_setores():
        campos_permitidos.add("setores")

    campos_validos = {
        chave: valor
        for chave, valor in campos.items()
        if chave in campos_permitidos
    }

    if "setores" in campos_validos:
        import json

        campos_validos["setores"] = json.dumps(
            _normalizar_setores(campos_validos["setores"]),
            ensure_ascii=False,
        )

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
    perfil_solicitado: str = "usuario",
) -> tuple[bool, str]:
    email = (email or "").strip().lower()
    setor = (setor or "").strip()
    setores = _normalizar_setores([setor])
    perfil_solicitado = _normalizar_perfil_solicitado(perfil_solicitado)

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
                "setores": setores,
                "perfil_solicitado": perfil_solicitado,
            },
        )

        return True, "pendente"

    connection = None
    cursor = None

    try:
        connection = get_mysql_connection()
        cursor = connection.cursor()
        tem_is_gestor = _tem_coluna_is_gestor()
        tem_perfil_solicitado = _tem_coluna_perfil_solicitado()
        tem_setores = _tem_coluna_setores()
        is_gestor_sql = ", is_gestor" if tem_is_gestor else ""
        is_gestor_placeholder = ", %s" if tem_is_gestor else ""
        perfil_sql = ", perfil_solicitado" if tem_perfil_solicitado else ""
        perfil_placeholder = ", %s" if tem_perfil_solicitado else ""
        setores_sql = ", setores" if tem_setores else ""
        setores_placeholder = ", %s" if tem_setores else ""
        valores = [
            str(uuid.uuid4()),
            email,
            nome or "",
            setor,
            _hash(senha),
            1,
            0,
            0,
        ]
        if tem_is_gestor:
            valores.append(0)
        if tem_perfil_solicitado:
            valores.append(perfil_solicitado)
        if tem_setores:
            import json

            valores.append(json.dumps(setores, ensure_ascii=False))

        cursor.execute(
            f"""
            INSERT INTO painel_acessos (
                id,
                email,
                nome,
                setor,
                senha_hash,
                ativo,
                aprovado,
                is_admin
                {is_gestor_sql}
                {perfil_sql}
                {setores_sql}
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s{is_gestor_placeholder}{perfil_placeholder}{setores_placeholder})
            """,
            valores,
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
        gestor_sql = "is_gestor" if _tem_coluna_is_gestor() else "0 AS is_gestor"
        perfil_sql = (
            "perfil_solicitado"
            if _tem_coluna_perfil_solicitado()
            else "'usuario' AS perfil_solicitado"
        )
        setores_sql = (
            "setores"
            if _tem_coluna_setores()
            else "NULL AS setores"
        )

        cursor.execute(
            f"""
            SELECT
                email,
                nome,
                setor,
                {setores_sql},
                ativo,
                aprovado,
                is_admin,
                {gestor_sql},
                {perfil_sql},
                criado_em
            FROM painel_acessos
            ORDER BY criado_em DESC
            """
        )

        acessos = cursor.fetchall()
        for acesso in acessos:
            acesso["setores"] = _setores_do_acesso(acesso)
        return acessos

    except Exception:
        return []

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()


def aprovar_acesso(email: str) -> bool:
    acesso = _buscar_acesso(email)
    if not acesso:
        return False

    perfil = _normalizar_perfil_solicitado(acesso.get("perfil_solicitado"))
    campos = {"aprovado": 1, "ativo": 1}

    if perfil == "diretor":
        campos.update({"is_admin": 1, "is_gestor": 0})
    elif perfil == "gestor":
        campos.update({"is_admin": 0, "is_gestor": 1})
    else:
        campos.update({"is_admin": 0, "is_gestor": 0})

    _update(email, campos)
    return True


def definir_setor(email: str, setor: str, setores=None) -> bool:
    if not _buscar_acesso(email):
        return False

    todos_setores = _normalizar_setores(setores)
    setor = (setor or "").strip()
    if setor:
        todos_setores = _normalizar_setores([setor] + todos_setores)
    elif todos_setores:
        setor = todos_setores[0]

    _update(email, {"setor": setor, "setores": todos_setores})
    return True


def definir_admin(email: str, virar_admin: bool) -> bool:
    email = (email or "").strip().lower()
    if not _buscar_acesso(email):
        return False
    _update(email, {"is_admin": 1 if virar_admin else 0})
    return True


def definir_gestor(email: str, virar_gestor: bool) -> bool:
    email = (email or "").strip().lower()
    if not _tem_coluna_is_gestor():
        return False
    if not _buscar_acesso(email):
        return False
    _update(email, {"is_gestor": 1 if virar_gestor else 0})
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


def is_gestor_setor() -> bool:
    return bool(session.get("gestor_setor"))


def login_session(email: str = "", admin: bool = False, setor: str = "") -> None:
    session["diretor"] = True
    email = (email or "").strip().lower()
    session["email"] = email

    acesso = _buscar_acesso(email) if email else None
    setores = _setores_do_acesso(acesso) or _normalizar_setores([setor])
    setor = setores[0] if setores else (setor or "").strip()
    session["setor"] = setor
    session["setores"] = setores

    is_adm = bool(admin) or (email in _admin_emails())
    if not is_adm and email:
        is_adm = bool(acesso and acesso.get("is_admin"))

    is_gestor = bool(acesso and acesso.get("is_gestor"))

    session["admin"] = is_adm
    session["gestor_setor"] = (not is_adm) and is_gestor
    session["acesso_total"] = (
        is_adm
        or any(setor_diretoria(item) for item in setores)
        or (not email)
    )
    session.permanent = True


def logout_session() -> None:
    for key in ("diretor", "email", "admin", "gestor_setor", "setor", "setores", "acesso_total"):
        session.pop(key, None)


def sessao_email() -> str:
    return session.get("email", "") or ""


def sessao_setor() -> str:
    return session.get("setor", "") or ""


def sessao_setores() -> list[str]:
    return _normalizar_setores(session.get("setores") or [sessao_setor()])


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
