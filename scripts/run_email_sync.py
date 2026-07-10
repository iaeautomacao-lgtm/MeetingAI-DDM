"""
Runner manual do pipeline de e-mail (sem Celery/Redis).
Puxa e-mails via IMAP → grava no Supabase → analisa com IA → atualiza grafo.

Uso:
    python scripts/run_email_sync.py [dias] [limite]
    python scripts/run_email_sync.py 2 10
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.extensions import get_supabase
from app.pipeline.imap_client import get_emails_imap
from app.pipeline.analysis import extrair_email


def main(dias: int, limite: int):
    db = get_supabase()
    since = datetime.now(timezone.utc) - timedelta(days=dias)
    setor_remetente = os.getenv("IMAP_USER", "").split("@")[0]

    print(f"Buscando e-mails dos ultimos {dias} dias (limite {limite})...")
    emails = get_emails_imap(since, limite=limite)
    print(f"IMAP retornou {len(emails)} e-mails.\n")

    novos, analisados = 0, 0
    for mail in emails:
        msg_id = mail.get("message_id")
        if not msg_id:
            continue

        exists = db.table("emails").select("id").eq("message_id", msg_id).execute()
        if exists.data:
            continue

        row = db.table("emails").insert({
            "message_id": msg_id,
            "de_email": mail.get("de_email", ""),
            "de_nome": mail.get("de_nome", ""),
            "para": mail.get("para", []),
            "assunto": mail.get("assunto", ""),
            "setor_remetente": setor_remetente,
            "data": mail.get("data"),
            "thread_id": mail.get("thread_id", ""),
            "plataforma": "imap",
            "status": "pending",
        }).execute()
        novos += 1
        email_id = row.data[0]["id"]

        # análise + classificação IA (com filtro rápido embutido)
        analise = extrair_email(mail.get("assunto", ""), mail.get("corpo", ""), mail.get("de_email", ""))
        db.table("emails").update({
            "status": "completed",
            "resumo": analise.get("resumo", ""),
            "temas": analise.get("temas", []),
            "sentimento": analise.get("sentimento", "neutro"),
            "categoria": analise.get("categoria", "corporativo"),
            "relevante": analise.get("relevante", True),
        }).eq("id", email_id).execute()
        analisados += 1

        # grafo de interações
        for dest in mail.get("para", []):
            de = mail.get("de_email", "")
            para = dest.get("email", "")
            if not (de and para):
                continue
            for tema in analise.get("temas", []):
                db.table("interacoes").upsert({
                    "pessoa_a": de,
                    "pessoa_b": para,
                    "tema": tema,
                    "contagem": 1,
                    "ultima_interacao": datetime.now(timezone.utc).isoformat(),
                }, on_conflict="pessoa_a,pessoa_b,tema").execute()

        print(f"  [OK] {mail.get('assunto','')[:55]} | {analise.get('sentimento','?')}")

    print(f"\nResumo: {novos} novos, {analisados} analisados.")


if __name__ == "__main__":
    dias = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    limite = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    main(dias, limite)
