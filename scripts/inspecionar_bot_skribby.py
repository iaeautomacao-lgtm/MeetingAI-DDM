"""
Radiografia de um bot do Skribby: mostra se vieram os dados que permitem
identificar os locutores, e por qual via o vínculo foi obtido.

Serve para validar o teste do add-on realtime (SKRIBBY_REALTIME_AUDIO=1):
com o modelo async esperamos "nenhum evento de fala"; com realtime esperamos
started-speaking e/ou speaker_name preenchido.

Uso:
    python scripts/inspecionar_bot_skribby.py <bot_id>
    python scripts/inspecionar_bot_skribby.py --ultima
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(override=True)

from app import create_app
from app.pipeline.locutores import (
    mapear_com_ia,
    mapear_por_eventos_de_fala,
    nomes_de_pessoas,
    speakers_genericos,
)
from app.pipeline.skribby_client import (
    extract_skribby_participants,
    get_bot,
    parse_skribby_transcript,
)


def ultimo_bot_id():
    from app.extensions import get_mysql_connection

    connection = get_mysql_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT recall_bot_id
        FROM reunioes
        WHERE recall_bot_id IS NOT NULL
        ORDER BY data DESC
        LIMIT 1
        """
    )
    linha = cursor.fetchone()
    cursor.close()
    connection.close()
    return linha[0] if linha else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bot_id", nargs="?")
    ap.add_argument("--ultima", action="store_true", help="usa a reunião mais recente")
    args = ap.parse_args()

    app = create_app()

    with app.app_context():
        bot_id = args.bot_id

        if args.ultima or not bot_id:
            bot_id = ultimo_bot_id()

        if not bot_id:
            print("Informe o bot_id.")
            return

        print(f"bot {bot_id}\n")
        bot = get_bot(bot_id)

        print("modelo      :", bot.get("transcription_model"))
        print("status      :", bot.get("status"), "| stop:", bot.get("stop_reason"))
        print("realtime    :", bot.get("realtime_audio"))
        print("idioma      :", bot.get("lang"), "| detectado:", bot.get("detected_lang"))
        print()

        # 1) Participantes e eventos
        participantes = bot.get("participants") or []
        print(f"PARTICIPANTES ({len(participantes)})")
        tem_evento_fala = False

        for p in participantes:
            tipos = {}
            for e in p.get("events") or []:
                tipo = (e.get("type") or "?")
                tipos[tipo] = tipos.get(tipo, 0) + 1

            if "started-speaking" in tipos:
                tem_evento_fala = True

            resumo = ", ".join(f"{t}x{n}" for t, n in sorted(tipos.items())) or "sem eventos"
            print(f"  - {p.get('name')}: {resumo}")

        print()
        print(
            "eventos started-speaking:",
            "SIM -> vínculo determinístico possível" if tem_evento_fala
            else "NÃO -> só sobra inferência por IA",
        )
        print()

        # 2) Campos de nome dentro da transcrição
        segmentos = bot.get("transcript") or []
        com_speaker_name = 0
        com_palpite = 0

        for seg in segmentos:
            alvos = seg.get("utterances") if isinstance(seg.get("utterances"), list) else [seg]
            for u in alvos or []:
                if not isinstance(u, dict):
                    continue
                if u.get("speaker_name"):
                    com_speaker_name += 1
                if u.get("potential_speaker_names"):
                    com_palpite += 1

        print(f"TRANSCRIÇÃO ({len(segmentos)} segmentos)")
        print("  speaker_name preenchido           :", com_speaker_name)
        print("  potential_speaker_names preenchido:", com_palpite)
        print()

        # 3) Resultado prático
        utterances = parse_skribby_transcript(bot)
        nomes = nomes_de_pessoas([
            p["nome"] for p in extract_skribby_participants(bot) if p.get("nome")
        ])

        print("rótulos genéricos:", speakers_genericos(utterances) or "nenhum (já vem com nome)")
        print("nomes de pessoas :", nomes)
        print()

        por_eventos = mapear_por_eventos_de_fala(bot, utterances)
        print("mapa por eventos de fala:", por_eventos or "{} (indisponível/inconclusivo)")

        if not por_eventos and speakers_genericos(utterances):
            print("mapa por IA             :", mapear_com_ia(utterances, nomes) or "{}")


if __name__ == "__main__":
    main()
