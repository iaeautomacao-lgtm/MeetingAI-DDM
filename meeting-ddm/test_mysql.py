import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

print("Tentando conectar...")

try:
    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT")),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        connection_timeout=10,
    )

    cursor = conn.cursor()
    cursor.execute("SELECT VERSION(), DATABASE();")

    version, database = cursor.fetchone()

    print("=" * 60)
    print("✅ CONEXÃO REALIZADA COM SUCESSO")
    print(f"Banco: {database}")
    print(f"Versão: {version}")
    print("=" * 60)

    cursor.close()
    conn.close()

except Exception as e:
    print("=" * 60)
    print("❌ ERRO")
    print(type(e).__name__)
    print(e)
    print("=" * 60)