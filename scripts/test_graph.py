"""
Teste isolado da credencial Microsoft Graph (app-only).
Uso:
    1. Preencha .env com AZURE_CLIENT_ID / AZURE_CLIENT_SECRET / AZURE_TENANT_ID / TEAMS_DOMAIN
    2. python scripts/test_graph.py

Valida, em ordem:
    [1] Aquisição de token (client credentials)
    [2] Listagem de usuários do domínio (permissão User.Read.All)
    [3] (opcional) Reuniões do 1º usuário nas últimas 24h
"""

import os
import sys
from datetime import datetime, timedelta, timezone

# permite rodar da raiz do projeto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

OK = "[OK]"
FAIL = "[X]"


def check_env():
    faltando = [
        k for k in ("AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID")
        if not os.getenv(k)
    ]
    if faltando:
        print(f"{FAIL} .env incompleto — faltam: {', '.join(faltando)}")
        sys.exit(1)
    print(f"{OK} .env carregado")


def test_token():
    from app.pipeline.graph import _get_token
    try:
        token = _get_token()
        print(f"{OK} [1] Token obtido ({len(token)} chars)")
        return True
    except Exception as e:
        print(f"{FAIL} [1] Falha ao obter token: {e}")
        print("    → Verifique client id/secret/tenant e se o secret não expirou.")
        return False


def test_users():
    from app.pipeline.graph import get_users
    domain = os.getenv("TEAMS_DOMAIN", "grupoddm.com.br")
    try:
        users = get_users(domain)
        print(f"{OK} [2] Usuários retornados: {len(users)}")
        for u in users[:5]:
            print(f"       - {u.get('displayName','?')} <{u.get('mail','?')}> [{u.get('department','')}]")
        return users
    except Exception as e:
        print(f"{FAIL} [2] Falha ao listar usuários: {e}")
        print("    → Confirme permissão User.Read.All + consentimento de admin.")
        return []


def test_meetings(users):
    if not users:
        print("    [3] pulado (sem usuários).")
        return
    from app.pipeline.graph import get_meetings
    uid = users[0]["id"]
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        meetings = get_meetings(uid, since)
        print(f"{OK} [3] Reuniões (24h) p/ {users[0].get('displayName','?')}: {len(meetings)}")
        if not meetings:
            print("    ⚠ 0 reuniões — pode ser normal (sem reunião) OU limitação do Graph.")
    except Exception as e:
        print(f"{FAIL} [3] Falha ao listar reuniões: {e}")
        print("    → Confirme Application Access Policy (Grant-CsApplicationAccessPolicy).")


if __name__ == "__main__":
    print("── Teste Microsoft Graph (app-only) ──")
    check_env()
    if test_token():
        users = test_users()
        test_meetings(users)
    print("── Fim ──")
