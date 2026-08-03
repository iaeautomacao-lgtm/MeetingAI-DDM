import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

print("Tentando conectar ao PostgreSQL...")

try:
    conn = psycopg.connect(
        host=os.getenv("PG_HOST"),
        port=os.getenv("PG_PORT"),
        dbname=os.getenv("PG_DATABASE"),
        user=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD"),
        sslmode=os.getenv("PG_SSLMODE"),
    )

    cur = conn.cursor()

    cur.execute("SELECT current_database(), version();")

    db, version = cur.fetchone()

    print("=" * 60)
    print("✅ CONECTADO AO POSTGRESQL")
    print("Banco:", db)
    print("Versão:", version)
    print("=" * 60)

    cur.close()
    conn.close()

except Exception as e:
    print("=" * 60)
    print("❌ ERRO")
    print(type(e).__name__)
    print(e)
    print("=" * 60)