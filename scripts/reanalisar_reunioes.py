"""
Reanalisa reuniões já gravadas com o prompt novo, gerando os blocos de insight
(recados, decisões tipadas, plano de ação, riscos, dúvidas em aberto, clima).

Trabalha sobre a transcrição guardada no banco — não depende do Skribby, então
funciona mesmo com a gravação já expirada. Não mexe em `utterances`: os nomes
dos locutores já corrigidos ficam como estão.

Uso:
    python scripts/reanalisar_reunioes.py                  # simula
    python scripts/reanalisar_reunioes.py --aplicar        # grava
    python scripts/reanalisar_reunioes.py --aplicar --desde 2026-08-01
    python scripts/reanalisar_reunioes.py --aplicar --id <reuniao_id>
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
from app.pipeline.analysis import extrair_reuniao


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
    ap.add_argument("--desde", help="só reuniões a partir desta data (AAAA-MM-DD)")
    args = ap.parse_args()

    app = create_app()

    with app.app_context():
        connection = get_mysql_connection()
        cursor = connection.cursor(dictionary=True)

        sql = """
            SELECT id, titulo, data, utterances, transcricao_full
            FROM reunioes
            WHERE status = 'completed'
              AND excluida_em IS NULL
              AND utterances IS NOT NULL
        """
        params = []

        if args.id:
            sql += " AND id = %s"
            params.append(args.id)

        if args.desde:
            sql += " AND data >= %s"
            params.append(args.desde)

        sql += " ORDER BY data DESC"

        cursor.execute(sql, tuple(params))
        reunioes = cursor.fetchall()

        print(f"{len(reunioes)} reuniões para reanalisar\n")

        ok = falha = 0

        for r in reunioes:
            titulo = (r["titulo"] or "")[:38]
            utterances = as_lista(r["utterances"])

            if not utterances:
                print(f"[sem transcr] {titulo}")
                continue

            texto = r["transcricao_full"] or " ".join(
                u.get("texto", "") for u in utterances
            )

            try:
                analise = extrair_reuniao(texto, utterances)
            except Exception as exc:
                print(f"[erro      ] {titulo} — {exc}")
                falha += 1
                continue

            resumo = "%d recado(s), %d decisão(ões), %d ação(ões), %d risco(s), %d dúvida(s), clima: %s" % (
                len(analise.get("key_takeaways") or []),
                len(analise.get("decisoes") or []),
                len(analise.get("pendencias") or []),
                len(analise.get("riscos") or []),
                len(analise.get("perguntas_abertas") or []),
                (analise.get("clima") or {}).get("tipo") or "—",
            )
            print(f"[analisado ] {titulo} — {resumo}")

            if not args.aplicar:
                continue

            grav = connection.cursor()
            grav.execute(
                """
                UPDATE reunioes
                SET resumo_executivo = %s,
                    key_takeaways = %s,
                    decisoes = %s,
                    pendencias = %s,
                    riscos = %s,
                    perguntas_abertas = %s,
                    clima = %s,
                    topicos = %s,
                    sentimento_geral = %s,
                    participantes = %s
                WHERE id = %s
                """,
                (
                    analise.get("resumo_executivo", ""),
                    json.dumps(analise.get("key_takeaways", []), ensure_ascii=False),
                    json.dumps(analise.get("decisoes", []), ensure_ascii=False),
                    json.dumps(analise.get("pendencias", []), ensure_ascii=False),
                    json.dumps(analise.get("riscos", []), ensure_ascii=False),
                    json.dumps(analise.get("perguntas_abertas", []), ensure_ascii=False),
                    json.dumps(analise.get("clima", {}), ensure_ascii=False),
                    json.dumps(analise.get("topicos", []), ensure_ascii=False),
                    analise.get("sentimento_geral", "neutro"),
                    json.dumps(analise.get("participantes_ativos", []), ensure_ascii=False),
                    r["id"],
                ),
            )
            connection.commit()
            grav.close()
            ok += 1

        cursor.close()
        connection.close()

    if args.aplicar:
        print(f"\ngravadas: {ok} | falhas: {falha}")
    else:
        print("\nSimulação. Rode com --aplicar para gravar.")


if __name__ == "__main__":
    main()
