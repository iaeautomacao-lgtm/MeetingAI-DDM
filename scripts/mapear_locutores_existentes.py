"""
Aplica o mapeamento de locutores nas reuniões que já estão no banco com
"Speaker N" na transcrição.

Reprocessa só a identificação — não refaz resumo, decisões nem pendências.
Depende da gravação ainda existir no Skribby (é de lá que vêm os nomes reais).

Uso:
    python scripts/mapear_locutores_existentes.py            # simula, não grava
    python scripts/mapear_locutores_existentes.py --aplicar  # grava no banco
    python scripts/mapear_locutores_existentes.py --aplicar --id <reuniao_id>
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(override=True)

from app import create_app
from app.extensions import get_mysql_connection
from app.pipeline.analysis import _participantes_de_utterances
from app.pipeline.locutores import (
    aplicar_mapa,
    mapear_com_ia,
    nomes_de_pessoas,
    rotulos_mapeaveis,
    speakers_genericos,
)
from app.pipeline.skribby_client import (
    extract_skribby_participants,
    get_bot,
)


def carregar(cursor, apenas_id=None):
    sql = """
        SELECT id, titulo, data, recall_bot_id, utterances, participantes
        FROM reunioes
        WHERE status = 'completed'
          AND recall_bot_id IS NOT NULL
          AND utterances IS NOT NULL
    """
    params = []

    if apenas_id:
        sql += " AND id = %s"
        params.append(apenas_id)

    sql += " ORDER BY data DESC"

    cursor.execute(sql, tuple(params))
    return cursor.fetchall()


def as_lista(valor):
    if isinstance(valor, list):
        return valor
    if isinstance(valor, (bytes, bytearray)):
        valor = valor.decode("utf-8", "replace")
    if isinstance(valor, str) and valor.strip():
        try:
            dados = json.loads(valor)
        except json.JSONDecodeError:
            return []
        return dados if isinstance(dados, list) else []
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true", help="grava no banco")
    ap.add_argument("--id", help="processa só uma reunião")
    args = ap.parse_args()

    app = create_app()

    with app.app_context():
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        reunioes = carregar(cursor, args.id)
        print(f"{len(reunioes)} reuniões concluídas com bot\n")

        for r in reunioes:
            utterances = as_lista(r["utterances"])
            genericos = speakers_genericos(utterances)
            titulo = (r["titulo"] or "")[:40]

            if not genericos:
                print(f"[ok      ] {titulo} — já tem nomes")
                continue

            try:
                bot = get_bot(r["recall_bot_id"])
                nomes = [
                    p["nome"]
                    for p in extract_skribby_participants(bot)
                    if p.get("nome")
                ]
            except Exception as exc:
                print(f"[skribby ] {titulo} — não deu para buscar: {exc}")
                continue

            if not nomes:
                print(f"[sem nome] {titulo} — Skribby não tem participantes")
                continue

            if not rotulos_mapeaveis(genericos, nomes_de_pessoas(nomes)):
                print(
                    f"[sem diariz] {titulo} — transcrição veio sem separação "
                    f"de vozes ({genericos}) e há {len(nomes)} participantes. "
                    "Não há o que mapear."
                )
                continue

            mapa = mapear_com_ia(utterances, nomes)

            if not mapa:
                print(
                    f"[sem pista] {titulo} — IA não identificou. "
                    f"Rótulos: {genericos} | Participantes: {nomes}"
                )
                continue

            print(f"[mapeado ] {titulo} — {mapa}")

            if not args.aplicar:
                continue

            novas = aplicar_mapa(utterances, mapa)
            participantes = _participantes_de_utterances(novas)

            if not participantes:
                participantes = as_lista(r["participantes"])

            grav = connection.cursor()
            grav.execute(
                """
                UPDATE reunioes
                SET utterances = %s, participantes = %s
                WHERE id = %s
                """,
                (
                    json.dumps(novas, ensure_ascii=False),
                    json.dumps(participantes, ensure_ascii=False),
                    r["id"],
                ),
            )
            connection.commit()
            grav.close()
            print("           gravado")

        cursor.close()
        connection.close()

    if not args.aplicar:
        print("\nSimulação. Rode com --aplicar para gravar.")


if __name__ == "__main__":
    main()
